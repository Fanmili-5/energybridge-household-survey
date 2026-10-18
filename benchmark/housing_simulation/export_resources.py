"""Recreate the bundled official component subset from an EnergyPlus24.1 install."""
import argparse
import gzip
import json
from pathlib import Path
import shutil

from .kernel.core_tools import parse_idf
from .pipeline import fresh, portable_gzip, read, sha


def export(energyplus_dir, output):
    ep=Path(energyplus_dir);idf=ep/'ExampleFiles/PackagedTerminalHeatPump.idf';schema=ep/'Energy+.schema.epJSON'
    if sha(idf)!='8ec79076fd535c4192de135aa784e4d496a5a39567db21e04224c95c6063e90a':raise ValueError('official template hash mismatch')
    if sha(schema)!='d94276ce43d7673d752392f1d1fbc0f66884700ecbbba12d50bfa5f8c709bc72':raise ValueError('official schema hash mismatch')
    out=fresh(output)
    fields={k:v['legacy_idd']['fields']for k,v in read(schema)['properties'].items()if 'fields'in v.get('legacy_idd',{})}
    (out/'schema_fields.json.gz').write_bytes(portable_gzip((json.dumps(fields,sort_keys=True,separators=(',',':'))+'\n').encode()))
    kinds={'ZoneHVAC:PackagedTerminalHeatPump','Fan:SystemModel','Coil:Cooling:DX:SingleSpeed','Coil:Heating:DX:SingleSpeed','Coil:Heating:Electric','OutdoorAir:Mixer'}
    rows=[r for r in parse_idf(idf.read_text())if(r[0]in kinds and r[1].startswith('Zone1'))or r[0].startswith('Curve:')]
    data={'schema':'eb.housing_components.energyplus24.1.v1',
        'source_url':'https://github.com/NatLabRockies/EnergyPlus/blob/v24.1.0/testfiles/PackagedTerminalHeatPump.idf',
        'source_idf_sha256':sha(idf),'source_schema_sha256':sha(schema),'rows':rows}
    (out/'heat_pump.json').write_text(json.dumps(data,indent=2)+'\n')
    shutil.copyfile(ep/'LICENSE.txt',out/'ENERGYPLUS_LICENSE.txt')
    return {p.name:sha(p)for p in sorted(out.iterdir())}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--energyplus-dir',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(export(a.energyplus_dir,a.out),indent=2))
