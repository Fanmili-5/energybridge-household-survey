"""One shared official numerical package;no house/device/threshold tuning."""
import argparse
import copy
from pathlib import Path

from national_idf.common import ROOT,read,save,require,digest
from national_idf.idf import parse,render,objects
from national_idf.source_adapter import source_file,selector,housing_fingerprint
from national_idf.source_numerics import zone_air_solver_probe
from national_idf.reference_ports import rebind
from national_idf.program_resources import model_signature
from national_idf.reference_workflow import ref
from national_idf.assembly import compile_assembly


def execute(parent,out):
    parent=Path(parent).resolve();out=Path(out).resolve()
    require(not out.exists() or not any(out.iterdir()),'CONDITION_SOLVER_OUTPUT_EXISTS');out.mkdir(parents=True,exist_ok=True)
    fixture=read(parent/'FIXTURE.json');case=read(parent/'CASE.json')
    source=parse(source_file(fixture['model'],ROOT).read_text());indices=[i for i,r in enumerate(source) if r[0]=='ZoneAirHeatBalanceAlgorithm']
    require(len(indices)<=1,'CONDITION_SOLVER_SOURCE_CARDINALITY')
    index=indices[0] if indices else None
    before=source[index] if index is not None else ['ZoneAirHeatBalanceAlgorithm','ThirdOrderBackwardDifference']
    explicit=copy.deepcopy(source)
    if index is None:
        schema=read(source_file(fixture['engine_schema'],ROOT))
        require(schema['properties']['ZoneAirHeatBalanceAlgorithm']['patternProperties']['.*']['properties']['algorithm']['default']=='ThirdOrderBackwardDifference',
                'CONDITION_SOLVER_IMPLICIT_DEFAULT_NOT_CONFIRMED')
        explicit.append(before)
        save(out/'IMPLICIT_DEFAULT.json',{'source_model':fixture['model'],'schema':fixture['engine_schema'],
            'source_object_absent':True,'effective_algorithm_from_official_schema':'ThirdOrderBackwardDifference',
            'physical_fields_filled':False})
    probe={'schema':'national_idf.official_zone_air_solver_probe.v1','scope':'one_factor_official_air_heat_balance_integration_pilot',
        'before':before,'after':['ZoneAirHeatBalanceAlgorithm','AnalyticalSolution'],
        'source_model':fixture['model'],'engine_schema':fixture['engine_schema'],'protocol':ref(ROOT/'configs/study_protocol.json'),
        'formal_admitted':False}
    save(out/'PROBE.json',probe);zone_air_solver_probe(explicit,ref(out/'PROBE.json'),fixture['engine_schema'],probe['protocol'])
    (out/'METHOD.idf').write_text(render([probe['after']]))
    expected=copy.deepcopy(source)
    if index is None:expected.append(probe['after'])
    else:expected[index]=probe['after']
    mapping=copy.deepcopy(fixture['EB_mapping']);save(out/'MAPPING.json',mapping)
    adapter={'schema':'national_idf.source_adapter.v1','adapter':'native_idf_objects.v1','id':'official_solver_source_'+digest(fixture['model'])[:20],
        'package_id':'condition-source-exact-official-solver','model':fixture['model'],'engine_version':'25.2',
        'housing_sha256':housing_fingerprint(source),'thermal_zones':[r[1] for r in objects(source,'Zone')],
        'legacy_groups':{},'schedule_files':[],'support_conditions':{'use':'explicit official air-solver method study'},
        'source_scope_gaps':['New numerical method not automatically admitted across housing or seasons']}
    for i,row in enumerate(source):
        if row[0]!='Schedule:File':continue
        matches=[v['source'] for v in fixture['dependencies'] if v['output_path']==row[3]]
        require(matches and len({(v['path'],v['sha256']) for v in matches})==1,'CONDITION_SOLVER_SCHEDULE_DEPENDENCY')
        adapter['schedule_files'].append({'object':selector(source,i),'original_filename':row[3],'file':matches[0]})
    save(out/'ADAPTER.json',adapter)
    identifier='condition_solver_'+digest({'source_configuration_id':fixture['id'],
        'source_model_sha256':fixture['model']['sha256'],'weather':fixture['weather'],
        'engine_schema':fixture['engine_schema'],'method':probe['after']})[:24]
    operation={'action':'add' if index is None else 'replace','after':{'file':ref(out/'METHOD.idf'),'object':selector([probe['after']],0)},
          'reason':'One source-bound official zone air integration method;all physical inputs unchanged','evidence':ref(out/'PROBE.json'),'affected_meters':['*']}
    if index is not None:operation['object']=selector(source,index)
    blueprint={'schema':'national_idf.assembly_blueprint.v1','id':identifier,'source_adapter':ref(out/'ADAPTER.json'),
        'changes':[operation],
        'legacy_group_policy':{},'components':{k:{'status':'engineering_reference','evidence':ref(out/'PROBE.json')} for k in ('air_conditioner','washer','dryer','dishwasher','water_heater','ev')},
        'engine_schema':fixture['engine_schema'],'eb_mapping':ref(out/'MAPPING.json'),'eb_binding_implementation':fixture['EB_modules']['binding'],
        'site_weather':{'artifacts':[ref(out/'PROBE.json')],'weather':fixture['weather']},
        'numerical_protocol':probe['protocol'],'review_receipts':{},'assembly_gaps':[],'formal_release_gaps':adapter['source_scope_gaps']}
    save(out/'BLUEPRINT.json',blueprint);compile_assembly(identifier,out/'assembly',mode='engineering_reference',blueprint_ref=ref(out/'BLUEPRINT.json'))
    actual=parse((out/'assembly/in.idf').read_text())
    # Assembly may relocate a repeated shared CSV by its content hash.
    for model in (actual,expected):
        for row in objects(model,'Schedule:File'):row[3]='BOUND_UNCHANGED_CSV'
    require(actual==expected,'CONDITION_SOLVER_CHANGED_MORE_THAN_DECLARED_METHOD')
    actual=parse((out/'assembly/in.idf').read_text())
    # Rebinding source life ownership changes no person/water/background row;
    # the complete source compiler still supplies all physical equations.
    life=rebind(fixture,source,actual,ref(out/'PROBE.json'));save(out/'LIFE_INSTALLATION.json',life)
    pack=read(source_file(fixture['resource_pack'],ROOT));pack['binding_model_signature']=model_signature(actual)
    pack['source_evidence'].append(ref(out/'PROBE.json'));save(out/'RESOURCE_PACK.json',pack)
    domain=read(source_file(fixture['input_domain'],ROOT));domain['physics_configuration_id']=identifier
    for programme in domain['programs'].values():programme['resource_pack']=ref(out/'RESOURCE_PACK.json')
    save(out/'DOMAIN.json',domain)
    derived=copy.deepcopy(fixture);derived.update(id=identifier,model=ref(out/'assembly/in.idf'),
        input_domain=ref(out/'DOMAIN.json'),resource_pack=ref(out/'RESOURCE_PACK.json'),
        life_installation_receipt=ref(out/'LIFE_INSTALLATION.json'),dependencies=read(out/'assembly/ASSEMBLY.json')['dependencies'])
    save(out/'FIXTURE.json',derived);case['case_id']=identifier;case['environment']['physics_configuration_id']=identifier;save(out/'CASE.json',case)
    save(out/'DERIVATION.json',{'source_fixture':ref(parent/'FIXTURE.json'),'probe':ref(out/'PROBE.json'),
        'same_source_compiler_used':True,'only_official_air_solver_method_changed':True,
        'original_EB_tank_house_device_and_weather_unchanged':True,'accuracy_criteria_unchanged':True,'admission_granted':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();execute(a.parent,a.out)
