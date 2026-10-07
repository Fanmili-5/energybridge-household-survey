"""School-side metadata and rule review; never imports or starts EP."""
import collections,hashlib,json,math,os,re,sys
from pathlib import Path
from ab_semantics import combinations,probes,fixture
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent;REPO=BASE.parents[3];UP=REPO/'upstream_2b17ae6'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
    if sys.platform!='linux':raise SystemExit('static review is assigned to school server')
    assert (OUT/'EP_HOLD.json').exists(),'EP hold context must be preserved'
    schema=read(Path(os.environ['EB_EP_ROOT'])/'Energy+.schema.epJSON')['properties']
    source=UP/'experiments/models/family_home/family_simple_3day.idf'
    rows=[[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',source.read_text()).split(';') if q.strip()]
    def value(row,name):
        i=schema[row[0]]['legacy_idd']['fields'].index(name)+1
        return row[i] if i<len(row) else ''
    tank=next(r for r in rows if r[0]=='WaterHeater:Stratified')
    volume=float(value(tank,'tank_volume'));height=float(value(tank,'tank_height'));u=float(value(tank,'uniform_skin_loss_coefficient_per_unit_area_to_ambient_temperature'))
    radius=math.sqrt(volume/(math.pi*height));area=2*math.pi*radius*(radius+height)
    wh_fields=['tank_volume','tank_height','tank_shape','maximum_temperature_limit','heater_1_capacity','heater_2_capacity','heater_thermal_efficiency','uniform_skin_loss_coefficient_per_unit_area_to_ambient_temperature','number_of_nodes']
    wh={k:value(tank,k) for k in wh_fields}
    draw=next(r for r in rows if r[0]=='WaterUse:Equipment' and r[1].startswith('Showers'))
    draw_schedule=value(draw,'target_temperature_schedule_name');target=next(r for r in rows if r[0]=='Schedule:Constant' and r[1]==draw_schedule)
    target_C=float(value(target,'hourly_value'));peak=float(value(draw,'peak_flow_rate'))
    defaults=read(OUT/'inputs/eb_equipment_defaults.json')
    dx=next(r for r in rows if r[0]=='Coil:Cooling:DX:SingleSpeed');parents=[r for r in rows if r[0]=='AirLoopHVAC:UnitaryHeatPump:AirToAir' and dx[1] in r]
    control_zones=sorted(set(value(r,'controlling_zone_or_thermostat_location') for r in parents))
    areas=collections.Counter();ground=0.
    for r in rows:
        if r[0]!='BuildingSurface:Detailed' or value(r,'surface_type')!='Floor':continue
        n=int(value(r,'number_of_vertices'));offset=schema[r[0]]['legacy_idd']['fields'].index('number_of_vertices')+2
        ps=[list(map(float,r[offset+3*i:offset+3*i+3])) for i in range(n)]
        assert max(p[2] for p in ps)-min(p[2] for p in ps)<1e-6
        a=abs(sum(ps[i][0]*ps[(i+1)%n][1]-ps[(i+1)%n][0]*ps[i][1] for i in range(n)))/2
        areas[value(r,'zone_name')]+=a
        if value(r,'outside_boundary_condition')=='Ground':ground+=a
    spec={'source_native_IDF_sha256':sha(source),'WH_proxy_rated_kW':defaults['water_heater']['rated_kw'],'native_WH_fields':wh,
        'native_WH_total_heater_kW':(float(wh['heater_1_capacity'])+float(wh['heater_2_capacity']))/1000,
        'native_target_mixed_water_temperature_C':target_C,'native_shower_peak_L_per_min':peak*60000,
        'explicit_reference_30L_per_person_10min_flow_fraction':3/(peak*60000),
        'cylinder_total_skin_UA_equivalent_W_per_K':u*area,'UA_equivalence_scope':'geometric diagnostic only;full Stratified tank implementation remains authoritative',
        'AC_first_native_coil':dx[1],'AC_unitary_controlling_zones':control_zones,'native_thermal_zone_floor_areas_m2':dict(areas),
        'native_ground_floor_footprint_m2':ground,
        'AC_scope_warning':'controlling-zone linkage is not a full independently validated served-zone graph;do not silently substitute ground footprint for served zone floor area or sizing load',
        'canonical_parameter_pack_decision':'select and version one physics/controller parameter lane;no proxy2kW/native3kW/new60L mixing'}
    save(OUT/'NATIVE_PARAMETER_FINDINGS.json',spec)
    old=BASE/'random10_task_worlds_20261007';counts=collections.Counter();conditions=collections.Counter()
    for p in (old/'worlds').glob('*.json'):
        w=read(p);k=sum(a['present'] for a in w['assets'].values());counts[k]+=1
        if not any(m['age_years']>=18 for m in w['members']):conditions['no_adult_resident']+=1
        if w['layout']['stock_reference_features']['piped_water']!='present':conditions['old_reference_no_piped_water']+=1
    patterns=combinations();assert len(patterns)==17
    result={'host':'school server','EP_started':0,'model_API_calls':0,'hold_active':True,'user_device_scope':[4,5,6],
        'old_worlds_K_counts':dict(counts),'old_worlds_satisfying4to6':sum(v for k,v in counts.items() if 4<=k<=6),
        'old_worlds_needing_joint_resynthesis':sum(v for k,v in counts.items() if not 4<=k<=6),
        'joint_boundary_contexts':dict(conditions),'structural_type_combinations':patterns,
        'combinations_by_K':dict(collections.Counter(len(c) for c in patterns)),
        'semantic_rule_probes':probes(),'native_parameter_findings_file_sha256':sha(OUT/'NATIVE_PARAMETER_FINDINGS.json'),
        'new_1000_worlds_produced':False,'new_10000_AB_pairs_produced':False,
        'scope':'contract fixtures,structural combinations,native metadata extraction and old-cohort diagnosis;not full geometric fit,thermal service,physical calibration,human validation,or EP release'}
    save(OUT/'STATIC_DESIGN_REVIEW.json',result)
    for n in [4,5,6]:save(OUT/'inputs'/f'AB_contract_fixture_K{n}.json',fixture(n))
    print({k:result[k] for k in ['EP_started','old_worlds_satisfying4to6','old_worlds_needing_joint_resynthesis','combinations_by_K']},flush=True)
    print({'positive_fixtures':3,'targeted_invalid_fixtures':len(result['semantic_rule_probes'])-3,'WH_native_L':volume*1000,'WH_native_kW':spec['native_WH_total_heater_kW'],'target_water_C':target_C},flush=True)
if __name__=='__main__':main()
