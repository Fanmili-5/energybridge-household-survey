"""Review actual active branches of a frozen public reference, without filling fields.

This reviews model definitions and output scope, not empirical household truth.
Inactive fourth-speed/secondary-coil fields do not require product data. Active
defaults retain the declared complete source method, never regional estimates.
Unknown branches stay unreviewed. Physical validation remains a separate gate.
"""
import math
import re

from .common import require
from .idf import objects


def classify(item, row, rows, fields, source_rows):
    kind,name,key=item['object']['kind'],item['object']['name'],item['field']
    default=item['declared_schema_default']
    source={(r[0],r[1]):r for r in source_rows if len(r)>1}
    inherited=source.get((kind,name))
    same_source_field=inherited is not None and not fields.get(inherited,key)
    def result(disposition,reason,condition):
        require(condition,'REFERENCE_DEFAULT_BRANCH_PRECONDITION',[kind,name,key])
        return {'disposition':disposition,'reason':reason,'branch_precondition_verified':True}
    if kind.startswith('Output:') or kind=='LifeCycleCost:Parameters':
        return result('reporting_policy','Tabular output or life-cycle-cost reporting;not thermal/energy input',True)
    if kind.startswith('Curve:') and ('unit_type' in key):
        return result('unit_metadata','Source numerical coefficients and input coordinates retained;unit label supplies no fitted coefficient',same_source_field)
    if kind=='ScheduleTypeLimits' and key=='unit_type':
        return result('unit_metadata','Unchanged source schedule label;does not rescale schedule numbers',same_source_field or name.startswith('EB_LIFE_'))
    if kind=='Space' and key=='space_type':
        return result('reporting_policy','Source space grouping label;no independent zone load or occupant value supplied',same_source_field)
    if kind=='People' and key in ('cold_stress_temperature_threshold','heat_stress_temperature_threshold'):
        return result('reporting_policy','Optional stress-report thresholds;not a comfort/service acceptance threshold in this experiment',
            not any(r[0]=='EnergyManagementSystem:Sensor' and any('stress' in v.casefold() for v in r[2:]) for r in rows))
    if kind=='OtherEquipment' and key=='carbon_dioxide_generation_rate' or kind=='ZoneCapacitanceMultiplier:ResearchSpecial' and key in (
            'carbon_dioxide_capacity_multiplier','generic_contaminant_capacity_multiplier'):
        return result('inactive','CO2/contaminant balance and exposure service are not installed or claimed',not objects(rows,'ZoneAirContaminantBalance'))
    if kind=='Building' and key in ('north_axis','solar_distribution'):
        return result('complete_public_reference_method',
            'Source zero global rotation and FullExterior solar-distribution approximation are retained;not reconstructed local geometry or detailed interior optics',
            same_source_field and default in (0,0.,'FullExterior'))
    if kind=='Building' and key in ('loads_convergence_tolerance_value','temperature_convergence_tolerance_value'):
        return result('frozen_numerical_algorithm','Source official warmup convergence setting retained;14/28day comparison is separate evidence,not a relaxed threshold',same_source_field)
    if kind=='Zone' and key in ('direction_of_relative_north','type'):
        return result('complete_public_reference_method','Unchanged source thermal-zone orientation/type',same_source_field and default in (0,0.,1))
    if kind in ('Zone','Space') and key in ('ceiling_height','floor_area'):
        return result('geometry_derived','Official calculation on the complete source faces;zone air volume remains separately explicit;not a closed-mesh or measured-house claim',same_source_field and default=='Autocalculate')
    if kind in ('BuildingSurface:Detailed','FenestrationSurface:Detailed') and key in ('number_of_vertices','view_factor_to_ground'):
        start=fields.index(kind,'number_of_vertices')+1;coordinates=row[start:]
        return result('geometry_derived','Source polygon count/ground view-factor derived by the frozen engine;actual terrain/obstruction equivalence not inferred',
            default=='Autocalculate' and len(coordinates)>=9 and len(coordinates)%3==0 and all(math.isfinite(float(v)) for v in coordinates))
    if kind=='FenestrationSurface:Detailed' and key=='multiplier':
        return result('complete_public_reference_method','Source one-copy window multiplier;no second frame or dwelling multiplier applied',same_source_field and default==1.)
    if kind=='SurfaceProperty:ExposedFoundationPerimeter' and key=='exposed_perimeter_fraction':
        return result('inactive','Source supplies explicit total exposed perimeter;fraction branch is not selected',
            fields.get(row,'exposed_perimeter_calculation_method')=='TotalExposedPerimeter' and float(fields.get(row,'total_exposed_perimeter'))>0)
    if kind=='Foundation:Kiva':
        if key=='interior_horizontal_insulation_depth':
            return result('inactive','No interior-horizontal insulation material is installed',not fields.get(row,'interior_horizontal_insulation_material_name'))
        if key=='exterior_horizontal_insulation_width':
            return result('inactive','No exterior-horizontal insulation material is installed',not fields.get(row,'exterior_horizontal_insulation_material_name'))
        if key=='footing_depth':
            return result('inactive','No source footing material or footing-wall construction is installed',
                not fields.get(row,'footing_material_name') and not fields.get(row,'footing_wall_construction_name'))
    if kind=='ZoneInfiltration:DesignFlowRate' and key in ('constant_term_coefficient','temperature_term_coefficient',
        'velocity_term_coefficient','velocity_squared_term_coefficient'):
        controlled=[r for r in objects(rows,'EnergyManagementSystem:Actuator') if r[2].casefold()==name.casefold()
                    and r[4]=='Air Exchange Flow Rate']
        return result('complete_public_reference_method','Source zero base Flow/Zone object with published EMS airflow actuation;not a newly estimated regional infiltration coefficient',
            same_source_field and fields.get(row,'design_flow_rate_calculation_method')=='Flow/Zone'
            and float(fields.get(row,'design_flow_rate'))==0 and bool(controlled))
    if kind=='ZoneMixing' and key=='delta_temperature':
        return result('complete_public_reference_method','Source mixing reference has no additional temperature-difference gate;source flow calculation retained',same_source_field and default==0.)
    if kind=='Lights' and key.startswith('return_air_'):
        return result('inactive','Source return-air fraction is zero and no plenum-temperature rule is selected',
            float(fields.get(row,'return_air_fraction'))==0 and not fields.get(row,'return_air_fraction_calculated_from_plenum_temperature'))
    if kind=='AirTerminal:SingleDuct:ConstantVolume:NoReheat' and key=='per_person_ventilation_rate_mode':
        return result('inactive','No DesignSpecification:OutdoorAir is attached;this flag does not supply a per-person ventilation rate',
            not fields.get(row,'design_specification_outdoor_air_object_name'))
    if kind=='ZoneHVAC:AirDistributionUnit' and key in ('nominal_upstream_leakage_fraction','constant_downstream_leakage_fraction'):
        return result('complete_public_reference_method','Published ductless terminal has zero modeled duct leakage;not measured infiltration evidence',same_source_field and default==0.)
    if kind=='SimulationControl' and key in ('do_hvac_sizing_simulation_for_sizing_periods','maximum_number_of_hvac_sizing_simulation_passes'):
        return result('inactive','Native zone/system/plant autosizing and sizing-period simulations are disabled for this frozen CASE',
            all(fields.get(row,k)=='No' for k in ('do_zone_sizing_calculation','do_system_sizing_calculation','do_plant_sizing_calculation','run_simulation_for_sizing_periods')))
    if kind=='RunPeriod' and key in ('treat_weather_as_actual','first_hour_interpolation_starting_values'):
        return result('frozen_numerical_algorithm','TMY reference and original Hour24 first-hour interpolation policy retained;not actual-year chronology or a reset correction',same_source_field)
    if kind=='ZoneAirHeatBalanceAlgorithm' and key in ('do_space_heat_balance_for_sizing','do_space_heat_balance_for_simulation'):
        return result('frozen_numerical_algorithm','Official zone-level air balance retained;space-level heat balance is disabled,not new room-level capability',
            default=='No' and not fields.get(row,key))
    if kind=='OutdoorAir:Node' and key in ('height_above_ground','symmetric_wind_pressure_coefficient_curve','wind_angle_type'):
        return result('complete_public_reference_method','Source external node uses the weather/reference-height convention;no household facade pressure or installation-height claim',same_source_field)
    if kind=='AirLoopHVAC:UnitarySystem' and key in ('design_heat_recovery_water_flow_rate','maximum_temperature_for_heat_recovery'):
        return result('inactive','No heat-recovery water inlet or outlet is connected',
            not fields.get(row,'heat_recovery_water_inlet_node_name') and not fields.get(row,'heat_recovery_water_outlet_node_name'))
    if kind in ('Coil:Heating:DX:MultiSpeed','Coil:Cooling:DX:MultiSpeed'):
        if 'speed_4_' in key:
            return result('inactive','Only three speeds are installed;fourth-speed default is not a missing performance point',int(fields.get(row,'number_of_speeds'))==3)
        if 'secondary_coil_fan_flow_scaling_factor' in key:
            return result('inactive','No secondary evaporator-placement zone is installed',not fields.get(row,'zone_name_for_evaporator_placement'))
    if kind=='PlantLoop' and key=='pressure_simulation_type':
        return result('public_network_simplification','Complete source water loop omits pressure hydraulics;pressure/pipe-capacity service is unsupported',same_source_field and default=='None')
    if kind=='PlantLoop' and key=='loop_circulation_time':
        value=fields.get(row,'plant_loop_volume')
        return result('inactive','Loop volume is explicitly0.003m3 in the source;circulation time is only an autocalculation input',same_source_field and value and value.casefold()!='autocalculate' and float(value)>0)
    if kind=='WaterHeater:Stratified':
        if key=='additional_destratification_conductivity' or re.fullmatch(r'node_\d+_additional_loss_coefficient',key):
            return result('complete_original_EB_model','Unchanged complete original EB tank schema defaults;no added loss,layer or heater calibration',same_source_field and default==0.)
        if key=='source_side_flow_control_mode':
            return result('inactive','No source-side inlet/outlet nodes are connected to the original EB electric tank',
                not fields.get(row,'source_side_inlet_node_name') and not fields.get(row,'source_side_outlet_node_name'))
    return None


def review(rows, inventory, fields, source_rows):
    actual={(r[0],r[1]):r for r in rows if len(r)>1};reviewed=[];unreviewed=[]
    for item in inventory['fields']:
        if item['status']!='omitted_with_schema_default':continue
        row=actual[item['object']['kind'],item['object']['name']]
        classification=classify(item,row,rows,fields,source_rows)
        record={'object':item['object'],'field':item['field'],'effective_default':item['declared_schema_default']}
        (reviewed if classification else unreviewed).append({**record,**(classification or {})})
    return {'schema':'national_idf.reference_default_branch_review.v1','reviewed':reviewed,'unreviewed':unreviewed,
        'all_schema_default_branches_accounted':not unreviewed,
        'physical_fields_filled_or_overridden':False,'empirical_household_or_regional_values_validated':False,
        'joint_physical_admission_complete':False}
