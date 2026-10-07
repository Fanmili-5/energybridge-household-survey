"""Compile exact reference worlds to multi-zone IDF shells and diagnostic runs.

Wall assemblies are source-bound; the semantically misnamed native floor is
replaced by a documented RC reference. Geometry/portals/windows are explicitly
engineered. Diagnostic ideal heater is thermal demand, NOT AC electricity.
Production shells contain no invented household-owned appliance instances.
"""
import copy,hashlib,json,math,re,sqlite3,subprocess
from pathlib import Path
from collections import defaultdict
from reference_world import assemblies,OUT,BASE,HEIGHT

ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
REPO=OUT.parents[4]
EPW=REPO/'artifacts/private_research/role_weather_300_20260925/CHN_Beijing.Beijing.545110_CSWD.epw'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def fmt(x):return format(float(x),'.9f').rstrip('0').rstrip('.') if isinstance(x,(int,float)) else str(x)
def dump(rows):return '\n'.join(',\n  '.join(fmt(x) for x in r)+';' for r in rows)+'\n'
def area3(v):
    sums=[sum(a[1]*b[2]-a[2]*b[1] for a,b in zip(v,v[1:]+v[:1])),sum(a[2]*b[0]-a[0]*b[2] for a,b in zip(v,v[1:]+v[:1])),sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(v,v[1:]+v[:1]))]
    return sum(x*x for x in sums)**.5/2
def points_flat(p):return [x for v in p for x in v]

def model(world,fixture=False,delta=3):
    rooms={x['room_id']:x for x in world['rooms']};a=assemblies();cons=copy.deepcopy(a['names'])
    material_rows=copy.deepcopy(a['rows'])
    admission=json.loads((OUT/'MATERIAL_SEMANTIC_ADMISSION.json').read_text())
    assert admission['replacement']['reference_material_parameters']=={'conductivity_W_mK':1.74,'density_kg_m3':2500.,'specific_heat_J_kgK':920.}
    old_floor=next(r for r in material_rows if r[0]=='Construction' and r[1]==cons['floor'])
    # Preserve the native source and its numeric audit. The native floor's
    # middle layer is fibreboard, so its RC name cannot authorize RC identity.
    core='Reference_RC_core_120mm';floor='Reference_RC_floor_165mm'
    material_rows += [['Material',core,'MediumRough','.12','1.74','2500','920','.9','.7','.7'],
                      ['Construction',floor,old_floor[2],core,old_floor[-1]]]
    cons['floor']=floor
    # Compile only the dependency closure of actually used constructions.
    # Unused historical source alternatives remain in the immutable source.
    used={v for k,v in cons.items() if k!='window' or not fixture};construction_rows=[r for r in material_rows if r[0]=='Construction' and r[1] in used]
    required={n for r in construction_rows for n in r[2:]}
    material_rows=[r for r in material_rows if r[0]!='Construction' and r[1] in required]+construction_rows
    if fixture:
        for r in material_rows:
            if r[0].lower()=='material':r[7]='0.00000001';r[8]='0';r[9]='0'
    props=material_rows+[['Material:NoMass','ReferenceDoorR','Smooth','.2','.9','.7','.7'],['Construction','ReferenceDoor','ReferenceDoorR']]
    if fixture:props[-2][4]='0.00000001'
    rows=[['Version','24.1'],['Building','Declared_reference_geometry','0','Suburbs',
        '.00001' if fixture else '.04','.0001' if fixture else '.4','FullExterior','100' if fixture else '25','60' if fixture else '6'],
       ['Timestep','4'],['SimulationControl','No','No','No','No','Yes'],
       ['RunPeriod','Geometry_reference_day','7','1','2007','7','1','2007','Sunday','No','No','No','Yes','Yes'],
       ['GlobalGeometryRules','UpperLeftCorner','Counterclockwise','Relative','Relative'],*props,
       ['Output:SQLite','SimpleAndTabular'],['Output:Variable','*','Zone Mean Air Temperature','Hourly']]
    for name,r in rooms.items():
        rows.append(['Zone',name,'0','0','0','0','1','1',HEIGHT,r['usable_area_m2']*HEIGHT,r['usable_area_m2']])
    boxes={k:r['thermal_centerline_rect_m'] for k,r in rooms.items()}
    xs=sorted(set(v for x in boxes.values() for v in [x[0],x[2]]));ys=sorted(set(v for x in boxes.values() for v in [x[1],x[3]]))
    # Do not merge merely close vertices. Reference construction uses common
    # exact endpoints; all intervals have a single owning rectangular space.
    owner={}
    for i,(x0,x1) in enumerate(zip(xs,xs[1:])):
        for j,(y0,y1) in enumerate(zip(ys,ys[1:])):
            if x1-x0<1e-8 or y1-y0<1e-8:continue
            mid=((x0+x1)/2,(y0+y1)/2);containing=[n for n,(a,b,c,d) in boxes.items() if a<mid[0]<c and b<mid[1]<d]
            if len(containing)!=1:raise ValueError('thermal_centerline_partition_gap_or_overlap')
            owner[(i,j)]=containing[0]
    floors=[];walls=[]
    for name,(x0,y0,x1,y1) in boxes.items():
        fv=[[x0,y0,0],[x0,y1,0],[x1,y1,0],[x1,y0,0]];cv=[[x0,y1,HEIGHT],[x0,y0,HEIGHT],[x1,y0,HEIGHT],[x1,y1,HEIGHT]]
        for typ,vs in [('Floor',fv),('Ceiling',cv)]:
            floors.append({'name':name+'_'+typ,'zone':name,'type':typ,'construction':cons['floor'],'bc':'Adiabatic','peer':'','vertices':vs})
    sid=0
    for (i,j),name in owner.items():
        x0,x1,y0,y1=xs[i],xs[i+1],ys[j],ys[j+1]
        boundaries=[('south',(i,j-1),[[x0,y0,HEIGHT],[x1,y0,HEIGHT],[x1,y0,0],[x0,y0,0]]),
          ('north',(i,j+1),[[x1,y1,HEIGHT],[x0,y1,HEIGHT],[x0,y1,0],[x1,y1,0]]),
          ('east',(i+1,j),[[x1,y0,HEIGHT],[x1,y1,HEIGHT],[x1,y1,0],[x1,y0,0]]),
          ('west',(i-1,j),[[x0,y1,HEIGHT],[x0,y0,HEIGHT],[x0,y0,0],[x0,y1,0]])]
        for side,neigh,vs in boundaries:
            peer=owner.get(neigh)
            if peer==name:continue
            sid+=1
            outdoor=peer is None and (side in ['south','north'] or (side=='east' and name=='corridor'))
            walls.append({'name':f'wall_{sid:04}','zone':name,'type':'Wall','construction':cons['interior'] if peer else cons['exterior'],
             'bc':'Surface' if peer else 'Outdoors' if outdoor else 'Adiabatic','peer_zone':peer,'peer':'','side':side,
             'vertices':[vs[1],vs[0],vs[3],vs[2]]})
    signatures=defaultdict(list)
    for w in walls:
        if w['peer_zone']:
            sig=tuple(sorted(tuple(round(x,8) for x in p) for p in w['vertices']));signatures[sig].append(w)
    for sig,faces in signatures.items():
        if len(faces)!=2 or faces[0]['zone']!=faces[1]['peer_zone']:raise ValueError('nonreciprocal_shared_wall')
        faces[0]['peer']=faces[1]['name'];faces[1]['peer']=faces[0]['name']
    openings=[]
    def aperture(face,width,height,name,typ,construction,z0=.8,peer=''):
        a,b=face['vertices'][:2];dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if width>length-.1 or z0+height>HEIGHT-.1:raise ValueError('opening_does_not_fit_parent')
        u=((length-width)/2/length,(length+width)/2/length)
        xy=[(a[0]+v*dx,a[1]+v*dy) for v in u]
        vs=[[xy[0][0],xy[0][1],z0+height],[xy[1][0],xy[1][1],z0+height],
            [xy[1][0],xy[1][1],z0],[xy[0][0],xy[0][1],z0]]
        openings.append({'name':name,'type':typ,'construction':construction,'parent':face['name'],'peer':peer,'vertices':vs,'zone':face['zone']})
    for access in world['access']:
        candidates=[w for w in walls if w['zone']==access['from'] and w['peer_zone']=='corridor' and math.dist(w['vertices'][0][:2],w['vertices'][1][:2])>=.9]
        if not candidates:raise ValueError('declared_portal_not_on_IDF_common_wall')
        f=max(candidates,key=lambda w:area3(w['vertices']));partner=next(w for w in walls if w['name']==f['peer'])
        n='door_'+access['from'];aperture(f,.8,2.,n,'Door','ReferenceDoor',.01,n+'_peer')
        aperture(partner,.8,2.,n+'_peer','Door','ReferenceDoor',.01,n)
    entrance=max([w for w in walls if w['zone']=='corridor' and w['side']=='east' and w['bc']=='Outdoors'],key=lambda w:area3(w['vertices']))
    aperture(entrance,.9,2.,'entry_door','Door','ReferenceDoor',.01)
    if not fixture:
        for name in rooms:
            ext=[w for w in walls if w['zone']==name and w['bc']=='Outdoors' and w['side'] in ['north','south']]
            if not ext:continue
            f=max(ext,key=lambda w:area3(w['vertices']));L=math.dist(f['vertices'][0][:2],f['vertices'][1][:2])
            width=min(L-.2,area3(f['vertices'])*.25/1.2)
            if width>.15:aperture(f,width,1.2,'window_'+name,'Window',cons['window'])
    if fixture:
        rows += [['SurfaceProperty:OtherSideCoefficients','Guard','18','20','1','0','0','0','0','','No','24',''],
                 ['Schedule:Constant','HeatingControl','','1'],['Schedule:Constant','CellTemperature','',20+delta],
                 ['Schedule:Constant','ElecFixture','','1']]
        for n in rooms:
            supply=n+'_supply';ret=n+'_return'
            rows += [['ZoneHVAC:IdealLoadsAirSystem',n+'_heater','',supply,'','','50','13','.015','.009','NoLimit','autosize','','LimitCapacity','autosize','0','','','None','','None'],
              ['ZoneHVAC:EquipmentList',n+'_equipment','SequentialLoad','ZoneHVAC:IdealLoadsAirSystem',n+'_heater','1','1'],
              ['ZoneHVAC:EquipmentConnections',n,n+'_equipment',supply,'',n+'_air',ret],
              ['ThermostatSetpoint:SingleHeating',n+'_setpoint','CellTemperature'],
              ['ZoneControl:Thermostat',n+'_thermostat',n,'HeatingControl','ThermostatSetpoint:SingleHeating',n+'_setpoint']]
    for f in floors+walls:
        bc,obj=f['bc'],f['peer']
        if fixture and bc=='Outdoors':bc,obj='OtherSideCoefficients','Guard'
        rows.append(['BuildingSurface:Detailed',f['name'],f['type'],f['construction'],f['zone'],'',bc,obj,
            'SunExposed' if bc=='Outdoors' else 'NoSun','WindExposed' if bc=='Outdoors' else 'NoWind','Autocalculate','4',*points_flat(f['vertices'])])
        if fixture:rows.append(['SurfaceProperty:ConvectionCoefficients',f['name'],'Inside','Value','3'])
    for f in openings:
        rows.append(['FenestrationSurface:Detailed',f['name'],f['type'],f['construction'],f['parent'],f['peer'],'Autocalculate','','1','4',*points_flat(f['vertices'])])
        if fixture:
            # Coefficients on an opaque parent do not fix its subsurface film.
            rows.append(['SurfaceProperty:ConvectionCoefficients',f['name'],'Inside','Value','3'])
    if fixture:
        private=next(n for n,r in rooms.items() if r['using_household_ids']==[world['target_household_id']] and r['census_room_class']=='bedroom')
        rows += [['ElectricEquipment','PrivateElectricalFixture',private,'ElecFixture','EquipmentLevel','1000','','','0','0','1','DiagnosticFixture'],
          ['ElectricEquipment','CommonElectricalFixture','corridor','ElecFixture','EquipmentLevel','500','','','0','0','1','DiagnosticFixture'],
          ['Output:Meter','Electricity:Facility','Hourly'],['Output:Variable','*','Electric Equipment Electricity Energy','Hourly'],
          ['Output:Variable','*','Zone Ideal Loads Supply Air Sensible Heating Rate','Hourly']]
    metadata={'surfaces':floors+walls,'openings':openings,'source_assemblies_sha256':a['source_sha256'],
      'source_envelope_identity':a['climate_identity'],'source_geometry_preserved':False,
      'floor_material_policy':'native_fibreboard_core_not_admitted_as_RC; replace_with_declared_RC_reference',
      'material_semantic_admission_sha256':sha(OUT/'MATERIAL_SEMANTIC_ADMISSION.json'),
      'floor_core_thickness_design_m':.12,'floor_total_thickness_design_m':.165,
      'RC_reference_source_material_id':837899393,'floor_parameters_are_not_stock_or_asbuilt_observations':True,
      'geometry_is_engineering_reference':True,'floor_and_side_neighbor_policy':'midfloor_north_south_exposed_east_west_zero_flux_except_gallery_entry; explicit_scenario',
      'windows':'new_reference_WWR0_25_on_selected_north_south_faces; not_observed_source_windows',
      'door_R_m2K_per_W':.2,'door_R_is_engineering_reference_not_observed':True,
      'door_bottom_elevation_reference_m':.01,
      'door_bottom_policy':'explicit10mm_reference_threshold; avoid_flush_subsurface_base_edge_shadow_geometry_warning; not_observed_source_threshold',
      'centerline_surface_geometry_convention':True,'Zone_floor_area_and_air_volume_use_computed_usable_area':True,
      'actual_household_appliance_instances_or_HVAC_installed':False,'fixture_is_household_device':False,
      'city_climate_and_real_neighbor_conditions_matched_to_household':False,
      'source_original_thermal_absorptance_preserved':not fixture,
      'fixture_absorptance_override':1e-8 if fixture else None,'fixture_no_windows_for_opaque_UA_test':fixture}
    metadata['fixture_steady_initialization_policy']='minimum60 maximum100 warmup_days; load_convergence1e-5 temperature_convergence1e-4K' if fixture else None
    return rows,metadata

def material_Rs(rows):
    mats={r[1]:float(r[3])/float(r[4]) for r in rows if r[0].lower()=='material'}
    mats.update({r[1]:float(r[3]) for r in rows if r[0].lower()=='material:nomass'})
    return {r[1]:sum(mats[x] for x in r[2:]) for r in rows if r[0].lower()=='construction' and all(x in mats for x in r[2:])}

def run_fixture(profile_id,delta=3,negative_control=False):
    world=json.loads((OUT/'worlds'/f'{profile_id}.json').read_text())['world'];rows,meta=model(world,True,delta)
    if negative_control:
        subsurfaces={s['name'] for s in meta['openings']}
        rows=[r for r in rows if not(r[0]=='SurfaceProperty:ConvectionCoefficients' and r[1] in subsurfaces)]
    folder=OUT/('negative_control_runs' if negative_control else 'diagnostic_runs')/f'{profile_id}_delta{delta}';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'reference_fixture.idf';path.write_text('! Opaque steady and electrical diagnostic only. No empirical housing validity claim.\n'+dump(rows))
    run=subprocess.run([str(ENGINE),'-w',str(EPW),'-d',str(folder/'run'),str(path)],capture_output=True,text=True,timeout=120)
    (folder/'console.txt').write_text(run.stdout+'\n'+run.stderr)
    err=(folder/'run/eplusout.err').read_text() if (folder/'run/eplusout.err').exists() else ''
    if run.returncode:raise RuntimeError('fixture_failed:'+str(folder/'run/eplusout.err'))
    db=sqlite3.connect(folder/'run/eplusout.sql');series={}
    for index,key,name,units in db.execute('SELECT ReportDataDictionaryIndex,KeyValue,Name,Units FROM ReportDataDictionary'):
        series[(key,name,units)]=db.execute('SELECT t.Hour,t.Minute,r.Value FROM ReportData r JOIN Time t USING(TimeIndex) WHERE r.ReportDataDictionaryIndex=? AND COALESCE(t.WarmupFlag,0)=0',(index,)).fetchall()
    db.close()
    heating={key.removesuffix('_HEATER'):float(sum(v for h,m,v in vals if h>=7)/len([v for h,m,v in vals if h>=7])) for (key,name,u),vals in series.items() if name=='Zone Ideal Loads Supply Air Sensible Heating Rate'}
    Rs=material_Rs(rows);openings=defaultdict(float)
    for f in meta['openings']:openings[f['parent']]+=area3(f['vertices'])
    analytic=defaultdict(float)
    for f in meta['surfaces']:
        if f['bc']=='Outdoors':analytic[f['zone'].upper()]+=(area3(f['vertices'])-openings[f['name']])*delta/(Rs[f['construction']]+1/3+1/18)
    for f in meta['openings']:
        parent=next(p for p in meta['surfaces'] if p['name']==f['parent'])
        if parent['bc']=='Outdoors':analytic[f['zone'].upper()]+=area3(f['vertices'])*delta/(Rs[f['construction']]+1/3+1/18)
    prediction=sum(heating.values());oracle=sum(analytic.values())
    q=world['shared_household_count_design'];hh=world['target_household_id'];private={r['room_id'].upper() for r in world['rooms'] if r['using_household_ids']==[hh]};common={r['room_id'].upper() for r in world['rooms'] if len(r['using_household_ids'])>1}
    allocated=sum(v for k,v in heating.items() if k in private)+sum(v for k,v in heating.items() if k in common)/q
    alloc_oracle=sum(v for k,v in analytic.items() if k in private)+sum(v for k,v in analytic.items() if k in common)/q
    elec={key:sum(v for _,_,v in values)/3.6e6 for (key,name,u),values in series.items() if name=='Electric Equipment Electricity Energy'}
    facility=next(sum(v for _,_,v in values)/3.6e6 for (key,name,u),values in series.items() if name=='Electricity:Facility')
    assert abs(elec['PRIVATEELECTRICALFIXTURE']-24)<1e-7 and abs(elec['COMMONELECTRICALFIXTURE']-12)<1e-7 and abs(facility-36)<1e-7
    residual=abs(prediction-oracle)/oracle
    if negative_control:
        assert residual>.001,'Untreated_door_film_control_should_be_rejected_by_analytic_guard'
    else:
        if residual>.001:raise ValueError('steady_UA_readback_residual_exceeds_declared_numerical_diagnostic')
        if abs(allocated-alloc_oracle)/alloc_oracle>.001:raise ValueError('target_allocated_heat_operator_residual')
    result={'household_id':profile_id,'delta_T_K':delta,'R':world['target_H7'],'q_design':q,'model_UA_oracle_W':oracle,
      'EnergyPlus_total_heating_mean_W':prediction,'relative_mean_residual':abs(prediction-oracle)/oracle,
      'allocated_target_heat_W':allocated,'allocated_target_analytic_W':alloc_oracle,
      'private_fixture_24h_kWh':elec['PRIVATEELECTRICALFIXTURE'],'common_fixture_24h_kWh':elec['COMMONELECTRICALFIXTURE'],
      'parent_unit_fixture_24h_kWh':facility,'target_allocated_fixture_24h_kWh':24+12/q,
      'wrong_whole_unit_meter_as_target_rejected':q==1 or abs(facility-(24+12/q))>1e-7,
      'warning_count':len(re.findall(r'\*\*\s*Warning\s*\*\*',err)),'severe_or_fatal':len(re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*',err)),
      'IDF_sha256':sha(path),'SQL_sha256':sha(folder/'run/eplusout.sql'),
      'negative_control_omitted_subsurface_inside_film':negative_control,
      'UA_diagnostic_admitted':not negative_control,
      'independent_analytic_operator_check_not_empirical_building_validation':True}
    save(folder/'RESULT.json',result);return result

def main():
    body=json.loads((OUT/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text());folder=OUT/'reference_idfs';folder.mkdir(exist_ok=True)
    records=[]
    for p in body['profiles']:
        world=json.loads((OUT/p['housing']['world_path']).read_text())['world'];rows,meta=model(world)
        path=folder/(p['slot_id']+'.idf');path.write_text('! Geometry-bound REFERENCE shell; household services and climate not completed.\n'+dump(rows))
        p['reference_IDF_generated']=True
        p['reference_IDF_path']=str(path.relative_to(OUT))
        p['complete_household_IDF_generated']=False
        p['legacy_physical_IDF_generated_flag_scope']='complete_household_services_and_stock_matching; reference_shell_is_a_separate_stage'
        records.append({'household_id':p['slot_id'],'IDF_path':str(path.relative_to(OUT)),'IDF_sha256':sha(path),
          'world_path':p['housing']['world_path'],'world_sha256':sha(OUT/p['housing']['world_path']),
          'H6':p['housing']['H6_census_building_area_design_m2'],'H7':world['target_H7'],'q_design':world['shared_household_count_design'],
          'Zone_count':len(world['rooms']),'source_envelope_sha256':meta['source_assemblies_sha256'],
          'material_semantic_admission_sha256':meta['material_semantic_admission_sha256'],
          'floor_material_policy':meta['floor_material_policy'],
          'actual_household_services_complete':False,'actor_ready':False,'scientific_benchmark_admitted':False})
    save(OUT/'IDF_REFERENCE_BINDINGS1000.json',{'bindings':records,'geometry_bound_reference_IDFs':1000,
       'byte_unique_reference_IDFs':len({r['IDF_sha256'] for r in records}),
       'complete_household_IDFs':0,'climate_envelope_source':'Beijing2018_reference_only; not_province_stock_match',
       'engineering_geometry_not_reconstructed_asbuilt_source':True,'scope':'census_and_metric_geometry_reference_shells_only'})
    save(OUT/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json',body)
    # Coverage across every detailed H7 and each observed sharing alternative;
    # extrema are diagnostic selections, not an independent population sample.
    chosen={}
    for r in records:chosen.setdefault(('H7',r['H7']),r['household_id']);chosen.setdefault(('q',r['q_design']),r['household_id'])
    for key in ['H6','Zone_count']:
        chosen[('min',key)]=min(records,key=lambda r:r[key])['household_id'];chosen[('max',key)]=max(records,key=lambda r:r[key])['household_id']
    results=[run_fixture(i) for i in sorted(set(chosen.values()))]
    shared=next((x for x in results if x['q_design']>1),results[0]);refined=run_fixture(shared['household_id'],6)
    ratio=refined['EnergyPlus_total_heating_mean_W']/shared['EnergyPlus_total_heating_mean_W']
    assert abs(ratio-2)<.001
    save(OUT/'IDF_DIAGNOSTIC_RESULTS.json',{'cases':results,'delta_T_linearity_case':refined,'delta_T_linearity_ratio':ratio,
      'reference_geometry_IDFs_written':1000,'new_EnergyPlus_diagnostic_runs':len(results)+1,
      'opaque_geometry_shared_meter_analytic_checks_passed':True,'full1000_annual_or_climate_energy_validation':False,
      'window_service_or_HVAC_electricity_calibrated':False,'empirical_ETNA_reference_coverage':'previous_v6_steady_UA_equivalent_only_not_this_geometry',
      'household_complete_IDFs':0,'scientific_benchmark_admitted':False})
    negative=run_fixture(shared['household_id'],3,True)
    save(OUT/'SUBSURFACE_FILM_NEGATIVE_CONTROL.json',{'case':negative,
      'only_change_vs_positive_fixture':'omit explicit Inside h=3 on door subsurfaces; keep parent coefficients and all other objects',
      'expected_outcome':'analytic_UA_accuracy_guard_rejects','guard_rejected':negative['relative_mean_residual']>.001,
      'new_negative_control_runs':1,'empirical_energy_validity_claim':False})
    print(json.dumps({'IDF_reference_shells':1000,'diagnostic_runs':len(results)+1,'linearity_ratio':ratio,
      'max_UA_numerical_residual':max(r['relative_mean_residual'] for r in results),'complete_household_IDFs':0},indent=2))

if __name__=='__main__':main()
