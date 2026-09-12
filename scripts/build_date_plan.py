"""Build candidate dates only; never promote them into the live validated pool."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'realtime_pilot'))
from common import file_hash
from date_sampling import candidates,SEASONS

def main():
    p=argparse.ArgumentParser();p.add_argument('--season',choices=SEASONS,default='summer');p.add_argument('--per-stratum',type=int,default=3);p.add_argument('--seed',default='eb-weather-v1');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    c=json.loads((ROOT/'simulation_resources/catalog.json').read_text());rows={}
    for w in c['weather']:
        if w['status']!='verified':continue
        epw=ROOT/w['epw']
        if file_hash(epw)!=w['epw_sha256']:raise ValueError('EPW changed')
        rows[w['id']]={'weather_sha256':w['epw_sha256'],'candidates':candidates(epw,a.seed+':'+w['id'],a.per_stratum,a.season)}
    result={'version':'eb.candidate_date_plan.v1','season':a.season,'seed':a.seed,'candidate_only':True,'weather':rows,'questionnaire_ready':False,'purpose':'optional offline coverage validation; live annual dates are assigned before intake'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(len(rows),'stations; candidate dates only')
if __name__=='__main__':main()
