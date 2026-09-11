"""Questionnaire server; loopback listener with explicit reverse-proxy origins."""
from __future__ import annotations
import argparse
from copy import deepcopy
from durable_storage import Database
from durable_queue import DurableQueue
import sqlite3
import logging
import fcntl
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from common import ROOT, VERSION, SCENARIO, QUESTIONS, PROFILE_IDS, RATING_IDS, digest, normalize_answers, training_candidate, write_json
from common import PROPOSAL_PROFILE_QUESTIONS
from questionnaire_persona import QUESTIONNAIRE_VERSION, components, visible_profile
import proposal_contract as proposals
import paired_contract as paired

TERMINAL = {"complete", "failed", "timeout", "cancelled", "interrupted"}

def stop_process(process):
    # The worker owns native EP descendants; kill the whole group on cancellation/timeout.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

class Store:
    def __init__(self, root, workers=1, timeout=240, human_pilot=False, max_pending=100, max_session_jobs=3, max_daily_jobs=250):
        if min(max_pending,max_session_jobs,max_daily_jobs)<1:raise ValueError('Admission limits must be positive')
        self.max_daily_jobs=max_daily_jobs
        self.max_pending=max_pending
        self.max_session_jobs=max_session_jobs
        self.human_pilot = human_pilot
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.timeout = timeout
        self.workers = workers
        self.db = Database(self.root)
        self.jobs = {job['id']:job for job in self.db.jobs()}
        self.processes = {}
        self.pool = DurableQueue(self,workers)
        # Import old files once, without inventing missing requests or labels.
        for path in self.root.glob('*/job.json'):
            if path.parent.name in self.jobs:continue
            job = json.loads(path.read_text())
            docs = {}
            for name in ('request.json','questionnaire_submission.json','household_config.json','household_record.json','profile_components.json','decision.json','rating.json','sft_candidate.json','outcome.json'):
                src=path.parent/name
                if src.exists():docs[name]=json.loads(src.read_text())
            self.persist(job,docs)
        for job in list(self.jobs.values()):
            if job['status'] not in TERMINAL:
                request=self.db.document(job['id'],'request.json')
                if request is None:
                    job.update(status='interrupted',message='旧任务缺少执行输入，已保留原记录，请重新提交。')
                elif job.get('attempts',0)>=3:
                    job.update(status='interrupted',message='任务多次中断，已保留答案，等待研究人员处理。')
                else:
                    job.update(status='queued',message='答案已保存，等待计算（中断的仿真将重新开始）。')
                    job['recovery_count']=job.get('recovery_count',0)+1
                    for key in ('started_at','finished_at','end_to_end_seconds'):
                        job.pop(key,None)
                self.persist(job)
            self.db.export(job['id'])

    def persist(self, job, documents=None):
        self.db.save(job,documents)
        self.jobs[job['id']]=job

    def household_owned(self, sid, session):
        if not isinstance(sid,str) or not re.fullmatch(r'[a-f0-9]{32}',sid):raise KeyError('找不到本次家庭资料')
        row=self.db.household(sid)
        if row is None or not secrets.compare_digest(row['owner'],session):
            raise KeyError('找不到本次家庭资料')
        if digest(row['household_record'])!=row['household_record_hash'] or digest(row['profile'])!=row['profile_hash'] or digest(row['questionnaire_snapshot'])!=row['questionnaire_hash']:
            raise ValueError('家庭资料校验失败，请联系研究人员')
        return row

    def household_public(self, row, full=True):
        keys=('id','created_at','questionnaire_version','questionnaire_hash','household_record_hash')
        out={k:row[k] for k in keys}
        out.update(submission_id=row['id'],saved=True,
                   case_ids=[j['id'] for j in self.jobs.values() if j.get('household_submission_id')==row['id']])
        if full:
            out.update({k:row[k] for k in ('profile','raw_answers','questionnaire_snapshot','household_record','research_consent','research_notice_version','ui_version')})
        return out

    def save_household(self, session, payload):
        nonce=payload.get('request_id','')
        if not isinstance(nonce,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',nonce):
            raise ValueError('提交标识无效，请刷新后重试')
        request_hash=digest(payload)
        with self.lock:
            for previous in self.db.households(session):
                if previous['request_id']==nonce:
                    if previous['request_hash']!=request_hash:raise ValueError('同一提交标识不能修改家庭资料')
                    return {**self.household_public(previous,False),'duplicate':True}
            for key,expected in (('questionnaire_version',paired.QUESTIONNAIRE_VERSION),('questionnaire_hash',digest(paired.QUESTIONS))):
                if payload.get(key)!=expected:raise ValueError('问卷版本已更新，请刷新核对后保存；已有资料保持原样')
            if self.human_pilot and (payload.get('research_consent') is not True or payload.get('research_notice_version')!='eb.research_notice.v1'):
                raise ValueError('请阅读研究说明并同意保存家庭资料')
            profile=paired.sanitize_profile(normalize_answers(payload.get('answers'),list(paired.LOOKUP),paired.LOOKUP))
            owned=paired.required(profile,'B05')
            for qid in ('B02','B04','F_EVENING'):paired.required(profile,qid)
            paired.validate_count(profile)
            for q in paired.QUESTIONS:
                if q.get('research_only') or profile[q['id']]['response_status']=='not_applicable':continue
                if q.get('device') and q['device'] not in owned:continue
                if q.get('required') or q.get('device') or q['group'] in ('attitude','stated_preference'):
                    paired.required(profile,q['id'])
            # Deliberately no paired.prepare: truthful answers survive unsupported physics.
            from household_extensions import build_record
            now=time.time();sid=secrets.token_hex(16);hid='household_'+digest(session)[:20]
            record=build_record(profile,paired.QUESTIONS,household_id=hid,raw_answers=payload.get('answers'),questionnaire_version=paired.QUESTIONNAIRE_VERSION,submitted_at=now)
            row={'id':sid,'owner':session,'request_id':nonce,'request_hash':request_hash,'created_at':now,
                 'household_id':hid,'profile':profile,'profile_hash':digest(profile),
                 'raw_answers':deepcopy(payload.get('answers')),'questionnaire_snapshot':deepcopy(paired.QUESTIONS),
                 'questionnaire_version':paired.QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(paired.QUESTIONS),
                 'household_record':record,'household_record_hash':digest(record),
                 'data_origin':'local_pilot_self_reported_human' if self.human_pilot else 'synthetic_engineering_test',
                 'research_consent':payload.get('research_consent') is True,
                 'research_notice_version':payload.get('research_notice_version'),'ui_version':payload.get('ui_version')}
            self.db.save_household(row)
            return self.household_public(row,False)

    def create(self, session, payload, proposal=False, paired_flow=False):
        intake=None
        if self.human_pilot and not paired_flow:raise ValueError('真人采集仅开放当前问卷流程')
        # Retry receipts are returned before version and queue admission checks.
        nonce=payload.get('request_id','')
        with self.lock:
            for previous in self.jobs.values():
                if previous['owner']==session and previous['request_id']==nonce:
                    if previous['request_hash']!=digest(payload):raise ValueError('同一提交标识不能修改内容')
                    return previous
        if paired_flow:
            proposal = True
            if payload.get('submission_id'):
                intake=self.household_owned(payload['submission_id'],session)
                expected_origin='local_pilot_self_reported_human' if self.human_pilot else 'synthetic_engineering_test'
                if intake['data_origin']!=expected_origin:raise ValueError('采集模式已变化，请重新确认并保存家庭资料')
                if intake['questionnaire_version']!=paired.QUESTIONNAIRE_VERSION or intake['questionnaire_hash']!=digest(paired.QUESTIONS):
                    raise ValueError('家庭资料使用旧版问卷，请核对并保存新版资料；原记录仍已保留')
                if 'answers' in payload:raise ValueError('请使用已保存的家庭资料生成，不要同时提交另一份答案')
                if payload.get('household_record_hash',intake['household_record_hash'])!=intake['household_record_hash']:
                    raise ValueError('家庭资料版本不一致')
            elif self.human_pilot:raise ValueError('请先保存家庭资料，再生成方案')
            for key, expected in (("questionnaire_version", paired.QUESTIONNAIRE_VERSION),
                                  ("questionnaire_hash", digest(paired.QUESTIONS))):
                if key in payload and payload[key] != expected:
                    raise ValueError("问卷版本已更新，请刷新后重新核对答案；本次尚未提交。")
        scenario = paired.CONTEXT if paired_flow else proposals.CONTEXT if proposal else SCENARIO
        if payload.get("scenario_id") != scenario["id"] or payload.get("scenario_understood") is not True:
            raise ValueError("请先确认已理解本次模拟情境")
        applicability = "shared_simulated_context" if paired_flow else payload.get("applicability")
        if not paired_flow and applicability not in {"close", "different_but_evaluable"}:
            raise ValueError("如无法代入本次情境，请保留家庭回答，暂不评价此案例")
        profile_questions = paired.LOOKUP if paired_flow else {q["id"]: q for q in PROPOSAL_PROFILE_QUESTIONS} if proposal else QUESTIONS
        profile_ids = list(profile_questions) if proposal else PROFILE_IDS
        profile = deepcopy(intake["profile"]) if intake else normalize_answers(payload.get("answers"), profile_ids, profile_questions)
        if paired_flow:
            profile = paired.sanitize_profile(profile)
        original = None
        if proposal and not paired_flow:
            if payload.get("original_confirmed") is not True:
                raise ValueError("请确认原安排后再生成调整建议")
            if payload.get("baseline_source") not in {"usual_routine_in_scenario", "chosen_scenario_arrangement"}:
                raise ValueError("请选择原安排来自家庭习惯还是本次情境设定")
            original = proposals.ordinary_plan(profile, payload.get("routine"))
        nonce = payload.get("request_id", "")
        if not isinstance(nonce, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}", nonce):
            raise ValueError("提交标识无效，请刷新后重试")
        request_hash = digest(payload)
        with self.lock:
            for job in self.jobs.values():
                if job["owner"] == session and job["request_id"] == nonce:
                    if job["request_hash"] != request_hash:
                        raise ValueError("同一提交标识不能修改内容")
                    return job
            if any(j["owner"] == session and j["status"] not in TERMINAL for j in self.jobs.values()):
                raise OverflowError("您已有一项计算正在进行")
            utc_day=int(time.time()//86400)
            if sum(int(j.get('created_at',0)//86400)==utc_day for j in self.jobs.values())>=self.max_daily_jobs:
                raise OverflowError('今日方案生成额度已用完，家庭资料仍已保存，请明天再试')
            if sum(j['status'] not in TERMINAL for j in self.jobs.values())>=self.max_pending:
                raise OverflowError('计算队列已满，家庭资料仍已保存，请稍后重试生成')
            if sum(j['owner']==session for j in self.jobs.values())>=self.max_session_jobs:
                raise OverflowError('本会话已达到方案生成次数上限，已保存的家庭资料和评价不受影响')
            documents = {}
            jid = secrets.token_hex(16)
            if paired_flow:
                original, scenario = paired.prepare(profile, jid)
            job = {
                "schema_version": VERSION, "id": jid, "owner": session,
                "household_id": "household_"+digest(session)[:20],
                "respondent_id": "respondent_"+digest(session)[:20],
                "profile": profile, "profile_hash": digest(profile),
                "request_id": nonce, "request_hash": request_hash,
                "scenario_id": scenario["id"], "applicability": applicability,
                "scenario": scenario, "scenario_hash": digest(scenario),
                "questionnaire_hash": digest([QUESTIONS[k] for k in PROFILE_IDS+RATING_IDS]),
                "data_origin": "synthetic_engineering_test" if payload.get("engineering_test", True) else "local_pilot_self_reported_human",
                "created_at": time.time(), "status": "queued", "message": "等待计算", "rating_saved": False,
            }
            if intake:job['household_submission_id']=intake['id']
            request = {"profile": profile, "data_origin": job["data_origin"]}
            if intake:request['household_submission_id']=intake['id']
            if proposal:
                job.update(schema_version=proposals.VERSION, task="plan_judgement", original_plan=original,
                           questionnaire_hash=digest(PROPOSAL_PROFILE_QUESTIONS),
                           questionnaire_version=QUESTIONNAIRE_VERSION,
                           questionnaire_snapshot=PROPOSAL_PROFILE_QUESTIONS,
                           profile_components=components(profile, PROPOSAL_PROFILE_QUESTIONS),
                           original_plan_hash=digest(original), baseline_source=payload.get("baseline_source", "deterministic_habit_mapping_v1"),
                           original_confirmed_at=job["created_at"], decision_saved=False)
                request.update(original_plan=original, baseline_source=payload.get("baseline_source", "deterministic_habit_mapping_v1"),
                               scenario=scenario, task="plan_judgement",
                               questionnaire_version=QUESTIONNAIRE_VERSION,
                               questionnaire_snapshot=PROPOSAL_PROFILE_QUESTIONS,
                               profile_components=job["profile_components"],
                               observable_profile=visible_profile(profile, PROPOSAL_PROFILE_QUESTIONS))
            if paired_flow:
                job.update(flow="paired_ep_v1", schema_version=paired.VERSION, scenario=scenario,
                           scenario_hash=digest(scenario), questionnaire_version=paired.QUESTIONNAIRE_VERSION,
                           questionnaire_snapshot=paired.QUESTIONS, questionnaire_hash=digest(paired.QUESTIONS),
                           profile_components=paired.profile_components(profile), baseline_source=original["source"],
                           data_origin="local_pilot_self_reported_human" if self.human_pilot else "synthetic_engineering_test")
                job.pop("original_confirmed_at", None)
                request.update(scenario=scenario, data_origin=job["data_origin"], flow="paired_ep_v1",
                               baseline_source=job["baseline_source"], questionnaire_version=paired.QUESTIONNAIRE_VERSION,
                               questionnaire_snapshot=paired.QUESTIONS, profile_components=job["profile_components"],
                               observable_profile=visible_profile(profile, paired.QUESTIONS))
            if paired_flow:
                from household_config import build_household_config
                config=build_household_config(profile,paired.QUESTIONS,original,job['household_id'])
                job.update(household_config=config,household_config_hash=digest(config))
                request.update(household_id=job['household_id'],household_config=config,household_config_hash=digest(config))
                documents['household_config.json']=config
                submission = {
                    "schema_version": "eb.questionnaire_submission.v1",
                    "case_id": jid, "household_id": job['household_id'],
                    "submitted_at": job['created_at'],
                    "questionnaire_version": paired.QUESTIONNAIRE_VERSION,
                    "questionnaire_hash": job['questionnaire_hash'],
                    "questionnaire_snapshot": paired.QUESTIONS,
                    "raw_answers": intake['raw_answers'] if intake else payload.get('answers'),
                    "normalized_answers": profile,
                    "profile_hash": job['profile_hash'],
                    "household_config_hash": job['household_config_hash'],
                    "ui_version": intake['ui_version'] if intake else payload.get('ui_version'),
                    "data_origin": job['data_origin'],
                }
                job['submission_hash'] = digest(submission)
                request['submission_hash'] = job['submission_hash']
                documents['questionnaire_submission.json']=submission
                from household_extensions import build_record
                record=deepcopy(intake['household_record']) if intake else build_record(profile,paired.QUESTIONS,household_id=job['household_id'],raw_answers=payload.get('answers'),questionnaire_version=paired.QUESTIONNAIRE_VERSION,submitted_at=job['created_at'])
                job['household_record']=record
                job['household_record_hash']=digest(record)
                request['household_record_hash']=job['household_record_hash']
                documents['household_record.json']=record
            documents["request.json"]=request
            if proposal:
                documents["profile_components.json"]=job["profile_components"]
            self.persist(job,documents)
            self.pool.submit(self.execute, jid)
            return job

    def execute(self, jid):
        process=None
        log=None
        result=None
        status='failed'
        message='计算未完成，答案已保存；请勿对失败任务填写评价。'
        try:
            with self.lock:
                job=self.jobs[jid]
                if job['status']!='queued' or getattr(self,'stopping',False):return
                proposal=job.get('task')=='plan_judgement'
                job.update(status='running',started_at=time.time(),message='正在计算两份方案')
                job['attempts']=job.get('attempts',0)+1
                job['queue_seconds']=job['started_at']-job['created_at']
                folder=self.root/jid/'attempts'/f"{job['attempts']:04d}"
                folder.mkdir(parents=True,exist_ok=False)
                job['run_directory']=str(folder.relative_to(self.root/jid))
                self.persist(job)
                request=self.db.document(jid,'request.json')
                if request is None:raise ValueError('Missing durable request')
                write_json(folder/'request.json',request)
                log=(folder/'worker.log').open('w')
                worker='paired_worker.py' if job.get('flow')=='paired_ep_v1' else 'proposal_worker.py' if proposal else 'worker.py'
                command=self.worker_command(folder) if hasattr(self,'worker_command') else [sys.executable,'-u',str(ROOT/worker),str(folder)]
                process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                self.processes[jid]=process
            code=process.wait(timeout=self.timeout)
            if code==0 and (folder/'outcome.json').exists():
                result=json.loads((folder/'outcome.json').read_text())
                if proposal:
                    if result["original_plan_hash"] != job["original_plan_hash"]:
                        raise ValueError("Original plan changed during proposal generation")
                    if job.get("flow") == "paired_ep_v1":
                        paired.validate(job["original_plan"], result["proposal_plan"], job["scenario"])
                        if result.get("simulation_status") != "paired_energyplus_complete" or not result["prediction"]["prefix_check"]["passed"]:
                            raise ValueError("Incomplete paired simulation")
                    else:
                        proposals.validate_offer(job["original_plan"], result["proposal_plan"])
                    if digest(result["display"]) != result["display_hash"] or digest(result["proposal_plan"]) != result["proposal_plan_hash"]:
                        raise ValueError("Result hash mismatch")
                status,message='complete','两份安排已准备好，请代表家庭评价'
            else:
                result=None
        except subprocess.TimeoutExpired:
            status,message='timeout',f'计算超过 {self.timeout} 秒，已停止；您的答案已保存。'
        except Exception:
            logging.exception('Job %s failed',jid)
        finally:
            if process and process.poll() is None:
                stop_process(process)
                process.wait()
            if log:log.close()
        with self.lock:
            self.processes.pop(jid,None)
            if job['status']!='cancelled':
                if getattr(self,"stopping",False):
                    status,message="queued","服务维护中，答案已保存，稍后重新计算。"
                    result=None
                job.update(status=status,message=message,finished_at=time.time())
                job['end_to_end_seconds']=job['finished_at']-job['created_at']
                if status=='queued':
                    for key in ('started_at','finished_at','end_to_end_seconds'):
                        job.pop(key,None)
                docs={}
                if status=='complete' and result is not None:
                    job['result']=result
                    docs['outcome.json']=result
                self.persist(job,docs)

    def owned(self, jid, session):
        job = self.jobs.get(jid)
        if job is None or not secrets.compare_digest(job["owner"], session):
            raise KeyError("找不到本次任务")
        return job

    def public(self, job):
        data = {k: v for k, v in job.items() if k not in {"owner", "request_hash", "request_id"}}
        progress = self.root / job["id"] / job.get("run_directory","") / "progress.json"
        if progress.exists():
            try:data["progress"] = json.loads(progress.read_text())
            except (OSError,ValueError):pass
        return data

    def status(self,job):
        data={k:job[k] for k in ('id','flow','status','created_at','started_at','finished_at','end_to_end_seconds','message','decision_saved','rating_saved') if k in job}
        if job['status']=='queued':
            waiting=sorted((j for j in self.jobs.values() if j['status']=='queued'),key=lambda j:(j['created_at'],j['id']))
            data['queue_position']=next(i+1 for i,j in enumerate(waiting) if j['id']==job['id'])
            data['message']=f"回答已保存，前面还有 {data['queue_position']-1} 个等待任务。"
        if job['status']=='running':
            path=self.root/job['id']/job.get('run_directory','')/'progress.json'
            try:data['progress']=json.loads(path.read_text())
            except (OSError,ValueError):pass
        data['poll_after_ms']=2000
        return data

    def rate(self, jid, session, payload):
        with self.lock:
            job = self.owned(jid, session)
            if job.get("task") == "plan_judgement":
                raise ValueError("本次需要记录方案选择，不能作为执行后评分")
            if job["status"] != "complete":
                raise ValueError("只有成功完成并展示的结果才能评价")
            if payload.get("display_hash") != job["result"]["display_hash"]:
                raise ValueError("评价的结果版本不一致，请重新打开本次结果")
            answers = normalize_answers(payload.get("answers"), RATING_IDS)
            rating = {"answers": answers, "display_hash": payload["display_hash"],
                      "target_source": "engineering_test" if job["data_origin"] == "synthetic_engineering_test" else "household_representative_self_report"}
            previous=self.db.document(jid,"rating.json")
            if previous:
                if previous["rating_hash"] != digest(rating):
                    raise ValueError("本次评价已经保存；修改条件请新建案例")
                return {"saved": True, "duplicate": True}
            rating.update(rating_hash=digest(rating), submitted_at=time.time())
            job=deepcopy(job)
            job["rating_saved"] = True
            self.persist(job,{"rating.json":rating,"sft_candidate.json":training_candidate(job,rating)})
            return {"saved": True, "training_release": False}

    def decide(self, jid, session, payload):
        with self.lock:
            job = deepcopy(self.owned(jid, session))
            if job.get("task") != "plan_judgement" or job["status"] != "complete":
                raise ValueError("仅可对已生成并展示的两份方案作选择")
            decision = proposals.decision_record(job, payload)
            previous=self.db.document(jid,"decision.json")
            content_hash = digest(decision)
            if previous:
                if previous["decision_hash"] != content_hash:
                    raise ValueError("本次选择已保存，不能覆盖原始回答")
                return {"saved": True, "duplicate": True}
            decision.update(decision_hash=content_hash, submitted_at=time.time())
            candidate=proposals.candidate(job,decision)
            job.update(decision_saved=True, decision=decision)
            self.persist(job,{"decision.json":decision,"sft_candidate.json":candidate})
            return {"saved": True, "training_release": False, "execution_status": "not_run"}

    def example(self, session):
        if self.human_pilot:raise ValueError('真人采集不开放工程示例')
        source = ROOT / "data/smoke_agent_002"
        outcome_path = source / "outcome.json"
        if not outcome_path.exists():
            source = ROOT / "data/smoke_agent_001"
            outcome_path = source / "recovered_outcome.json"
        if not outcome_path.exists():
            raise ValueError("还没有可回看的真实测试结果")
        with self.lock:
            for job in self.jobs.values():
                if job["owner"] == session and job.get("replay_source") == source.name:
                    return job
            request = json.loads((source / "request.json").read_text())
            result = json.loads(outcome_path.read_text())
            jid = secrets.token_hex(16)
            job = {"schema_version": VERSION, "id": jid, "owner": session,
                   "household_id": "engineering_example_household", "respondent_id": "engineering_example_viewer",
                   "profile": request["profile"], "profile_hash": digest(request["profile"]),
                   "request_id": "replay_"+jid, "request_hash": digest(request),
                   "scenario_id": SCENARIO["id"], "applicability": "engineering_replay",
                   "scenario": json.loads((source/"provenance.json").read_text())["scenario"],
                   "data_origin": "synthetic_engineering_test", "created_at": time.time(),
                   "status": "complete", "rating_saved": False, "result": result,
                   "replay_source": source.name,
                   "message": "正在回看已完成的测试案例；使用的是测试家庭答案，不是刚按您家信息生成的方案。"}
            self.jobs[jid] = job
            self.persist(job)
            return job

    def cancel(self, jid, session):
        with self.lock:
            job = self.owned(jid, session)
            if job["status"] not in TERMINAL:
                job.update(status="cancelled", message="本次计算已取消", finished_at=time.time())
                process = self.processes.get(jid)
                if process:
                    stop_process(process)
                self.persist(job)
            return {"status": job["status"]}

class PilotHTTPServer(ThreadingHTTPServer):
    request_queue_size=128
    daemon_threads=True

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    server_version = "EBLocalPilot"
    def log_message(self, fmt, *args):
        pass

    def reply(self, code, data, cookie=None, content_type="application/json; charset=utf-8"):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        if cookie:
            self.send_header("Set-Cookie", f"pilot_session={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"+('; Secure' if getattr(self.server,'secure_cookie',False) else ''))
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        value = cookies.get("pilot_session")
        return value.value if value and re.fullmatch("[a-f0-9]{64}", value.value) else None

    def do_GET(self):
        path = urlparse(self.path).path
        if self.headers.get("Host") not in self.server.allowed_hosts:
            return self.reply(403, {"error": "请求地址不匹配"})
        if path in {"/", "/app.js", "/time-input.js", "/preview.js", "/plan-view.js", "/plan-preview.html", "/style.css", "/legacy", "/legacy.js"}:
            name = {"/": "index.html", "/app.js": "app.js", "/time-input.js": "time-input.js", "/preview.js": "preview.js", "/plan-view.js": "plan-view.js", "/plan-preview.html": "plan-preview.html", "/style.css": "style.css", "/legacy": "legacy.html", "/legacy.js": "legacy.js"}[path]
            mime = "text/html" if name.endswith("html") else "application/javascript" if name.endswith("js") else "text/css"
            return self.reply(200, (ROOT / "static" / name).read_bytes(), content_type=mime+"; charset=utf-8")
        if path == "/api/session":
            session = self.session() or secrets.token_hex(32)
            with self.server.store.lock:
                jobs = [self.server.store.status(j) for j in sorted(self.server.store.jobs.values(),key=lambda j:j.get("created_at",0)) if j.get("owner") == session][-100:]
                households=[self.server.store.household_public(r,False) for r in self.server.store.db.households(session)]
            return self.reply(200, {"households":households,"intake_enabled":True,"research_notice_version":"eb.research_notice.v1","schema_version": VERSION, "scenario": SCENARIO,
                                   "paired_version": paired.VERSION, "paired_context": paired.CONTEXT, "paired_questions": paired.QUESTIONS,
                                   "paired_questionnaire_version": paired.QUESTIONNAIRE_VERSION,
                                   "paired_questionnaire_hash": digest(paired.QUESTIONS),
                                   "collection_mode": "human_pilot" if self.server.store.human_pilot else "engineering",
                                   "planning_enabled": not self.server.planning_disabled,
                                   "proposal_context": proposals.CONTEXT, "proposal_version": proposals.VERSION,
                                   "proposal_profile_questions": PROPOSAL_PROFILE_QUESTIONS,
                                   "proposal_questionnaire_version": QUESTIONNAIRE_VERSION,
                                   "profile_questions": [QUESTIONS[k] for k in PROFILE_IDS],
                                   "rating_questions": [QUESTIONS[k] for k in RATING_IDS], "jobs": jobs}, cookie=session)
        household_match=re.fullmatch(r"/api/households/([a-f0-9]{32})",path)
        if household_match:
            try:
                with self.server.store.lock:
                    row=self.server.store.household_owned(household_match[1],self.session() or '')
                    return self.reply(200,self.server.store.household_public(row))
            except KeyError:return self.reply(404,{'error':'找不到本次家庭资料'})
            except ValueError:return self.reply(503,{'error':'家庭资料暂不可读取，请联系研究人员'})
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})(/status)?", path)
        if match:
            try:
                with self.server.store.lock:
                    job = self.server.store.owned(match[1], self.session() or "")
                    data=self.server.store.status(job) if match[2] else self.server.store.public(job)
                return self.reply(200,data)
            except KeyError:
                return self.reply(404, {"error": "找不到本次任务"})
        return self.reply(404, {"error": "页面不存在"})

    def do_POST(self):
        if self.headers.get("Host") not in self.server.allowed_hosts or self.headers.get("Origin") not in self.server.allowed_origins:
            return self.reply(403, {"error": "请求来源不匹配"})
        session = self.session()
        if not session:
            return self.reply(401, {"error": "请刷新页面恢复会话"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 32768:
                raise ValueError("请求大小无效")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("请求格式无效")
            path = urlparse(self.path).path
            if path=='/api/households':
                return self.reply(201,self.server.store.save_household(session,payload))
            if self.server.store.human_pilot and path in {'/api/jobs','/api/proposals','/api/example'}:
                return self.reply(403,{'error':'真人采集仅开放当前问卷流程'})
            if self.server.planning_disabled and path in {"/api/jobs", "/api/paired", "/api/proposals", "/api/example"}:
                return self.reply(503, {"error": "正在进行 EnergyPlus 独立测试，模型 API 与方案生成已暂停。"})
            if path == "/api/jobs":
                job = self.server.store.create(session, payload)
                return self.reply(202, self.server.store.public(job))
            if path == "/api/paired":
                job = self.server.store.create(session, payload, paired_flow=True)
                return self.reply(202, self.server.store.public(job))
            if path == "/api/proposals":
                job = self.server.store.create(session, payload, proposal=True)
                return self.reply(202, self.server.store.public(job))
            if path == "/api/example":
                return self.reply(200, self.server.store.public(self.server.store.example(session)))
            match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/(rating|cancel|decision)", path)
            if match:
                if match[2] == "decision":
                    data = self.server.store.decide(match[1], session, payload)
                else:
                    data = self.server.store.rate(match[1], session, payload) if match[2] == "rating" else self.server.store.cancel(match[1], session)
                return self.reply(200, data)
            return self.reply(404, {"error": "接口不存在"})
        except ValueError as exc:
            return self.reply(400, {"error": str(exc) if not isinstance(exc, json.JSONDecodeError) else "请求 JSON 无效"})
        except TypeError:
            return self.reply(400, {"error": "提交字段格式无效，请检查选项。"})
        except KeyError:
            return self.reply(404, {"error": "找不到本次任务"})
        except OverflowError as exc:
            return self.reply(429, {"error": str(exc)})
        except (sqlite3.Error,OSError):
            return self.reply(503,{"error":"保存暂时不可用，请保留页面并重试同一次提交。"})

def make_server(port=8766, root=None, workers=1, timeout=240, human_pilot=False, public_origin=None, disable_planning=False, max_pending=100, max_session_jobs=3, max_daily_jobs=250):
    if public_origin:
        origin = urlparse(public_origin)
        if (origin.scheme not in {"http", "https"} or not origin.hostname
                or origin.username or origin.password or origin.path
                or origin.query or origin.fragment):
            raise ValueError("public_origin must be an exact http(s) origin without path")
    if human_pilot and public_origin and origin.scheme!='https':
        raise ValueError('Public human data collection requires an HTTPS public_origin')
    if min(max_pending,max_session_jobs,max_daily_jobs)<1:raise ValueError('Admission limits must be positive')
    server = PilotHTTPServer(("127.0.0.1", port), Handler)
    server.secure_cookie=bool(public_origin and origin.scheme=='https')
    server.planning_disabled = disable_planning
    port = server.server_address[1]
    server.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    server.allowed_origins = {f"http://{host}" for host in server.allowed_hosts}
    if public_origin:
        server.allowed_hosts.add(origin.netloc)
        server.allowed_origins.add(public_origin)
    server.store = Store(root or ROOT / "data/web", workers, timeout, human_pilot,max_pending,max_session_jobs,max_daily_jobs)
    if not disable_planning:server.store.pool.resume()
    return server

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--human-pilot", action="store_true", help="Record real pilot self-reports; default is engineering test mode")
    parser.add_argument("--public-origin", help="Exact external origin served by a reverse proxy; listener remains loopback")
    parser.add_argument("--data-dir", type=Path, help="Persistent job directory outside the application release")
    parser.add_argument("--disable-planning", action="store_true", help="Keep the UI readable but reject all job creation; no model calls")
    parser.add_argument('--max-pending',type=int,default=100,help='Maximum admitted unfinished calculations')
    parser.add_argument('--max-session-jobs',type=int,default=3,help='Lifetime calculation quota per browser session')
    parser.add_argument('--max-daily-jobs',type=int,default=250,help='Global new calculation quota per UTC calendar day; failed jobs count')
    args = parser.parse_args()
    data_root=args.data_dir or ROOT/'data/web'
    data_root.mkdir(parents=True,exist_ok=True)
    singleton=(data_root/'server.lock').open('a')
    try:fcntl.flock(singleton,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:parser.error('This data directory already has an active server')
    server = make_server(args.port, root=args.data_dir, workers=args.workers, timeout=args.timeout, human_pilot=args.human_pilot, public_origin=args.public_origin, disable_planning=args.disable_planning,max_pending=args.max_pending,max_session_jobs=args.max_session_jobs,max_daily_jobs=args.max_daily_jobs)
    print(f"Local: http://127.0.0.1:{server.server_address[1]}", flush=True)
    def terminate(signum,frame):
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with server.store.lock:
            server.store.stopping=True
            server.store.pool.stopped=True
            processes=list(server.store.processes.values())
        for process in processes:
            stop_process(process)
        server.store.pool.shutdown(wait=True, cancel_futures=True)
        server.server_close()
        server.store.db.close()
