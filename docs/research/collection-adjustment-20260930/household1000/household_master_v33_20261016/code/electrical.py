"""Explicit installation planning, never an inferred measured household supply."""
import math


def configure(w):
    ds=w['parameter_pack']['devices'];circuits={};ledger=[]
    for i,d in enumerate(ds):
        if 'ev'in d['types']:name='EV_bay'
        elif 'ac'in d['types']:name='AC_'+str(i+1)
        else:name='appliance_'+str(i+1)
        d['circuit']=name;power=d['max_electric_kw'];amps=next(a for a in(10,16,20,25,32,40,63)if .220*a>=power)
        circuits[name]=.220*amps
        ledger.append({'asset_id':d['asset_id'],'branch':name,'reference_current_A':amps,
                       'rated_reference_max_kW':power,'on_target_dwelling_main':name!='EV_bay'})
    peak=sum(d['max_electric_kw']for d in ds if d['circuit']!='EV_bay')+w['parameter_pack']['background_reserved_kw']
    mains=next(a for a in(40,60,80,100,125,160,200,250)if .220*a>=peak)
    w['parameter_pack'].update(circuit_limit_kw=circuits,home_service_limit_kw=.220*mains)
    w['installation_contract']={'schema':'eb.reference_installation.v33','voltage_V':220,'dwelling_main_A':mains,
        'connected_reference_peak_kW':peak,'branches':ledger,'EV_bay_outside_target_main':True,
        'water_supply':'explicit connected potable-water line for all wet appliances;15C is a later simulation reference,not measured',
        'drainage':'given connected drain at placed wet appliances',
        'actual_property_supply_and_structural_wall_certified':False,
        'design_condition':'supply and dedicated branches provisioned as part of the reference dwelling adaptation;not a claim of national installed supply'}
    return w
