"""Reuse a complete existing EB component; do not edit its physical parameters."""
from .common import ROOT, read, require
from .source_adapter import source_file
from .tank_reference import replace_complete_tank


def install_tank(rows, pack_ref, target_schema_ref, *, root=ROOT):
    pack=read(source_file(pack_ref,root))
    require(pack['schema']=='national_idf.complete_reference_tank_installation.v1','REFERENCE_TANK_PACK_SCHEMA')
    component=read(source_file(pack['component'],root))
    require(component['schema']=='national_idf.public_reference_tank.v1','REFERENCE_TANK_SOURCE_SCHEMA')
    result,receipt=replace_complete_tank(rows,component['source_model'],component['source_schema'],
                                       target_schema_ref,target_name=pack['target_name'],root=root)
    names=set(pack['retire_old_zero_correction_names']);retired=[r for r in result if len(r)>1 and r[1] in names]
    require(len(retired)==len(names)==7 and any(r[0]=='EnergyManagementSystem:Program' and
            any('= 0.0 * dhw_e_cons' in s for s in r[2:]) for r in retired),'REFERENCE_TANK_OLD_CORRECTION_NOT_ISOLATED_ZERO')
    result=[r for r in result if r not in retired]
    # Retained wildcard reports may mention object names; no physical/EMS
    # consumer may retain a retired identifier after installation.
    require(not any(any(v in names for v in r[1:]) for r in result if not r[0].startswith('Output')),
            'REFERENCE_TANK_RETIRED_CORRECTION_STILL_REFERENCED')
    receipt.update(component=pack['component'],installation_pack=pack_ref,
                   retired_old_zero_correction_objects=retired,original_EB_physical_fields_preserved=True)
    return result,receipt
