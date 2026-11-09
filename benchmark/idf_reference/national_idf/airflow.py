"""Alternative pressure structure on original surfaces; not measured airtightness."""
from __future__ import annotations
from .idf import objects
from .prototypes import vertices,area
from .common import require


def pressure_network(rows,fields,reference_ach):
    require(not objects(rows,'Fan:ZoneExhaust'),'AFN_EXHAUST_LINK_NOT_IMPLEMENTED')
    rows=[r for r in rows if r[0]not in ['ZoneInfiltration:DesignFlowRate','ZoneMixing','ZoneCrossMixing']]
    zones={r[1]:r for r in objects(rows,'Zone')}
    surfaces={r[1]:r for r in objects(rows,'BuildingSurface:Detailed')}
    external=[r for r in surfaces.values()if r[6].lower()=='outdoors']
    require(bool(external),'AFN_EXTERIOR_REQUIRED')
    total_area=sum(area(vertices(r))for r in external)
    total_volume=sum(float(z[9])for z in zones.values())
    total_coefficient=reference_ach*total_volume/3600*1.2/(4**.65)
    rows +=[fields.obj('AirflowNetwork:SimulationControl',name='source_surface_pressure_reference',
      airflownetwork_control='MultizoneWithoutDistribution',wind_pressure_coefficient_type='SurfaceAverageCalculation',
      height_selection_for_local_wind_pressure_calculation='OpeningHeight',building_type='HighRise',
      maximum_number_of_iterations=1000,relative_airflow_convergence_tolerance=1e-5,
      absolute_airflow_convergence_tolerance=1e-6,
      azimuth_angle_of_long_axis_of_building=0,
      ratio_of_building_width_along_short_axis_to_width_along_long_axis=.5)]
    for z in zones:rows +=[fields.obj('AirflowNetwork:MultiZone:Zone',zone_name=z,ventilation_control_mode='NoVent')]
    links=[];visited=set()
    for name,s in surfaces.items():
        if s[6].lower()=='outdoors':
            coefficient=total_coefficient*area(vertices(s))/total_area
        elif s[6].lower()=='surface':
            peer=surfaces.get(s[7]);require(peer is not None,'AFN_MISSING_PEER')
            if peer[4]==s[4]or s[7]in visited:continue
            # An explicit wall-leakage reference; source has no measured door-opening process.
            coefficient=.0001*area(vertices(s))
        else:continue
        visited.add(name);component='crack_'+str(len(links))
        rows +=[fields.obj('AirflowNetwork:MultiZone:Surface:Crack',name=component,
          air_mass_flow_coefficient_at_reference_conditions=coefficient,air_mass_flow_exponent=.65),
          fields.obj('AirflowNetwork:MultiZone:Surface',surface_name=name,leakage_component_name=component,
                     window_door_opening_factor_or_crack_factor=1)]
        links.append({'surface':name,'zone':s[4],'coefficient_kg_s_Pa_n':coefficient,
          'peer_zone':surfaces[s[7]][4]if s[6].lower()=='surface'else None})
    return rows,{'model':'native_AirflowNetwork','links':links,'reference_ACH_at_4Pa':reference_ach,
      'actual_ACH_is_solved_not_fixed':True,'highrise_WPC_geometry_and_height_are_reference':True,
      'interzone_crack_coefficient_is_design':True,'observed_door_behavior':False}
