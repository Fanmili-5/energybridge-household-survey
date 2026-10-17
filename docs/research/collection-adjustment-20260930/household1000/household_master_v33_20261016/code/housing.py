"""Rebuild reference enclosure, sleep allocation and installations together.
No EnergyPlus invocation. Original source modules supply geometry equations;
all writes are performed by the calling versioned stage, never by ancestors.
"""
import ast,copy,importlib.util,json,math,sys,types
from pathlib import Path
from scipy.optimize import brentq
from shapely.geometry import box
from shapely.ops import unary_union
from room_assignment import assign
from ac_resources import install
from integrity import verify_fixed_family
def read(p):return json.loads(Path(p).read_text())
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def functions(path,names,namespace):
    tree=ast.parse(Path(path).read_text());selected=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name in names]
    if len(selected)!=len(names):raise ValueError('SOURCE_FUNCTION_SET_CHANGED')
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),namespace)
    return namespace
def compiler_modules(base):
    ref=load(base/'idf_joint_production_20261005/code/reference_world.py','v31_reference_world')
    old=sys.modules.get('reference_world');sys.modules['reference_world']=ref
    try:compiler=load(base/'idf_joint_production_20261005/code/compile_reference_idfs.py','v31_shell_compiler')
    finally:
        if old is None:sys.modules.pop('reference_world',None)
        else:sys.modules['reference_world']=old
    from surface_merge import install as merge_shell_faces
    compiler=merge_shell_faces(compiler,base/'idf_joint_production_20261005/code/compile_reference_idfs.py')
    gpath=Path(__file__).with_name('geometry.py');tree=ast.parse(gpath.read_text())
    shapes={n.targets[0].id:ast.literal_eval(n.value)for n in tree.body if isinstance(n,ast.Assign)and isinstance(n.targets[0],ast.Name)and n.targets[0].id in ['SHAPES','STUDIOS']}
    geometry=functions(gpath,{'make','sized'},{'math':math,'brentq':brentq,'box':box,'unary_union':unary_union})
    return compiler,geometry,shapes
def geometry_module(base):
    common=types.ModuleType('common');common.BASE=base;common.OUT=base/'joint_static_production_20261007_v16'
    common.KINDS=['ac','washer','dishwasher','dryer','water_heater','ev'];common.Path=Path;common.read=read
    old=sys.modules.get('common');sys.modules['common']=common
    try:return load(base/'joint_static_production_20261007_v16/code/joint_geometry.py','v31_installation_geometry')
    finally:
        if old is None:sys.modules.pop('common',None)
        else:sys.modules['common']=old
def rebuild(world,profile,selected,facet,assembly,templates,base,schema):
    compiler,geometry,shapes=compiler_modules(base);joint=geometry_module(base)
    compiler.assemblies=lambda:copy.deepcopy(assembly)
    def obj(kind,values):
        fields=schema['properties'][kind]['legacy_idd']['fields'];last=max(fields.index(k)for k in values)
        return [kind]+[values.get(f,'')for f in fields[:last+1]]
    exposure=functions(base/'joint_housing_service_worlds_20261006/code/assemble_worlds.py',{'exposure'},{'copy':copy,'math':math,'obj':obj})['exposure']
    hid=world['household_id'];p=copy.deepcopy(profile);p['family']['members']=copy.deepcopy(world['members'])
    studio=world['H7']==1 and world['layout']['shared_household_count_design']==1
    # These are design alternatives, not frequencies or a population prior.
    # Corridor and service dimensions stay independent of bedroom scale.
    options=[(4.,3.,1.,2.4,.5),(4.5,3.2,1.,2.6,.55),(3.5,4.,1.,2.4,.55)]if studio else[(2.8,3.,1.,3.8,.5),(2.4,3.4,1.,3.8,.5),(3.2,2.8,1.,4.2,.5)]
    options += [(a,d,c,service,k)for a in([3.5,4.,4.5,5.]if studio else[2.2,2.6,3.,3.4])for d in[2.6,3.,3.4,3.8]
                for c in[1.,1.2]for service in([2.2,2.6,3.]if studio else[3.2,3.6,4.,4.4])for k in[.45,.5,.55]]
    if not studio:
        options += [(a,d,1.,service,k)for a in[1.4,1.8,2.2,2.6,3.]for d in[4.,5.,6.]
                    for service in[2.8,3.2,3.6,4.,4.4]for k in[.4,.45,.5,.55]]
    if world['layout']['shared_household_count_design']>1:
        gallery=[(a,d,1.,service,.5,h)for a in[1.8,2.2,2.6]for d in[2.6,3.,3.4,4.]
                 for service in[2.2,2.6,3.]for h in[.5,.6]]
        options=gallery+options if world['H6']<40 else options+gallery
    attempts=[];wanted=sorted({t for d in world['parameter_pack']['devices']for t in d['types']}|{'ac'})
    for shape in dict.fromkeys(options):
        try:
            layout=geometry['sized'](p,facet,assembly,shape);rows,meta=compiler.model(layout)
            # The old kernel's fixed165mm label is valid for only one finish
            # stack. Native finish layers differ across source models.
            oldname='Reference_RC_floor_165mm';floor=next(r for r in rows if r[0]=='Construction'and r[1]==oldname)
            mats={r[1]:r for r in rows if r[0]=='Material'}
            thickness=sum(float(mats[n][3])for n in floor[2:]);newname=f'Reference_RC_midfloor_{round(thickness*1000)}mm'
            rows=[[newname if v==oldname else v for v in r]for r in rows]
            for surface in meta['surfaces']:
                if surface['construction']==oldname:surface['construction']=newname
            meta.update(floor_total_thickness_design_m=thickness,
                floor_material_policy='native floor finish layers plus explicitly given120mm RC reference core;not native/asbuilt whole floor',
                source_original_thermal_absorptance_preserved=False,
                metadata_scope='background enclosure only; household devices compiled later',
                absorptance_roughness_and_terrain_are_declared_references=True)
            rows,boundary=exposure(rows,layout,facet,assembly)
            actual={r[1]:r for r in rows if r[0]=='BuildingSurface:Detailed'}
            for surface in meta['surfaces']:
                r=actual[surface['name']]
                surface.update(type=r[2],construction=r[3],bc=r[6],peer=r[7])
            if facet['building_storeys']=='one_storey':
                proof=next(x for x in assembly['native_opaque_provenance']if x['kind']=='ground')
                meta.update(floor_material_policy='actual native KIND4 ground; native KIND3 roof; no RC midfloor in one-storey shell',
                    floor_total_thickness_design_m=proof['thickness_m'],floor_core_thickness_design_m=None)
            meta['actual_boundary_reference']=boundary
            w=copy.deepcopy(world);w['layout']=layout
            layout.update(stock_reference_features=copy.deepcopy(facet),boundary_reference=boundary,
                source_parameter_reference={'model_key':selected['model_key'],'catalogue_type':selected['catalogue_type'],
                    'reference_epoch':selected['catalogue_reference_epoch'],'physical_reference_city':selected['catalogue_city'],
                    'source_native_sha256':selected['source_sha256'],'weather':copy.deepcopy(selected['coordinate_confirmed_WMO_station_candidates']),
                    'glazing_regional_native_match_admitted':False},reference_task_geometry_complete=True)
            w=assign(w,rows)
            # Neighbor beds must also fit before accepting a shape. They are
            # not added only after the target household has passed.
            from shared_context import configure as shared_housing
            w=shared_housing(w,rows)
            from geometry_review import space_issues
            issues=space_issues(w)
            if issues:raise ValueError('SPACE_FUNCTION:'+','.join(issues))
            # Query only this household's requested resource set. The inherited
            # kernel otherwise enumerates every4/5/6-class combination per shape.
            joint.patterns=lambda:[wanted]
            placements,fail=joint.candidates(w,rows)
            found=next((c for c in placements if c['types']==wanted),None)
            if found is None:raise ValueError('EXACT_INSTALLED_FUNCTIONS_HAVE_NO_SPACE_WITNESS')
            bykind={x['kind']:x for x in found['placements']}
            for d in w['parameter_pack']['devices']:
                if 'ac'in d['types']or'ev'in d['types']:continue
                kind='laundry'if set(d['types'])&{'washer','dryer'}else'tank'if'water_heater'in d['types']else'dishwasher'
                place=bykind[kind];d['room_id']=place['room_id'];d['served_rooms']=[place['room_id']];d['installation']=copy.deepcopy(place)
            w['joint_matching'].update(spatial_witnesses=found['placements'],sleep_metric_access_witnesses=found['sleep_metric_access_witnesses'],fixed_walls_beds_and_portals_preserved=False,new_geometry_sleep_and_installation_witnesses=True)
            # Reservation uses the newly compiled room areas and sharing rights.
            w['parameter_pack']['background_reserved_kw']=sum(r['thermal_reference_area_m2']*((1.8 if r['census_room_class']=='corridor'else 4.2)+.5*(5 if r['census_room_class']=='kitchen'else 2))/len(r['using_household_ids'])/1000 for r in layout['rooms']if hid in r['using_household_ids'])+.01
            w=install(w,templates)
            total=sum(r['gross_area_m2']*r['area_allocation_fractions'].get(hid,0)for r in layout['rooms'])
            if abs(total-world['H6'])>1e-6:raise AssertionError('H6_ALLOCATION_DRIFT')
            if sum(r['census_room_class']=='bedroom'and r['using_household_ids']==[hid]for r in layout['rooms'])!=world['H7']:raise AssertionError('H7_DRIFT')
            attempts.append({'shape':list(shape),'passed':True})
            w['housing_rebuild']={'source_native_model':selected['model_key'],'original_model_geometry_preserved':False,
                'native_walls_roof_ground_and_scalar_glazing_parameters_used':True,'midfloor_opaque_RC_is_declared_reference':True,'fixed_H6_H7_and_roster':True,'shape_attempts':attempts,
                'geometry_sleep_devices_jointly_checked':True,'physical_outcomes_not_yet_computed':True}
            w['housing_rebuild']['geometry_compiler_metadata']=meta
            verify_fixed_family(world,w)
            return w,rows,meta
        except (ValueError,AssertionError)as error:
            import traceback
            last=traceback.extract_tb(error.__traceback__)[-1]
            attempts.append({'shape':list(shape),'passed':False,'error':str(error),'error_type':type(error).__name__,'location':Path(last.filename).name+':'+str(last.lineno)})
    raise ValueError('NO_JOINT_HOUSING_WITNESS:'+hid+':'+json.dumps(attempts,ensure_ascii=False))
