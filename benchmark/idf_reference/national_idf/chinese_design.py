"""Independent design-day instruments on a complete Chinese source fixture.

No selected capacity, new soil value, household or new performance curve is
created. Public table limits, compressor lockout and empirical evidence are
different layers. A successful design simulation cannot approve any of them.
"""
import copy
from decimal import Decimal, ROUND_HALF_UP
import re
import xml.etree.ElementTree as ET

from .common import ROOT,digest,read,require,sha
from .idf import Fields,objects,parse
from .source_adapter import housing_fingerprint,source_file


def design_pair(ddy_ref,weather_ref,fields,*,root=ROOT):
    ddy=source_file(ddy_ref,root);weather=source_file(weather_ref,root)
    text=ddy.read_text()
    with weather.open() as stream:header=stream.readline().strip().split(',')
    require(header[0]=='LOCATION' and re.search(r'\bWMO='+re.escape(header[5])+r'\b',text),'DESIGN_WMO_CONFLICT')
    rows=parse(text);locations=objects(rows,'Site:Location');require(len(locations)==1,'DESIGN_LOCATION_CARDINALITY')
    loc=locations[0]
    # DDY prints fewer geographic decimal places than EPW; verify at that
    # published precision, rather than granting an arbitrary distance buffer.
    for d,e in zip(loc[2:6],header[6:10]):
        precision=Decimal(d).as_tuple().exponent
        require(Decimal(e).quantize(Decimal(1).scaleb(precision),rounding=ROUND_HALF_UP)==Decimal(d),
                'DESIGN_LOCATION_NUMERIC_CONFLICT',[d,e])
    rules={'heating_99_6':'Ann Htg 99.6% Condns DB',
           'cooling_DB_0_4':'Ann Clg .4% Condns DB=>MWB',
           'cooling_WB_0_4':'Ann Clg .4% Condns WB=>MDB'}
    selected={}
    for role,suffix in rules.items():
        found=[r for r in objects(rows,'SizingPeriod:DesignDay') if r[1].endswith(suffix)]
        require(len(found)==1,'DESIGN_CONDITION_NOT_UNIQUE',[role,len(found)])
        row=found[0];require(not fields.get(row,'dry_bulb_temperature_range_modifier_day_schedule_name')
            and not fields.get(row,'humidity_condition_day_schedule_name')
            and not fields.get(row,'beam_solar_day_schedule_name')
            and not fields.get(row,'diffuse_solar_day_schedule_name'),'DESIGN_EXTERNAL_SCHEDULE_REQUIRED')
        require(fields.get(row,'day_type')==('WinterDesignDay' if role.startswith('heating') else 'SummerDesignDay'),
                'DESIGN_DAY_TYPE_CONFLICT')
        selected[role]=row
    return loc,selected,{'ddy':ddy_ref,'annual_weather_identity_only':weather_ref,'wmo':header[5],
        'selected_names':{k:r[1] for k,r in selected.items()},'geography_checked_at_DDY_print_precision':True,
        'annual_weather_used_for_design_simulation':False,'formal_admitted':False}


def performance_layers(rows,xml_ref,fields,*,root=ROOT):
    tree=ET.parse(source_file(xml_ref,root))
    for element in tree.iter():element.tag=element.tag.split('}')[-1]
    pumps=tree.findall('.//HVACPlant/HeatPump');require(len(pumps)==1,'PERFORMANCE_SOURCE_HEATPUMP_AMBIGUOUS')
    raw={}
    for mode in ('Heating','Cooling'):
        points=[]
        for p in pumps[0].findall('./'+mode+'DetailedPerformanceData/PerformanceDataPoint'):
            efficiency=p.find('Efficiency')
            require(efficiency is not None and efficiency.findtext('Units')=='COP','PERFORMANCE_POINT_EFFICIENCY_UNSUPPORTED')
            capacity,fraction=p.findtext('Capacity'),p.findtext('CapacityFractionOfNominal')
            require((capacity is None)!=(fraction is None),'PERFORMANCE_CAPACITY_PARAMETERIZATION_AMBIGUOUS')
            point={'outdoor_temperature_F':float(p.findtext('OutdoorTemperature')),
                'outdoor_temperature_C':(float(p.findtext('OutdoorTemperature'))-32)*5/9,
                'speed_label':p.findtext('CapacityDescription'),'COP':float(efficiency.findtext('Value'))}
            point['capacity_Btu_h' if capacity is not None else 'capacity_fraction_of_nominal']=float(capacity if capacity is not None else fraction)
            points.append(point)
        require(points,'PERFORMANCE_SOURCE_POINTS_MISSING',mode)
        raw[mode.lower()]={'points':points,'outdoor_temperature_range_C':[
            min(p['outdoor_temperature_C'] for p in points),max(p['outdoor_temperature_C'] for p in points)],
            'manufacturer_measurement_or_independent_product_certification':None}
    variables={r[1]:r for r in objects(rows,'Table:IndependentVariable')}
    lists={r[1]:r[2:] for r in objects(rows,'Table:IndependentVariableList')}
    tables={}
    for r in objects(rows,'Table:Lookup'):
        require(r[2] in lists,'PERFORMANCE_TABLE_AXIS_LIST_MISSING')
        axes=[]
        for name in lists[r[2]]:
            require(name in variables,'PERFORMANCE_TABLE_AXIS_MISSING',name)
            axis=variables[name];require(not fields.get(axis,'external_file_name'),'PERFORMANCE_EXTERNAL_AXIS_UNBOUND')
            values=[float(v) for v in axis[11:]]
            require(values and all(a<b for a,b in zip(values,values[1:])),'PERFORMANCE_AXIS_NOT_ORDERED')
            axes.append({'name':name,'grid_range':[min(values),max(values)],'grid_values':values,
                'interpolation':fields.get(axis,'interpolation_method'),'extrapolation':fields.get(axis,'extrapolation_method'),
                'numeric_input_limits':[fields.get(axis,'minimum_value'),fields.get(axis,'maximum_value')]})
        tables[r[1]]={'axes':axes,'source_row_sha256':digest(r)}
    require(tables,'PERFORMANCE_TABLES_MISSING')
    coil=objects(rows,'Coil:Heating:DX:MultiSpeed');require(len(coil)==1,'PERFORMANCE_HEATING_COIL_AMBIGUOUS')
    return {'raw_published_model_input':{'xml':xml_ref,'modes':raw},'generated_lookup_tables':tables,
        'heating_compressor_minimum_outdoor_C':float(fields.get(coil[0],'minimum_outdoor_dry_bulb_temperature_for_compressor_operation')),
        'operating_limit_is_not_capacity_or_COP_evidence':True,
        'generated_points_are_not_additional_measurements':True,'formal_admitted':False}


def prepare(folder,branch,ddy_ref,*,step=1,warmup=14,root=ROOT):
    require(branch in ('independent_control_zone_load','installed_heatpump','whole_source_envelope_load'),
            'CHINESE_DESIGN_BRANCH')
    require(step in (1,2,5) and warmup in (14,28),'CHINESE_DESIGN_PROTOCOL')
    spec=read(folder/'BLUEPRINT.json');plan=read(folder/'ASSEMBLY_PLAN.json')
    fields=Fields(source_file(spec['engine_schema'],root))
    original=parse((folder/'assembly/in.idf').read_text());rows=copy.deepcopy(original)
    target=read(folder/'EB_MAPPING.json')['hvac']['zone']
    recipe=read(folder/'OPERATION_REPLACEMENT.json')
    if branch=='independent_control_zone_load':
        for change in reversed(plan['joint_installation']['HVAC_changes']):
            if change['after'] is not None:
                require(rows.count(change['after'])==1,'DESIGN_HVAC_REVERSAL_AMBIGUOUS',change['after'][:2]);rows.remove(change['after'])
            if change['before'] is not None:rows.append(copy.deepcopy(change['before']))
        require(len(objects(rows,'ZoneHVAC:IdealLoadsAirSystem'))==1,'DESIGN_TARGET_IDEAL_NOT_RESTORED')
    elif branch=='whole_source_envelope_load':
        from scripts.verify_chinese_wholehome_spaces import ideal_instrument
        from .native_enclosures import bind_dwellings
        rows=parse((folder/'source.idf').read_text())
        rows=[r for r in rows if not r[0].startswith(('ZoneHVAC:','ZoneControl:','ThermostatSetpoint:'))
            and not(r[0].startswith('Schedule') and r[1].startswith('instrument_'))]
        bundle=read(source_file(read(folder/'HOUSEHOLD_SCOPE.json')['source_bundle'],root))
        native=read(source_file(recipe['native_table_manifest'],root))
        groups={r['ROOM_GROUP_ID']:r for r in read(source_file(native['canonical_tables']['ROOM_GROUP'],root))}
        conditioned=[r['NAME'] for r in bundle['rooms'] if groups[r['OF_ROOM_GROUP']]['IS_AC_ROOM']]
        require(len(conditioned)==39,'CHINESE_SOURCE_SERVICE_SCOPE_DRIFT')
        rows=ideal_instrument(rows,conditioned,fields,{'heating_C':20.,'cooling_C':25.5555555555556})
        require(not objects(rows,'ElectricEquipment') and not objects(rows,'People'),'DESIGN_ENVELOPE_HAS_INTERNAL_LOADS')
    require(housing_fingerprint(rows)==housing_fingerprint(original),'CHINESE_DESIGN_CHANGED_SOURCE_HOUSING')
    # Bind the same explicit engineering thermostat in both physical and load
    # branches. Unused source DesignDay schedule slots must not become 0 C.
    rows += [['ScheduleTypeLimits','DESIGN_TEMPERATURE',-100,100,'Continuous','Temperature'],
             ['Schedule:Constant','DESIGN_HEATING','DESIGN_TEMPERATURE',20.],
             ['Schedule:Constant','DESIGN_COOLING','DESIGN_TEMPERATURE',25.5555555555556]]
    for r in objects(rows,'ThermostatSetpoint:DualSetpoint'):
        fields.set(r,'heating_setpoint_temperature_schedule_name','DESIGN_HEATING')
        fields.set(r,'cooling_setpoint_temperature_schedule_name','DESIGN_COOLING')
    loc,days,join=design_pair(ddy_ref,spec['site_weather']['artifacts'][0],fields,root=root)
    rows=[r for r in rows if r[0] not in ('Site:Location','RunPeriod') and not r[0].startswith('SizingPeriod:')]
    rows += [loc,*days.values()]
    simulation=objects(rows,'SimulationControl')[0]
    for key,value in {'do_zone_sizing_calculation':'No','do_system_sizing_calculation':'No','do_plant_sizing_calculation':'No',
        'run_simulation_for_sizing_periods':'Yes','run_simulation_for_weather_file_run_periods':'No'}.items():fields.set(simulation,key,value)
    objects(rows,'Timestep')[0][1]=60//step
    building=objects(rows,'Building')[0]
    fields.set(building,'minimum_number_of_warmup_days',warmup)
    fields.set(building,'maximum_number_of_warmup_days',60 if warmup==14 else 84)
    rows=[r for r in rows if r[0]!='Output:Variable']
    for variable in ['Site Outdoor Air Drybulb Temperature','Site Ground Temperature','Zone Mean Air Temperature',
        'Zone Thermostat Heating Setpoint Temperature','Zone Thermostat Cooling Setpoint Temperature',
        'Zone Ideal Loads Supply Air Total Heating Rate','Zone Ideal Loads Supply Air Total Cooling Rate',
        'Zone Ideal Loads Supply Air Total Heating Energy','Zone Ideal Loads Supply Air Total Cooling Energy',
        'Heating Coil Heating Rate','Cooling Coil Total Cooling Rate','Heating Coil Electricity Energy',
        'Cooling Coil Electricity Energy','Heating Coil Defrost Electricity Energy','Fan Electricity Energy',
        'Electric Equipment Electricity Energy','Schedule Value','Performance Curve Output Value',
        'Performance Curve Input Variable 1 Value','Performance Curve Input Variable 2 Value']:
        rows.append(['Output:Variable','*',variable,'Timestep'])
    if branch=='installed_heatpump':require(not objects(rows,'ZoneHVAC:IdealLoadsAirSystem'),'DESIGN_HIDDEN_BACKUP')
    return rows,{'schema':'national_idf.chinese_source_design_diagnostic.v1','branch':branch,'target_zone':target,
        'source_blueprint':{'path':str((folder/'BLUEPRINT.json').relative_to(root)),'sha256':sha(folder/'BLUEPRINT.json')},
        'design_condition_join':join,'selected_design_rows':days,'dependencies':plan['dependencies'],
        'step_min':step,'warmup_min_days':warmup,'conditional_source_ground_retained':True,
        'independent_wholehouse_capacity_selection_approved':False,'formal_admitted':False,
        'internal_load_scope':'None, enclosure-only' if branch=='whole_source_envelope_load' else 'Identical published reference plugs/water background, not a design-person envelope',
        'ideal_thermal_load_is_not_device_electricity':True,
        'zero_people_scope_is_not_general_family_design':True,
        'implementation':{'path':'national_idf/chinese_design.py','sha256':sha(__file__)}}
