"""Run actual shipped questionnaire in school Chromium; isolated invented actors only."""
import argparse,json,re,ssl,subprocess,sys,tempfile,threading
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'formal_questionnaires_20261014'))
from server import Server,Release

def run(release_path,output,node,tools,maximum):
    release=Release(release_path)
    with tempfile.TemporaryDirectory(prefix='eb-v29-browser-fixture-')as tmp:
        root=Path(tmp);cert=root/'cert.pem';key=root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1','-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        server=Server([release],root/'fixture_db','https://127.0.0.1',0,fixtures=True)
        server.origin='https://127.0.0.1:'+str(server.server_port)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key);server.socket=tls.wrap_socket(server.socket,server_side=True)
        rows=list(release.rows.values())
        # 50: all 500 pages. 950: deterministic spread, 100 complete households.
        if maximum and maximum<len(rows):rows=[rows[i*len(rows)//maximum]for i in range(maximum)]
        fixtures=[]
        for i,row in enumerate(rows):
            token='invented-browser-fixture-invitation-'+str(i).zfill(5)
            server.store.provision([('browser-fixture-'+str(i),release.batch,row['household_id'],token)])
            _,_,cases,_=release.household(row['route'])
            fixtures.append({'route':row['route'],'household_id':row['household_id'],'credential':token,'cases':cases})
        config={'origin':server.origin,'prefix':release.prefix,'release_signature':release.signature,'source_case_count':len(release.rows)*10,'fixtures':fixtures,'output':str(output),'tools':str(tools)}
        configpath=root/'private-config.json';configpath.write_text(json.dumps(config,ensure_ascii=False))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            script=HERE/'browser_fixture_parallel.cjs'
            subprocess.run([str(node),str(script),str(configpath)],check=True)
            with server.store.connect()as db:
                records=[json.loads(r[0])for r in db.execute('select record_json from answers')]
            assert len(records)==2 and all(r['human_label_count']==0 and r['label_origin']=='engineering_fixture'for r in records)
            assert server.store.export()==[]
            report=json.loads(output.read_text());report.update(isolated_fixture_database=True,fixture_submissions=len(records),production_records_written=0,human_answers_generated=0,fixture_formal_export_count=0)
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False),flush=True)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--node',type=Path,required=True);p.add_argument('--tools',type=Path,required=True);p.add_argument('--maximum-households',type=int,default=0);a=p.parse_args();run(a.release,a.output,a.node,a.tools,a.maximum_households)
