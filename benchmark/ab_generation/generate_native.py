"""Reproducible household -> daily A -> one B per date, plan qualification only.

Run with --help. Source household JSONL, a reviewed physical reference and the
unchanged original appliance module are explicit inputs; no labels are created.
"""
import argparse
from copy import deepcopy
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

from .common import digest
from .eb_alignment import audit
from .model import apply
from .paper_v1_native_replay import replay
from .unified.candidates import generate_household_day
from .unified.contract import entry_config
from .unified.selection import select_block
from .v9_date_adapter import generate_day_baseline

def implementation():
    root=Path(__file__).resolve().parent
    files=[p for p in root.rglob("*") if p.is_file() and
           (p.suffix==".py" or p.suffix==".json" and not any(part in {"examples","validation"} for part in p.relative_to(root).parts)) and
           "__pycache__" not in p.parts and p.name!="PACKAGE_MANIFEST.json"]
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}

def record_raw_cells(catalogue):
    """Freeze legal root-cell denominator before selecting materialized rows."""
    mapping={};specs=[]
    for i,(descriptors,values) in enumerate(zip(catalogue["factors"],catalogue["native_domains"])):
        family=next(r["family"] for r in values if r)
        for descriptor in descriptors:
            if descriptor["label"]=="no_change":continue
            label=json.loads(descriptor["label"])
            if label[-1]!="event_root":continue
            eligible=[j for j in descriptor["ids"] if not values[j].get("_intrinsic_issues")]
            key=json.dumps([family,descriptor["label"]],ensure_ascii=False,separators=(",",":"))
            specs.append(dict(key=key,family=family,label=descriptor["label"],
                admissible_raw_alternatives=len(eligible),factor=i))
            for j in eligible:mapping[values[j]["id"]]=key
    catalogue["declared_raw_root_cells"]=specs
    for row in catalogue["rows"]:
        row["raw_root_cells"]=sorted({mapping[c["id"]] for c in row["components"] if c["id"] in mapping and c["event_relevance"]["role"]=="direct_event_request"})
    return catalogue

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))

def zipped(path,value):
    with gzip.open(path,'wt',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,separators=(',',':'))

def generate(case,dates,reference,manifest_sha256,out,native_source,configuration=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    cfg=deepcopy(configuration) if configuration is not None else entry_config(Path(__file__).with_name('GENERATION_REPAIR_CONFIG.json'))
    frozen=implementation();portrait=digest(case)
    save(out/'PRE_RUN.json',dict(schema='eb.native_daily_plan_pre_run.v2',household_sha256=portrait,
        source_manifest_sha256=manifest_sha256,reference_sha256=digest(reference),
        dates=dates,configuration=cfg,implementation=frozen,scope='plans_and_original_native_execution_only',
        physical_outcomes_computed=False,human_answers_generated=False))
    contexts={};candidates=[];catalogues=[]
    for date in dates:
        baseline=generate_day_baseline(case,date,reference,cfg,manifest_sha256,native_appliance_source_path=native_source)
        if baseline['status']!='accepted_plan_only':raise ValueError('DAILY_A_REJECTED:'+date+':'+baseline['status'])
        contexts[date]=baseline
        zipped(out/(date+'_A.json.gz'),baseline)
        catalogue=generate_household_day(baseline['context'],case,manifest_sha256,cfg,native_appliance_source_path=native_source)
        if catalogue['status']!='candidate_catalogue' or not catalogue['rows']:raise ValueError('NO_B_CANDIDATES:'+date)
        record_raw_cells(catalogue)
        candidates.extend(catalogue['rows'])
        # Literal domains regenerate from the frozen input/code/seed. Preserve
        # every materialized witness and the actual denominator, not just hits.
        catalogues.append({k:v for k,v in catalogue.items() if k not in {'native_domains','native_templates','support_native_domain'}})
    zipped(out/'CATALOGUES.json.gz',catalogues)
    selected=select_block(candidates,cfg);zipped(out/'SELECTION.json.gz',selected)
    chosen=[r for r in candidates if r['id'] in set(selected['selected_ids'])]
    if len(chosen)!=len(dates) or any(sum(r['date']==d for r in chosen)!=1 for d in dates):raise ValueError('ONE_B_PER_DATE_NOT_ESTABLISHED')
    pairs=[]
    for date in dates:
        e=contexts[date];context=e['context'];row=next(r for r in chosen if r['date']==date)
        b=apply(context['A'],row['patches']);native=audit(context,b,row['components'],side='B')
        if not native['passed']:raise ValueError('SELECTED_B_NATIVE_ERROR:'+date)
        traces={side:replay(e['problem'],context,plan,native_source) for side,plan in [('A',context['A']),('B',b)]}
        pair=dict(schema='eb.paper_v1.native_verified_pair.v2',date=date,
            source_household_sha256=portrait,source_manifest_sha256=manifest_sha256,
            A=context['A'],B=b,A_sha256=digest(context['A']),B_sha256=digest(b),
            selected_proposal=row,daily_service_contract=context['daily_service_requirements'],
            native_B_acceptance=native,paper_v1_execution=traces,
            physical_outcomes=None,human_answers=None,formal_questionnaire_release=False)
        name=date+'_PAIR.json.gz';zipped(out/name,pair)
        pairs.append(dict(date=date,path=name,A_sha256=pair['A_sha256'],B_sha256=pair['B_sha256']))
    if digest(case)!=portrait or implementation()!=frozen:raise ValueError('SOURCE_OR_IMPLEMENTATION_CHANGED_DURING_GENERATION')
    result=dict(schema='eb.native_daily_plan_result.v2',status='native_plan_qualification_passed',pairs=pairs,
        source_household_unchanged=True,implementation_unchanged=True,
        physical_outcomes_computed=False,formal_questionnaire_release=False,human_answers_generated=False)
    save(out/'RESULT.json',result)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--households',type=Path,required=True)
    parser.add_argument('--case-id',required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--start-date',required=True)
    parser.add_argument('--days',type=int,default=10)
    parser.add_argument('--native-source',type=Path,required=True)
    parser.add_argument('--configuration',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.days<1:parser.error('--days must be positive')
    raw=args.households.read_bytes();cases=[json.loads(line) for line in raw.splitlines() if line.strip()]
    matches=[c for c in cases if c['case_id']==args.case_id]
    if len(matches)!=1:parser.error('--case-id must identify exactly one input household')
    start=dt.date.fromisoformat(args.start_date);dates=[(start+dt.timedelta(days=i)).isoformat() for i in range(args.days)]
    cfg=entry_config(args.configuration) if args.configuration else None
    result=generate(matches[0],dates,json.loads(args.reference.read_text()),hashlib.sha256(raw).hexdigest(),args.out,args.native_source,cfg)
    if hashlib.sha256(args.households.read_bytes()).hexdigest()!=hashlib.sha256(raw).hexdigest():raise ValueError('HOUSEHOLD_SOURCE_FILE_CHANGED')
    print(json.dumps(dict(status=result['status'],questions=len(result['pairs']),physical_outcomes_computed=False,human_answers_generated=False)))
if __name__=='__main__':main()
