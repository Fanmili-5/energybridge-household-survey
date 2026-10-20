"""Persistent drafts and append-only, version-bound formal responses."""
import copy
import hashlib
import json
import math
import re
import secrets
import sqlite3
import time
from pathlib import Path
from release import UI_VERSION,CONTRACT_VERSION,encoded,digest

from identity import Store as IdentityStore,now

NOTICE_VERSION='eb.reference50.collection_notice.v69'
NOTICE='本研究邀请您扮演给定参考家庭，评价10个日期的A/B用电安排。记录包括四项评分、接受判断、原因、所见页面与版本，以及保存进度所需的操作。参与自愿，可停止或使用恢复码续填、撤回答卷；无需提供姓名或联系方式。模型结果为参考仿真。您的回答用于研究和评估，通过质量检查后才可能用于模型训练。'
FIELDS={'decision','score','comfort_score','energy_score','vpp_score','reason'}
SCORES=('score','comfort_score','energy_score','vpp_score')


class Conflict(ValueError):
    pass


def response(value,complete):
    if not isinstance(value,dict)or set(value)!=FIELDS:raise ValueError('答卷字段不完整。')
    out=copy.deepcopy(value)
    if out['decision']not in ({'accept','reject'}if complete else{None,'accept','reject'}):raise ValueError('请选择接受或不接受。')
    for key in SCORES:
        v=out[key]
        if v is None and not complete:continue
        if isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)or not 1<=v<=5 or abs(v*10-round(v*10))>1e-8:
            raise ValueError('四项评分均须为1—5分，可填一位小数。')
    reason=out['reason']
    if reason is None and not complete:return out
    if not isinstance(reason,str)or len(reason)>4000:raise ValueError('主要原因须为4000字以内的文本。')
    out['reason']=reason.strip()
    if complete and not out['reason']:raise ValueError('请填写主要原因。')
    return out


def integer(value):
    if type(value)is not int or value<0:raise ValueError('保存版本无效。')
    return value


class CollectionStore(IdentityStore):
    def __init__(self,root,release,*,fixtures=False):
        root=Path(root);path=root/'formal_responses.sqlite3'
        if path.exists():
            with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)as db:
                try:prior=db.execute("select value from collection_metadata where key='release_sha256'").fetchone()
                except sqlite3.OperationalError:raise RuntimeError('此数据库不属于新版50户采集；请使用独立数据目录。')
                if not prior or prior[0]!=release.signature:raise RuntimeError('发布版本与数据库不一致；保留原库并使用新版本目录。')
        self.public_release=release
        self.cohort=release.manifest['cohort_id'];self.lease_seconds=release.manifest['assignment_lease_seconds']
        super().__init__(root,release.signature,fixtures=fixtures)
        with self.connect()as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS collection_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS current_drafts(actor_id TEXT NOT NULL,release TEXT NOT NULL,case_id TEXT NOT NULL,version INTEGER NOT NULL,value_json TEXT,base_answer_revision INTEGER NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(actor_id,release,case_id));
            CREATE TABLE IF NOT EXISTS view_history(actor_id TEXT NOT NULL,release TEXT NOT NULL,case_id TEXT NOT NULL,first_presented_at TEXT NOT NULL,last_presented_at TEXT NOT NULL,schedule_seen INTEGER NOT NULL CHECK(schedule_seen IN(0,1)),schedule_sha256 TEXT,first_schedule_opened_at TEXT,PRIMARY KEY(actor_id,release,case_id));
            CREATE TABLE IF NOT EXISTS responses_v69(request_id TEXT PRIMARY KEY,actor_id TEXT NOT NULL,release TEXT NOT NULL,case_id TEXT NOT NULL,revision INTEGER NOT NULL,payload_sha256 TEXT NOT NULL,receipt_id TEXT UNIQUE NOT NULL,record_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(actor_id,release,case_id,revision));
            CREATE TRIGGER IF NOT EXISTS immutable_v69_update BEFORE UPDATE ON responses_v69 BEGIN SELECT RAISE(ABORT,'append only');END;
            CREATE TRIGGER IF NOT EXISTS immutable_v69_delete BEFORE DELETE ON responses_v69 BEGIN SELECT RAISE(ABORT,'append only');END;
            CREATE TABLE IF NOT EXISTS quality_reviews(review_id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id TEXT NOT NULL,release TEXT NOT NULL,case_id TEXT NOT NULL,answer_revision INTEGER NOT NULL,status TEXT NOT NULL,rule_version TEXT NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,reviewed_at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS immutable_quality_update BEFORE UPDATE ON quality_reviews BEGIN SELECT RAISE(ABORT,'append only');END;
            CREATE TRIGGER IF NOT EXISTS immutable_quality_delete BEFORE DELETE ON quality_reviews BEGIN SELECT RAISE(ABORT,'append only');END;
            ''')
            db.execute("insert or ignore into collection_metadata values('release_sha256',?)",(release.signature,))
            db.execute("insert or ignore into collection_metadata values('schema','eb.reference50.collection.v69')")
            db.execute("insert or ignore into collection_metadata values('mode',?)",('engineering_fixture'if fixtures else'formal',))
            assert db.execute("select value from collection_metadata where key='mode'").fetchone()[0]==('engineering_fixture'if fixtures else'formal')

    def actor(self,session,db=None,*,consent=False):
        a=super().actor(session,db,consent=False)
        if a['batch']!=self.cohort or a['household_id']not in self.public_release.households:raise PermissionError('参与身份不属于当前发布。')
        if consent and a['consent_version']!=NOTICE_VERSION:raise PermissionError('请先确认参与说明。')
        return a

    def start_open(self,session):
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('select actor_id from sessions where session_digest=?',(session['session_digest'],)).fetchone()
            if not current:raise PermissionError('会话已失效，请刷新。')
            prior=db.execute('select * from actors where actor_id=?',(current['actor_id'],)).fetchone()
            if prior and prior['active']:
                actor=self.actor(session,db)
                db.execute('update assignment_leases set active_until=? where actor_id=?',(time.time()+self.lease_seconds,actor['actor_id']))
                return {'participant_id':actor['actor_id'],'household_id':actor['household_id'],'recovery_code':None}
            # Complete submissions are a load-balancing measure, not quality validation.
            completed={r['household_id']:r['n']for r in db.execute('''select household_id,count(*)as n from
              (select a.actor_id,a.household_id from actors a join responses_v69 r using(actor_id)
               where a.active=1 and a.consent_version=? and r.release=? group by a.actor_id,a.household_id
               having count(distinct r.case_id)=?)group by household_id''',(NOTICE_VERSION,self.release,self.public_release.questions_per_household))}
            busy={r['household_id']:r['n']for r in db.execute('''select l.household_id,count(*)as n from assignment_leases l join actors a using(actor_id)
                where a.active=1 and l.active_until>? group by l.household_id''',(time.time(),))}
            starts={r['household_id']:r['n']for r in db.execute('select household_id,count(*)as n from actors group by household_id')}
            hid=min(self.public_release.households,key=lambda h:(completed.get(h,0),busy.get(h,0),starts.get(h,0),self.public_release.households.index(h)))
            actor_id='P-'+secrets.token_hex(12);recovery=secrets.token_urlsafe(32)
            db.execute('insert into actors values(?,?,?,?,1,NULL,NULL,?)',(actor_id,self.cohort,hid,self.secret_hash('recovery',recovery),now()))
            db.execute('insert into assignment_leases values(?,?,?)',(actor_id,hid,time.time()+self.lease_seconds))
            db.execute('update sessions set actor_id=? where session_digest=?',(actor_id,session['session_digest']))
            return {'participant_id':actor_id,'household_id':hid,'recovery_code':recovery}

    def consent(self,session,payload):
        if payload!={'accept':True,'understood_assigned_role':True,'notice_version':NOTICE_VERSION}:raise ValueError('请先阅读并确认参与说明。')
        with self.lock,self.connect()as db:
            a=self.actor(session,db);db.execute('update actors set consent_version=?,consent_at=? where actor_id=?',(NOTICE_VERSION,now(),a['actor_id']))
        return {'consented':True}

    def state(self,session):
        base={'notice':NOTICE,'notice_version':NOTICE_VERSION,'ui_revision':UI_VERSION,
              'release_sha256':self.release,'participant_id':None,'consented':False,'answers':[],'drafts':[],
              'fixtures':self.fixtures,'question_count':self.public_release.questions_per_household,'views':[]}
        try:a=self.actor(session)
        except PermissionError:return base
        with self.connect()as db:
            rows=db.execute('select * from responses_v69 where actor_id=? and release=? order by rowid',(a['actor_id'],self.release)).fetchall()
            drafts=db.execute('select * from current_drafts where actor_id=? and release=?',(a['actor_id'],self.release)).fetchall()
            views=[self.view_state(db,a['actor_id'],r['case_id'])for r in db.execute('select case_id from view_history where actor_id=? and release=?',(a['actor_id'],self.release)).fetchall()]
        answers={}
        for row in rows:
            r=json.loads(row['record_json']);answers[row['case_id']]={'case_id':row['case_id'],'date':r['date'],'response':r['response'],
                'revision':row['revision'],'receipt_id':row['receipt_id'],'saved_at':row['created_at'],'presentation':r['presentation']}
        active=[]
        for d in drafts:
            latest=answers.get(d['case_id'],{}).get('revision',0)
            active.append({'case_id':d['case_id'],'version':d['version'],'base_answer_revision':d['base_answer_revision'],
                           'response':json.loads(d['value_json'])if d['value_json']is not None and d['base_answer_revision']==latest else None,
                           'saved_at':d['updated_at']})
        live=[d for d in active if d['response']is not None]
        resume=max(live,key=lambda d:d['saved_at'])['case_id']if live else next((r['case_id']for r in self.public_release.records.values()if r['household_id']==a['household_id']and r['case_id']not in answers),None)
        if resume is None and answers:resume=max(answers.values(),key=lambda r:r['saved_at'])['case_id']
        return {**base,'participant_id':a['actor_id'],'household_id':a['household_id'],
                'consented':a['consent_version']==NOTICE_VERSION,'answers':list(answers.values()),'drafts':active,
                'completed_count':len(answers),'resume_date':self.public_release.records[resume]['date']if resume else None,'views':views}

    def binding(self,session,payload,db=None):
        a=self.actor(session,db,consent=True)
        if not isinstance(payload,dict)or payload.get('participant_id')!=a['actor_id']:raise Conflict('参与身份已变化，请刷新后继续。')
        if not isinstance(payload,dict)or payload.get('release_sha256')!=self.release or payload.get('ui_revision')!=UI_VERSION:raise Conflict('问卷版本已变化，请刷新；原记录不会覆盖到新版。')
        row,case=self.public_release.case(payload.get('case_id'),a['household_id'])
        if payload.get('case_sha256')!=row['sha256']:raise Conflict('案例版本不一致，请刷新。')
        return a,row,case

    def presentation(self,case_id,value):
        if not isinstance(value,dict)or set(value)!={'fields','schedule_seen','schedule_text','presented_at'}:raise ValueError('页面显示记录不完整。')
        expected=self.public_release.models[case_id]
        fields=value['fields']
        if not isinstance(fields,dict)or set(fields)!={'family','request','changes','impacts'}:raise ValueError('页面内容不完整。')
        normalize=lambda s:re.sub(r'\s+','',s)
        for k,v in fields.items():
            if not isinstance(v,str)or len(v)>100000 or normalize(v)!=normalize(expected[k]):raise ValueError('所见页面与发布版本不一致，请刷新。')
        if type(value['schedule_seen'])is not bool:raise ValueError('排程显示标记无效。')
        if value['schedule_seen']:
            if not isinstance(value['schedule_text'],str)or normalize(value['schedule_text'])!=normalize(expected['schedule']):raise ValueError('展开排程与发布版本不一致。')
        elif value['schedule_text']is not None:raise ValueError('未查看排程不应进入角色输入。')
        if not isinstance(value['presented_at'],str)or not 10<=len(value['presented_at'])<=50:raise ValueError('页面时间记录无效。')
        return copy.deepcopy(value)

    @staticmethod
    def current_answer(db,actor,release,case):
        return db.execute('select * from responses_v69 where actor_id=? and release=? and case_id=? order by revision desc limit 1',(actor,release,case)).fetchone()

    def view_state(self,db,actor,case):
        r=db.execute('select * from view_history where actor_id=? and release=? and case_id=?',(actor,self.release,case)).fetchone()
        if not r:return None
        return {'case_id':case,'schedule_seen':bool(r['schedule_seen']),
                'schedule_text':self.public_release.models[case]['schedule']if r['schedule_seen']else None,
                'schedule_sha256':r['schedule_sha256'],'first_presented_at':r['first_presented_at'],
                'last_presented_at':r['last_presented_at'],'first_schedule_opened_at':r['first_schedule_opened_at']}

    def remember_presentation(self,db,actor,case,presentation):
        """Monotone information history for one participant / release / case."""
        current=self.view_state(db,actor,case);stamp=now()
        seen=presentation['schedule_seen']or bool(current and current['schedule_seen'])
        schedule=self.public_release.models[case]['schedule']if seen else None
        schedule_hash=hashlib.sha256(schedule.encode()).hexdigest()if seen else None
        first=current['first_presented_at']if current else stamp
        opened=(current['first_schedule_opened_at']if current else None)or(stamp if seen else None)
        db.execute('insert or replace into view_history values(?,?,?,?,?,?,?,?)',(actor,self.release,case,first,stamp,int(seen),schedule_hash,opened))
        db.execute('update assignment_leases set active_until=? where actor_id=?',(time.time()+self.lease_seconds,actor))
        effective={**copy.deepcopy(presentation),'schedule_seen':seen,'schedule_text':schedule}
        return effective,self.view_state(db,actor,case)

    def view(self,session,payload):
        required={'participant_id','release_sha256','ui_revision','case_id','case_sha256','presentation'}
        if not isinstance(payload,dict)or set(payload)!=required:raise ValueError('查看记录字段无效。')
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');a,row,_=self.binding(session,payload,db)
            shown=self.presentation(row['case_id'],payload['presentation'])
            effective,view=self.remember_presentation(db,a['actor_id'],row['case_id'],shown)
        return {'saved':True,'case_id':row['case_id'],'view':view,'presentation':effective}

    def draft(self,session,payload,*,clear=False):
        fields={'participant_id','release_sha256','ui_revision','case_id','case_sha256','expected_version','expected_answer_revision'}| (set()if clear else{'response','presentation'})
        if not isinstance(payload,dict)or set(payload)!=fields:raise ValueError('草稿字段无效。')
        expected=integer(payload['expected_version']);answer_rev=integer(payload['expected_answer_revision'])
        answer=None if clear else response(payload['response'],False)
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');a,row,_=self.binding(session,payload,db)
            if not clear:
                shown=self.presentation(row['case_id'],payload['presentation'])
                effective,view=self.remember_presentation(db,a['actor_id'],row['case_id'],shown)
            else:effective=None;view=self.view_state(db,a['actor_id'],row['case_id'])
            current=db.execute('select * from current_drafts where actor_id=? and release=? and case_id=?',(a['actor_id'],self.release,row['case_id'])).fetchone()
            prior=self.current_answer(db,a['actor_id'],self.release,row['case_id']);actual_answer=prior['revision']if prior else 0
            if answer_rev!=actual_answer:raise Conflict('另一个页面已提交更新，请刷新后继续；本机未同步内容仍保留。')
            version=current['version']if current else 0
            if expected!=version:raise Conflict('另一个页面已更新草稿，请刷新后继续。')
            version+=1;stamp=now()
            db.execute('insert or replace into current_drafts values(?,?,?,?,?,?,?)',(a['actor_id'],self.release,row['case_id'],version,encoded(answer).decode()if answer is not None else None,actual_answer,stamp))
        return {'saved':True,'case_id':row['case_id'],'version':version,'base_answer_revision':actual_answer,'response':answer,'saved_at':stamp,'presentation':effective,'view':view}

    def save(self,session,payload):
        required={'participant_id','release_sha256','ui_revision','case_id','case_sha256','expected_answer_revision','expected_draft_version','request_id','response','presentation'}
        if not isinstance(payload,dict)or set(payload)!=required:raise ValueError('提交字段无效。')
        if not isinstance(payload['request_id'],str)or not re.fullmatch(r'[a-f0-9-]{36}',payload['request_id']):raise ValueError('提交标识无效。')
        answer=response(payload['response'],True);prior_rev=integer(payload['expected_answer_revision']);draft_rev=integer(payload['expected_draft_version'])
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');a,row,case=self.binding(session,payload,db)
            presentation=self.presentation(row['case_id'],payload['presentation']);phash=digest(payload)
            duplicate=db.execute('select * from responses_v69 where request_id=?',(payload['request_id'],)).fetchone()
            if duplicate:
                if duplicate['actor_id']!=a['actor_id']or duplicate['payload_sha256']!=phash:raise Conflict('同一提交标识的内容发生变化。')
                stored=json.loads(duplicate['record_json'])
                return {'saved':True,'duplicate':True,'case_id':row['case_id'],'revision':duplicate['revision'],'receipt_id':duplicate['receipt_id'],'response':answer,'saved_at':duplicate['created_at'],'presentation':stored['presentation'],'view':self.view_state(db,a['actor_id'],row['case_id'])}
            prior=self.current_answer(db,a['actor_id'],self.release,row['case_id']);actual=prior['revision']if prior else 0
            if prior_rev!=actual:raise Conflict('此题已有更新答卷，请刷新。未提交修改仍保留在本机。')
            revision=actual+1;stamp=now();receipt=('TEST-'if self.fixtures else'ANS-')+secrets.token_hex(8).upper()
            current_display=copy.deepcopy(presentation)
            presentation,view=self.remember_presentation(db,a['actor_id'],row['case_id'],presentation)
            model_input={'schema':'eb.visible_role_input.v69','date':case['date'],'fields':presentation['fields'],
                         'expanded_schedule':presentation['schedule_text']if presentation['schedule_seen']else None,
                         'schedule_context':'previously_displayed_in_this_case_and_release'if presentation['schedule_seen']else'not_displayed',
                         'answer_instructions':copy.deepcopy(self.public_release.answer_instructions)}
            record={'schema':'eb.formal_role_response.v69','ui_revision':UI_VERSION,'answer_contract':CONTRACT_VERSION,
                    'presentation_revision':self.public_release.manifest.get('presentation_revision',UI_VERSION),
                    'collection_condition':self.public_release.manifest.get('collection_condition','legacy_reference_collection'),
                    'source_release_sha256':self.release,'source_case_sha256':row['sha256'],
                    'source_profile_sha256':self.public_release.index['profiles_sha256'][a['household_id']],
                    'source_bindings':case['bindings'],'ui_assets_sha256':self.public_release.index['ui_assets_sha256'],
                    'case_id':row['case_id'],'household_id':a['household_id'],'date':case['date'],'participant_id':a['actor_id'],
                    'input':model_input,'input_sha256':digest(model_input),'response':answer,
                    'presentation':presentation,'current_display_presentation':current_display,'view_history':view,
                    'objective_results':{'schema':'eb.fixed_simulation_outcomes.v69','source_case_sha256':row['sha256'],'VPP_requests':copy.deepcopy(case['VPP_requests']),'VPP_results':copy.deepcopy(case['VPP_results']),
                                         **({'physical_review':copy.deepcopy(case['physical_review'])}if 'physical_review'in case else{})},
                    'revision':revision,'receipt_id':receipt,'submitted_at':stamp,
                    'consent':{'version':NOTICE_VERSION,'accepted_at':a['consent_at'],'notice_sha256':hashlib.sha256(NOTICE.encode()).hexdigest()},
                    'label_origin':'engineering_fixture'if self.fixtures else'participant_roleplay_submission',
                    'collection_phase':'reference_collection','cohort_id':self.cohort,'formal_auto_inclusion':False,
                    'human_label_count':0 if self.fixtures else 1,'human_identity_validation':'not_performed','training_release':False}
            db.execute('insert into responses_v69 values(?,?,?,?,?,?,?,?,?)',(payload['request_id'],a['actor_id'],self.release,row['case_id'],revision,phash,receipt,encoded(record).decode(),stamp))
            completed=db.execute('select count(distinct case_id)from responses_v69 where actor_id=?and release=?',(a['actor_id'],self.release)).fetchone()[0]
            if completed==self.public_release.questions_per_household:db.execute('update assignment_leases set active_until=0 where actor_id=?',(a['actor_id'],))
            current=db.execute('select version from current_drafts where actor_id=? and release=? and case_id=?',(a['actor_id'],self.release,row['case_id'])).fetchone()
            dv=current['version']if current else 0
            cleared=dv==draft_rev
            if cleared:
                dv+=1;db.execute('insert or replace into current_drafts values(?,?,?,?,NULL,?,?)',(a['actor_id'],self.release,row['case_id'],dv,revision,stamp))
        return {'saved':True,'duplicate':False,'case_id':row['case_id'],'revision':revision,'receipt_id':receipt,'response':answer,'saved_at':stamp,'draft_cleared':cleared,'draft_version':dv,'presentation':presentation,'view':view}

    def review(self,value):
        fields={'actor_id','case_id','answer_revision','status','rule_version','reviewer','reason'}
        if not isinstance(value,dict)or set(value)!=fields:raise ValueError('质控字段不完整。')
        if type(value['answer_revision'])is not int or value['answer_revision']<1:raise ValueError('质控答卷修订无效。')
        if value['status']not in {'valid','excluded','pending'}or any(not isinstance(value[k],str)or not value[k].strip()for k in ['rule_version','reviewer','reason']):raise ValueError('质控结论必须有规则版本、复核者及理由。')
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE')
            prior=self.current_answer(db,value['actor_id'],self.release,value['case_id'])
            if not prior or prior['revision']!=value['answer_revision']:raise Conflict('质控必须对应当前答卷修订。')
            db.execute('insert into quality_reviews(actor_id,release,case_id,answer_revision,status,rule_version,reviewer,reason,reviewed_at)values(?,?,?,?,?,?,?,?,?)',
                       (value['actor_id'],self.release,value['case_id'],value['answer_revision'],value['status'],value['rule_version'],value['reviewer'],value['reason'],now()))
        return {'review_saved':True,'answer_revision':value['answer_revision'],'status':value['status']}

    def export(self,quality='all'):
        if quality not in {'all','valid'}:raise ValueError('未知质控范围。')
        with self.connect()as db:
            rows=db.execute('select r.* from responses_v69 r join actors a using(actor_id) where a.active=1 and a.consent_version=? and r.release=? order by r.rowid',(NOTICE_VERSION,self.release)).fetchall()
            reviews=db.execute('select * from quality_reviews where release=?order by review_id',(self.release,)).fetchall()
        review_by_key={(r['actor_id'],r['case_id'],r['answer_revision']):dict(r)for r in reviews}
        latest={}
        for row in rows:
            record=json.loads(row['record_json'])
            if record['label_origin']=='participant_roleplay_submission':latest[row['actor_id'],row['case_id']]=record
        output=[]
        for (actor,case),record in latest.items():
            review=review_by_key.get((actor,case,record['revision']))
            record['quality_review']=review or {'status':'unreviewed'}
            if quality=='all'or(review and review['status']=='valid'):output.append(record)
        return output
