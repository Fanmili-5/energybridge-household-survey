#!/usr/bin/env python3
"""Bind the source review to its exact local inputs and honest access status."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PUBLIC=HERE.parent/'evidence_contract_20261001'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    c=read(PUBLIC/'CITY_AUTHORITY_CONSTRAINTS_V2.json')
    package=read(HERE/'PACKAGE_MANIFEST.json')
    sources=[]
    for k,t in c['tables'].items():
        p=PUBLIC/t['file'];assert sha(p)==t['sha256']
        sources.append({'id':'NBS_'+k,'publisher':'国家统计局','title':t['title'],
            'url':t['url'],'observation_year':2020,'retrieved_date_HKT':'2026-10-01',
            'local_file':str(p.relative_to(HERE.parent)),'sha256':t['sha256'],
            'access':'downloaded_and_spreadsheet_validated','frame':t['frame'],
            'provenance_coordinates':'worksheet and1-based Excel rows in CITY_AUTHORITY_CONSTRAINTS_V2.json',
            'allowed_use':'the actual joint/marginal categories in this table, with its denominator and eligibility bridge',
            'forbidden_use':'unobserved household joint, arbitrary bin midpoint, electric heater/EV/home-charge inference or all-city extrapolation from ordinary housing sample'})
    p=PUBLIC/'raw/census2020_plan_retry.pdf'
    sources.append({'id':'NBS_INDICATORS','publisher':'国家统计局','url':c['indicator_authority']['url'],
        'local_file':str(p.relative_to(HERE.parent)),'sha256':sha(p),'access':'PDF_text_read',
        'pages_1based':c['indicator_authority']['pages_1based'],'observation_year':2020,
        'allowed_use':'H5 housing skip pattern, H6 area conversion, H7 room definition, H8-H19 field semantics',
        'forbidden_use':'derive a calibrated floorplan, modern appliance ownership, household control consent or every city household living in ordinary housing'})
    for name,sourceid,allowed,forbidden in [
        ('nbs_long_short_definition.html','NBS_LONG_SHORT','short-form full census versus long-form10percent sampled published counts','multiply published long-form counts by10 as exact full counts'),
        ('census2020_preface.html','NBS_PREFACE','actual enumeration aggregation, long-form sample denominator, reference date','ignore survey frame/rounding/registration error'),
        ('timeuse_2024_1.html','NBS_TIMEUSE_METHOD','survey population6plus, day design and diary resolution','source under6 activity or exact city-only household schedules'),
        ('timeuse_2024_2.html','NBS_TIMEUSE_TOTAL','auxiliary individual time-budget/participation margins, weekday5/7+weekend2/7','hard city household clock/operator quotas'),
        ('timeuse_2024_3.html','NBS_TIMEUSE_PARTICIPANT','conditional participant-duration means','replace overall means or identify activity clock time'),
        ('income_2025.html','NBS_INCOME_2025','urban(city+town) per-capita annual disposable income context','city-only household salary or household joint target'),
        ('CHFS_2026_release.html','CHFS_RELEASE','public file/wave/weight documentation','claim approved or downloaded microdata'),
        ('CHFS_application.html','CHFS_APPLICATION','verify official application availability','treat2023/2025 as already publicly applied/downloaded'),
        ('CHFS_use_terms.html','CHFS_TERMS','official access and use terms','reuse unapproved third-party microdata'),
        ('CRECS_samples_http.html','CRECS_CATALOG','identify year/topic/population and2013 rural exclusion','assume later thematic collections are downloaded national city samples'),
        ('CRECS_application_http.html','CRECS_APPLICATION','official2012/2013/2014 application/research-use terms','redistribute data or treat download as representative city sample'),
        ('haier_HW9_B176U1.html','HAIER_DISHWASHER_PAGE','one-model dimensions/rated parameters; keep capacity conflict','ownership rate or sustained-cycle power'),
        ('haier_HW9_B176U1_manual.pdf','HAIER_DISHWASHER_MANUAL','one-model installation/program documentation; PDF p1/p20/p26 checked','resolve9-versus10-place conflict without explanation or invent energy curve/duration')]:
        p=PUBLIC/'raw'/name;assert p.exists(),name
        manifests=read(PUBLIC/'PUBLIC_DOWNLOADS.json')['sources']+read(PUBLIC/'PUBLIC_SUPPLEMENT.json')['sources']+read(PUBLIC/'PUBLIC_DOCUMENTATION.json')['sources']
        candidates=[v for v in manifests if v.get('name')==name and v.get('path')]
        url=candidates[-1]['url'] if candidates else 'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/note.htm'
        sources.append({'id':sourceid,'url':url,'local_file':str(p.relative_to(HERE.parent)),
            'sha256':sha(p),'access':'downloaded_public_document_read','retrieved_date_HKT':'2026-10-01',
            'allowed_use':allowed,'forbidden_use':forbidden})
    for e in package['entries']:
        y=e['year'];is_data=e['format']=='.dta'
        sources.append({'id':f'CRECS{y}_'+('DATA' if is_data else 'QUESTIONNAIRE'),
            'publisher_identification':'中国人民大学CRECS/CGSS as identified by questionnaire; archive externally provided by user',
            'observation_year':y,'external_download_url':'not provided',
            'catalog_url':'http://crecs.ruc.edu.cn/sjjs/Introduction/index.htm',
            'local_file':e.get('local_file'),'sha256':e['sha256'],
            'access':'excluded_rural_microdata_not_loaded' if y==2013 else
                     'local_microdata_aggregate_QC_completed' if is_data else 'local_questionnaire_text_and_relevant_pages_checked',
            'allowed_use':'2012 city-labeled historical same-record support;2014 questionnaire/schema pending city/weight metadata' if y!=2013 else 'exclusion record only',
            'forbidden_use':'current weighted national-city frequencies, missing as zero, unsupported exact-clock activities, EnergyBridge human acceptance labels',
            'raw_rows_exported':0})
    sources.append({'id':'HAIER_AC_EXAMPLE','publisher':'海尔','url':'https://www.haier.com/air_conditioners/20130503_99020.shtml',
        'access':'full_webpage_read_2026-10-03','local_file':None,'sha256':None,
        'allowed_use':'verify cooling capacity and electric input are different quantities; inference aid for survey power-band semantics',
        'forbidden_use':'infer survey authors intended term as confirmed fact, national ownership, or a universal performance curve'})
    ids=[s['id'] for s in sources];assert len(ids)==len(set(ids))
    fields=read(HERE/'FIELD_SOURCE_RULES.json')
    rule_refs={r['id']:([f'CRECS{r["year"]}_DATA',f'CRECS{r["year"]}_QUESTIONNAIRE'] if r['year'] else []) for r in fields['rules']}
    for v in rule_refs.values():assert set(v)<=set(ids)
    out={'batch_id':'CITY1000_SOURCE_LEDGER_20261003_V1','source_count':len(sources),'sources':sources,
        'rule_source_ids':rule_refs,'parameter_semantics_addendum':'PARAMETER_INTERPRETATION.json',
        'formal_population_reference':'../city_representativeness_20261001/CITY_TARGET_AUDIT.json',
        'source_QC':'CRECS_SOURCE_QC.json','support_gaps':'SUPPORT_GAP_MATRIX.json',
        'full_generation_gates':'PILOT_ACCEPTANCE.json',
        'no_raw_microdata_public_release':True,'no_remote_jobs':True,'collection_release':False,
        'code_sha256':sha(Path(__file__))}
    with (HERE/'SOURCE_LEDGER.json').open('x') as f:json.dump(out,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'source_count':len(sources),'rule_groups':len(rule_refs),'collection_release':False},ensure_ascii=False))

if __name__=='__main__':main()
