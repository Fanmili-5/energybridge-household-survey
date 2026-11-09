"""Native quality of a source combination using existing EB execution kernels."""
import copy
from pathlib import Path

from .case_commands import CaseTimeline
from .common import ROOT, digest, read, require, save, sha, verify
from .idf import Fields, parse, render
from .reference_workflow import ref
from .source_adapter import source_file


def compile_native(parent_ref, pack_ref, case, out, *, root=ROOT):
    if pack_ref:
        from .reference_inventory import compile_case
        return compile_case(parent_ref, pack_ref, case, out, root=root)
    from .joint_case_runtime import compile_joint_case
    return compile_joint_case(parent_ref, case, out, mode='engineering_reference', root=root)


def run_native(compiled, out, *, root=ROOT):
    if read(Path(compiled) / 'MANIFEST.json')['schema'] == 'national_idf.compiled_inventory_reference.v1':
        from .reference_inventory import run
        return run(compiled, out, root=root)
    from .joint_case_runtime import run_joint_case
    return run_joint_case(compiled, out, mode='engineering_reference', root=root)


def validate_native(compiled, out, *, root=ROOT):
    from scripts.validate_multicountry_life import validate
    compiled, out = Path(compiled), Path(out); metadata = verify(compiled)
    if metadata['schema'] == 'national_idf.compiled_inventory_reference.v1':
        return validate(out, read(compiled / 'PARENT_FIXTURE.json'), read(compiled / 'CASE.json'),
                        metadata['installed_devices'], compiled / 'DOMAIN.json')
    return validate(out, read(compiled / 'FIXTURE.json'), read(compiled / 'CASE.json'))


def observe(parent_ref, pack_ref, case, prior_run, out, *, root=ROOT):
    from .reference_curve_observer import instrument, report
    parent = read(source_file(parent_ref, root)); original = parse(source_file(parent['model'], root).read_text())
    fields = Fields(source_file(parent['engine_schema'], root)); rows, tables = instrument(original, fields)
    out = Path(out); out.mkdir()
    (out / 'parent.idf').write_text(render(rows)); parent['model'] = ref(out / 'parent.idf', root)
    save(out / 'PARENT_FIXTURE.json', parent)
    if pack_ref:
        pack = read(source_file(pack_ref, root)); pack['parent_model'] = parent['model']
        save(out / 'PACK.json', pack); pack_ref = ref(out / 'PACK.json', root)
    compile_native(ref(out / 'PARENT_FIXTURE.json', root), pack_ref, case, out / 'compiled', root=root)
    run_native(out / 'compiled', out / 'run', root=root)
    require((Path(prior_run) / 'TRACE.csv').read_bytes() == (out / 'run/TRACE.csv').read_bytes(),
            'COMBINATION_CURVE_OBSERVER_CHANGED_TRACE')
    result = report(rows, tables, fields, out / 'run', root=root)
    result.update(native_trace_unchanged=True, actual_case_sha256=digest(case))
    save(out / 'CURVE_CHECKS.json', result)
    return result


def matrix(parent_ref, pack_ref, contract_ref, case, library, out, *, root=ROOT):
    """Choose a legal registered clock without rounding the requested events."""
    from .reference_numeric_fixture import prepare
    from .reference_retirement import rebase
    from .reference_controls import validate as validate_contract
    from scripts.analyze_multicountry_life_numerics import PAIRS, compare_paths
    from scripts.analyze_multicountry_water_convergence import native_grid
    parent = read(source_file(parent_ref, root)); out = Path(out); out.mkdir()
    original = parse(source_file(parent['model'], root).read_text()); variants = [(1,14,7),(2,14,7),(5,14,7),(2,28,7),(2,14,14)]
    available, unavailable, native = {}, {}, {}
    for step, warmup, days in variants:
        for arm in ('baseline','intervention'):
            tag = f's{step}_w{warmup}_d{days}_{arm}'; folder = out / tag
            identifier = 'cq_' + digest({'case':case, 'source':parent_ref,'variant':tag})[:24]
            numeric_ref, numeric_case = prepare(parent_ref, case, library, folder / 'parent', step,warmup,days,arm,identifier,root=root)
            numeric = read(source_file(numeric_ref,root)); domain = read(source_file(numeric['input_domain'],root))
            timeline = CaseTimeline(numeric_case, domain, root=root) if step != 5 else None
            if step == 5:
                from .request_support import assess_inputs
                support = assess_inputs(numeric_case,domain,root)
                if support['failures']:
                    require(all(v['code']=='COMMAND_OUTSIDE_BOUND_GRID' for v in support['failures']),
                            'COMBINATION_NON_GRID_NUMERIC_INPUT_FAILURE',support['failures'])
                    unavailable[tag]={'reason':'Requested events cannot be represented on5-minute grid;no event was rounded',
                                      'failures':support['failures']}; continue
                timeline=CaseTimeline(numeric_case,domain,root=root)
            current_pack=None
            if pack_ref:
                pack=read(source_file(pack_ref,root));pack['parent_model']=numeric['model']
                pack['changes']=rebase(original,pack,parse(source_file(numeric['model'],root).read_text()))
                pack['id']=identifier+'_inventory';numeric_case['environment']['physics_configuration_id']=pack['id']
                save(folder/'PACK.json',pack);current_pack=ref(folder/'PACK.json',root)
            if contract_ref:
                contract=read(source_file(contract_ref,root));fixed=read(source_file(contract['fixed_background_case'],root))
                fixed['environment']['physics_configuration_id']=identifier;save(folder/'FIXED.json',fixed)
                contract.update(physics_configuration_id=identifier,fixed_background_case=ref(folder/'FIXED.json',root))
                save(folder/'CONTRACT.json',contract);validate_contract(numeric_case,timeline,ref(folder/'CONTRACT.json',root),root=root)
            compile_native(numeric_ref,current_pack,numeric_case,folder/'compiled',root=root)
            # The established water-convergence reader resolves the exact
            # numerical clock beside the run, rather than inside compilation.
            compiled_domain=folder/'compiled/DOMAIN.json'
            save(folder/'DOMAIN.json',read(compiled_domain) if compiled_domain.exists() else domain)
            run_native(folder/'compiled',folder/'run',root=root)
            native[tag]=validate_native(folder/'compiled',folder/'run',root=root)
            available[(step,warmup,days,arm)]=folder/'run'
    comparisons={};water={}
    for name,a,b in PAIRS:
        keys=[(*args,arm) for args in (a,b) for arm in ('baseline','intervention')]
        if not all(key in available for key in keys):
            comparisons[name]={'passed':None,'applicable':False,'reason':'Same requested instruction is not representable at the coarser grid'}
        else:
            result=compare_paths([available[(*a,arm)] for arm in ('baseline','intervention')],
                                 [available[(*b,arm)] for arm in ('baseline','intervention')]);result['applicable']=True
            comparisons[name]=result
            water[name]={}
            for arm in ('baseline','intervention'):
                aa,bb=[native_grid(available[(*args,arm)]) for args in (a,b)]
                active=[k for k in set(aa)&set(bb) if aa[k]['kg']>0 and bb[k]['kg']>0]
                errors=[abs(aa[k]['delivery_C']-bb[k]['delivery_C']) for k in active]
                water[name][arm]={'active_10min_bins':len(active),'delivery_MAE_C':sum(errors)/len(errors) if errors else None,
                    'delivery_max_difference_C':max(errors) if errors else None,
                    'comfort_threshold_C':None,'service_success_inferred':False}
    fine=all(comparisons[name]['passed'] is True for name in ('2_vs_1min','warmup_14_vs_28days','tail_7_vs_14days'))
    selected=5 if fine and comparisons['5_vs_2min']['passed'] is True else 2 if fine else None
    result={'schema':'national_idf.combination_request_numerics.v1','comparisons':comparisons,'native_checks':native,
        'unrepresentable_variants':unavailable,'selected_step_min':selected,'quality_passed':selected is not None,
        'water_delivery_convergence':water,
        'criteria_or_requested_times_changed':False,'protocol':ref(root/'configs/study_protocol.json',root)}
    save(out/'QUALITY.json',result);return result
