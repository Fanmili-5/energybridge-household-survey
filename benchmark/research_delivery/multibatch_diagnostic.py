"""One fixed post-hoc query; never supplements the official candidate bank."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha
from benchmark.ab_generation.unified.candidates import prepare,Oracle
from benchmark.ab_generation.unified.factorized import ProgramRecipe
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.independent import audit
from benchmark.ab_generation.model import apply
from .acceptance import record_sources


def run(out):
    out=Path(out);root=out/'fifty';pre,inputs=record_sources(root)
    key=('ordinary-v6-0841','2025-07-14')
    slot=next(s for s in read(root/'GENERATION.json') if (s['household_id'],s['date'])==key)
    cat=read(root/slot['path']);values=[]
    for group in cat['native_domains']:
        vs=[]
        for r in group:
            if r and 'recipe' in r:
                t=cat['native_templates'][r['recipe']['template']]
                v=ProgramRecipe(t['template'],t['load'],t['unload'],r['recipe']['load_min'],r['recipe']['unload_min']);v.update(r);vs.append(v)
            else:vs.append(r)
        values.append(vs)
    indices=[i for i,vs in enumerate(values) if vs[1]['family']=='washer']
    if len(indices)!=2:raise ValueError('PREDECLARED_TARGET_CHANGED')
    cfg=config({**pre['configuration'],'oracle_native_encoding_budget':1000000,'oracle_deterministic_time':.2,'rows_per_unit':256,'queries_per_row':16})
    c=prepare(read(inputs[key]),cfg)
    profile=next(m['household_profile'] for m in read(root/'MATERIALS.json.gz') if m['household_id']==key[0])
    g=dict(values=values,descriptors=cat['factors'],domains=[list(range(len(ds))) for ds in cat['factors']]);oracle=Oracle(c,g,cfg,profile)
    status,witness,reason=oracle({i:0 for i in range(len(values)) if i not in indices},order=2,
        native_required={i:list(range(1,len(values[i]))) for i in indices})
    rows=list(oracle.rows.values());result=dict(status=status,reason=reason,witness=witness,rows=rows,diagnostics=oracle.diagnostics,
        calls=oracle.calls,materializations=oracle.materializations,source_catalogue_sha256=sha(root/slot['path']),configuration=cfg,
        independent_errors=[dict(id=r['id'],errors=audit(c,c['A'],apply(c['A'],r['patches']))) for r in rows],
        posthoc_fixed_target_diagnostic=True,only_one_query=True,no_reseed=True,original_catalogue_or_selection_changed=False,
        official_coverage_counts_unchanged=True,physical_runs=0)
    save(out/'SAME_FAMILY_TARGETED_DIAGNOSTIC.json.gz',result);return dict(status=status,reason=reason,rows=len(rows))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();print(run(a.out))
