"""Original numerical/native/retirement checks for generic declared inventories."""
import argparse
import copy
from pathlib import Path
import time

from national_idf.common import ROOT,read,require,save,verify,sha
from national_idf.condition_inventory import make_pack,project_engineering_case,require_no_absent_demands
from national_idf.idf import parse,Fields
from national_idf.reference_inventory import compile_case,run
from national_idf.reference_retirement import audit
from national_idf.reference_scenarios import FUNCTIONS,inventory
from national_idf.reference_workflow import ref
from national_idf.source_adapter import source_file
from scripts.validate_multicountry_life import validate
from scripts.analyze_multicountry_life_numerics import PAIRS,compare_paths


def execute(parent,equipment_ref,out):
    parent=Path(parent).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    equipment=read(source_file(equipment_ref,ROOT));installed=inventory(equipment)['installed']
    def one(base,dest):
        fixture_ref=ref(base/'FIXTURE.json');fixture=read(source_file(fixture_ref,ROOT))
        if not (dest/'inventory/PACK.json').exists():make_pack(fixture_ref,equipment,dest/'inventory')
        pack_ref=ref(dest/'inventory/PACK.json');pack=read(source_file(pack_ref,ROOT))
        case=project_engineering_case(read(base/'CASE.json'),pack);require_no_absent_demands(case,pack)
        save(dest/'CASE.json',case)
        if not (dest/'compiled').exists():compile_case(fixture_ref,pack_ref,case,dest/'compiled')
        if not (dest/'run/RUNTIME.json').exists():run(dest/'compiled',dest/'run')
        verify(dest/'compiled')
        for name,signature in read(dest/'compiled/IMPLEMENTATION.json').items():
            require(sha(ROOT/name)==signature,'CONDITION_INVENTORY_CACHED_CODE_CHANGED',name)
        checks=validate(dest/'run',fixture,case,installed,dest/'compiled/DOMAIN.json')
        before=parse(source_file(fixture['model'],ROOT).read_text());after=parse((dest/'compiled/in.idf').read_text())
        save(dest/'RETIREMENT_AUDIT.json',audit(before,after,pack,Fields(source_file(fixture['engine_schema'],ROOT))))
        return checks
    start=time.monotonic();one(parent,out/'main');available={};native={}
    for step,warmup,days in [(1,14,7),(2,14,7),(5,14,7),(2,28,7),(2,14,14)]:
        for arm in ('baseline','intervention'):
            name=f's{step}_w{warmup}_d{days}_{arm}';base=parent/'numerics'/name/'parent'
            require((base/'FIXTURE.json').exists(),'CONDITION_INVENTORY_PARENT_NUMERICS_MISSING',name)
            dest=out/'numerics'/name;native[name]=one(base,dest);available[(step,warmup,days,arm)]=dest/'run'
            print(out.name,name,'native',flush=True)
    comparisons={name:compare_paths([available[(*a,arm)] for arm in ('baseline','intervention')],
                                  [available[(*b,arm)] for arm in ('baseline','intervention')]) for name,a,b in PAIRS}
    fine=all(comparisons[k]['passed'] for k in ('2_vs_1min','warmup_14_vs_28days','tail_7_vs_14days'))
    selected=5 if fine and comparisons['5_vs_2min']['passed'] else 2 if fine else None
    from national_idf.reference_combination_quality import observe
    curve=out/'curve_observed'
    if not (curve/'CURVE_CHECKS.json').exists():
        observe(ref(parent/'FIXTURE.json'),ref(out/'main/inventory/PACK.json'),read(out/'main/CASE.json'),out/'main/run',curve)
    result={'schema':'national_idf.generated_housing_inventory_quality.v1','parent_fixture':ref(parent/'FIXTURE.json'),
        'declared_equipment':equipment_ref,'installed_devices':installed,'comparisons':comparisons,
        'native_checks':native,'quality_passed':selected is not None,'selected_step_min':selected,
        'curve_domain_passed':read(curve/'CURVE_CHECKS.json')['passed_observed_domain_screen'],
        'retirement_audit':ref(out/'main/RETIREMENT_AUDIT.json'),'criteria_changed':False,
        'original_EB_physics_and_house_geometry_retained':True,'model_admission_granted':False,
        'seconds':time.monotonic()-start}
    save(out/'QUALITY.json',result);print(out.name,'numerical',result['quality_passed'],'curves',result['curve_domain_passed'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--equipment',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();execute(a.parent,ref(a.equipment),a.out)
