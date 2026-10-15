"""Two separately versioned formal questionnaires over the existing household UI."""
import argparse,collections,hashlib,hmac,html,json,os,re,secrets,threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from engineering_contract import field_json,encoded,validate_record
from store import Store,UI_VERSION,NOTICE_VERSION,NOTICE

ASSETS={'style.css','candidate.css','joint-view.css','plan-view.js','source-draft.js','household-view.js','joint-view.js','respondent-info.js','formal-client.js'}
COOKIE='eb_formal_collection';MAX_BODY=8*1024*1024

class Release:
    def __init__(self,path):
        self.root=Path(path).resolve();manifest_path=self.root/'FORMAL_RELEASE.json';self.manifest=json.loads(manifest_path.read_text());m=self.manifest
        assert m['schema']=='eb.formal_questionnaire.release.v1'and m['human_collection_release']is True and m['training_release']is False
        assert m['batch']in ('formal50','formal950')and len(m['households'])==int(m['batch'][6:])
        self.batch=m['batch'];self.signature=hashlib.sha256(encoded({k:v for k,v in m.items()if k!='release_signature'})).hexdigest();assert self.signature==m['release_signature']
        self.prefix=m.get('public_prefix','/household'+self.batch[6:]);assert re.fullmatch(r'/[a-z][a-z0-9-]{2,40}',self.prefix)
        self.rows={r['route']:r for r in m['households']};self.cache=collections.OrderedDict();self.lock=threading.RLock()
    def file(self,relative):
        expected=self.manifest['files'].get(relative)
        if not expected:raise FileNotFoundError(relative)
        p=self.root/relative
        if p.is_symlink()or not p.resolve().is_relative_to(self.root):raise FileNotFoundError(relative)
        raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise RuntimeError('Questionnaire release content changed')
        return raw
    def household(self,route):
        with self.lock:
            if route in self.cache:self.cache.move_to_end(route);return self.cache[route]
            row=self.rows[route];raw=self.file('households/'+row['household_id']+'/index.html');text=raw.decode();cases=field_json(text,'joint-cases-data');hashes=field_json(text,'source-hashes-data')
            assert len(cases)==len(hashes)==10 and all(c['identity']['role_id']==row['household_id']for c in cases)
            result=(row,text,cases,hashes);self.cache[route]=result
            while len(self.cache)>4:self.cache.popitem(last=False)
            return result

def landing(release,config):
    title=release.batch[6:]+'户正式问卷'
    return ('''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+title+''' · EnergyBridge</title><link rel="stylesheet" href="'''+release.prefix+'''/style.css"></head><body class="survey-page"><header><span class="brand">EnergyBridge</span><span>'''+title+'''</span></header><main><section class="panel"><h1>'''+title+'''</h1><p>您将扮演分配给您的参考家庭，阅读10个日期的A/B用电安排与影响，提交自己的判断。</p><p>请输入研究者提供的邀请码；已领取的参与者请使用恢复码继续填写。</p><form id="claim-form"><label class="field" for="credential">邀请码或恢复码<input id="credential" autocomplete="off" type="password" required minlength="24" maxlength="100"></label><button type="submit">进入问卷</button></form><p id="claim-status" role="status"></p><div id="recovery-panel" hidden><p>请妥善保存恢复码。更换浏览器或设备后，可凭此码继续填写或撤回。</p><input id="recovery-code" readonly aria-label="您的恢复码"><p><a id="assigned-link">进入分配给我的家庭问卷</a></p></div><p>本人年龄和性别选填；请勿填写姓名或联系方式。所有家庭和仿真均为研究参考情境。</p></section></main><script>window.EBFormalLanding='''+json.dumps(config,separators=(',',':'))+'''</script><script src="'''+release.prefix+'''/formal-client.js" defer></script></body></html>''').encode()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,value,*,mime='application/json; charset=utf-8',token=None,location=None):
        body=value if isinstance(value,bytes)else encoded(value)
        self.send_response(status)
        for k,v in {'Content-Type':mime,'Content-Length':str(len(body)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
                    'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; object-src 'none'; form-action 'self'"}.items():self.send_header(k,v)
        if token:self.send_header('Set-Cookie',f'{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000')
        if location:self.send_header('Location',location)
        self.end_headers();self.wfile.write(body)
    def session(self,create=False):
        jar=SimpleCookie()
        try:jar.load(self.headers.get('Cookie',''));token=jar.get(COOKIE);token=token.value if token else None
        except Exception:token=None
        return self.server.store.session(token,create)
    def resolve(self):
        path=urlsplit(self.path).path
        for release in self.server.releases.values():
            if path in (release.prefix,release.prefix+'/'):return release,None,'/'
            if path.startswith(release.prefix+'/'):return release,None,path[len(release.prefix):]
            route='/'+path.split('/')[1]
            if route in release.rows:return release,route,path[len(route):]or'/'
        raise FileNotFoundError('Questionnaire not available')
    def do_GET(self):
        try:
            release,route,path=self.resolve()
            if path=='/api/health':return self.send(200,{'mode':'verification_fixture'if self.server.store.fixtures else'formal_role_collection','batch':release.batch,'households':len(release.rows),'cases':len(release.rows)*10,'source_world_version':release.manifest['source_world_version'],'questionnaire_ui_version':UI_VERSION,'human_collection_release':not self.server.store.fixtures,'training_release':False,'scientific_benchmark_validated':False,'release_signature':release.signature})
            session,token=self.session(create=True);config={'api_base':release.prefix,'csrf':session['csrf'],'batch':release.batch}
            if route is None:
                if path=='/':return self.send(200,landing(release,config),mime='text/html; charset=utf-8',token=token)
                if path=='/api/session':return self.send(200,{**self.server.store.state(session,release.batch),'csrf':session['csrf']},token=token)
                if path in ('/style.css','/formal-client.js'):
                    if path=='/style.css':raw=release.file('households/'+next(iter(release.rows.values()))['household_id']+'/style.css')
                    else:raw=release.file('formal-client.js')
                    return self.send(200,raw,mime='text/css'if path.endswith('.css')else'text/javascript')
                raise FileNotFoundError()
            row=release.rows[route]
            try:actor=self.server.store.actor(session)
            except PermissionError:return self.send(302,b'',location=release.prefix,token=token)
            if (actor['batch'],actor['household_id'])!=(release.batch,row['household_id']):raise PermissionError('当前身份未分配到此家庭。')
            if path in ('/','/index.html'):
                row,page,cases,hashes=release.household(route)
                live={'base':route,'csrf':session['csrf']};formal={**config,'participant_id':actor['actor_id'],'household_id':row['household_id'],'cohort_name':release.batch[6:]+'户正式问卷'}
                page=page.replace('</head>','<script>window.EBLiveConfig='+json.dumps(live,separators=(',',':'))+';window.EBFormalConfig='+json.dumps(formal,separators=(',',':'))+'</script></head>',1)
                return self.send(200,page.encode(),mime='text/html; charset=utf-8',token=token)
            name=path.lstrip('/')
            if '/'not in name and name in ASSETS:
                raw=release.file('households/'+row['household_id']+'/'+name)
                return self.send(200,raw,mime='text/css'if name.endswith('.css')else'text/javascript')
            raise FileNotFoundError()
        except FileNotFoundError:return self.send(404,{'error':'未找到问卷或资源。'})
        except PermissionError as e:return self.send(403,{'error':str(e)})
        except Exception:return self.send(503,{'error':'问卷资料暂时无法核验，请稍后再试。'})
    def do_POST(self):
        try:
            release,route,path=self.resolve();session,_=self.session()
            if not session or self.headers.get('Origin')!=self.server.origin or not hmac.compare_digest(session['csrf'],self.headers.get('X-EB-CSRF','')):raise PermissionError('会话或来源校验失败，请刷新。')
            n=int(self.headers.get('Content-Length','0'))
            if n<1 or n>MAX_BODY or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('请求格式无效。')
            data=json.loads(self.rfile.read(n));store=self.server.store
            if route is None:
                if path=='/api/claim':
                    if not isinstance(data,dict)or set(data)!={'credential'}:raise ValueError('凭据字段无效。')
                    result=store.claim(session,release.batch,data['credential'],self.headers.get('X-Real-IP')or self.client_address[0]);row=next(r for r in release.rows.values()if r['household_id']==result['household_id']);return self.send(200,{**result,'route':row['route']+'/'})
                if path=='/api/consent':return self.send(200,store.consent(session,data))
                if path=='/api/withdraw':return self.send(200,store.withdraw(session))
                if path=='/api/logout':
                    with store.connect()as db:db.execute('update sessions set actor_id=NULL where session_digest=?',(session['session_digest'],))
                    return self.send(200,{'logged_out':True})
                raise FileNotFoundError()
            row,page,cases,hashes=release.household(route)
            if path=='/api/answers':return self.send(201,store.save(session,data,cases,hashes,release.batch,row['household_id'],release.signature))
            if path=='/api/issues':
                actor=store.actor(session)
                if (actor['batch'],actor['household_id'])!=(release.batch,row['household_id']):raise PermissionError('家庭身份不匹配。')
                index=data['case_index'];record=data['record'];mapped=dict(record,status='engineering_issue_submission');validate_record('issues',mapped,index,cases,hashes)
                with store.connect()as db:
                    db.execute('create table if not exists issues(request_id TEXT PRIMARY KEY,actor_id TEXT,record_json TEXT,receipt_id TEXT)');prior=db.execute('select * from issues where request_id=?',(data['request_id'],)).fetchone()
                    if prior:
                        if prior['actor_id']!=actor['actor_id']or prior['record_json']!=encoded(record).decode():raise ValueError('问题提交标识冲突。')
                        return self.send(200,{'saved':True,'duplicate':True,'receipt_id':prior['receipt_id']})
                    receipt='ISS-'+secrets.token_hex(8).upper();db.execute('insert into issues values(?,?,?,?)',(data['request_id'],actor['actor_id'],encoded(record).decode(),receipt))
                return self.send(201,{'saved':True,'receipt_id':receipt})
            raise FileNotFoundError()
        except FileNotFoundError:return self.send(404,{'error':'未找到接口。'})
        except PermissionError as e:return self.send(403,{'error':str(e)})
        except (ValueError,TypeError,KeyError,IndexError,json.JSONDecodeError)as e:return self.send(400,{'saved':False,'error':str(e)})
        except Exception:return self.send(503,{'saved':False,'error':'暂时无法保存，请保留页面并稍后重试。'})

class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=64
    def __init__(self,releases,data_root,origin,port=0,*,fixtures=False):
        assert origin.startswith('https://')and'/'not in origin[8:]
        self.releases={r.batch:r for r in releases};self.origin=origin
        allids=[row['household_id']for r in releases for row in r.rows.values()];assert len(allids)==len(set(allids)),'cohorts overlap'
        signature=hashlib.sha256(encoded({r.batch:r.signature for r in releases})).hexdigest()
        self.store=Store(data_root,signature,fixtures=fixtures,cohort_releases={r.batch:r.signature for r in releases});self.request_slots=threading.BoundedSemaphore(8);super().__init__(('127.0.0.1',port),Handler)
    def process_request(self,request,client_address):
        self.request_slots.acquire()
        try:super().process_request(request,client_address)
        except BaseException:self.request_slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.request_slots.release()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release50',type=Path,required=True);p.add_argument('--release950',type=Path);p.add_argument('--data-root',type=Path,required=True);p.add_argument('--public-origin',required=True);p.add_argument('--port',type=int,default=18775);p.add_argument('--fixture-mode',action='store_true');a=p.parse_args();os.umask(0o077)
    releases=[Release(a.release50)]+([Release(a.release950)]if a.release950 else[]);server=Server(releases,a.data_root,a.public_origin,a.port,fixtures=a.fixture_mode);server.serve_forever()
