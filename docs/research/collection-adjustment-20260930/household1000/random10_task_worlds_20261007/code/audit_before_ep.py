"""Read-only scientific design audit. No EnergyPlus import or execution."""
import collections,hashlib,json
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    prior={r['household_id']:r for r in read(BASE/'production_evidence_completion_20261006/DEVICE_PRIOR_ROUTES1000.json')['routes']}
    profiles={r['slot_id']:r for r in read(BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']}
    presence=collections.Counter();hist_presence=collections.Counter();historical_types=collections.Counter();reasons=collections.defaultdict(collections.Counter)
    routes=collections.Counter();combinations=collections.Counter();totals=collections.Counter();single_ac_multiple_report=[];heater_type_mismatch=[];roster_errors=[];draw_clock_errors=[]
    world_hashes={}
    for p in sorted((OUT/'worlds').glob('*.json')):
        w=read(p);hid=w['household_id'];pr=prior[hid];source=profiles[hid];assets=w['assets'];world_hashes[hid]=sha(p)
        totals['households']+=1;totals['residents']+=w['N'];routes[pr['match_route']]+=1
        if w['N']!=source['family']['resident_count'] or w['G']!=source['family']['generation_count'] or w['H6']!=source['housing']['H6_census_building_area_design_m2'] or w['H7']!=source['housing']['H7_independent_natural_rooms_design']:roster_errors.append(hid)
        for k,a in assets.items():presence[k]+=int(a['present']);reasons[k][a['reference_choice_reason']]+=1
        combination=tuple(k for k,a in assets.items() if a['present']);combinations[','.join(combination) or 'none']+=1
        reports=pr['auxiliary_reported_assets'];classes={r['class'] for r in reports}
        hist_presence['ac']+=int(bool(classes&{'split_AC','household_central_AC','building_central_AC'}));hist_presence['washer']+=int(bool(classes&{'washer','washer_dryer_combo_report'}))
        hist_presence['dryer_or_combo_not_verified_separate_dryer']+=int(bool(classes&{'dryer','washer_dryer_combo_report'}))
        electric=[r for r in reports if r['class']=='water_heater' and r['fuel_code']==1];hist_presence['electric_water_heater_any_type']+=int(bool(electric))
        for r in electric:historical_types[str(r.get('type_code'))]+=1
        if assets['water_heater']['present'] and any(r.get('type_code')==2 for r in electric):heater_type_mismatch.append(hid)
        ac_reports=[r for r in reports if r['class'] in {'split_AC','household_central_AC','building_central_AC'}]
        if len(ac_reports)>1 and assets['ac']['present']:single_ac_multiple_report.append({'household_id':hid,'historical_report_slots':len(ac_reports),'reference_modeled_AC_units':1})
        n=w['N'];begin=20.5;end=begin+n/6;slots=[s for s in range(144) if begin<=s*(1/6)<end]
        if len(slots)!=n and assets['water_heater']['present']:draw_clock_errors.append({'household_id':hid,'N':n,'expected_slots_per_day':n,'actual_slots_per_day':len(slots),'requested_litres_per_day':30*n,'encoded_litres_per_day':30*len(slots)})
    report={'schema':'eb.pre_EP_design_audit.v1','EP_executed_by_this_audit':False,'decision':'NOT_READY_FOR_EP_PRODUCTION',
        'worlds':dict(totals),'frozen_N_G_H6_H7_mismatches':roster_errors,'device_matching_routes':dict(routes),
        'configured_device_presence':{k:{'households':n,'percent':n/10} for k,n in presence.items()},
        'historical_auxiliary_positive_households_not_population_prevalence':dict(hist_presence),
        'historical_electric_water_heater_type_reports':dict(historical_types),'configured_device_selection_reasons':{k:dict(v) for k,v in reasons.items()},
        'device_combination_counts':dict(combinations),'all_six_configured_households':combinations['ac,washer,dishwasher,dryer,water_heater,ev'],
        'historical_multi_AC_collapsed_to_one_reference_unit':{'households':len(single_ac_multiple_report),'examples':single_ac_multiple_report[:10]},
        'instantaneous_electric_report_any_to_mixed_tank_reference':{'households':len(heater_type_mismatch),'examples':heater_type_mismatch[:10],'claimed_as_observed_topology':False},
        'water_draw_clock_semantic_errors':{'households':len(draw_clock_errors),'by_N':dict(collections.Counter(x['N'] for x in draw_clock_errors)),'examples':draw_clock_errors[:10]},
        'design_concerns':[
          {'priority':'critical','item':'dishwasher,dryer,EV presence','finding':'a hashed 3-bit coverage factor,conditional on eligibility,creates presence;it is not calibrated China city prevalence'},
          {'priority':'critical','item':'matching transport','finding':'2012 equipment motifs and 2021 household motifs are statistically joined;geographic/NG/area relaxation is recorded,but joint real-household identity is not observed'},
          {'priority':'critical','item':'A/B plan origin','finding':'A is a designed weekly grammar and B is a prespecified rule;neither is established as a real household routine or a current EB agent-generated proposal'},
          {'priority':'important','item':'ownership versus modeled/control availability','finding':'presence combines source desire,adult operator,spatial fit,service access,and designed modern asset factors;these stages must not be conflated with population ownership'},
          {'priority':'important','item':'topology/multiplicity','finding':'multiple AC reports can collapse to one served-room model;instantaneous electric reports can become a generic mixed tank;requires explicit justified archetype mapping'},
          {'priority':'critical','item':'program semantics','finding':'floating-hour draw endpoints can encode extra water demand;full integer-slot volume,dependencies,notice deadlines,and prestate assertions are required before EP'},
          {'priority':'important','item':'task sampling interpretation','finding':'10 random dates retained;7685 action-design and2315 no-action cases in current school audit;these are opportunities/controls,not10,000 IID human benchmark observations'}],
        'admission_order':['freeze estimand and target/reference year','audit ownership and availability separately with source-calibrated device marginals','freeze and justify household-housing-weather/device archetype matchers','define A provenance and B agent or explicit rule baseline','static semantics and stratified design review','user reviews corrected design,then authorizes school EP checks'],
        'sources':{'source_device_routes_sha256':sha(BASE/'production_evidence_completion_20261006/DEVICE_PRIOR_ROUTES1000.json'),'source_profiles_sha256':sha(BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json'),'world_sha256_by_household':world_hashes}}
    path=OUT/'PRE_EP_DESIGN_AUDIT.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['decision','worlds','frozen_N_G_H6_H7_mismatches','device_matching_routes','configured_device_presence','all_six_configured_households','historical_electric_water_heater_type_reports']},ensure_ascii=False))
    print({'water_clock_errors':len(draw_clock_errors),'multi_AC_collapsed':len(single_ac_multiple_report),'instantaneous_reports_with_tank_reference':len(heater_type_mismatch)})
if __name__=='__main__':main()
