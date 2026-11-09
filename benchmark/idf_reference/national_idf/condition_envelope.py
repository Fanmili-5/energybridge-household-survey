"""Instantiate a frozen public design recipe on semantic source surfaces.

Targets and complete material properties come from existing reviewed-source
packs. Only positive insulation thickness is derived;unknown walls are never
inferred from a U-value,country or household identity.
"""
import copy

from .common import ROOT,read,save,require,digest
from .idf import objects,Fields
from .source_adapter import source_file,selector
from .reference_workflow import ref
from .envelope_adaptation import MATERIAL_FIELDS,construction_properties,insulation_thickness,apply

CATALOG='configs/condition_envelope_recipes_v3.json'


def recipe(recipe_id,*,root=ROOT):
    catalog=read(root/CATALOG);found=[v for v in catalog['recipes'] if v['id']==recipe_id]
    require(len(found)==1,'CONDITION_ENVELOPE_RECIPE_UNKNOWN',recipe_id)
    definition=found[0]
    if definition.get('adapter')=='complete_reference_constructions_v1':
        library=read(source_file(definition['source_pack'],root))
        require(library['origin_country']==definition['country'],'CONDITION_ENVELOPE_LIBRARY_COUNTRY')
        return {**definition,'scope':'Complete published reference wall,roof,floor and window package;not surveyed home,national stock or code compliance',
                'source_differences':['Published Chinese enclosure;declared public reference geometry,ground and EB equipment retained']}
    old=read(source_file(definition['source_pack'],root));insertions=[]
    for assignment in old['assignments']:
        require(assignment['surface_type']=='Roof' and assignment['outside_boundary_condition']=='Outdoors',
                'CONDITION_ENVELOPE_RECIPE_NOT_ROOF')
        require(len(assignment['insert_layers'])==1,'CONDITION_ENVELOPE_RECIPE_NOT_UNIFORM')
        insertions.append(assignment['insert_layers'][0])
    require(insertions and all(v==insertions[0] for v in insertions),'CONDITION_ENVELOPE_RECIPE_LAYER_DIFFERS')
    layer=insertions[0];target=layer['thermal_design']
    require(layer['purpose']=='design_derived_uniform_insulation' and target['not_existing_stock_claim']
            and not target['code_compliance_claimed'],'CONDITION_ENVELOPE_RECIPE_SCOPE')
    source_file(target['evidence'],root)
    for name,origin in layer['field_provenance'].items():
        require(origin['method']==('design_derived' if name=='thickness' else 'inherit_source'),
                'CONDITION_ENVELOPE_RECIPE_PROPERTY_METHOD')
        if origin.get('evidence'):source_file(origin['evidence'],root)
    return {**definition,'country':old['country'],'reference_insert':layer,'target':target,
            'source_differences':old['source_differences'],
            'scope':'Controlled complete public reference plus this declared historical roof-plane design;not local stock,a survey home or code compliance'}


def instantiate(rows,schema_ref,recipe_id,out,*,root=ROOT):
    rule=recipe(recipe_id,root=root)
    if rule.get('adapter')=='complete_reference_constructions_v1':
        from .reference_enclosure import instantiate as complete_enclosure
        return complete_enclosure(rows,schema_ref,rule['source_pack'],out,root=root)
    fields=Fields(source_file(schema_ref,root))
    material=next((r for r in objects(rows,'Material') if r[1]==rule['reference_insert']['source_material']['name']),None)
    require(material is not None,'CONDITION_ENVELOPE_COMPLETE_SOURCE_MATERIAL_MISSING')
    reference=rule['reference_insert']['after']
    for key in MATERIAL_FIELDS:
        if key!='thickness':
            require(fields.get(material,key)==fields.get(reference,key),'CONDITION_ENVELOPE_SOURCE_MATERIAL_INCOMPATIBLE',key)
    matches=[(i,r) for i,r in enumerate(rows) if r[0]=='BuildingSurface:Detailed'
        and fields.get(r,'surface_type')=='Roof' and fields.get(r,'outside_boundary_condition')=='Outdoors']
    require(matches,'CONDITION_ENVELOPE_NO_EXPOSED_ROOF')
    require(all(fields.get(r,'zone_name')==rule['source_roof_zone'] for _,r in matches),
            'CONDITION_ENVELOPE_ATTIC_CONTEXT_UNSUPPORTED')
    pack={'schema':'national_idf.envelope_adaptation.v1','id':'condition_envelope_'+digest({'model':rows,'recipe':rule})[:24],
        'country':rule['country'],'representation_kind':'controlled_reference','scope':rule['scope'],
        'source_differences':rule['source_differences'],'source_rows_sha256':digest(rows),'assignments':[]}
    no_change=[];target=rule['target'];film=target['film_R_m2K_W'];conductivity=float(fields.get(material,'conductivity'))
    for index,surface in matches:
        construction=next(r for r in objects(rows,'Construction') if r[1]==fields.get(surface,'construction_name'))
        properties=construction_properties(rows,construction,fields);resistance=properties['R_layers_m2K_W']
        # A design limit is an upper bound:do not remove source insulation to
        # force equality when a complete source roof already meets the target.
        if 1/(film+resistance)<=target['target_U_W_m2K']:
            no_change.append({'surface':selector(rows,index),'reason':'Complete source already meets frozen roof-plane target',
                              'U_static_W_m2K':1/(film+resistance)});continue
        thickness=insulation_thickness(target['target_U_W_m2K'],film,resistance,conductivity)
        after=copy.deepcopy(material);fields.set(after,'thickness',format(thickness,'.17g'))
        provenance=copy.deepcopy(rule['reference_insert']['field_provenance'])
        provenance['thickness']['inputs'].update(source_layers_R_m2K_W=resistance,source_k_W_mK=conductivity)
        layers=[{'source_material':selector(rows,rows.index(next(r for r in rows if r[0].startswith('Material') and r[1]==name))),
                 'after':None,'basis':'unchanged_complete_source_layer'} for name in construction[2:] if name]
        pack['assignments'].append({'surface':selector(rows,index),'construction':selector(rows,rows.index(construction)),
            'surface_type':'Roof','outside_boundary_condition':'Outdoors','layers':layers,
            'insert_layers':[{'source_material':selector(rows,rows.index(material)),'after':after,
                'after_source_layer_index':len(layers)-1,'purpose':'design_derived_uniform_insulation',
                'field_provenance':provenance,'thermal_design':target}]})
    out.mkdir(parents=True,exist_ok=False);save(out/'PACK.json',pack)
    if pack['assignments']:
        result,report=apply(rows,ref(out/'PACK.json',root),schema_ref,root=root)
    else:
        require(len(no_change)==len(matches),'CONDITION_ENVELOPE_EMPTY_UNEXPLAINED_RECIPE')
        result=copy.deepcopy(rows)
        report={'schema':'national_idf.envelope_modifications.v1','pack':ref(out/'PACK.json',root),
            'source_rows_sha256':digest(rows),'result_rows_sha256':digest(result),'modifications':[],
            'geometry_and_adjacency_unchanged':True,'unselected_objects_unchanged':True,
            'source_materials_retained':True,'physical_validation_passed':False,'formal_admitted':False,
            'no_modification_needed_for_declared_static_upper_bound':True}
    report.update(recipe_id=recipe_id,recipe_source=rule['source_pack'],surfaces_already_meet_target=no_change,
        all_exposed_roofs_accounted=len(matches)==len(pack['assignments'])+len(no_change),
        no_handwritten_surface_names_or_indices=True,material_properties_inherited_from_complete_source=True,
        design_is_not_local_stock_or_code_compliance=True)
    save(out/'MODIFICATIONS.json',report)
    return result,report
