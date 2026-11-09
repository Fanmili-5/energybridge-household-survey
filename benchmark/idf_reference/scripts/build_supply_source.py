"""Published stratified source plus the separately declared condensing option."""
import subprocess
import time
import xml.etree.ElementTree as ET

from national_idf.common import ROOT, locked, read, require, save, sha

OUT = ROOT / 'reports/tengchong_supply_20261031'
SOURCE = ROOT / 'work/p1_hpxml_004ca3ce'


def ref(path):
    return {'path': str(path.relative_to(ROOT)), 'sha256': sha(path)}


def main():
    parent = SOURCE / 'workflow/sample_files/base-dhw-tank-model-type-stratified-detailed-occupancy-stochastic.xml'
    tree = ET.parse(parent); root = tree.getroot()
    namespace = root.tag.split('}')[0][1:]; ET.register_namespace('', namespace)
    local = lambda element: element.tag.rsplit('}', 1)[-1]
    dependencies, changes = [], []
    for element in root.iter():
        if local(element) in ('SchedulesFilePath', 'EPWFilePath'):
            path = (parent.parent / element.text).resolve()
            if local(element) == 'EPWFilePath' and not path.exists(): path = SOURCE / 'weather' / element.text
            require(path.is_file(), 'SOURCE_DEPENDENCY_MISSING')
            dependencies.append(ref(path)); element.text = str(path)
        if local(element) == 'ClothesDryer':
            for child in list(element):
                if local(child) == 'DryingMethod':
                    changes.append({'field': 'DryingMethod', 'before': child.text, 'after': 'condensing'})
                    child.text = 'condensing'
                if local(child) == 'CombinedEnergyFactor':
                    changes.append({'field': 'CombinedEnergyFactor', 'before': child.text, 'after': None,
                        'basis': 'Published condensing-specific generic default, no vented performance reuse'})
                    element.remove(child)
    require(any(local(e) == 'TankModelType' and e.text == 'stratified' for e in root.iter()), 'SOURCE_NOT_STRATIFIED')
    path = OUT / 'stratified_condensing.xml'; tree.write(path, encoding='utf-8', xml_declaration=True)
    sdk = read(ROOT / 'data/source/p1_reference_components_20261029/OFFICIAL_SDK.json'); locked(sdk['archive'], ROOT)
    output = OUT / 'source_model'
    command = [str(ROOT / sdk['CLI_paths'][0]), str(SOURCE / 'workflow/run_simulation.rb'), '-x', str(path),
               '-o', str(output), '-d', '--skip-simulation']
    start = time.monotonic()
    with (OUT / 'SOURCE_BUILD.log').open('w') as log:
        code = subprocess.run(command, cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT, timeout=300).returncode
    require(code == 0, 'SOURCE_CONVERSION_FAILED')
    translate = [str(ROOT / sdk['CLI_paths'][0]), str(ROOT / 'scripts/forward_translate_source.rb'),
                 str(output / 'run/in.osm'), str(output / 'run/in.idf')]
    with (OUT / 'FORWARD_TRANSLATION.log').open('w') as log:
        code = subprocess.run(translate, stdout=log, stderr=subprocess.STDOUT).returncode
    require(code == 0, 'SOURCE_FORWARD_TRANSLATION_FAILED')
    save(OUT / 'SOURCE_RECEIPT.json', {'parent': ref(parent), 'derived_XML': ref(path), 'dependencies': dependencies,
        'command': command, 'translation_command': translate, 'exit_code': code, 'seconds': time.monotonic()-start,
        'component_changes': changes, 'tank_type_from_published_original': 'stratified',
        'stochastic_or_family_generator_called': False, 'EnergyPlus_started': False,
        'formal_admitted': False, 'source_context_not_Chinese_dwelling': True})
    print('Public stratified source translated; condensing option separate, no family generator called')


if __name__ == '__main__': main()
