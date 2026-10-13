"""Local licensed source read -> anonymous, coarsened joint age-gap evidence.

Raw source IDs, dates of birth, exact ages, income/area values and rows are
never written. Only aggregated source-motif hashes and five-year gap bins leave
the process. Production/simulation/validation runs use these on school Linux.
"""
import collections,hashlib,json,sys
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];H=OUT.parent
sys.path.insert(0,str(H/'production_route_v6_20261004/code'))
import joint_motifs as jm
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def save(name,x):(OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n')
def main():
    records,qc=jm.load_source()
    import run_bridge as rb
    # Load only source-native roster fields needed to align gap bins with the
    # existing coarse motif. Keep the original-source identity in memory only.
    df=rb.read('ind',['hhid','a2000c','a2001','a2003','a2005','a3100a'])
    groups={hid:g.drop(columns=['hhid']).to_dict('records') for hid,g in df.groupby('hhid')}
    motifs=collections.defaultdict(lambda:collections.defaultdict(lambda:{'weight':0.,'source_count':0}));meta={}
    pairs=collections.defaultdict(lambda:{'weight':0.,'source_count':0});review=[]
    for r in records:
        raw=[p for p in groups[r['_private_id']] if rb.number(p['a2000c']) in (1,2)]
        aligned=[]
        for m in raw:
            age=r['visit_year']-int(m['a2005']);atom=(int(m['a2001']),int(m['a2003']),max(0,age-1)//5,age//5,jm.integer(m['a3100a']))
            aligned.append((atom,age))
        aligned.sort(key=lambda x:(x[0][0],x[0][2],x[0][3],x[0][1],-1 if x[0][4] is None else x[0][4],x[1]))
        assert tuple(x[0] for x in aligned)==r['atom']
        key=(r['atom'],r['economic_member_count'],r['income_bin'],r['asset_groups'],r['tenure_code'],r['visit_year']);mh=digest(key)
        meta[mh]={'coarse_atoms':r['atom'],'source_N':r['N'],'source_G':r['G'],'visit_year':r['visit_year']}
        root=next((a,age) for a,age in aligned if a[0]==1)
        gaps=tuple((age-root[1])//5 for atom,age in aligned)
        bucket=motifs[mh][gaps];bucket['weight']+=r['weight'];bucket['source_count']+=1
        fold=jm.fold(r)
        for atom,age in aligned:
            if atom[0]==1:continue
            features=(r['N'],r['G'],atom[0],root[0][1],atom[1],root[0][2],root[0][3],atom[2],atom[3])
            group=(fold,features,(age-root[1])//5)
            pairs[group]['weight']+=r['weight'];pairs[group]['source_count']+=1
        if len(review)<3 and mh in {
          'b607c470fa86aae3fd11bf19546ecf528e75a4ee0d86353dbec139bc3770eb26',
          '4508124e4bf5a980e2a904bb75fe875eae04f20fc26895e0f47f40116c66ee5a',
          '208f03c792bfdedb99bdd98e4c30be10d3eed85fe382d285b5e6cbbe5691b443'}:
            review.append({'source_motif_hash':mh,'member_coarse_atoms':r['atom'],'signed_gap_bins_5y':gaps,'source_count':bucket['source_count'],'source_relation_subtype':'not_differentiated_by_A2001; legal_step/adoptive_within_family_definition; subtype remains unknown'})
    result={'schema':'eb.coarsened_joint_age_gap_source.v1','date':'2026-10-10','QC':qc,'motifs':{k:{**meta[k],'patterns':[{'signed_gap_bin5':list(g),'weight':v['weight'],'source_count':v['source_count']} for g,v in rows.items()]} for k,rows in motifs.items()},'gap_bin_semantics':'floor((member_age_proxy-ego_age_proxy)/5); birthday-year difference,not exact birthdays','projection_gap_interval':'[5*bin-1,5*bin+5], including birthday uncertainty; all exact role ages remain synthetic','source_birth_years_or_ids_exported':False,'source_exact_ages_exported':False,'source_relation_subtype_observed':False,'coarsening_is_not_formal_privacy_guarantee':True,'review_motifs':review,'raw_source_republication':False,'training_release':False}
    save('JOINT_AGE_SOURCE_AGGREGATES.json',result)
    save('JOINT_AGE_FOLD_AGGREGATES.json',{'schema':'eb.coarse_gap_whole_source_household_folds.v1','records':[{'fold':f,'features':list(k),'gap_bin5':g,**v} for (f,k,g),v in pairs.items()],'features':['N','G','relation','ego_sex','member_sex','ego_bin_lo','ego_bin_hi','member_bin_lo','member_bin_hi'],'raw_source_ids_exported':False,'coarse_target_support_not_a_full_generator_validation':True})
    print({'source_households':len(records),'aggregate_motifs':len(motifs),'review_source_gap_bins':review,'raw_identifiers_exported':0},flush=True)
if __name__=='__main__':main()
