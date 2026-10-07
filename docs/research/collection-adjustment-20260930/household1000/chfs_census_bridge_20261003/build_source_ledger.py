#!/usr/bin/env python3
"""Bind bridge rules to locked inputs and verify local byte integrity."""
import json
from pathlib import Path
from run_bridge import HERE, PARENT, BATCH, sha, write

def main():
    prior_path=PARENT/'chfs_admission_20261003/SOURCE_LEDGER.json'
    prior=json.loads(prior_path.read_text())
    aliases={
        'chfs2021_hh_pub_v0_20260131.dta':'CHFS2021_HOUSEHOLD_MICRODATA',
        'chfs2021_ind_pub_v0_20260131.dta':'CHFS2021_INDIVIDUAL_MICRODATA',
        'chfs2021_master_hh_pub_v0_20260131.dta':'CHFS2021_HOUSEHOLD_MASTER',
        'chfs2021_master_ind_pub_v0_20260131.dta':'CHFS2021_INDIVIDUAL_MASTER',
        'CHFS2021综合变量计算表.xlsx':'CHFS2021_CALCULATION_WORKBOOK',
        'CHFS数据使用说明-2021.pdf':'CHFS2021_USE_MANUAL',
        '2021年中国家庭金融调查(CHFS)问卷.pdf':'CHFS2021_QUESTIONNAIRE',
        '2022年中国家庭金融调查(CHFS)问卷.pdf':'CHFS2022_QUESTIONNAIRE',
        'CITY_AUTHORITY_CONSTRAINTS_V2.json':'CENSUS2020_DERIVED_CITY_CONSTRAINTS',
        'POPULATION_ALLOCATION_CANDIDATE_V2.json':'CENSUS2020_TARGET1000_ALLOCATION'
    }
    entries=[]
    for item in prior['entries']:
        e=dict(item)
        base=Path(e.get('local_path',e['source_id'])).name
        e['prior_source_id']=e['source_id']
        e['source_id']=aliases.get(base,e['source_id'])
        e['read_status_this_bridge']='source-native subset read locally in run_bridge' if base in {
            'chfs2021_hh_pub_v0_20260131.dta','chfs2021_ind_pub_v0_20260131.dta','chfs2021_master_hh_pub_v0_20260131.dta'
        } else ('questionnaire/manual semantics reviewed; not a new financial re-estimation' if base.endswith(('.pdf','.xlsx')) else 'inherited admission evidence or target quota input')
        entries.append(e)
    entries += [
        {'source_id':'NBS_FAMILY_SIZE_GENERATION_FAQ','kind':'official_public_document',
         'url':'https://www.stats.gov.cn/hd/lyzx/zxgk/202402/t20240201_1947115.html',
         'answer_date':'2023-12-25','issuer':'国家统计局人口和就业统计司、住户调查司',
         'local_path':str(HERE/'raw/census_family_faq_20261003.html'),
         'sha256':'4ec8ebfcdeb7da70ee967080f781197dad9c8653d5c0d303e33c4d42d1528bee',
         'read_status_this_bridge':'official full-page reviewed by primary and independent reviewer',
         'supports':['household size based on usual residents rather than H2 registered total','absent registered members excluded; resident nanny boundary differs from CHFS','two occupied generations even if intervening generation absent']},
        {'source_id':'NBS_POPULATION_FAQ','kind':'official_public_document',
         'url':'https://www.stats.gov.cn/hd/cjwtjd/202302/t20230207_1902273.html',
         'local_path':str(HERE/'raw/census_population_faq_20261003.html'),
         'sha256':'8e397550a836157e25f04cde6f45bcdbaade586b000ff13969b4b62a2b16bc41',
         'read_status_this_bridge':'official full-page independently reviewed',
         'supports':['halfyear geographic residency at township/town/subdistrict scale, not six continuous months in exact dwelling']},
        {'source_id':'CENSUS2020_PLAN','kind':'official_public_document',
         'url':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf',
         'local_path':str(PARENT/'evidence_contract_20261001/raw/census2020_plan_retry.pdf'),
         'sha256':'cc748c279b5307ee671a87bcc6db1bd0195dc40264d481f734151de31c64ff4f',
         'read_status_this_bridge':'official indicator definitions and skip paths independently reviewed',
         'supports':['usual residence exceptions','H1/H2/H5/H6/H7/D2 definitions','ordinary dwelling conditional housing scope']},
        {'source_id':'CHFS2021_HH_METADATA','kind':'local_source_metadata',
         'local_path':str(PARENT/'chfs_admission_20261003/private_metadata/chfs2021_hh_pub_v0_20260131_metadata.json'),
         'read_status_this_bridge':'source variable labels used to select current dwelling columns; no record values',
         'supports':['actual property loop indices1..6','actual shi/hall and multiselect column names']},
        {'source_id':'BASE_GENERATION_CONTRACT','kind':'inherited_local_contract',
         'local_path':str(PARENT/'chfs_admission_20261003/GENERATION_SOURCE_CONTRACT.json'),
         'supports':['11-step generation order and unmodified downstream gates']},
        {'source_id':'BASE_FIELD_SOURCE_RULES','kind':'inherited_local_contract',
         'local_path':str(PARENT/'chfs_admission_20261003/FIELD_SOURCE_RULES.json'),
         'supports':['finance source-derived/imputed provenance','source financial reference times','combined appliance groups not individual ownership']}
    ]
    checks=[]
    for e in entries:
        if not e.get('local_path'):
            checks.append({'source_id':e['source_id'],'status':'not_locally_cached','scope':'inherited document review; no byte-integrity claim'})
            continue
        path=Path(e['local_path'])
        assert path.is_file(),str(path)
        observed=sha(path)
        locked=e.get('sha256')
        if locked is not None: assert observed==locked,(e['source_id'],'source bytes changed')
        e['sha256']=observed
        e['bytes']=path.stat().st_size
        checks.append({'source_id':e['source_id'],'status':'matches_locked_sha256' if locked else 'new_local_hash_recorded','sha256':observed,'bytes':e['bytes']})
    bindings=[
        {'rule_id':'residence_and_economic_boundary','source_ids':['CENSUS2020_PLAN','NBS_FAMILY_SIZE_GENERATION_FAQ','NBS_POPULATION_FAQ','CHFS2021_QUESTIONNAIRE','CHFS2022_QUESTIONNAIRE'],
         'census_pdf_pages':[23,24,26],'CHFS_pdf_pages_both':[9,11,13,16,20],
         'fields':['a2000','a2000c','a1008','a2023g','ts001'],'api':'bridge_rules.py:derive_members',
         'status':'co-residence proxy; exact census membership not identified'},
        {'rule_id':'occupied_generation_count','source_ids':['NBS_FAMILY_SIZE_GENERATION_FAQ','CENSUS2020_PLAN','CHFS2021_QUESTIONNAIRE','CHFS2022_QUESTIONNAIRE'],
         'census_pdf_pages':[27],'CHFS_pdf_pages_both':[12,13,14],
         'fields':['a2001'],'api':'bridge_rules.py:derive_members',
         'status':'derived occupied levels; incomplete relationship graph'},
        {'rule_id':'current_dwelling_selector','source_ids':['CHFS2021_QUESTIONNAIRE','CHFS2022_QUESTIONNAIRE','CHFS2021_HH_METADATA'],
         'CHFS_pdf_pages_both':[63,66,67,68,73,74,75],
         'fields':['c1001','c2000x_j','c2008b_j'],'api':'bridge_rules.py:select_housing',
         'status':'source-referenced dwelling; unique current marker required'},
        {'rule_id':'H6_area_and_sharing','source_ids':['CENSUS2020_PLAN','CHFS2021_QUESTIONNAIRE','CHFS2022_QUESTIONNAIRE'],
         'census_pdf_pages':[26],'CHFS2021_pdf_pages':[63,64,66,67,68,72,74,75],'CHFS2022_pdf_pages':[63,64,66,67,68,74,75],
         'fields':['c1004','c1002ab','c2000c_j','c2003_j','c2004_j','c2008ba_j','c2008ba_option_mc_j'],
         'api':'bridge_rules.py:select_housing','status':'building-area candidate/derived proxy; shared scope and source imputation retained'},
        {'rule_id':'H7_shi_hall_proxy','source_ids':['CENSUS2020_PLAN','CHFS2021_QUESTIONNAIRE','CHFS2022_QUESTIONNAIRE','CHFS2021_HH_METADATA'],
         'census_pdf_pages':[26,27],'CHFS_pdf_pages_both':[74],
         'fields':['c2005aa1_j','c2005aa2_j'],'api':'bridge_rules.py:select_housing',
         'status':'shi excluding hall proxy; exact natural rooms/bedrooms/layout not observed'},
        {'rule_id':'ordinary_dwelling_conditional_scope','source_ids':['CENSUS2020_PLAN','CENSUS2020_DERIVED_CITY_CONSTRAINTS'],
         'census_pdf_pages':[4,8,26,27],'fields':['H5','H6','H7'],
         'api':'run_bridge.py:main','status':'conditional H7 vectors only; no H5 or actual H7 assigned'},
        {'rule_id':'member_housing_reference_time','source_ids':['CHFS2021_QUESTIONNAIRE','CHFS2022_QUESTIONNAIRE','CHFS2021_HOUSEHOLD_MASTER'],
         'CHFS_pdf_pages_both':[67,68,75],'fields':['interviewtime','c2008b_j'],
         'api':'run_bridge.py:load_bridge_pool','status':'2022 current members vs2021-07-end housing kept separate; no finance synchronization claim'},
        {'rule_id':'source_geography_and_weights','source_ids':['CHFS2021_USE_MANUAL','CHFS2021_HOUSEHOLD_MASTER'],
         'CHFS_manual_pdf_pages':[6],'fields':['category','prov','wgt_hh','interviewtime'],
         'api':'run_bridge.py:load_bridge_pool','status':'city classification111/112 and source-stratum province; moved household current weather location unidentified'}
    ]
    ledger={'batch_id':BATCH,'inherited_ledger':str(prior_path),'inherited_ledger_sha256':sha(prior_path),
            'entries':entries,'page_numbering':'all PDF page lists are1-based file page order, not printed page numbers',
            'rule_evidence_bindings':bindings,'local_byte_hash_is_not_official_origin_authentication':True,
            'raw_microdata_redistributed':False,'source_donor_assignment_executed':False}
    write(HERE/'SOURCE_LEDGER.json',ledger)
    write(HERE/'SOURCE_INTEGRITY_VERIFICATION.json',{'batch_id':BATCH,'status':'pass_for_locked_local_input_bytes',
        'checks':checks,'files_checked':sum(c['status']!='not_locally_cached' for c in checks),
        'not_locally_cached':sum(c['status']=='not_locally_cached' for c in checks),
        'ledger_sha256':sha(HERE/'SOURCE_LEDGER.json'),'builder_sha256':sha(Path(__file__)),
        'limits':['local byte integrity, not official download authentication','source semantics verified by cited reviews, not by SHA itself','no new individual-master record analysis in this bridge']})
    print(json.dumps({'checked':sum(c['status']!='not_locally_cached' for c in checks),'uncached':sum(c['status']=='not_locally_cached' for c in checks),'status':'pass'}))

if __name__=='__main__':main()
