"""Offline recheck of the already school-accepted sealed50;no source/SQL rerun."""
import argparse,hashlib,json,math,re,subprocess,tarfile
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--artifact-directory',type=Path,required=True);parser.add_argument('--repository-root',type=Path,required=True);args=parser.parse_args();A=args.artifact_directory;ROOT=args.repository_root
SIGNATURE='0c6893ef23e8467218b1e0489e4baa98ef2514b4d15f2028143d4b3669faa9f0'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,x):(A/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
    dest=A/'sealed50';dest.mkdir(exist_ok=True,mode=0o700)
    with tarfile.open(A/'formal50_v30.tar.gz')as tar:
        for m in tar.getmembers():
            p=dest/m.name;assert m.isfile()and not m.issym()and p.resolve().is_relative_to(dest.resolve())
            data=tar.extractfile(m).read();p.parent.mkdir(parents=True,exist_ok=True)
            if p.exists():assert p.read_bytes()==data
            else:p.write_bytes(data)
    root=dest/SIGNATURE[:16];m=json.loads((root/'FORMAL_RELEASE.json').read_text())
    assert m['release_signature']==SIGNATURE and m['batch']=='formal50'and len(m['households'])==50
    expected=hashlib.sha256(json.dumps({k:v for k,v in m.items()if k!='release_signature'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest();assert expected==SIGNATURE
    for n,h in m['files'].items():assert sha(root/n)==h
    count=equal=0;thermal=water=target_changes=0
    for row in m['households']:
        page=(root/'households'/row['household_id']/'index.html').read_text()
        cases=json.loads(re.search(r'id="joint-cases-data"[^>]*>(.*?)</script>',page,re.S).group(1));assert len(cases)==10
        for c in cases:
            count+=1;assert c['human_label_count']==0 and c['training_release']is False
            for side in('A','B'):assert c['plans'][side]['window_end_abs_min']-c['plans'][side]['window_start_abs_min']==1440
            assert {q['scope']for q in c['quantities']}=={'event','living_day','living_day_and_service_tail'}
            for q in c['quantities']:
                assert all(math.isfinite(q[s]['value'])and q[s]['status']=='computed'for s in('A','B'))
            same=all(math.floor(q['A']['value']*1000+.5)==math.floor(q['B']['value']*1000+.5)for q in c['quantities'])
            sides={s:sorted(x['description'][1:]for x in c['impacts']if re.match('^'+s+r'(?:\s|（)',x.get('description','')))for s in('A','B')}
            equal+=same and sides['A']==sides['B']
            thermal+=any(x['kind']=='ac_setpoint'for x in c['commands'])
            water+=any(x['device_class']=='electric_water_heater'for x in c['commands'])
            for x in c['commands']:
                if x['device_class']=='electric_water_heater'and x.get('from_setpoint_C')is not None and x.get('to_setpoint_C')is not None and x['from_setpoint_C']!=x['to_setpoint_C']:
                    assert f"{x['from_setpoint_C']:g}℃"in x['display_change_text']and f"{x['to_setpoint_C']:g}℃"in x['display_change_text'];target_changes+=1
    assert count==500 and equal==0 and target_changes>0
    node=json.loads(subprocess.run(['node',str(ROOT/'deploy/formal_questionnaires_20261014/verify_formal_bindings.cjs'),str(root)],check=True,capture_output=True,text=True).stdout)
    assert node['passed']and node['case_bindings_verified']==500
    result={'schema':'eb.sealed50_offline_recheck.v30','passed':True,'release_signature':SIGNATURE,'households':50,'cases_checked':500,
        'payload_files_hash_checked':len(m['files']),'same_displayed_outcomes':equal,'actual_shipped_JS_bindings':node,
        'cases_with_thermal_commands':thermal,'cases_with_tank_commands':water,'all_cases_full24hour_living_day':True,
        'hotwater_target_change_texts_checked':target_changes,
        'source_SQL_or_real_browser_rerun':False,'scope':'sealed package hashes,structural stimuli,visible outcomes and shipped JS canonical bindings only;school source/physics/browser acceptance was already completed',
        'human_answers_created':0,'training_release':False}
    save('SEALED50_LOCAL_REVIEW.json',result);print(result)
if __name__=='__main__':main()
