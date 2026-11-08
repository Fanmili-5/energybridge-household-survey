"""Assign control-function sets with explicit coverage and minimum edit cost."""
from pathlib import Path
from itertools import combinations
from collections import Counter, defaultdict
import hashlib,json,warnings,sys
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix
ROOT=Path(__file__).resolve().parent
PREV=ROOT
PIN='71a12d64ab98466624cecda6d649a5812f683b8ca0dac3ac8721a73f119baf18'
FUNCTIONS=('AC','WM','DR','DW','WH','EV')
KEY={'AC':'space_ac_available','WM':'washer_available','DR':'dryer_available','DW':'dishwasher_available','WH':'water_heater_available','EV':'home_vehicle_charging'}
COUNTS={'A':{4:55,5:55,6:56},'B':{4:66,5:66,6:66},'C':{4:42,5:42,6:41},'D':{4:50,5:50,6:51},'E':{4:52,5:52,6:52},'F':{4:68,5:68,6:68}}
MASKS=[tuple(c) for k in (4,5,6) for c in combinations(FUNCTIONS,k)]
def allowed(role,mask):return ('AC' in mask if role in 'AB' else True) and ('EV' in mask if role=='F' else True)
def native(c,f):
    q=c['household']['equipment'][KEY[f]]
    if not q['present']:return False
    if f=='WH':return q['energy_carrier']=='electricity' and q.get('appliance_type') not in ('instantaneous_electric_shower',)
    return q.get('energy_carrier')=='electricity'
def cost(c,mask):
    value=0
    for f in FUNCTIONS:
        raw=c['devices'][KEY[f]];q=c['household']['equipment'][KEY[f]]
        if f in mask:
            if native(c,f):value+=0 if raw['status']=='observed' else 1
            elif q['present']:value+=6 if f in ('WH','DR') else 3
            else:value+=10 if f=='EV' else 4 if raw['value'] is False else 3
        elif native(c,f):value+=1
    # Fixed, tiny tie-breaker; neither a preference score nor a statistical likelihood.
    tie=int(hashlib.sha256(json.dumps([c['case_id'],mask]).encode()).hexdigest()[:8],16)/2**32
    return value+tie*1e-4
