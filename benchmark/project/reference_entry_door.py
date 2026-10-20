"""Finite thermal storage for a declared reference exterior opaque door.

Same R-value, geometry, absorptances and all appliance requests/hardware. The
new heat capacity is an explicit reference-material assumption, not a measured
door and not a tuned acceptance criterion. Internal doors remain unchanged.
"""
from benchmark.housing_simulation.kernel.core_tools import parse_idf

POLICY={'schema':'eb.reference_entry_door.finite_mass.v1','conductivity_W_mK':.115,
    'density_kg_m3':513.,'specific_heat_J_kgK':1381.,
    'property_source':'https://raw.githubusercontent.com/NatLabRockies/EnergyPlus/v24.1.0/testfiles/5ZoneAirCooled.idf#WD01',
    'thickness_rule':'original_thermal_resistance_times_source_conductivity',
    'measured_material_claim':False,'internal_doors_changed':False}


def finite_entry(text):
    rows=parse_idf(text);lookup={(r[0].lower(),r[1].lower()):r for r in rows if len(r)>1}
    original=lookup[('material:nomass','referencedoorr')]
    resistance=float(original[3]);name='ReferenceExteriorDoorFiniteMass';material=name+'_material'
    if any(len(r)>1 and r[1].lower()in (name.lower(),material.lower())for r in rows):raise ValueError('DOOR_OVERRIDE_ALREADY_PRESENT')
    changed=[]
    for row in rows:
        if row[0].lower()!='fenestrationsurface:detailed'or row[2].lower()!='door':continue
        wall=lookup[('buildingsurface:detailed',row[4].lower())]
        if wall[6].lower()!='outdoors':continue
        if row[3].lower()!='referencedoor':raise ValueError('EXTERIOR_DOOR_IS_NOT_THE_DECLARED_REFERENCE')
        changed.append(row[1]);row[3]=name
    if not changed:raise ValueError('NO_REFERENCE_EXTERIOR_DOOR')
    rows.extend([['Material',material,original[2],resistance*POLICY['conductivity_W_mK'],POLICY['conductivity_W_mK'],
                  POLICY['density_kg_m3'],POLICY['specific_heat_J_kgK'],*original[4:7]],['Construction',name,material]])
    result='\n\n'.join(',\n  '.join(map(str,r))+';'for r in rows)+'\n'
    return result,{'policy':POLICY,'surface_names':changed,'original_R_m2K_W':resistance,
                   'new_R_m2K_W':resistance,'areal_heat_capacity_J_m2K':resistance*.115*513*1381}
