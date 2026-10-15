"""Private formal-role collection ledger, distinct from every engineering DB."""
import copy,hashlib,hmac,json,os,re,secrets,sqlite3,threading,time,uuid
from pathlib import Path
from datetime import datetime,timezone
from engineering_contract import validate_record,encoded
from respondent import validate_respondent

NOTICE_VERSION='eb.role_collection_notice.20261014.1'
NOTICE='本研究邀请您扮演给定的合成参考家庭，阅读十个日期的用电安排及模型后果，并按角色评价。记录包括采用判断、评分、理由、页面版本与操作记录；本人年龄和性别选填，与角色资料分开。请勿填写姓名、联系方式等身份信息。参与自愿，可停止填写，也可使用恢复码恢复或撤回全部答卷。模型结果是参考仿真；您的回答将用于研究和评估角色回应模型，通过数据质量检查后可用于模型训练。'
UI_VERSION='eb.formal_role_questionnaire.20261014.1'
MODEL_FIELDS={'role-instructions','home-intro','home-visual','home-caption','home-summary','home-device-inventory','home-targets','home-members','home-attitudes','joint-source-note','vpp-summary','joint-weather','joint-state','joint-needs-list','selected-assets','joint-timeline','joint-plan-A','joint-plan-B','joint-changes','joint-results','answer-instructions','decision-question','score-question','visible-visuals'}

def now():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(encoded(value)).hexdigest()

class Store:
    def __init__(self,root,release,*,fixtures=False,cohort_releases=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db_path=self.root/'formal_responses.sqlite3';self.lock=threading.RLock();self.release=release;self.fixtures=fixtures
        self.cohort_releases=cohort_releases or {}
        key=self.root/'credential_pepper'
        if not key.exists():
            if self.db_path.exists():raise RuntimeError('Existing collection database requires its original credential pepper; restore the recovery bundle.')
            with key.open('xb')as f:f.write(secrets.token_bytes(32))
            key.chmod(0o600)
        self.pepper=key.read_bytes();assert len(self.pepper)==32
        with self.connect()as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS invitations(invite_digest TEXT PRIMARY KEY,slot_id TEXT UNIQUE NOT NULL,batch TEXT NOT NULL,household_id TEXT NOT NULL,actor_id TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS actors(actor_id TEXT PRIMARY KEY,batch TEXT NOT NULL,household_id TEXT NOT NULL,recovery_digest TEXT UNIQUE NOT NULL,active INTEGER NOT NULL,consent_version TEXT,consent_at TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(session_digest TEXT PRIMARY KEY,csrf TEXT NOT NULL,actor_id TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(key_digest TEXT PRIMARY KEY,window_start REAL NOT NULL,count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS answers(request_id TEXT PRIMARY KEY,actor_id TEXT NOT NULL,case_id TEXT NOT NULL,payload_sha256 TEXT NOT NULL,receipt_id TEXT UNIQUE NOT NULL,record_json TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS withdrawals(actor_id TEXT PRIMARY KEY,withdrawn_at TEXT NOT NULL,receipt_id TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS immutable_answers_update BEFORE UPDATE ON answers BEGIN SELECT RAISE(ABORT,'append only');END;
            CREATE TRIGGER IF NOT EXISTS immutable_answers_delete BEFORE DELETE ON answers BEGIN SELECT RAISE(ABORT,'append only');END;
            ''')
        self.db_path.chmod(0o600)

    def connect(self):
        db=sqlite3.connect(self.db_path,timeout=20);db.row_factory=sqlite3.Row;return db
    def secret_hash(self,purpose,value):return hmac.new(self.pepper,(purpose+':'+value).encode(),hashlib.sha256).hexdigest()
    def session(self,token,create=False):
        with self.lock,self.connect()as db:
            row=db.execute('select * from sessions where session_digest=?',(self.secret_hash('session',token or ''),)).fetchone()
            if row:return dict(row),None
            if not create:return None,None
            token=secrets.token_urlsafe(32);row={'session_digest':self.secret_hash('session',token),'csrf':secrets.token_urlsafe(32),'actor_id':None,'created_at':now()}
            db.execute('insert into sessions values(?,?,?,?)',tuple(row.values()));return row,token
    def actor(self,session,db=None,*,consent=False):
        if db is None:
            with self.connect()as conn:return self.actor(session,conn,consent=consent)
        current=db.execute('select actor_id from sessions where session_digest=?',(session.get('session_digest'),)).fetchone()
        a=db.execute('select * from actors where actor_id=?',(current['actor_id'] if current else None,)).fetchone()
        if not a or not a['active']:raise PermissionError('请先使用邀请码或恢复码进入问卷。')
        if consent and a['consent_version']!=NOTICE_VERSION:raise PermissionError('请先确认参与说明。')
        return dict(a)
    def provision(self,assignments):
        assignments=list(assignments)
        if len({a[0]for a in assignments})!=len(assignments)or len({a[3]for a in assignments})!=len(assignments):raise ValueError('Duplicate invitation slots or credentials')
        inserted=0
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE')
            for slot,batch,hid,token in assignments:
                if batch not in ('formal50','formal950')or not isinstance(token,str)or not re.fullmatch(r'[a-zA-Z0-9_-]{24,100}',token):raise ValueError('Invalid invitation assignment')
                invite_digest=self.secret_hash('invite',token)
                existing=db.execute('select * from invitations where slot_id=?',(slot,)).fetchone()
                if existing:
                    if (existing['invite_digest'],existing['batch'],existing['household_id'])!=(invite_digest,batch,hid):raise ValueError('Existing invitation differs from private operator file; no credentials replaced')
                    continue
                db.execute('insert into invitations values(?,?,?,?,NULL)',(invite_digest,slot,batch,hid));inserted+=1
        return inserted
    def claim(self,session,batch,credential,remote_key):
        if not isinstance(credential,str)or not 24<=len(credential)<=100:raise ValueError('请输入完整的邀请码或恢复码。')
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');key=self.secret_hash('attempt',remote_key);t=time.time()
            row=db.execute('select * from attempts where key_digest=?',(key,)).fetchone()
            count=row['count']+1 if row and t-row['window_start']<60 else 1;start=row['window_start']if row and t-row['window_start']<60 else t
            db.execute('insert or replace into attempts values(?,?,?)',(key,start,count));db.commit()
            if count>12:raise PermissionError('尝试次数较多，请一分钟后再试。')
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('select * from actors where recovery_digest=?',(self.secret_hash('recovery',credential),)).fetchone()
            recovery=None
            if existing:
                if existing['batch']!=batch or not existing['active']:raise PermissionError('此凭据不属于本版本或已撤回。')
                actor_id=existing['actor_id'];hid=existing['household_id']
            else:
                invite=db.execute('select * from invitations where invite_digest=?',(self.secret_hash('invite',credential),)).fetchone()
                if not invite or invite['batch']!=batch:raise PermissionError('邀请码或恢复码无效，或不属于本版本。')
                if invite['actor_id']:
                    current=self.actor(session,db)
                    if invite['actor_id']!=current['actor_id']:raise PermissionError('邀请码已领取，请使用领取时的恢复码。')
                    actor_id=invite['actor_id'];hid=invite['household_id']
                else:
                    actor_id='P-'+secrets.token_hex(12);hid=invite['household_id'];recovery=secrets.token_urlsafe(32)
                    db.execute('insert into actors values(?,?,?,?,1,NULL,NULL,?)',(actor_id,batch,hid,self.secret_hash('recovery',recovery),now()))
                    db.execute('update invitations set actor_id=? where invite_digest=?',(actor_id,invite['invite_digest']))
            db.execute('update sessions set actor_id=? where session_digest=?',(actor_id,session['session_digest']))
            db.execute('delete from attempts where key_digest=?',(key,))
            return {'participant_id':actor_id,'household_id':hid,'batch':batch,'recovery_code':recovery}
    def consent(self,session,payload):
        if payload!={'accept':True,'understood_assigned_role':True,'notice_version':NOTICE_VERSION}:raise ValueError('请阅读说明，并确认愿意按给定角色参与。')
        with self.lock,self.connect()as db:
            actor=self.actor(session,db);db.execute('update actors set consent_version=?,consent_at=? where actor_id=?',(NOTICE_VERSION,now(),actor['actor_id']))
        return {'consented':True}
    def state(self,session,batch):
        result={'notice_version':NOTICE_VERSION,'notice':NOTICE,'ui_version':UI_VERSION,'consented':False,'participant_id':None,'answers':[]}
        try:actor=self.actor(session)
        except PermissionError:return result
        if actor['batch']!=batch:return result
        with self.connect()as db:
            rows=db.execute('select rowid,* from answers where actor_id=? order by rowid',(actor['actor_id'],)).fetchall()
        latest={};prior_release_answer_count=0
        for row in rows:
            record=json.loads(row['record_json'])
            if batch in self.cohort_releases and record.get('source_release_sha256')!=self.cohort_releases[batch]:
                prior_release_answer_count+=1;continue
            latest[row['case_id']]=(row['rowid'],{'case_id':row['case_id'],'case_index':record['case_index'],'feedback':record['response'],'respondent':record['respondent'],'receipt_id':row['receipt_id']})
        # A dict keeps a case's first insertion position after a revision. The
        # frontend restores respondent metadata from the final answer, so order
        # by each case's latest append instead of its first submission.
        answers=[item for _,item in sorted(latest.values(),key=lambda item:item[0])]
        return {**result,'consented':actor['consent_version']==NOTICE_VERSION,'participant_id':actor['actor_id'],'household_id':actor['household_id'],'answers':answers,'prior_release_answer_count':prior_release_answer_count}
    def save(self,session,payload,cases,hashes,batch,hid,cohort_release=None):
        actor=self.actor(session,consent=True)
        if (actor['batch'],actor['household_id'])!=(batch,hid):raise PermissionError('当前身份与家庭任务不匹配。')
        if not isinstance(payload,dict)or set(payload)!={'case_index','record','request_id'}:raise ValueError('答卷字段无效。')
        rid=payload['request_id']
        if not isinstance(rid,str)or not re.fullmatch(r'[a-f0-9-]{36}',rid):raise ValueError('提交标识无效。')
        r=payload['record'];index=payload['case_index']
        if not isinstance(r,dict)or r.get('schema')!='eb.role_response.v1'or r.get('questionnaire_ui_version')!=UI_VERSION or r.get('status')!='participant_submitted_role_response':raise ValueError('问卷版本不匹配，请刷新页面。')
        validate_respondent(r.get('respondent'))
        structural=copy.deepcopy(r);structural.update(schema='eb.joint_b.local_test_export.v6',questionnaire_ui_version='eb.household50.questionnaire.20261014.1',status='engineering_click_not_human_feedback',human_label_count=0,training_release=False,formal_export_eligible=False)
        structural['test_feedback']=r.get('response')
        validate_record('answers',structural,index,cases,hashes)
        stimulus=r.get('input',{});snapshot=r.get('audit',{}).get('presentation',{}).get('rendered_snapshot',{})
        if set(stimulus)!={'schema','date','fields','display_assignment','history'}or set(stimulus['fields'])!=MODEL_FIELDS:raise ValueError('角色输入字段不完整。')
        if stimulus['schema']!='eb.joint_b.displayed_input.v1'or stimulus['display_assignment']!=cases[index]['display_assignment']:raise ValueError('角色输入版本或A/B位置不匹配。')
        if any(not isinstance(v,str)for v in stimulus['fields'].values())or any(snapshot.get(k)!=v for k,v in stimulus['fields'].items()):raise ValueError('可见信息与角色输入不一致。')
        presentation=r['audit']['presentation']
        if digest(stimulus)!=presentation.get('model_input_sha256')or digest(snapshot)!=presentation.get('rendered_snapshot_sha256'):raise ValueError('问卷显示记录校验失败。')
        case=cases[index];phash=digest(payload)
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');current=self.actor(session,db,consent=True)
            if (current['actor_id'],current['batch'],current['household_id'])!=(actor['actor_id'],batch,hid):raise PermissionError('参与身份已变化，请刷新后提交。')
            actor=current
            prior=db.execute('select * from answers where request_id=?',(rid,)).fetchone()
            if prior:
                if prior['actor_id']!=actor['actor_id']or prior['payload_sha256']!=phash:raise ValueError('同一提交标识内容已变化，请重新提交。')
                return {'saved':True,'duplicate':True,'receipt_id':prior['receipt_id']}
            saved=copy.deepcopy(r);saved.update(case_index=index,participant_id=actor['actor_id'],collection_batch=batch,household_id=hid,
                status='engineering_fixture'if self.fixtures else 'participant_submitted_role_response',label_origin='engineering_fixture'if self.fixtures else 'participant_roleplay_submission',
                human_identity_validation='not_performed',human_label_count=0 if self.fixtures else 1,training_release=False,
                source_release_sha256=cohort_release or self.release,collection_service_scope_sha256=self.release,
                consent={'version':actor['consent_version'],'accepted_at':actor['consent_at'],'notice_sha256':hashlib.sha256(NOTICE.encode()).hexdigest()})
            saved['audit']['collection_linkage'].update(participant_id=actor['actor_id'],study_batch_id=batch)
            receipt='ANS-'+secrets.token_hex(8).upper();db.execute('insert into answers values(?,?,?,?,?,?,?)',(rid,actor['actor_id'],case['identity']['case_id'],phash,receipt,encoded(saved).decode(),now()))
            return {'saved':True,'duplicate':False,'receipt_id':receipt}
    def withdraw(self,session):
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');actor=self.actor(session,db);receipt='WD-'+secrets.token_hex(8).upper()
            db.execute('update actors set active=0,consent_version=NULL where actor_id=?',(actor['actor_id'],));db.execute('insert into withdrawals values(?,?,?)',(actor['actor_id'],now(),receipt))
            db.execute('update sessions set actor_id=NULL where actor_id=?',(actor['actor_id'],))
            return {'withdrawn':True,'receipt_id':receipt}
    def export(self):
        with self.connect()as db:
            rows=db.execute('select a.rowid,a.* from answers a join actors p using(actor_id) where p.active=1 and p.consent_version=? order by a.rowid',(NOTICE_VERSION,)).fetchall()
        latest={}
        for row in rows:
            r=json.loads(row['record_json'])
            if r['label_origin']=='participant_roleplay_submission':latest[row['actor_id'],row['case_id']]=r
        return list(latest.values())
