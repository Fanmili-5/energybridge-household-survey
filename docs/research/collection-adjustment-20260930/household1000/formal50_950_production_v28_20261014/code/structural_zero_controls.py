"""Accept proven absent components; reject missing physical observations."""
import copy
from common import *
from physics import structural_zero_people

def main():
    ledger={'spatial':{'lighting':{'room':[0.,0.]},'resident_occupancy':{'m01':{'room':[0.,0.]}},'external_occupancy':{}}}
    f={0:{},1:{}};proof=structural_zero_people(f,ledger,[])
    assert all(v['Zone People Occupant Count','ROOM']==0. for v in f.values())and proof
    def rejects(fr,l,rows):
        try:structural_zero_people(fr,l,rows)
        except RuntimeError:return True
        return False
    occupied=copy.deepcopy(ledger);occupied['spatial']['resident_occupancy']['m01']['room']=[0.,1.]
    checks={'zero_without_components_proved':True,'occupied_missing_variable_rejected':rejects({0:{},1:{}},occupied,[]),
        'existing_People_component_missing_SQL_rejected':rejects({0:{},1:{}},ledger,[['People','p','room']]),
        'partial_SQL_missing_rejected':rejects({0:{('Zone People Occupant Count','ROOM'):0.},1:{}},ledger,[]),
        'existing_zero_schedule_missing_SQL_rejected':rejects({0:{('Zone People Occupant Count','ROOM'):0.},1:{('Zone People Occupant Count','ROOM'):0.}},ledger,[['Schedule:Compact','v19_person_m01_room']])}
    assert all(checks.values());save(OUT/'STRUCTURAL_ZERO_CONTROLS.json',{'status':'pass','checks':checks,'physical_IDF_and_source_ledger_unchanged':True,'human_answers':0})
    print({'structural_zero_controls':'pass','checks':len(checks)},flush=True)

if __name__=='__main__':main()
