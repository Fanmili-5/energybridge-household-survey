"""Collect an explicit private receipt set after complete scientific-scope closure."""
import argparse,datetime,hashlib,json,tarfile
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def main(stage,output):
    complete=read(stage/'PHYSICAL_PRODUCTION_COMPLETE.json');assert complete['passed']and complete['substantive_task_contrast_verified']
    expected=read(stage/'REVIEWED_CODE_EXPECTATIONS.json')['expected_code_sha256']
    actual={p.name:sha(p)for p in(stage/'code').iterdir()if p.is_file()and p.suffix in('.py','.js','.cjs','.R')}
    assert actual==expected,'school execution code differs from reviewed source'
    parity={'schema':'eb.reviewed_source_parity.v30','passed':True,'code_files_checked':len(actual),'code_sha256':actual,
        'input_signature':complete['input_signatures']['other950'],'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (stage/'REVIEWED_SOURCE_PARITY.json').write_text(json.dumps(parity,indent=2)+'\n')
    names=['EB_AC_SOURCE_REVIEW.json','PROTOCOL_V29.json','CONTRAST_NEGATIVE_CONTROLS.json','PUBLIC_CONTRAST_SUMMARY.json','PHYSICAL_PRODUCTION_COMPLETE.json','REVIEWED_SOURCE_PARITY.json','INPUT_AUDIT.json','CLUSTER_COVERAGE1000_REVIEW.json','ORIGINAL50_CONTRAST_ACCEPTANCE.json','OTHER950_CONTRAST_ACCEPTANCE.json']
    for scope in('original50','other950','weather_sensitivity'):
        for prefix in('PHYSICS','SUBSTANTIVE','CONTROL_SQL'):names.append(f'{prefix}_{scope}_REVIEW.json')
    for batch in('formal50','formal950'):
        names.extend([f'FORMAL_{batch}_CASE_REVIEW.json',f'HTTP_{batch}_REVIEW.json',f'CASE_NEGATIVE_{batch}.json',f'BROWSER_{batch}_REVIEW.json',f'CONTRAST_{batch}_INPUT.json'])
    with tarfile.open(output,'w:gz')as t:
        for name in names:t.add(stage/name,arcname=name,recursive=False)
    print(json.dumps({'receipt_files':len(names),'archive_bytes':output.stat().st_size,'source_parity':True,'code_files':len(actual)}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.stage,a.output)
