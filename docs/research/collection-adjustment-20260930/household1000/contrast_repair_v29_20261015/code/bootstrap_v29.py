"""Sparse immutable-parent overlay. No runs or acceptance reports are inherited."""
import os,shutil
from common import *
from contrast_core import PROTOCOL
PARENT=BASE/'formal50_950_production_v28_20261014'

def main():
    school_guard();assert not(OUT/'BOOTSTRAP_V29.json').exists()
    assert sha(PARENT/'PHYSICAL_PRODUCTION_COMPLETE.json')=='cce9629b620a83de04f6e08db24563121a38d6a1de17b2ef0e0066d2d0b3c87a'
    names=['PARTITIONS.json','SELECTION1000.json','WORLD_BINDINGS1000.json','COMPILED1000.json','COMPILED_SENSITIVITY50.json','COMPILED_WEATHER_SENSITIVITY.json','WEATHER_QC_REVIEW.json','EXTERNAL_INPUT_LOCK.json']
    for name in names:shutil.copy2(PARENT/name,OUT/name)
    paths=set()
    for h in read(PARENT/'SELECTION1000.json')['records']:
        paths.add(h['world_path']);paths.update(r['pair_path']for r in h['rounds'])
    for name in('COMPILED1000.json','COMPILED_SENSITIVITY50.json','COMPILED_WEATHER_SENSITIVITY.json'):
        for c in read(PARENT/name)['records']:
            for side in('A','B'):
                for key in('IDF_path','native_IDF_path','signal_ledger_path'):paths.add(c[side][key])
    for name in sorted(paths):
        dest=OUT/name;dest.parent.mkdir(parents=True,exist_ok=True);os.link(PARENT/name,dest)
    save(OUT/'PROTOCOL_V29.json',{**PROTOCOL,'parent_acceptance_sha256':sha(PARENT/'PHYSICAL_PRODUCTION_COMPLETE.json'),
       'user_requested_original50_before950':True,'all1000_household_and_type_assignments_frozen':True,
       'baseline_AC_policy':'retainV28 occupied/seasonal reference control;EB24havailability is not continuous compressor duty',
       'no_full_EP_before_original50_contrast_acceptance':True})
    save(OUT/'BOOTSTRAP_V29.json',{'parent':str(PARENT),'parent_selection_sha256':sha(PARENT/'SELECTION1000.json'),'hardlinked_input_files':len(paths),
       'shared_files_replaced_atomically_before_any_edit':True,'run_receipts_or_acceptance_reports_inherited':False,'EP_started':False})
    print({'bootstrapped':len(paths),'EP_started':False},flush=True)
if __name__=='__main__':main()
