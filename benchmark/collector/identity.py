"""Anonymous sessions and recovery. No invitation-based entry or personal data."""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime,timezone
from pathlib import Path

def now():return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self,root,release,*,fixtures=False,cohort_releases=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db_path=self.root/'formal_responses.sqlite3';self.release=release;self.fixtures=fixtures
        self.lock=threading.RLock();key=self.root/'credential_pepper'
        if not key.exists():
            if self.db_path.exists():raise RuntimeError('Existing database requires its original recovery pepper.')
            with key.open('xb')as f:f.write(secrets.token_bytes(32))
            key.chmod(0o600)
        self.pepper=key.read_bytes();assert len(self.pepper)==32
        with self.connect()as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS actors(actor_id TEXT PRIMARY KEY,batch TEXT NOT NULL,household_id TEXT NOT NULL,recovery_digest TEXT UNIQUE NOT NULL,active INTEGER NOT NULL,consent_version TEXT,consent_at TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(session_digest TEXT PRIMARY KEY,csrf TEXT NOT NULL,actor_id TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(key_digest TEXT PRIMARY KEY,window_start REAL NOT NULL,count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS withdrawals(actor_id TEXT PRIMARY KEY,withdrawn_at TEXT NOT NULL,receipt_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assignment_leases(actor_id TEXT PRIMARY KEY,household_id TEXT NOT NULL,active_until REAL NOT NULL);
            ''')
        self.db_path.chmod(0o600)

    def connect(self):
        db=sqlite3.connect(self.db_path,timeout=20);db.row_factory=sqlite3.Row;return db

    def secret_hash(self,purpose,value):return hmac.new(self.pepper,(purpose+':'+value).encode(),hashlib.sha256).hexdigest()

    def session(self,token,create=False):
        with self.connect()as db:
            row=db.execute('select * from sessions where session_digest=?',(self.secret_hash('session',token or ''),)).fetchone()
            if row:return dict(row),None
            if not create:return None,None
            token=secrets.token_urlsafe(32)
            row={'session_digest':self.secret_hash('session',token),'csrf':secrets.token_urlsafe(32),'actor_id':None,'created_at':now()}
            db.execute('insert into sessions values(?,?,?,?)',tuple(row.values()));return row,token

    def actor(self,session,db=None,*,consent=False):
        if db is None:
            with self.connect()as conn:return Store.actor(self,session,conn)
        current=db.execute('select actor_id from sessions where session_digest=?',(session.get('session_digest'),)).fetchone()
        actor=db.execute('select * from actors where actor_id=?',(current['actor_id']if current else None,)).fetchone()
        if not actor or not actor['active']:raise PermissionError('请先从问卷首页进入。')
        return dict(actor)

    def claim(self,session,batch,credential,remote_key):
        if not isinstance(credential,str)or not 24<=len(credential)<=100:raise ValueError('请输入完整恢复码。')
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');key=self.secret_hash('attempt',remote_key);stamp=time.time()
            prior=db.execute('select * from attempts where key_digest=?',(key,)).fetchone()
            count=prior['count']+1 if prior and stamp-prior['window_start']<60 else 1
            start=prior['window_start']if prior and stamp-prior['window_start']<60 else stamp
            db.execute('insert or replace into attempts values(?,?,?)',(key,start,count));db.commit()
            if count>12:raise PermissionError('尝试次数较多，请一分钟后再试。')
            db.execute('BEGIN IMMEDIATE')
            actor=db.execute('select * from actors where recovery_digest=?',(self.secret_hash('recovery',credential),)).fetchone()
            if not actor or not actor['active']or actor['batch']!=batch:raise PermissionError('恢复码无效、已撤回或不属于本版本。')
            db.execute('update sessions set actor_id=? where session_digest=?',(actor['actor_id'],session['session_digest']))
            db.execute('update assignment_leases set active_until=? where actor_id=?',(stamp+self.lease_seconds,actor['actor_id']))
            db.execute('delete from attempts where key_digest=?',(key,))
            return {'participant_id':actor['actor_id'],'household_id':actor['household_id'],'batch':batch,'recovery_code':None}

    def withdraw(self,session):
        with self.lock,self.connect()as db:
            db.execute('BEGIN IMMEDIATE');actor=self.actor(session,db);receipt='WD-'+secrets.token_hex(8).upper()
            db.execute('update actors set active=0,consent_version=NULL where actor_id=?',(actor['actor_id'],))
            db.execute('insert into withdrawals values(?,?,?)',(actor['actor_id'],now(),receipt))
            db.execute('update sessions set actor_id=NULL where actor_id=?',(actor['actor_id'],))
            db.execute('update assignment_leases set active_until=0 where actor_id=?',(actor['actor_id'],))
            return {'withdrawn':True,'receipt_id':receipt}
