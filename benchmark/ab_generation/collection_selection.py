"""Selection concepts are separate from descriptive actuator fields.

Weights and bins are explicit experimental settings, not empirical proportions.
No thermal outcome or human preference is inferred here.
"""
from collections import defaultdict
from .common import canonical,digest

POLICY={'schema':'eb.collection.selection_policy.v4','household_device_budget':1.0,
        'household_tradeoff_budget':1.0,'batch_device_detail_budget':1.0,
        'household_semantic_repeat_weight':1.0,'household_family_repeat_weight':0.25,
        'household_composition_repeat_weight':0.5,'batch_joint_order_budget':0.25,
        'slots':10,'weights_are_experimental_settings':True,'category_proportions_prescribed':False}


def slack_level(x):
    return 'not_applicable' if x is None else 'shortfall' if x<0 else 'under_30min' if x<30 else '30_to_120min' if x<=120 else 'over_120min'


def time_level(x):
    return 'none' if not x else 'small' if x<=30 else 'medium' if x<90 else 'large'


def component_view(c):
    f=c['family'];m=c['magnitude'];direction=m.get('direction','none')
    if f in ('washer','dishwasher','dryer'):
        shift=m.get('signed_machine_shift_min',0)
        direction='earlier' if shift<0 else 'later' if shift>0 else 'handling_only'
        mechanism='with_handling' if m.get('manual_total_shift_min',0) else 'timer_only'
        dose=c['absolute_level']
    elif f=='ac':
        ac=m['ac_intervention'];mechanism=c['mechanism']+':'+m['axis']
        dose=ac['amplitude_axes']['cooling_pause'] if ac['cooling_stop_requested_min'] else ac['amplitude_axes']['temperature_offset']
    else:
        mechanism=c['mechanism'];dose=c['absolute_level']
    out={'family':f,'asset_id':c['asset_id'],'mechanism':mechanism+':'+direction,'dose':dose,
         'slack':slack_level(m.get('service_slack_min')),'manual_dose':time_level(m.get('manual_max_shift_min',0))}
    if f=='ac':
        ac=m['ac_intervention']
        out.update(control_state=ac['state_change'],event_duration=ac['amplitude_axes']['event_duration'],
                   preconditioning=ac['amplitude_axes']['preconditioning'])
    if f=='ev':out['energy_shortfall']=m.get('energy_shortfall_kWh',0)>1e-8
    return out


def view(row):
    roots=[];support=[]
    for c in row['components']:
        target=roots if c.get('event_relevance',{}).get('role')=='direct_event_request' else support
        target.append(component_view(c))
    roots.sort(key=canonical);support.sort(key=canonical);families=sorted({x['family'] for x in roots})
    if not roots:return {'families':[],'global':{},'detail':{},'signature':digest({'scarcity_control':True}),
                         'composition_signature':digest({'scarcity_control':True})}
    known=row['known_event_reduction_kWh'];constraints=set()
    for issue in row['issues']:
        if issue.startswith(('OPERATOR_','ROOM_')):constraints.add('person_or_room_conflict')
        elif any(s in issue for s in ('POWER','CAPACITY','ENVELOPE')):constraints.add('declared_capacity_stress')
        else:constraints.add('service_or_window_stress')
    # Two thermostat axes on one AC are one physical request service, whereas
    # two program batches on one machine remain distinct demand instances.
    services={(c['asset_id'],c.get('service_need_id')) if c['family'] in ('washer','dryer','dishwasher','ev')
              else (c['asset_id'],None) for c in row['components']
              if c.get('event_relevance',{}).get('role')=='direct_event_request'}
    axes={'manual':[row['features']['manual']],
          'known_plan_event':['reduction' if known>1e-9 else 'increase' if known<-1e-9 else 'zero'],
          'root_services':['single' if len(services)==1 else 'two' if len(services)==2 else 'three_or_more'],
          'coordination':['support_required' if support else 'direct_only'],
          'constraint':sorted(constraints or {'none_registered'})}
    detail={}
    for f in families:
        children=[x for x in roots if x['family']==f]
        detail[f]={k:sorted({x[k] for x in children if x[k]!='not_applicable'}) for k in ('mechanism','dose','slack')}
        detail[f]={k:v for k,v in detail[f].items() if v}
    # A weekday or date is not a new tradeoff. Preserve actual constraint and
    # service boundaries, including EV shortfall, rather than a raw timestamp.
    signature=digest({'roots':roots,'support':support,'global':axes,'issues':sorted(set(row['issues']))})
    from collections import Counter
    composition=Counter()
    seen=set()
    for c in row['components']:
        if c.get('event_relevance',{}).get('role')!='direct_event_request':continue
        key=(c['asset_id'],c.get('service_need_id')) if c['family'] in ('washer','dryer','dishwasher','ev') else (c['asset_id'],None)
        if key not in seen:composition[c['family']]+=1;seen.add(key)
    return {'families':families,'global':axes,'detail':detail,'signature':signature,
            'composition_signature':digest(sorted(composition.items()))}


def tokens(v):
    out={'root='+f for f in v['families']}
    out.update('tradeoff.'+k+'='+s for k,vs in v['global'].items() for s in vs)
    out.update('detail.'+f+'.'+k+'='+s for f,axes in v['detail'].items() for k,vs in axes.items() for s in vs)
    return out


def targets(rows,households):
    concepts={r['id']:tokens(view(r)) for r in rows};out=[]
    def add(scope,tag,weight,budget):
        pool=[r for r in rows if scope is None or r['household_id']==scope]
        out.append({'id':(scope or 'batch')+'::'+tag,'household':scope,'tag':tag,'weight':weight,'budget':budget,
                    'available_household_days':len({(r['household_id'],r['date']) for r in pool if tag in concepts[r['id']]})})
    for h in households:
        ts={t for r in rows if r['household_id']==h for t in concepts[r['id']]}
        roots=sorted(t for t in ts if t.startswith('root='))
        for t in roots or ['root=any_changed_request']:
            add(h,t,POLICY['household_device_budget']/max(1,len(roots)),'household_devices')
        axes=defaultdict(list)
        for t in sorted(ts):
            if t.startswith('tradeoff.') and not t.startswith('tradeoff.root_services='):
                axes[t.split('=')[0]].append(t)
        for values in axes.values():
            for t in values:add(h,t,POLICY['household_tradeoff_budget']/len(axes)/len(values),'household_tradeoffs')
    detail=defaultdict(lambda:defaultdict(list))
    for t in sorted({t for v in concepts.values() for t in v if t.startswith('detail.')}):
        family,axis=t.removeprefix('detail.').split('=',1)[0].split('.',1);detail[family][axis].append(t)
    for family,axes in sorted(detail.items()):
        for values in axes.values():
            for t in values:add(None,t,POLICY['batch_device_detail_budget']/len(detail)/len(axes)/len(values),'batch_device_details')
    # Joint-order witnesses belong to the whole batch, never one mandatory
    # single/two/high-order example per household. Repeats are soft costs.
    orders=sorted({t for v in concepts.values() for t in v if t.startswith('tradeoff.root_services=')})
    for t in orders:add(None,t,POLICY['batch_joint_order_budget']/len(orders),'batch_joint_order')
    return out
