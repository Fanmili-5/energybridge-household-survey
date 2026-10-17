"""Read all10000 requests for generation-design weaknesses, not just integrity."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    sig=rules_id();bs=sha(OUT/'PAIR_BINDINGS10000.json');counts=collections.Counter();paths=collections.Counter();failpaths=collections.Counter();axes=collections.defaultdict(collections.Counter);relations=collections.Counter();examples={};errors=[]
    special={'ordinary-v6-0001__2025-03-22','ordinary-v6-0006__2025-06-16','ordinary-v6-0017__2025-08-21','ordinary-v6-0048__2025-04-02','ordinary-v6-0045__2025-02-18','ordinary-v6-0224__2025-12-29'}
    for row in read(OUT/'PAIR_BINDINGS10000.json')['records']:
        world=None
        for rr in row['rounds']:
            p=read(OUT/rr['path']);counts['cases']+=1
            if world is None:world=read(A_STAGE/p['A_source']['world_path']);assets={d['asset_id']:d for d in world['parameter_pack']['devices']}
            for req,obs in zip(p['proposal']['requested_device_strengths'],p['proposal']['actual_device_strengths']):
                fam=req['device_family'];ctx=req['input_state_plan'];counts[fam+'_requests']+=1;counts['no_VPP_opportunity_requests']+=ctx['no_VPP_opportunity']
                for ax,v in obs['actual_strength_axes'].items():axes[fam+':'+ax][v['grade']]+=1
                if fam in('washer','dishwasher'):
                    for e in ctx['all_event_input_states']:
                        if e['direction']=='up'and e['input_opportunity_min']>0 and e['service_boundaries']and all(x['earliest_feasible_start_min']is None or x['earliest_feasible_start_min']>=e['end_min']for x in e['service_boundaries']):errors.append([p['case_id'],'PROGRAM_FALSE_UP_OPPORTUNITY'])
                    for f in req.get('program_plans',[]):counts['program_basis:'+f['request_basis']]+=1
                if fam=='ev':
                    if obs['actual_strength_axes']['window_fraction_removed']['grade']in('low','medium')and obs['actual_strength_axes']['start_delay_min']['value']>=120 and 'EV_large_delay_example'not in examples:
                        examples['EV_large_delay_example']={'case_id':p['case_id'],'path':rr['path'],'actual':obs}
                    for m in obs['EV_window_metrics']:
                        f=m['formation_path'];path=f['request_path'];failed=m['B_window_slack_minutes']<0;paths[path]+=1;failpaths[path]+=failed;counts['EV_energy_bound_shortfall_requests']+=failed
                        counts['EV_long_delay_120min_or_more']+=m['delay_minutes']>=120
                        if abs(f['target_deficit_kWh']-max(0,-m['B_window_slack_minutes'])*assets[req['asset_ids'][0]]['parameters']['charger_kw']*assets[req['asset_ids'][0]]['parameters']['efficiency']/60)>1e-6:errors.append([p['case_id'],'EV_CAUSE_ENERGY_MISMATCH'])
                    if ctx['behavior']in('normal_response','partial_response'):
                        ec=next(e for e in p['classification']['actual_actions']['events']if e['event_id']==ctx['event']['event_id'])
                        for ref in ec['EV_event_state_reference']['devices']:
                            if ref['asset_id']in obs['asset_ids']:relations[ref['response_relation']]+=1
                if fam in('ac','water_heater'):
                    st=ctx['event']['native_A_event_state'];counts[fam+'_native_mode:'+st.get('mode','unknown')]+=1;counts[fam+'_native_state_known']+=st['status']=='native_A_reference'
                    if ctx['thermal_axis_basis'].startswith('given_daily'):errors.append([p['case_id'],'DAILY_MEAN_AXIS_STILL_ACTIVE'])
            if p['case_id']in special:examples[p['case_id']]={'case_id':p['case_id'],'path':rr['path'],'requests':p['proposal']['requested_device_strengths'],'actual':p['proposal']['actual_device_strengths'],'events':p['classification']['actual_actions']['events'],'constraint_flags':p['assessment_B']['constraint_flags']}
            if counts['cases']%1000==0:print({'design_reviewed':counts['cases'],'errors':len(errors)},flush=True)
    report={'passed':not errors,'rules_sha256':sig,'bindings_sha256':bs,'counts':dict(counts),'actual_grade_counts_by_axis':{k:dict(v)for k,v in axes.items()},'EV_path_request_counts':dict(paths),'EV_path_shortfall_counts':dict(failpaths),'normal_or_partial_EV_selected_event_reference_relations':dict(relations),'errors':errors,'all10000_retained':True,'scope':'generation design + native A-only thermal state reference;not population realism proof,full B delivery or human acceptance','full_AB_physical_acceptance':False}
    assert rules_id()==sig and sha(OUT/'PAIR_BINDINGS10000.json')==bs
    save(OUT/'DESIGN_REVIEW.json',report);save(OUT/'review/四项修改案例.json',examples);print(canonical(report))
    if errors:raise SystemExit(2)
if __name__=='__main__':main()
