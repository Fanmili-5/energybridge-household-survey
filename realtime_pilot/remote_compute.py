"""Cloud-side worker proxy. The native EB/EP job runs as one remote process."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler
from common import digest, file_hash, write_json
from compute_protocol import PROTOCOL, MAX_ARCHIVE, release_hash, safe_unpack

def compute_connection():
    base=os.environ['EB_COMPUTE_URL'].rstrip('/')
    parsed=urlparse(base)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.username or parsed.path:
        raise ValueError('Compute endpoint must be SSH-forwarded loopback')
    token=Path(os.environ['EB_COMPUTE_TOKEN_FILE']).read_text().strip()
    opener=build_opener(ProxyHandler({}))
    def call(path,method='GET',value=None,timeout=15):
        data=None if value is None else json.dumps(value,allow_nan=False).encode()
        req=Request(base+path,data=data,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        return opener.open(req,timeout=timeout)
    return call

def check_remote_ready(*, expected=None, timeout=5):
    """Verify the live transport and loaded release without creating a job."""
    expected=expected or release_hash(verify_resources=False)
    with compute_connection()('/health',timeout=timeout) as response:
        health=json.load(response)
    if health.get('protocol')!=PROTOCOL or health.get('release')!=expected:
        raise ValueError('Compute release mismatch: deploy the same release to website and compute service, then restart compute')
    return health

def run_remote(folder):
    call=compute_connection()
    request=json.loads((folder/'request.json').read_text())
    # The compute service verifies the entire physical library at startup;
    # each native job verifies its selected IDF/EPW/DDY. Avoid re-reading the
    # nationwide archive on the 2-core web host for every submission.
    expected=release_hash(verify_resources=False);request_sha=digest(request)
    # A page/SSH listener being alive is insufficient. Detect a broken route or
    # partial deployment before creating a remote task or waiting for a lease.
    check_remote_ready(expected=expected)
    # Stable across cloud service recovery attempts for the same logical job.
    # A lost POST or a cloud restart must not start a second paid native run.
    scope=folder.parent.parent if folder.parent.name=='attempts' and folder.name.isdigit() else folder
    jid=digest({'job':str(scope.resolve()),'request':request_sha,'release':expected})
    path='/jobs/'+jid
    write_json(folder/'compute_transport.json',{'protocol':PROTOCOL,'job_id':jid,'release':expected,
               'request_hash':request_sha,'backend':'school_native_eb_ep'})
    payload={'protocol':PROTOCOL,'release':expected,'request_hash':request_sha,'request':request}
    started=time.monotonic();last_contact=started;submitted=False;finished=False
    deadline=int(os.environ.get('EB_REMOTE_TIMEOUT','660'))
    try:
        while time.monotonic()-started<deadline:
            try:
                with call(path,'GET' if submitted else 'POST',None if submitted else payload) as response:
                    state=json.load(response)
                last_contact=time.monotonic();submitted=True
                if state.get('release')!=expected or state.get('request_hash')!=request_sha:
                    raise ValueError('Remote result identity mismatch')
                if state.get('progress'):write_json(folder/'progress.json',state['progress'])
                if state['status'] in ('complete','failed') and state.get('archive_sha256'):
                    with tempfile.TemporaryDirectory(dir=folder.parent,prefix='compute-return-') as temp:
                        temp=Path(temp);archive=temp/'result.zip'
                        with call(path+'/archive') as response,archive.open('wb') as out:
                            total=0
                            while True:
                                block=response.read(1024*1024)
                                if not block:break
                                total+=len(block)
                                if total>MAX_ARCHIVE:raise ValueError('Remote result too large')
                                out.write(block)
                        if file_hash(archive)!=state['archive_sha256']:raise ValueError('Remote archive hash mismatch')
                        unpacked=temp/'unpacked';safe_unpack(archive,unpacked)
                        manifest=json.loads((unpacked/'transport_manifest.json').read_text())
                        for name,sha in manifest.items():
                            target=unpacked/name
                            if not target.resolve().is_relative_to(unpacked.resolve()) or file_hash(target)!=sha:
                                raise ValueError('Remote artifact hash mismatch')
                        if digest(json.loads((unpacked/'request.json').read_text()))!=request_sha:
                            raise ValueError('Remote request changed')
                        # Commit outcome last; the parent never sees a partial successful result.
                        for item in unpacked.iterdir():
                            if item.name in ('request.json','outcome.json'):continue
                            target=folder/item.name
                            if item.is_dir():shutil.copytree(item,target,dirs_exist_ok=True)
                            else:shutil.copy2(item,target)
                        if state['status']=='complete':
                            result=json.loads((unpacked/'outcome.json').read_text())
                            write_json(folder/'outcome.json',result)
                        write_json(folder/'compute_receipt.json',{**state,'archive_bytes':total,'transfer_complete':True})
                    finished=True
                    if state['status']!='complete':raise RuntimeError('Remote native job failed')
                    return
                if state['status'] in ('failed','cancelled','expired','interrupted'):
                    finished=True;raise RuntimeError('Remote job '+state['status'])
            except HTTPError as exc:
                if exc.code not in (429,502,503,504):raise
                if exc.code==429:write_json(folder/'progress.json',{'stage':'queued','message':'计算服务器繁忙，正在等待空闲位置。'})
            except (URLError,TimeoutError,ConnectionError):
                # Retry transport only with the same ID, never native execution.
                if time.monotonic()-last_contact>40:raise RuntimeError('Compute connection lost')
            time.sleep(2)
        raise TimeoutError('Remote computation exceeded deadline')
    finally:
        if not finished:
            try:
                with call(path,'DELETE'):pass
            except Exception:pass  # Remote heartbeat lease still enforces cancellation.
