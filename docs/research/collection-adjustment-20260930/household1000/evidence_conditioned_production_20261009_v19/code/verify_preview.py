"""Read back exact frozen pages/assets; prove the loopback preview cannot save answers."""
import argparse
import urllib.error
import urllib.request
from common import *

def main():
    school_guard();parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18789);args=parser.parse_args()
    origin='http://127.0.0.1:'+str(args.port);release=OUT/'frontend_release';index=read(release/'INDEX50.json')
    health=__import__('json').load(urllib.request.urlopen(origin+'/household50/api/health'))
    assert health['households']==50 and health['cases']==500 and not health['server_answer_writes']
    checked=0
    for h in index['households']:
        for name in ('index.html','style.css','candidate.css','joint-view.css','plan-view.js','source-draft.js','household-view.js','joint-view.js'):
            url=origin+h['route']+'/'+('' if name=='index.html' else name)
            assert urllib.request.urlopen(url).read()==(release/'households'/h['household_id']/name).read_bytes(),(h['household_id'],name)
            checked+=1
    try:
        urllib.request.urlopen(urllib.request.Request(origin+'/household50/api/answers',data=b'{}',method='POST'))
        raise AssertionError('POST unexpectedly accepted')
    except urllib.error.HTTPError as error:assert error.code==405
    report={'status':'pass','served_page_and_asset_bytes_checked':checked,'households':50,'actual_cases':500,
        'frontend_index_sha256':sha(release/'INDEX50.json'),'server_answers_writes':False,'POST_status':405,
        'question_contract':'original binary adoption,four optional scores,reason','human_answers':0}
    save(OUT/'READONLY_PREVIEW_REVIEW.json',report);print(report,flush=True)

if __name__=='__main__':main()
