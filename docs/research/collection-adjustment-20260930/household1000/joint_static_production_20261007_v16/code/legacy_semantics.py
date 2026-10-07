"""Input semantics only. No EnergyPlus, model API, scorer, or human labels."""
import copy,hashlib,itertools,json
KINDS={'ac','washer','dishwasher','dryer','water_heater','ev'}
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def combinations():
    return [list(c) for n in [4,5,6] for c in itertools.combinations(sorted(KINDS),n) if 'dryer' not in c or 'washer' in c]
def overlap(a,b):return max(a[0],b[0])<min(a[1],b[1])
def validate(pair):
    errors=[];world=pair['world'];assets={d['asset_id']:d for d in world['devices']};k={k for d in assets.values() for k in d['types']}
    if not k<=KINDS or not 4<=len(k)<=6:errors.append('DEVICE_TYPE_COUNT_OR_DOMAIN')
    if 'dryer' in k and 'washer' not in k:errors.append('DRYER_WASHER_SOURCE')
    if digest(pair['needs_A'])!=digest(pair['needs_B']):errors.append('DEMAND_CHANGED_BETWEEN_ARMS')
    if pair['A']['predecision_state_hash']!=pair['B']['predecision_state_hash']:errors.append('COMMON_STATE_BINDING')
    needs={n['need_id']:n for n in pair['needs_A']}
    decision=pair['decision_abs_min'];plans=pair['A'],pair['B'];beforeA={t['task_id']:t for t in plans[0]['tasks'] if t['start_min']<decision}
    beforeB={t['task_id']:t for t in plans[1]['tasks'] if t['start_min']<decision}
    if beforeA!=beforeB:errors.append('COMMITTED_PREFIX_CHANGED')
    for side,plan in zip(['A','B'],plans):
        tasks={t['task_id']:t for t in plan['tasks']};operations=plan['operations'];served=[t['need_id'] for t in tasks.values()]
        cycle_needs={n['need_id'] for n in needs.values() if n['kind'] in ['washer','dryer','dishwasher']}
        if len(served)!=len(set(served)) or set(served)!=cycle_needs:errors.append(side+':NEED_LOST_OR_DUPLICATED')
        for t in tasks.values():
            need=needs.get(t['need_id']);asset=assets.get(t['asset_id'])
            if not need or not asset or t['kind'] not in asset['types']:errors.append(side+':ASSET_NEED_BINDING');continue
            start,end=t['start_min'],t['end_min']
            if type(start)!=int or type(end)!=int or start%10 or end%10 or end-start!=need['duration_min']:errors.append(side+':INTEGER_CLOCK_DURATION')
            if start<need['release_min'] or end>need['deadline_min']:errors.append(side+':RELEASE_OR_DEADLINE')
            if need.get('loading_required'):
                handling=[o for o in operations if o['kind']=='load' and o['need_id']==need['need_id']]
                if len(handling)!=1 or handling[0]['end_min']>start:errors.append(side+':LOADING_NOT_COMPLETE')
            if t['kind']=='dryer':
                upstream=next((x for x in tasks.values() if x['need_id']==need['upstream_need_id']),None)
                if upstream is None:errors.append(side+':WASH_BATCH_MISSING');continue
                if needs[upstream['need_id']]['batch_id']!=need['batch_id']:errors.append(side+':LAUNDRY_BATCH_CHANGED')
                if t['asset_id']==upstream['asset_id']:
                    if start<upstream['end_min']:errors.append(side+':COMBO_RESOURCE_OVERLAP')
                else:
                    transfer=[o for o in operations if o['kind']=='wash_to_dry_transfer' and o['batch_id']==need['batch_id']]
                    if len(transfer)!=1 or transfer[0]['start_min']<upstream['end_min'] or transfer[0]['end_min']>start or transfer[0]['end_min']-transfer[0]['start_min']<need['transfer_min']:errors.append(side+':WASH_DRY_HANDLING')
        for op in operations:
            windows=world['operator_windows'].get(op['operator_id'],[])
            if not any(a<=op['start_min']<op['end_min']<=b for a,b in windows):errors.append(side+':OPERATOR_UNAVAILABLE')
        for i,a in enumerate(operations):
            for b in operations[i+1:]:
                if a['operator_id']==b['operator_id'] and overlap((a['start_min'],a['end_min']),(b['start_min'],b['end_min'])):errors.append(side+':OPERATOR_DOUBLE_BOOKED')
        for i,a in enumerate(list(tasks.values())):
            for b in list(tasks.values())[i+1:]:
                if a['asset_id']==b['asset_id'] and overlap((a['start_min'],a['end_min']),(b['start_min'],b['end_min'])):errors.append(side+':PHYSICAL_RESOURCE_OVERLAP')
        for c in plan['controls']:
            asset=assets.get(c['asset_id'])
            if not asset:errors.append(side+':CONTROL_ASSET');continue
            if type(c['start_min'])!=int or type(c['end_min'])!=int or c['start_min']%10 or c['end_min']%10 or c['end_min']<=c['start_min']:errors.append(side+':CONTROL_CLOCK')
            if c['kind']=='tank_setpoint' and c['value_C']>asset['tank_max_C']:errors.append(side+':TANK_MAXIMUM')
            if c['kind']=='ac_setpoint' and c['value_C']>asset['reference_upper_setpoint_C']:errors.append(side+':AC_REFERENCE_LIMIT')
            if c['kind']=='ev_charge_window':
                mobility=next((n for n in needs.values() if n['kind']=='ev' and n['connection_start_min']<=c['start_min']<n['departure_min']),None)
                if mobility is None:errors.append(side+':EV_CONNECTION');continue
                if not mobility['connection_start_min']<=c['start_min']<c['end_min']<=mobility['departure_min']:errors.append(side+':EV_CONNECTION')
        # Conservative rated-power envelope on declared circuits; thermal actual
        # consumption, duty cycles, and tank/comfort outcomes remain untested.
        for time_min in range(0,pair['horizon_min'],10):
            active={t['asset_id'] for t in tasks.values() if t['start_min']<=time_min<t['end_min']}
            active.update(c['asset_id'] for c in plan['controls'] if c['start_min']<=time_min<c['end_min'])
            circuit_kw={name:0. for name in world['circuit_limit_kw']}
            for aid in active:
                a=assets[aid];circuit_kw[a['circuit']]+=a['max_electric_kw']
            if any(p>world['circuit_limit_kw'][c]+1e-9 for c,p in circuit_kw.items()):errors.append(side+':DECLARED_CIRCUIT_CAPACITY');break
    for c in pair['B']['changed_controls']:
        if c['start_min']<decision:errors.append('B:RETROACTIVE_CHANGE')
    return sorted(set(errors))

def fixture(count=4):
    device_kinds=['ac','washer','dryer','water_heater']+(['dishwasher'] if count>=5 else [])+(['ev'] if count==6 else [])
    ratings={'ac':2.,'washer':1.5,'dryer':2.5,'water_heater':3.,'dishwasher':1.2,'ev':7.4}
    devices=[{'asset_id':k,'types':[k],'circuit':'EV' if k=='ev' else 'home','max_electric_kw':ratings[k],
              'tank_max_C':65.,'reference_upper_setpoint_C':27.} for k in device_kinds]
    needs=[{'need_id':'laundry_wash','kind':'washer','batch_id':'L1','release_min':0,'deadline_min':1440,'duration_min':120,'loading_required':True,'quantity':3,'unit':'kg'},
           {'need_id':'laundry_dry','kind':'dryer','batch_id':'L1','upstream_need_id':'laundry_wash','release_min':0,'deadline_min':1440,'duration_min':90,'transfer_min':10,'quantity':3,'unit':'kg'},
           {'need_id':'bath','kind':'water_heater','release_min':1260,'deadline_min':1270,'quantity':30.,'unit':'L mixed water','target_C':40.5555555555556}]
    A={'predecision_state_hash':'0'*64,'tasks':[{'task_id':'wash','need_id':'laundry_wash','asset_id':'washer','kind':'washer','start_min':1110,'end_min':1230},
         {'task_id':'dry','need_id':'laundry_dry','asset_id':'dryer','kind':'dryer','start_min':1240,'end_min':1330}],
       'operations':[{'kind':'load','need_id':'laundry_wash','operator_id':'op1','start_min':420,'end_min':430},
          {'kind':'wash_to_dry_transfer','batch_id':'L1','operator_id':'op1','start_min':1230,'end_min':1240},
          {'kind':'bathing','operator_id':'op1','start_min':1260,'end_min':1270}],
       'controls':[{'asset_id':'ac','kind':'ac_setpoint','start_min':1080,'end_min':1350,'value_C':26.},
          {'asset_id':'water_heater','kind':'tank_setpoint','start_min':1020,'end_min':1260,'value_C':60.}],'changed_controls':[]}
    B=copy.deepcopy(A)
    for t in B['tasks']:t['start_min']+=60;t['end_min']+=60
    B['operations'][1]['start_min']+=60;B['operations'][1]['end_min']+=60
    B['controls'][1]['start_min']-=60;B['controls'][1]['end_min']-=60
    B['changed_controls']=[copy.deepcopy(B['controls'][1])]
    if count>=5:
        needs.append({'need_id':'dishes','kind':'dishwasher','release_min':1170,'deadline_min':1410,'duration_min':90,'loading_required':True,'quantity':1,'unit':'program'})
        for side,plan in [('A',A),('B',B)]:
            start=1200 if side=='A' else 1230
            plan['tasks'].append({'task_id':'dishes','need_id':'dishes','asset_id':'dishwasher','kind':'dishwasher','start_min':start,'end_min':start+90})
            plan['operations'].append({'kind':'load','need_id':'dishes','operator_id':'op1','start_min':1170,'end_min':1180})
    if count==6:
        needs.append({'need_id':'next_morning_trip','kind':'ev','connection_start_min':1110,'departure_min':1890,'required_departure_soc':.85,'quantity':1,'unit':'trip'})
        for side,plan in [('A',A),('B',B)]:
            plan['controls'].append({'asset_id':'ev','kind':'ev_charge_window','start_min':1110 if side=='A' else 1140,'end_min':1890})
        B['changed_controls'].append(copy.deepcopy(B['controls'][-1]))
    return {'fixture_only':True,'decision_abs_min':960,'horizon_min':2880,'world':{'devices':devices,'operator_windows':{'op1':[[390,480],[1080,1350]]},
        'circuit_limit_kw':{'home':13.,'EV':7.4},'circuit_values_are_explicit_fixture_design':True},'needs_A':needs,'needs_B':copy.deepcopy(needs),'A':A,'B':B}

def probes():
    result=[]
    for n in [4,5,6]:
        p=fixture(n);e=validate(p);result.append({'name':'valid_'+str(n)+'_type_fixture','errors':e});assert not e,e
    mutations=[('demand_removed',lambda p:p['needs_B'].pop(), 'DEMAND_CHANGED_BETWEEN_ARMS'),
               ('transfer_removed',lambda p:p['B']['operations'].pop(1),'B:WASH_DRY_HANDLING'),
               ('operator_missing',lambda p:p['world']['operator_windows'].clear(),'B:OPERATOR_UNAVAILABLE'),
               ('tank_over_limit',lambda p:p['B']['controls'][1].update(value_C=80),'B:TANK_MAXIMUM'),
               ('retroactive_heating',lambda p:p['B']['changed_controls'][0].update(start_min=900),'B:RETROACTIVE_CHANGE'),
               ('circuits_unavailable',lambda p:p['world']['circuit_limit_kw'].update(home=1),'B:DECLARED_CIRCUIT_CAPACITY'),
               ('EV_after_departure',lambda p:p['B']['controls'][-1].update(end_min=2000),'B:EV_CONNECTION')]
    for name,mutate,expected in mutations:
        p=fixture(6);mutate(p);e=validate(p);assert expected in e,(name,e);result.append({'name':name,'expected_rejection':expected,'errors':e})
    return result
