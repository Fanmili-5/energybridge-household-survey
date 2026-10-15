"""Copy-on-write inputs only. Historical failed V29 receipts are not inherited."""
import os,shutil
from common import *
from contrast_core import PROTOCOL
PARENT=BASE/'contrast_repair_v29_20261015'
def main():
    school_guard();assert not(OUT/'BOOTSTRAP_V30.json').exists()
    for name in ('PARTITIONS.json','SELECTION1000.json','WORLD_BINDINGS1000.json','COMPILED1000.json','COMPILED_SENSITIVITY50.json','COMPILED_WEATHER_SENSITIVITY.json','WEATHER_QC_REVIEW.json','EXTERNAL_INPUT_LOCK.json','LEGACY_CONTRAST_QUEUE.json','EB_AC_SOURCE_REVIEW.json'):
        shutil.copy2(PARENT/name,OUT/name)
    paths=set()
    for h in read(PARENT/'SELECTION1000.json')['records']:
        paths.add(h['world_path']);paths.update(r['pair_path']for r in h['rounds'])
    for name in ('COMPILED1000.json','COMPILED_SENSITIVITY50.json','COMPILED_WEATHER_SENSITIVITY.json'):
        for c in read(PARENT/name)['records']:
            for side in ('A','B'):
                for key in ('IDF_path','native_IDF_path','signal_ledger_path'):paths.add(c[side][key])
    for name in sorted(paths):
        path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True);os.link(PARENT/name,path)
    save(OUT/'PROTOCOL_V29.json',PROTOCOL)
    save(OUT/'BOOTSTRAP_V30.json',{'parent':str(PARENT),'parent_selection_sha256':sha(PARENT/'SELECTION1000.json'),
        'hardlinked_input_files':len(paths),'atomic_replacement_required':True,'inherited_acceptance':False,'EP_started':False})
    print({'stage':OUT.name,'hardlinked_inputs':len(paths),'EP_started':False},flush=True)
if __name__=='__main__':main()
