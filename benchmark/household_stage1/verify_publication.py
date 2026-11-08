"""Verify public aggregate provenance and optional authorized household inputs."""
from pathlib import Path
from collections import Counter
import argparse,hashlib,json
from .required_controls import allowed_masks,validate_household
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--households',type=Path);args=parser.parse_args()
    manifest=read(HERE/'PACKAGE_MANIFEST.json')
    actual={str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file() and p.name!='PACKAGE_MANIFEST.json' and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    if actual!=set(manifest['files']):raise ValueError('PUBLIC_PACKAGE_INVENTORY_CHANGED')
    for name,pin in manifest['files'].items():
        if sha(HERE/name)!=pin:raise ValueError('PUBLIC_PACKAGE_FILE_CHANGED:'+name)
    current=read(HERE/'CURRENT.json');validation=read(HERE/'VALIDATION.json')
    if current['households']!=1000 or current['country_counts']!={co:125 for co in ('CN','US','GB','ES','IN','MX','AU','DE')}:raise ValueError('COUNTRY_QUOTAS_INVALID')
    if current['AC_present_households']!=1000 or current['AC_controlled_households']!=1000:raise ValueError('PUBLIC_AC_COUNTS_INVALID')
    if len(allowed_masks())!=16 or current['allowed_control_masks']!=16:raise ValueError('AC_PATTERN_DOMAIN_INVALID')
    if validation['status']!='passed' or validation['manifest_sha256']!=current['manifest_sha256']:raise ValueError('EVIDENCE_NOT_BOUND_TO_CURRENT')
    if any(current[k]!=0 for k in ('actual_physical_results','actual_AB_question_rows','actual_human_answers')):raise ValueError('STAGE1_SCOPE_INVALID')
    checked=0
    if args.households:
        if sha(args.households)!=current['manifest_sha256']:raise ValueError('CONTROLLED_MANIFEST_CHANGED')
        cases=[json.loads(x) for x in args.households.read_text().splitlines()]
        for c in cases:validate_household(c)
        if len(cases)!=1000 or len({c['case_id'] for c in cases})!=1000:raise ValueError('CONTROLLED_COHORT_SIZE_INVALID')
        if Counter(c['source']['country'] for c in cases)!=Counter(current['country_counts']):raise ValueError('CONTROLLED_COUNTRY_COUNTS_INVALID')
        if Counter(c['benchmark_role'] for c in cases)!=Counter(current['role_counts']):raise ValueError('CONTROLLED_ROLE_COUNTS_INVALID')
        checked=len(cases)
    print(json.dumps({'passed':True,'public_files_verified':len(actual),'private_households_checked':checked,
      'full_raw_source_audit_replayed':False,'EP_runs':0,'human_answers_created':0}))
if __name__=='__main__':main()
