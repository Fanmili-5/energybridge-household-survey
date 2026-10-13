"""Independent whole-production gate; source support is not human validity."""
import collections,copy,datetime as dt
from common import *
from checks import assess
from execution import realize

def main():
    school_guard();sel=read(OUT/'SELECTION1000.json');fail=[];counts=collections.Counter();rows=[];groups=collections.defaultdict(list)
    source=read(SOURCE/'SELECTION1000.json');original={r['household_id']:r for r in source['records']}
    for h in sel['records']:
        w=read(OUT/h['world_path']);old=read(SOURCE/original[h['household_id']]['world_path'])
        errors=[]
        if sha(OUT/h['world_path'])!=h['world_sha256']:errors.append('WORLD_FILE_BINDING')
        if digest({k:v for k,v in w.items() if k!='world_content_sha256'})!=w['world_content_sha256']:errors.append('WORLD_CONTENT')
        if digest(w['parameter_pack'])!=w['parameter_pack_sha256']:errors.append('PARAMETERS')
        for k in ('N','G','H6','H7','province','population_weight','random10_date_selection','ego_relationships'):
            if w[k]!=old[k]:errors.append('ANCHOR_CHANGED:'+k)
        if len(w['members'])!=w['N']:errors.append('ROSTER_COUNT')
        if len({m['generation_level'] for m in w['members']})!=w['G']:errors.append('GENERATION_COUNT')
        byid={m['member_id']:m for m in w['members']}
        for b in w['layout']['sleep_reference']['berths']:
            age=byid[b['member_id']]['age_years']
            if age!=b['age_years'] or b['level'] and not 6<=age<=59:errors.append('BERTH_AGE')
        age=w['joint_age_evidence']
        if 'signed_gap_bin5' in age:
            ego=next(m for m in w['members'] if m['ego_relation_code']==1)
            for m,j in zip(w['members'],age['member_to_source_atom']):
                if j is None:counts['graft_members_without_source_gap']+=1;continue
                g=age['signed_gap_bin5'][j];gap=m['age_years']-ego['age_years']
                if not 5*g-1<=gap<=5*g+5:errors.append('JOINT_AGE_GAP')
        for m,om in zip(w['members'],old['members']):
            if any(m[k]!=om[k] for k in ('employment_status','employment_evidence','current_work_source_proxy','sex','ego_relation_code','age_bin_reference')):errors.append('SOURCE_FACT_CHANGED')
            lo,hi=m['age_bin_reference']
            if m['age_years']<lo or hi is not None and m['age_years']>hi:errors.append('COARSE_AGE_BIN')
            if m['ego_relation_code'] in (3,4,5,6,7,8,9) and m['relationship_subtype_evidence']['subtype'] is not None:errors.append('INVENTED_PARENTAGE')
        group=age['source_motif_hash'];groups[group].append(w['household_id'])
        local=collections.Counter()
        for row in h['rounds']:
            p=read(OUT/row['pair_path']);ns={n['need_id']:n for n in p['needs_A']}
            if sha(OUT/row['pair_path'])!=row['pair_sha256']:errors.append('PAIR_FILE_BINDING')
            if p['world_sha256']!=w['world_content_sha256']:errors.append('PAIR_WORLD_BINDING')
            if assess(p)['integrity_errors']:errors.append('PAIR_INTEGRITY')
            if p['constraint_assessment']['constraint_flags']['A']:errors.append('A_STATIC_CONFLICT')
            for n in ns.values():
                if n['kind'] not in ('washer','dishwasher'):continue
                if n.get('deadline_uses_operator_availability') is not False:errors.append('DEPENDENT_SERVICE_BOUND')
                if n.get('subjective_importance') is not None or n.get('willingness_to_change_bound') is not None:errors.append('INVENTED_PREFERENCE')
                base=(dt.date.fromisoformat(n['need_id'].split(':')[0])-dt.date.fromisoformat(p['date'])).days*1440
                if n['kind']=='washer':expected=base+1440+[720,1080,1200][rank(w['household_id'],'v20-laundry-handover')%3]
                else:
                    day=p['dated_activity_days'][base//1440+1];expected=base+1440+day['family_context']['dinner_min']-30
                if n['delivery_deadline_min']!=expected:errors.append('SERVICE_PURPOSE_BINDING')
            for side in ('A','B'):
                ex=p['service_execution_reference'][side]
                for x in ex['program_services']:
                    local[side+'_batch_services']+=1
                    if not x['delivered_before_given_bound']:local[side+'_undelivered']+=1
                local[side+'_failed_operations']+=sum(not x['succeeded'] for x in ex['operations'])
                local[side+'_care_gap_slots']+=len(p['post_operation_care'][side])
            # Meaningful negative control: no load operations -> no batch runs.
            empty=copy.deepcopy(p['B']);empty['operations']=[]
            ex=realize(w,empty,p['world']['operator_windows'],p['needs_A'])
            if ex['realized_tasks'] or any(x['delivered_before_given_bound'] for x in ex['program_services']):errors.append('MISSING_LOADING_NEGATIVE_CONTROL')
            local['baseline_helper_bookings']+=sum(bool(x.get('given_baseline_booking')) for x in p['A']['operations'])
            counts['pairs']+=1
        if local['A_undelivered'] or local['A_failed_operations'] or local['A_care_gap_slots']:errors.append('A_REALIZED_SERVICE_OR_CARE')
        counts.update(local);counts['joint_age_changed_members']+=age['changed_members'];counts['members']+=w['N'];counts['households']+=1
        rows.append({'household_id':w['household_id'],'failures':sorted(set(errors)),**dict(local),'joint_age_changed_members':age['changed_members']})
        if errors:fail.append({'household_id':w['household_id'],'errors':sorted(set(errors))})
    # Source motif grouping is a diagnostic holdout scheme, never a released test split.
    manifest={'schema':'eb.source_motif_diagnostic_grouping.v1','formal_split':None,'records':[
        {'source_motif_group':g,'household_ids':ids,'diagnostic_fold5':rank(g,'v20-structural-diagnostic')%5,
         'all_10_dates_and_AB_arms_stay_together':True} for g,ids in sorted(groups.items())],
         'source_motif_group_count':len(groups),'households_in_repeated_groups':sum(len(x) for x in groups.values() if len(x)>1),
         'grouping_does_not_establish_model_performance_or_human_validity':True}
    save(OUT/'STRUCTURAL_GROUP_MANIFEST.json',manifest)
    save(OUT/'INPUT_CHECKS1000.json',rows)
    save(OUT/'INPUT_AUDIT.json',{'schema':'eb.coherent_production_input_audit.v22','failures':fail,'counts':dict(counts),
        'original_household_ids_and_dates_preserved':True,'missing_load_negative_controls':counts['pairs'],
        'national_joint_diary_validated':False,'human_answers':0,'claims':'reference input consistency and source support only'})
    print({'failures':len(fail),'counts':dict(counts),'first_failures':fail[:6]},flush=True)
    if fail:raise RuntimeError('whole-production input gate failed')
if __name__=='__main__':main()
