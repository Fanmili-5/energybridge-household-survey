"""Original numerical comparisons and passive curve checks for a new house."""
import argparse
from pathlib import Path
import time

from national_idf.common import ROOT,read,require,save,digest,verify,sha
from national_idf.condition_quality import prepare
from national_idf.joint_case_runtime import compile_joint_case,run_joint_case
from national_idf.reference_workflow import ref
from national_idf.source_adapter import source_file
from national_idf.request_support import assess_inputs
from scripts.analyze_multicountry_life_numerics import PAIRS,compare_paths
from scripts.validate_multicountry_life import validate


def execute(folder,libraries_ref):
    folder=Path(folder).resolve();out=folder/'numerics';out.mkdir(exist_ok=True)
    prior=read(out/'QUALITY.json') if (out/'QUALITY.json').exists() else None
    fixture_ref=ref(folder/'FIXTURE.json');case=read(folder/'CASE.json');libraries=read(source_file(libraries_ref,ROOT))
    from national_idf.condition_controls import fixed_control_fields
    fixed_fields=fixed_control_fields(read(folder/'EQUIPMENT.json')) if (folder/'EQUIPMENT.json').exists() else set()
    available={};native={};unavailable={};start=time.monotonic()
    for step,warmup,days in [(1,14,7),(2,14,7),(5,14,7),(2,28,7),(2,14,14)]:
        for arm in ('baseline','intervention'):
            label=f's{step}_w{warmup}_d{days}_{arm}';p=out/label
            if not (p/'parent/FIXTURE.json').exists():
                f,c=prepare(fixture_ref,case,libraries['fixtures'][str(step)],p/'parent',step,warmup,days,arm,
                    'cq_'+digest({'fixture':fixture_ref,'case':case,'variant':label})[:24],fixed_control_fields=fixed_fields)
            else:f=ref(p/'parent/FIXTURE.json');c=read(p/'parent/CASE.json')
            definition=read(source_file(f,ROOT));domain=read(source_file(definition['input_domain'],ROOT))
            support=assess_inputs(c,domain,ROOT)
            if support['failures']:
                require(step==5 and all(v['code']=='COMMAND_OUTSIDE_BOUND_GRID' for v in support['failures']),
                    'CONDITION_NUMERICAL_UNSUPPORTED',support['failures'])
                unavailable[label]=support['failures'];continue
            if not (p/'compiled').exists():compile_joint_case(f,c,p/'compiled',mode='engineering_reference')
            if not (p/'run/RUNTIME.json').exists():run_joint_case(p/'compiled',p/'run',mode='engineering_reference')
            verify(p/'compiled')
            for name,signature in read(p/'run/IMPLEMENTATION.json').items():
                require(sha(ROOT/name)==signature,'CONDITION_CACHED_NUMERICAL_BACKEND_CHANGED',name)
            native[label]=validate(p/'run',definition,c);available[(step,warmup,days,arm)]=p/'run'
            print(folder.name,label,'native',flush=True)
    comparisons={}
    for name,a,b in PAIRS:
        keys=[(*args,arm) for args in (a,b) for arm in ('baseline','intervention')]
        comparisons[name]=compare_paths([available[(*a,arm)] for arm in ('baseline','intervention')],
            [available[(*b,arm)] for arm in ('baseline','intervention')]) if all(k in available for k in keys) else {'passed':None,'applicable':False}
    fine=all(comparisons[k]['passed'] is True for k in ('2_vs_1min','warmup_14_vs_28days','tail_7_vs_14days'))
    selected=5 if fine and comparisons['5_vs_2min']['passed'] is True else 2 if fine else None
    from national_idf.reference_release import request_digest
    result={'schema':'national_idf.condition_housing_quality.v1','comparisons':comparisons,'native_checks':native,
        'parent_fixture':fixture_ref,'request_sha256':request_digest(case),
        'implementation':quality_identity(),
        'quality_passed':selected is not None,'selected_step_min':selected,'criteria_changed':False,
        'unrepresentable_coarse_grid_requests_not_rounded':unavailable,'seconds':time.monotonic()-start,
        'initial_full_execution_seconds':prior.get('initial_full_execution_seconds',prior['seconds']) if prior else time.monotonic()-start,
        'fractional_profile_library':libraries_ref,'source_powers_and_housing_not_copied_from_library':True,
        'full_geometry_site_admission_granted':False}
    save(out/'QUALITY.json',result)
    # Reuse existing reporting-only observer and unchanged model/domain policy.
    from national_idf.reference_combination_quality import observe
    curve=folder/'curve_observed'
    if not (curve/'CURVE_CHECKS.json').exists():observe(fixture_ref,None,case,folder/'run',curve)
    result['curve_domain_passed']=read(curve/'CURVE_CHECKS.json')['passed_observed_domain_screen']
    save(out/'QUALITY.json',result)
    print(folder.name,'original numerics',result['quality_passed'],'curves',result['curve_domain_passed'],flush=True)


def quality_identity():
    from national_idf.release import compiler_identity
    from national_idf.runtime_release import runtime_identity
    return {**compiler_identity(),**runtime_identity(),**{p:sha(ROOT/p) for p in (
        'national_idf/condition_quality.py','scripts/check_condition_housing.py',
        'scripts/analyze_multicountry_life_numerics.py','scripts/analyze_multicountry_numerics.py',
        'configs/study_protocol.json')}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);p.add_argument('--libraries',type=Path,required=True)
    a=p.parse_args();execute(a.folder,ref(a.libraries))
