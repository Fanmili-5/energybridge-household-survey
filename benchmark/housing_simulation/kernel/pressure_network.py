"""Native EnergyPlus pressure/airflow alternative; no parallel prescribed mixing.

Leakage is a declared4Pa reference scenario, not a Chinese airtightness fit.
Existing exhaust fans and physical openings are kept; exterior wall strips host
fan linkages without adding area or altering window hosts.
"""
import copy
import math
from .core import *
from ..policy import reference


def add_pressure_network(rows,pack,days,date,reference_environment,obj,schedule):
    policy=reference('pressure_network');rooms={r['room_id']:r for r in pack['world']['layout']['rooms']}
    # AFN replaces all prescribed exchange; never silently leave ignored loads.
    rows[:]=[r for r in rows if r[0]not in ('ZoneInfiltration:DesignFlowRate','ZoneMixing','ZoneCrossMixing','ZoneAirMassFlowConservation')]
    registrations={r[1]for r in rows if r[0]=='Fan:ZoneExhaust'and r[1].startswith('mass_ledger_registration_')}
    empty_lists={r[1]for r in rows if r[0]=='ZoneHVAC:EquipmentList'and len(r)>3 and r[4]in registrations}
    rows[:]=[r for r in rows if not(r[0]=='Fan:ZoneExhaust'and r[1]in registrations)
             and not(r[0]=='ZoneHVAC:EquipmentList'and r[1]in empty_lists)
             and not(r[0]=='ZoneHVAC:EquipmentConnections'and r[2]in empty_lists)]
    rows.append(obj('AirflowNetwork:SimulationControl',{'name':'reference_pressure_network',
        'airflownetwork_control':'MultizoneWithoutDistribution','wind_pressure_coefficient_type':'SurfaceAverageCalculation',
        'height_selection_for_local_wind_pressure_calculation':'OpeningHeight','building_type':'LowRise',
        'maximum_number_of_iterations':1000,'initialization_type':'LinearInitializationMethod',
        'relative_airflow_convergence_tolerance':1e-6,'absolute_airflow_convergence_tolerance':1e-8,
        'azimuth_angle_of_long_axis_of_building':0,'ratio_of_building_width_along_short_axis_to_width_along_long_axis':1,
        'allow_unsupported_zone_equipment':'Yes'}))
    for rid in sorted(rooms):rows.append(obj('AirflowNetwork:MultiZone:Zone',{'zone_name':rid,'ventilation_control_mode':'NoVent'}))
    # EP24.1 exhaust validation walks every exhaust node with a sticky found
    # flag (Solver::validate_exhaust_fan_input). List real exhaust fan inlets
    # before self-balanced local PTHP recirculation inlets. Keep native PTHP
    # topology; never convert its required exhaust-node interface into a return.
    for nodes in [r for r in rows if r[0]=='NodeList'and r[1].startswith('exhaust_nodes_')]:
        nodes[2:]=sorted(nodes[2:],key=lambda n:(n.startswith('hp_'),n))
    surfaces={r[1]:r for r in rows if r[0]=='BuildingSurface:Detailed'}
    outdoor={rid:sorted((r for r in surfaces.values()if r[4]==rid and r[2]=='Wall'and r[6]=='Outdoors'),key=lambda r:r[1])for rid in rooms}
    def vertices(row):return [list(map(float,row[i:i+3]))for i in range(12,24,3)]
    def area(row):
        v=vertices(row);a=[v[1][i]-v[0][i]for i in range(3)];b=[v[2][i]-v[1][i]for i in range(3)]
        return sum((a[i]*b[(i+1)%3]-a[(i+1)%3]*b[i])**2 for i in range(3))**.5
    links=[];fan_hosts={}
    for rid in sorted(rooms):
        vents=[v for v in reference_environment['spot_exhaust']if v['room']==rid]
        if not vents:continue
        if not outdoor[rid]:raise ValueError('AFN_EXHAUST_ROOM_HAS_NO_EXTERIOR_WALL:'+rid)
        host=max(outdoor[rid],key=area);original=vertices(host);bottom=min(v[2]for v in original);top=max(v[2]for v in original)
        strip_height=policy['exhaust_strip_height_m']
        if top-bottom<2*strip_height:raise ValueError('AFN_EXHAUST_HOST_TOO_SHORT')
        # Split vertically, retaining original name for the upper window host.
        for i in range(12,24,3):
            if float(host[i+2])==bottom:host[i+2]=bottom+strip_height
        left=original[0][:2];right=original[1][:2]
        for index,vent in enumerate(vents):
            a=[left[k]+(right[k]-left[k])*index/len(vents)for k in range(2)]
            b=[left[k]+(right[k]-left[k])*(index+1)/len(vents)for k in range(2)]
            v=[[a[0],a[1],bottom+strip_height],[b[0],b[1],bottom+strip_height],[b[0],b[1],bottom],[a[0],a[1],bottom]]
            strip=copy.deepcopy(host);strip[1]=host[1]+'_fan_'+str(index);strip[12:24]=[c for xyz in v for c in xyz];rows.append(strip)
            fan_hosts[strip[1]]=vent['name'];surfaces[strip[1]]=strip
            rows.append(obj('AirflowNetwork:MultiZone:Component:ZoneExhaustFan',{'name':vent['name'],
                'air_mass_flow_coefficient_when_the_zone_exhaust_fan_is_off_at_reference_conditions':policy['fan_off_coefficient_kg_s_Pan'],
                'air_mass_flow_exponent_when_the_zone_exhaust_fan_is_off':policy['flow_exponent']}))
    ach=float(os.environ['EB_REFERENCE_ACH']);exponent=policy['flow_exponent']
    for rid in sorted(rooms):
        external=[r for r in surfaces.values()if r[4]==rid and r[2]=='Wall'and r[6]=='Outdoors'and r[1]not in fan_hosts]
        total=sum(area(r)for r in external)
        if not external:continue
        zone=next(r for r in rows if r[0]=='Zone'and r[1]==rid);volume=float(zone[9])
        # Equivalent flow at4Pa, not an asserted ambient ACH or measured test.
        mass_coefficient=ach*volume/3600*policy['reference_density_kg_m3']/policy['reference_pressure_Pa']**exponent
        for wall in external:
            name='afn_crack_'+digest(wall[1])[:12]
            rows.append(obj('AirflowNetwork:MultiZone:Surface:Crack',{'name':name,
                'air_mass_flow_coefficient_at_reference_conditions':mass_coefficient*area(wall)/total,'air_mass_flow_exponent':exponent}))
            rows.append(obj('AirflowNetwork:MultiZone:Surface',{'surface_name':wall[1],'leakage_component_name':name,'window_door_opening_factor_or_crack_factor':1}))
            links.append({'surface':wall[1].upper(),'from':rid,'to':None,'kind':'envelope_crack'})
    for surface,name in fan_hosts.items():
        rid=surfaces[surface][4]
        rows.append(obj('AirflowNetwork:MultiZone:Surface',{'surface_name':surface,'leakage_component_name':name,'window_door_opening_factor_or_crack_factor':1}))
        links.append({'surface':surface.upper(),'from':rid,'to':None,'kind':'exhaust_fan','fan':name})
    fen={r[1]:r for r in rows if r[0]=='FenestrationSurface:Detailed'}
    for portal in pack['world']['layout']['access']:
        source=portal['from'];target=portal['to'];surface=fen['door_'+source]
        name='afn_door_'+digest([source,target])[:12]
        rows.append(obj('AirflowNetwork:MultiZone:Component:SimpleOpening',{'name':name,
            'air_mass_flow_coefficient_when_opening_is_closed':policy['door_closed_coefficient_kg_s_m_Pan'],
            'air_mass_flow_exponent_when_opening_is_closed':exponent,
            'minimum_density_difference_for_two_way_flow':.0001,'discharge_coefficient':policy['door_discharge_coefficient']}))
        # Reuse the already-derived frozen A door state, not the prescribed flow.
        prior=next(r for r in rows if r[0]=='Schedule:Compact'and r[1]=='portal_'+digest([source,target])[:12])
        current=copy.deepcopy(prior);current[1]=name+'_open'
        for i,value in enumerate(current[3:],3):
            if isinstance(value,(int,float)):current[i]=int(value==1)
        rows.append(current)
        rows.append(obj('AirflowNetwork:MultiZone:Surface',{'surface_name':surface[1],'leakage_component_name':name,
            'window_door_opening_factor_or_crack_factor':1,'ventilation_control_mode':'Constant','venting_availability_schedule_name':name+'_open'}))
        links.append({'surface':surface[1].upper(),'from':source,'to':target,'kind':'internal_opening'})
    for variable in ('AFN Node Total Pressure','AFN Linkage Node 1 to Node 2 Mass Flow Rate','AFN Linkage Node 2 to Node 1 Mass Flow Rate'):
        rows.append(['Output:Variable','*',variable,'Timestep','report_target_and_recovery'])
    return {'model':'native_EnergyPlus_AirflowNetwork','reference_environment_sha256':reference_environment['policy_sha256'],
        'links':links,'declared_parameters':policy,'equivalent_reference_ACH_at_4Pa':ach,
        'spot_exhaust':reference_environment['spot_exhaust'],'all_zones_registered_for_mass_balance':True,
        'prescribed_exchange_objects_present':False,'pressure_drivers':'native wind and buoyancy;declared reference leakage',
        'fan_host_wall_area_preserved':True,'door_schedules_from_frozen_A_calendars':True,
        'measured_Chinese_airtightness_claimed':False,'distribution_duct_network_modeled':False}
