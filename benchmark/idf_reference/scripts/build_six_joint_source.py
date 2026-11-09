"""Install the complete already-used public heat pump in the coherent source host."""
import copy
import subprocess
import xml.etree.ElementTree as ET

from national_idf.common import ROOT, read, require, save, sha
from national_idf.idf import parse
from national_idf.source_adapter import protected

OUT = ROOT / 'reports/eb_six_joint_20261031'


def ref(path): return {'path': str(path.relative_to(ROOT)), 'sha256': sha(path)}


def main():
    parent = ROOT / 'reports/tengchong_supply_20261031/stratified_condensing.xml'
    heatpump = ROOT / 'work/p1_hpxml_004ca3ce/workflow/sample_files/base-hvac-mini-split-heat-pump-ductless-detailed-performance.xml'
    tree, hp = ET.parse(parent), ET.parse(heatpump)
    root = tree.getroot(); namespace = root.tag.split('}')[0][1:]; ET.register_namespace('', namespace)
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    systems = next(e for e in root.iter() if local(e) == 'Systems')
    old = next(e for e in systems if local(e) == 'HVAC')
    new = next(e for e in hp.getroot().iter() if local(e) == 'HVAC')
    systems.remove(old); systems.insert(0, copy.deepcopy(new))
    path = OUT / 'six_source.xml'; tree.write(path, encoding='utf-8', xml_declaration=True)
    sdk = read(ROOT / 'data/source/p1_reference_components_20261029/OFFICIAL_SDK.json')
    command = [str(ROOT / sdk['CLI_paths'][0]), str(ROOT / 'work/p1_hpxml_004ca3ce/workflow/run_simulation.rb'),
        '-x', str(path), '-o', str(OUT / 'source_model'), '-d', '--skip-simulation']
    with (OUT / 'SOURCE_BUILD.log').open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT / 'work/p1_hpxml_004ca3ce')
    require(result.returncode == 0, 'PUBLIC_SIX_SOURCE_CONVERSION_FAILED')
    model = OUT / 'source_model/run/in.idf'
    command2 = [str(ROOT / sdk['CLI_paths'][0]), str(ROOT / 'scripts/forward_translate_source.rb'),
        str(OUT / 'source_model/run/in.osm'), str(model)]
    with (OUT / 'FORWARD_TRANSLATION.log').open('w') as log:
        result = subprocess.run(command2, stdout=log, stderr=subprocess.STDOUT)
    require(result.returncode == 0, 'PUBLIC_SIX_SOURCE_TRANSLATION_FAILED')
    original = ROOT / 'reports/tengchong_supply_20261031/source_model/run/in.idf'
    old_rows, new_rows = parse(original.read_text()), parse(model.read_text())
    removed = [r for r in old_rows if protected(r) and r not in new_rows]
    added = [r for r in new_rows if protected(r) and r not in old_rows]
    # The old ducted source generates a virtual 1m cube return plenum. Its
    # removal is part of the complete HVAC replacement, not a housing edit.
    require(not added and len(removed) == 17, 'SOURCE_ENVELOPE_CHANGED')
    allowed = {'central ac furnace airloop ret air zone', 'central ac furnace airloop ret air space',
        'Plenum Space Type', 'Adiabatic', 'AdiabaticConst', *[f'Surface {i}' for i in range(1, 7)]}
    require(all(r[1] in allowed for r in removed), 'NON_HVAC_HOUSING_REMOVED')
    require(all(r[4] == 'central ac furnace airloop ret air zone' for r in removed if r[0] == 'BuildingSurface:Detailed'),
        'NON_PLENUM_SURFACE_REMOVED')
    same_housing = True
    save(OUT / 'SOURCE_RECEIPT.json', {'parent': ref(parent), 'HVAC_source': ref(heatpump), 'derived_XML': ref(path),
        'public_commit': '004ca3ce1cc378aac3fdecd82d950d37f01e8c3e', 'source_model': ref(model),
        'old_HVAC_XML': ET.tostring(old, encoding='unicode'), 'installed_HVAC_XML': ET.tostring(new, encoding='unicode'),
        'commands': [command, command2], 'physical_source_envelope_unchanged': same_housing,
        'virtual_return_plenum_objects_removed': removed,
        'virtual_plenum_source_code': ref(ROOT / 'work/p1_hpxml_004ca3ce/HPXMLtoOpenStudio/resources/airflow.rb'),
        'changes': 'Whole published ductless heat-pump HVAC block replaces furnace+AC+ducts; no performance points merged',
        'original_source_host_not_Chinese': True, 'stochastic_or_family_generator_called': False,
        'device_capacity_not_resized_for_China': True, 'formal_admitted': False})
    print('Complete public heat pump + stratified storage + condensing dryer source translated, housing unchanged')


if __name__ == '__main__': main()
