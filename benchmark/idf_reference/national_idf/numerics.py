"""Independent equation audit for the pinned in-tree 24.1 research patch.

Original warnings are preserved. Each numerical replacement must have one
independently reproduced bounded root. No official-release fix is claimed.
"""
import importlib.util
from .common import ROOT,require,sha,locked


def review(stderr,pin):
    for item in pin['locked_sources']:locked(item,ROOT)
    path=ROOT/'resources/numerical_repair/independent_v24_reference.py'
    require(sha(path)==pin['independent_checker_sha256'],'NUMERICAL_CHECKER_CHANGED')
    spec=importlib.util.spec_from_file_location('_idf_independent_math',path)
    checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
    events=[];unresolved=[];clips=[]
    for line in stderr.splitlines():
        if not line.startswith('EBTWB_'):continue
        fields=dict(s.split('=',1)for s in line.split('\t')[1:]if'='in s)
        if line.startswith('EBTWB_REPAIR_UNRESOLVED'):unresolved.append(fields);continue
        if line.startswith('EBTWB_EXISTING_CLIP'):
            db,w,p,new=(float(fields[k])for k in ['tdb','w','p','clipped_return'])
            require(new==db,'NATIVE_CLIP_BOUNDARY_CHANGED')
            residual=checker.residual(db,w,p,new,new<0)
            require(abs(residual-float(fields['clipped_residual']))<=1e-12,'NATIVE_CLIP_RESIDUAL_MISMATCH')
            fields['relative_humidity_ratio_excess']=max(0.,-residual)/max(w+residual,1e-12)
            fields['initialization_boundary_only']=fields.get('warmup')=='1'and fields.get('sim_steps')=='1'
            # This unchanged saturation boundary is not a repaired iteration.
            # A real iteration limit at this boundary remains unresolved.
            fields['within_rounding_screen']=(fields['relative_humidity_ratio_excess']<=1e-3
                  or fields['initialization_boundary_only'])and int(fields['iter'])<=100
            clips.append(fields);continue
        require(line.startswith('EBTWB_REPAIR_APPLIED'),'UNKNOWN_REPAIR_EVENT',line)
        db,w,p,old,new=(float(fields[k])for k in ['tdb','w','p','old','new'])
        roots=checker.roots(db,w,p);residual=checker.residual(db,w,p,new,new<0)
        old_residual=checker.residual(db,w,p,old,old<0)
        require(len(roots)==1 and abs(new-roots[0])<=2e-7 and abs(residual)<=1e-8,
                'REPAIR_NOT_INDEPENDENTLY_UNIQUE')
        require(abs(old_residual)>1e-8 and abs(residual-float(fields['new_residual']))<=1e-12,
                'REPAIR_RESIDUAL_MISMATCH')
        require(abs(old_residual-float(fields['old_residual']))<=1e-12,'OLD_RESIDUAL_MISMATCH')
        events.append({'tdb_C':db,'humidity_ratio':w,'pressure_Pa':p,'old_C':old,'new_C':new,
                       'residual':residual,'context':fields})
    return {'passed':not unresolved and all(c['within_rounding_screen']for c in clips),
      'summary':{'repairs':len(events),'unresolved':len(unresolved)},
      'events':events,'unresolved':unresolved,'original_saturation_boundary_clips':clips,
      'max_abs_humidity_residual':max((abs(e['residual'])for e in events),default=0),
      'independent_checker_sha256':sha(path),'original_warnings_retained':True,
      'official_release_fix_claimed':False,'binary_attestation':'exact_source_build_hashes_checked_by_runtime'}
