#!/usr/bin/env python3
"""Directed actual-IDF signature and split counterexamples; edits only /tmp."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib
import json
import re
import shutil
import tempfile
import subprocess
from build_actual_dependency_plan import actual_closure,verify_triple_split

HERE=Path(__file__).resolve().parent
H=HERE.parent.parent
STAGE=H/'household_to_idf_v3_20261003/frozen_v2_context_comparison_v1'
PLAN=HERE/'baseline_ACTUAL_DEPENDENCY_PLAN_v2.json'
p=json.loads(PLAN.read_text());rows=p['rows'];checks=[]
def check(name,ok,detail=None):checks.append({'name':name,'passed':bool(ok),'detail':detail})
check('1000retained',len(rows)==1000 and len({r['slot_id'] for r in rows})==1000)
check('ready849blocked151',p['counts']['ready']==849 and p['counts']['blocked']==151)
check('triplezero',verify_triple_split(rows)['pass'])
check('no_population_new_samples',p['population_slots_reallocated'] is False)
check('51components',p['counts']['components']==51)
check('allfold200',p['counts']['prototype_fold_sizes']==[200]*5)
check('refusalnull',all(r['actual_used_assembly_signature'] is None for r in rows if r['structural_status']=='blocked'))
for key in ['source_group_id','assembly_numeric_signature','actual_used_assembly_signature']:
 x=deepcopy(rows);counts=Counter(r[key] for r in x if r[key] is not None);unit=counts.most_common(1)[0][0]
 victim=next(r for r in x if r[key]==unit);victim['prototype_test_fold']=(victim['prototype_test_fold']+1)%5
 for other in ['source_group_id','assembly_numeric_signature','actual_used_assembly_signature']:
  if other!=key:victim[other]=None if other=='actual_used_assembly_signature' else 'unique-counterexample'
 v=verify_triple_split(x);check('isolated_fold_leak_'+key,not v['pass'],v)
x=deepcopy(rows);next(r for r in x if r['structural_status']=='blocked')['actual_used_assembly_signature']='a'*64
check('rejected_actual_signature_detected',not verify_triple_split(x)['pass'])

r=next(r for r in rows if r['structural_status']=='idf_ready')
summary=json.loads((STAGE/'SUMMARY.json').read_text());status=next(x for x in summary['records'] if x['case_id']==r['case_id'])
folder=STAGE/'cases'/status['case_folder'];original=actual_closure(folder)
temp=Path(tempfile.mkdtemp(prefix='actual_closure_policy_checks_',dir='/private/tmp'))
def case(name):
 d=temp/name;d.mkdir();shutil.copyfile(folder/'ASSEMBLY_BINDING.json',d/'ASSEMBLY_BINDING.json');shutil.copyfile(folder/'building.idf',d/'building.idf');return d
d=case('material_rename');b=json.loads((d/'ASSEMBLY_BINDING.json').read_text());firstmat=next(z[1] for z in b['source_assembly_rows'] if z[0].casefold()=='material')
(d/'building.idf').write_text((d/'building.idf').read_text().replace(firstmat,'Counterexample_Renamed_Material'))
check('material_names_do_not_create_novelty',actual_closure(d)['signature']==original['signature'])
d=case('numeric_change');s=(d/'building.idf').read_text();pat=re.compile(r'(Material\s*,\s*[^,]+,\s*[^,]+,\s*)([^,]+)',re.I)
s,n=pat.subn(lambda m:m[1]+str(float(m[2].strip())+.001),s,count=1);(d/'building.idf').write_text(s)
check('physical_numeric_change_changes_signature',n==1 and actual_closure(d)['signature']!=original['signature'])
d=case('reverse_layers');b=json.loads((d/'ASSEMBLY_BINDING.json').read_text());name=b['construction_map']['external_wall'];s=(d/'building.idf').read_text();pat=re.compile(r'Construction\s*,\s*'+re.escape(name)+r'\s*,([^;]+);')
s,n=pat.subn(lambda m:'Construction,'+name+','+','.join(reversed([x.strip() for x in m[1].split(',')]))+';',s,count=1);(d/'building.idf').write_text(s)
check('ordered_layers_not_set_equivalent',n==1 and actual_closure(d)['signature']!=original['signature'])
for name,mutation in [('unsupported_addon','MaterialProperty:PhaseChange,Fake,0,10;'),('unknown_declared_assembly',None)]:
 d=case(name)
 if mutation:(d/'building.idf').write_text((d/'building.idf').read_text()+'\n'+mutation)
 else:
  b=json.loads((d/'ASSEMBLY_BINDING.json').read_text());old=b['construction_map']['external_wall'];(d/'building.idf').write_text((d/'building.idf').read_text().replace(old,'Declared_Unknown_Construction'))
 try:actual_closure(d);refused=False
 except (ValueError,KeyError):refused=True
 check(name+'_fails_closed',refused)

bad=temp/'bad_planned.json';p0=json.loads((HERE.parent/'BASELINE_DEPENDENCY_PLAN.json').read_text());p0['rows'][0]['family_sha256']='b'*64;bad.write_text(json.dumps(p0,ensure_ascii=False))
out=temp/'must_not_exist.json';cli=subprocess.run(['/Users/fanmili/studytest/.venv/bin/python',str(HERE/'build_actual_dependency_plan.py'),'--planned',str(bad),'--static',str(STAGE),'--output',str(out)],capture_output=True,text=True)
check('generation_digest_mismatch_blocks_before_output',cli.returncode!=0 and not out.exists() and 'planned_generation_binding_mismatch' in cli.stderr)
report={'schema':'eb.actual_dependency_plan.directed_verification.v1','checks':len(checks),'passed':sum(x['passed'] for x in checks),'failures':sum(not x['passed'] for x in checks),'results':checks,
 'report_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
 'builder_sha256':hashlib.sha256((HERE/'build_actual_dependency_plan.py').read_bytes()).hexdigest(),
 'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'scope':'synthetic counterexamples on copied actual-IDF case files in/tmp;no existing artifacts changed;source/physical split only,not human model evaluation'}
(HERE/'ACTUAL_DEPENDENCY_VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['checks','passed','failures']}));raise SystemExit(bool(report['failures']))
