"""SQLite is authoritative; JSON files are recoverable compatibility exports."""
import json
import sqlite3
import threading
from pathlib import Path
from common import write_json
from job_index import SUMMARY_FIELDS

class Database:
    def __init__(self, root):
        self.root=Path(root)
        self.path=self.root/'state.sqlite3'
        self.lock=threading.RLock()
        self.conn=sqlite3.connect(self.path,timeout=30,check_same_thread=False)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL,
          status TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL,
          UNIQUE(owner, request_id));
        CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,created);
        CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner,created);
        CREATE TABLE IF NOT EXISTS documents (
          job_id TEXT NOT NULL REFERENCES jobs(id), name TEXT NOT NULL,
          payload TEXT NOT NULL, PRIMARY KEY(job_id,name));
        CREATE TABLE IF NOT EXISTS household_submissions (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL,
          created REAL NOT NULL, payload TEXT NOT NULL, UNIQUE(owner, request_id));
        CREATE INDEX IF NOT EXISTS household_owner ON household_submissions(owner,created);
        CREATE TABLE IF NOT EXISTS case_reports (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL,
          created REAL NOT NULL, payload TEXT NOT NULL, UNIQUE(owner,request_id));
        CREATE INDEX IF NOT EXISTS report_owner_created ON case_reports(owner,created);
        PRAGMA user_version=3;
        ''')

    def save(self, job, documents=None):
        dumps=lambda value:json.dumps(value,ensure_ascii=False,allow_nan=False)
        payload=dumps(job)
        docs={**(documents or {}),'job.json':job}
        encoded=[(job['id'],name,dumps(value)) for name,value in docs.items()]
        with self.lock,self.conn:
            self.conn.execute('''INSERT INTO jobs VALUES(?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload''',
            (job['id'],job.get('owner',job['id']),job.get('request_id',job['id']),job['status'],job.get('created_at',0),payload))
            self.conn.executemany('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(job_id,name) DO UPDATE SET payload=excluded.payload',encoded)
        # The successful DB transaction is the receipt. A later mirror failure
        # cannot undo it or cause a resubmission to execute twice.
        self.export(job['id'],docs)

    def export(self, jid, docs=None):
        if docs is None:
            with self.lock:
                docs={name:json.loads(payload) for name,payload in self.conn.execute('SELECT name,payload FROM documents WHERE job_id=?',(jid,))}
        for name,value in docs.items():
            try:write_json(self.root/jid/name,value)
            except OSError:
                # Regenerated from SQLite at startup or by the backup/export CLI.
                pass

    def document(self,jid,name):
        with self.lock:
            row=self.conn.execute('SELECT payload FROM documents WHERE job_id=? AND name=?',(jid,name)).fetchone()
        return json.loads(row[0]) if row else None

    def save_household(self, submission):
        # Immutable intake receipt, independent of simulation jobs and mirror files.
        payload=json.dumps(submission,ensure_ascii=False,allow_nan=False)
        with self.lock,self.conn:
            self.conn.execute('INSERT INTO household_submissions VALUES(?,?,?,?,?)',
                (submission['id'],submission['owner'],submission['request_id'],submission['created_at'],payload))

    def households(self, owner=None):
        with self.lock:
            sql='SELECT payload FROM household_submissions'
            params=()
            if owner is not None:sql+=' WHERE owner=?';params=(owner,)
            return [json.loads(r[0]) for r in self.conn.execute(sql+' ORDER BY created,id',params)]

    def household(self, sid):
        with self.lock:
            row=self.conn.execute('SELECT payload FROM household_submissions WHERE id=?',(sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def job(self, jid):
        with self.lock:
            row=self.conn.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()
        return json.loads(row[0]) if row else None

    def job_summaries(self):
        # SQLite extracts the small scalar index; Python never decodes all history.
        columns=','.join("json_extract(payload, '$."+key+"')" for key in SUMMARY_FIELDS)
        with self.lock:
            rows=self.conn.execute('SELECT '+columns+' FROM jobs ORDER BY created,id')
            return [{key:(bool(value) if key in {'decision_saved','rating_saved'} else value)
                     for key,value in zip(SUMMARY_FIELDS,row) if value is not None} for row in rows]

    def household_by_request(self, owner, request_id):
        with self.lock:
            row=self.conn.execute('SELECT payload FROM household_submissions WHERE owner=? AND request_id=?',
                                  (owner,request_id)).fetchone()
        return json.loads(row[0]) if row else None

    def household_count(self, owner=None, utc_day=None, include_admin=False):
        """Count immutable intake receipts without decoding their JSON payloads."""
        clauses=[];params=[]
        if owner is not None:
            clauses.append('owner=?');params.append(owner)
        if utc_day is not None:
            start=float(utc_day)*86400
            clauses.append('created>=? AND created<?');params.extend((start,start+86400))
        if not include_admin:
            clauses.append("COALESCE(json_extract(payload,'$.admin_test'),0)=0")
        sql='SELECT COUNT(*) FROM household_submissions'
        if clauses:sql+=' WHERE '+' AND '.join(clauses)
        with self.lock:
            return int(self.conn.execute(sql,tuple(params)).fetchone()[0])

    def household_summaries(self, owner):
        fields=('id','created_at','questionnaire_version','questionnaire_hash','household_record_hash')
        columns=','.join("json_extract(payload, '$."+key+"')" for key in fields)
        with self.lock:
            rows=self.conn.execute('SELECT '+columns+' FROM household_submissions WHERE owner=? ORDER BY created,id',(owner,))
            return [{key:value for key,value in zip(fields,row) if value is not None} for row in rows]

    def jobs(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.conn.execute('SELECT payload FROM jobs ORDER BY created,id')]

    def backup(self,path):
        with self.lock,sqlite3.connect(path) as target:
            self.conn.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'

    def close(self):
        with self.lock:self.conn.close()

    def __del__(self):
        try:self.conn.close()
        except Exception:pass
