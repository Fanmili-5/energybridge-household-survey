"""Requested grades and observed command magnitudes, with no cross-device score."""
from common import *
from strengths import controller_key, grade_table, selected_levels
from classify import control_differences
from actual_strength import annotate
from planning import contexts


def describe(w, source, plan, defs, vector=0):
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']}
    ctxs=contexts(w,source,defs);levels=selected_levels(defs,vector);diff=control_differences(source['A'],plan)
    programs_a={x['task_id']:x for x in source['A']['tasks']};ops_a={x['operation_id']:x for x in source['A']['operations']}
    requests=[];actual=[];changes=[]
    for key,d in sorted(defs.items()):
        aid=d['asset_ids'][0];family=d['family'];level=levels[key]
        request={'controller_key':key,'device_family':family,'asset_ids':d['asset_ids'],
                 'grade':LEVELS[level],'parameters':grade_table(family,level,assets[aid]),
                 'grade_is_device_specific_not_household_utility':True}
        request['input_state_plan']=ctxs[key]
        request['thermal_phases']=[x for x in plan.get('thermal_phase_requests',[])if x['controller_key']==key]
        requests.append(request)
        pp=[];oo=[]
        for x in plan['tasks']:
            if x['asset_id']not in d['asset_ids']:continue
            a=programs_a[x['task_id']]
            if (x['start_min'],x['end_min'])!=(a['start_min'],a['end_min']):
                pp.append({'task_id':x['task_id'],'kind':x['kind'],'A_start_min':a['start_min'],
                           'B_start_min':x['start_min'],'start_shift_minutes':x['start_min']-a['start_min'],
                           'A_end_min':a['end_min'],'B_end_min':x['end_min'],'request_formation':x.get('request_formation')})
        for x in plan['operations']:
            if x['asset_id']not in d['asset_ids']:continue
            a=ops_a[x['operation_id']]
            if (x['start_min'],x['end_min'])!=(a['start_min'],a['end_min']):
                oo.append({'operation_id':x['operation_id'],'kind':x['kind'],
                           'A_start_min':a['start_min'],'B_start_min':x['start_min'],
                           'start_shift_minutes':x['start_min']-a['start_min']})
        cc=[x for x in diff if x['asset_id']in d['asset_ids']]
        ev=[]
        if family=='ev':
            for a in source['A']['controls']:
                if a['kind']!='ev_charge_window'or a['asset_id']not in d['asset_ids']:continue
                xs=[x for x in plan['controls']if x['kind']=='ev_charge_window'and x['asset_id']==a['asset_id']and x['need_id']==a['need_id']]
                b=next((x for x in xs if x['end_min']==a['end_min']),xs[0]if len(xs)==1 else None)
                if b is None:continue
                if (a['start_min'],a['end_min'],a['stop_at_target_soc'])==(b['start_min'],b['end_min'],b['stop_at_target_soc']):continue
                p=assets[a['asset_id']]['parameters'];full=a['battery_energy_kWh']/(p['charger_kw']*p['efficiency'])*60
                ev.append({'need_id':a['need_id'],'A_window_min':[a['start_min'],a['end_min']],
                    'B_window_min':[b['start_min'],b['end_min']],
                    'delay_minutes':b['start_min']-a['start_min'],'window_cut_minutes':a['end_min']-b['end_min'],
                    'constant_power_full_charge_minutes':full,'formation_path':b.get('formation_path'),
                    'A_window_slack_minutes':a['end_min']-a['start_min']-full,
                    'B_window_slack_minutes':b['end_min']-b['start_min']-full,
                    'required_target_soc_unchanged':a['stop_at_target_soc']==b['stop_at_target_soc'],
                    'scope':'given_connection_and_constant_charger_upper_bound;not_observed_SOC_or_trip_success'})
        observed={'controller_key':key,'device_family':family,'asset_ids':d['asset_ids'],
                  'program_changes':pp,'manual_operation_changes':oo,'control_segments':cc,'EV_window_metrics':ev,
                  'requested_grade':LEVELS[level],
                  'actual_grade_not_inferred_from_physical_or_human_outcomes':True}
        annotate(observed,request)
        actual.append(observed)
        has=bool(pp or oo or cc)
        description=(f'{family}输入剂量{LEVELS[level]}；实际强度各轴'+str([(x['label'],x['value'],x['grade'])for x in observed['strength_presentation']['axes']])+'；' +
            (f'程序移时{[x["start_shift_minutes"]for x in pp]}分钟；装取操作移时{[x["start_shift_minutes"]for x in oo]}分钟'if family in('washer','dishwasher')else
             f'充电窗口变化{[(x["A_window_min"],x["B_window_min"])for x in ev]}；目标SOC及插拔保持'if family=='ev'else
             f'实际许可/温控修改为{[(x["start_min"],x["end_min"],x["A"],x["B"])for x in cc]}')+
            '；实际负荷、服务后果与用户接受待验证')
        actualbasis=sorted({x['request_formation']['request_basis']for x in pp if x.get('request_formation')})
        change={'actual_input_request_basis':actualbasis,'device_family':family,'asset_id':aid,'affected_asset_ids':d['asset_ids'],
                'selected_event_id':ctxs[key]['event']['event_id'],
                'behavior':ctxs[key]['behavior'],
                'device_strength_request':request,'actual_command_metrics':observed,
                'actual_command_changed':has,'description':description}
        changes.append(change)
    return requests,actual,changes
