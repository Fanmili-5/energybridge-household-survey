"""Prepare all eight supported sources from explicitly supplied original files."""
from pathlib import Path
import json
from .engine import load_engine,bind_sources,digest

def prepare(config_file,out):
    out=Path(out)
    if out.exists():raise ValueError('OUTPUT_EXISTS; choose a fresh directory')
    out.mkdir(parents=True)
    engine=load_engine();a=engine.a
    paths,layout,sources=bind_sources(engine,config_file,out)
    # Build current US/IN/MX records afresh; the port removes unused historic routes.
    old=a.components.seed.load_candidates()
    records=[]
    for co in ('US','IN','MX'):
        for row in old[co]:
            a.components.sources.enrich(row)
            row['pool_id']=row['source']['dataset']+':'+row['source']['household_key']
            records.append(row)
    intermediate=layout/'v7/inputs/candidate_pool.jsonl';a.write_rows(intermediate,records)
    a.ROOT=out
    pools=a.build_source_pools(sources)
    de,*_=a.shared.german_pool();au,*_=a.shared.australia_pool()
    pools.update(DE=de,AU=au)
    ordered=[row for co in ('CN','US','GB','ES','IN','MX','AU','DE') for row in pools[co]]
    pool=out/'candidate_pool.jsonl';a.write_rows(pool,ordered)
    report={'schema':'eb.household.normalized_source_pool.v1','source_scope':'licensed historical survey inputs; roles are not observed',
       'records':len(ordered),'country_candidates':{c:len(v) for c,v in pools.items()},'pool_file':'candidate_pool.jsonl','pool_sha256':digest(pool),
       'data_config':str(Path(config_file).resolve()),'source_files':{k:{'filename':p.name,'sha256':digest(p)} for k,p in paths.items()},
       'hidden_historical_inputs_required':False,'raw_survey_records_redistributed':False,'actual_human_answers':0}
    (out/'SOURCE_POOL.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('data_config','source_files')},ensure_ascii=False),flush=True)
    return report
