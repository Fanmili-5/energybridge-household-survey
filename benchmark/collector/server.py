"""Original-50 formal collection service with a separate immutable release/ledger."""
import argparse
import hmac
import json
import mimetypes
import os
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from release import Release,PREFIX,UI_VERSION,encoded
from ledger import CollectionStore,Conflict

COOKIE='eb_current50_v69'
ASSETS={'base.css','view.css','required-response.js','view.js','collection-client.js','entry.js'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def send(self,status,value,*,mime='application/json; charset=utf-8',token=None,location=None):
        raw=value if isinstance(value,bytes)else encoded(value)
        self.send_response(status)
        headers={'Content-Type':mime,'Content-Length':str(len(raw)),'Cache-Control':'no-store',
                 'Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
                 'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"}
        if token:headers['Set-Cookie']=f'{COOKIE}={token}; Path={PREFIX}; HttpOnly; SameSite=Lax; Max-Age=2592000'+('; Secure'if self.server.origin.startswith('https:')else'')
        if location:headers['Location']=location
        for k,v in headers.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(raw)

    def session(self,create=False):
        jar=SimpleCookie()
        try:jar.load(self.headers.get('Cookie',''));item=jar.get(COOKIE);token=item.value if item else None
        except Exception:token=None
        return self.server.store.session(token,create)

    def routed_path(self):
        path=urlsplit(self.path).path
        if path==PREFIX:return ''
        if not path.startswith(PREFIX+'/'):raise FileNotFoundError()
        return path[len(PREFIX)+1:]

    def do_GET(self):
        try:
            if urlsplit(self.path).path==PREFIX:return self.send(302,b'',location=PREFIX+'/')
            path=self.routed_path();release=self.server.release;store=self.server.store
            if path=='api/health':return self.send(200,{'mode':'engineering_fixture'if store.fixtures else'formal_role_collection',
                'households':len(release.households),'cases':len(release.records),'release_sha256':release.signature,'ui_revision':UI_VERSION,
                'presentation_revision':release.manifest.get('presentation_revision',UI_VERSION),
                'entry_mode':'open_no_invitation','questions_per_participant':release.questions_per_household,'cohort_id':store.cohort,
                'assignment_policy':'system_assigned_stable_participant_optional_rounds.v1','questions_per_round':release.questions_per_household,
                'A_stage':release.manifest['A_stage'],'B_stage':release.manifest['B_stage'],
                'physical_stage':release.manifest['physical_stage'],'impact_stage':release.manifest['impact_stage'],
                'formal_collection_ready':release.manifest.get('formal_collection_ready',False),
                'physical_statuses':release.manifest.get('physical_statuses',{}),
                'human_collection_release':not store.fixtures,'training_release':False,'full1000_deferred_by_user':True})
            if path in ASSETS:
                return self.send(200,release.file('public/'+path),mime=(mimetypes.guess_type(path)[0]or'application/octet-stream')+'; charset=utf-8')
            session,token=self.session(create=True)
            if path=='api/state':return self.send(200,{**store.state(session),'csrf':session['csrf']},token=token)
            if path=='':
                return self.send(200,release.file('public/entry.html'),mime='text/html; charset=utf-8',token=token)
            if path=='form':
                try:store.actor(session,consent=True)
                except PermissionError:return self.send(302,b'',token=token,location=PREFIX+'/')
                return self.send(200,release.file('public/index.html'),mime='text/html; charset=utf-8',token=token)
            a=store.actor(session,consent=True)
            if path=='index.json':return self.send(200,release.actor_index(a['household_id'],store.state(session)['resume_date']),token=token)
            if path.startswith('cases/'):
                row=release.by_path.get(path)
                if not row or row['household_id']!=a['household_id']:raise PermissionError('此题不属于当前家庭。')
                return self.send(200,release.file('public/'+path),token=token)
            if path=='households/'+a['household_id']+'.json':return self.send(200,release.file('public/'+path),token=token)
            raise FileNotFoundError()
        except FileNotFoundError:return self.send(404,{'error':'未找到此资源。'})
        except PermissionError as e:return self.send(403,{'error':str(e)})
        except Exception:return self.send(503,{'error':'问卷暂时无法核验，请稍后重试。'})

    def do_POST(self):
        try:
            path=self.routed_path();session,_=self.session()
            if not session or self.headers.get('Origin')!=self.server.origin or not hmac.compare_digest(session['csrf'],self.headers.get('X-EB-CSRF','')):
                raise PermissionError('会话已失效或来源不一致，请刷新。')
            length=int(self.headers.get('Content-Length','0'))
            if not 1<=length<=256*1024 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('请求格式无效。')
            def invalid_constant(x):raise ValueError('数字格式无效。')
            value=json.loads(self.rfile.read(length),parse_constant=invalid_constant);store=self.server.store
            if path=='api/start':
                if value!={}:raise ValueError('进入请求不需要其他字段。')
                return self.send(200,store.start_open(session))
            if path=='api/recover':
                if not isinstance(value,dict)or set(value)!={'credential'}:raise ValueError('恢复码格式无效。')
                return self.send(200,store.claim(session,store.cohort,value['credential'],self.headers.get('X-Real-IP')or self.client_address[0]))
            if path=='api/consent':return self.send(200,store.consent(session,value))
            if path=='api/next-round':return self.send(200,store.next_round(session,value))
            if path=='api/view':return self.send(200,store.view(session,value))
            if path=='api/draft':return self.send(200,store.draft(session,value))
            if path=='api/revert':return self.send(200,store.draft(session,value,clear=True))
            if path=='api/answers':return self.send(201,store.save(session,value))
            if path=='api/withdraw':
                if value!={}:raise ValueError('撤回请求无效。')
                return self.send(200,store.withdraw(session))
            if path=='api/logout':
                if value!={}:raise ValueError('退出请求无效。')
                with store.connect()as db:db.execute('update sessions set actor_id=NULL where session_digest=?',(session['session_digest'],))
                return self.send(200,{'logged_out':True})
            raise FileNotFoundError()
        except FileNotFoundError:return self.send(404,{'error':'未找到此接口。'})
        except PermissionError as e:return self.send(403,{'saved':False,'error':str(e)})
        except Conflict as e:return self.send(409,{'saved':False,'error':str(e)})
        except (ValueError,TypeError,KeyError,IndexError)as e:return self.send(400,{'saved':False,'error':str(e)})
        except Exception:return self.send(503,{'saved':False,'error':'暂时无法保存，未提交修改仍保留在本机，请稍后重试。'})


class Server(ThreadingHTTPServer):
    daemon_threads=True;request_queue_size=32
    def __init__(self,release,root,origin=None,port=0,*,fixtures=False):
        self.release=release;self.store=CollectionStore(root,release,fixtures=fixtures)
        assert not release.manifest['fixture_only']or fixtures,'Synthetic protocol fixtures cannot run as human collection.'
        self.slots=threading.BoundedSemaphore(8)
        super().__init__(('127.0.0.1',port),Handler)
        self.origin=origin or f'http://127.0.0.1:{self.server_port}'
        parsed=urlsplit(self.origin)
        assert parsed.path in ('','/')and not parsed.query and not parsed.fragment
        assert parsed.scheme=='https' or (fixtures and parsed.scheme=='http'and parsed.hostname=='127.0.0.1')
        self.origin=self.origin.rstrip('/')

    def process_request(self,request,address):
        self.slots.acquire()
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise

    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--public-origin');p.add_argument('--port',type=int,default=18783);p.add_argument('--fixture-mode',action='store_true')
    a=p.parse_args();os.umask(0o077)
    if not a.fixture_mode and not a.public_origin:raise ValueError('正式服务必须指定HTTPS入口。')
    s=Server(Release(a.release),a.data_root,a.public_origin,a.port,fixtures=a.fixture_mode)
    print(json.dumps({'origin':s.origin,'prefix':PREFIX,'fixture_mode':a.fixture_mode,'households':len(s.release.households),'cases':len(s.release.records)}),flush=True)
    try:s.serve_forever()
    finally:s.server_close()
