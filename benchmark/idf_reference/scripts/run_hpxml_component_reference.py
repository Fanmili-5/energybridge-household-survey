"""Run unchanged public appliance source fixtures, without family/A/B generation."""
import argparse
import subprocess
import time

from national_idf.common import ROOT, locked, read, require, save, sha

OUT=ROOT/'reports/p1_reference_components_20261029'
SOURCE=ROOT/'data/source/p1_reference_components_20261029'
CHECKOUT=ROOT/'work/p1_hpxml_004ca3ce'


def run(name):
    require(name in ('author_test_base','source_base','source_published_schedule'),'UNKNOWN_SOURCE_PROBE')
    sdk=read(SOURCE/'OFFICIAL_SDK.json');locked(sdk['archive'],ROOT)
    package=read(SOURCE/'COMPLETE_SOURCE_PACKAGE.json');locked(package['archive'],ROOT)
    cli=ROOT/sdk['CLI_paths'][0]
    output=OUT/name;require(not output.exists(),'OUTPUT_EXISTS',str(output));output.mkdir()
    if name=='author_test_base':
        cmd=[str(cli),str(CHECKOUT/'HPXMLtoOpenStudio/tests/test_hotwater_appliance.rb'),'-n','test_base']
        inputs=[CHECKOUT/'HPXMLtoOpenStudio/tests/test_hotwater_appliance.rb']
    else:
        filename='base.xml' if name=='source_base' else 'base-schedules-detailed-occupancy-stochastic.xml'
        xml=CHECKOUT/'workflow/sample_files'/filename
        inputs=[xml,CHECKOUT/'weather/USA_CO_Denver.Intl.AP.725650_TMY3.epw']
        if name=='source_published_schedule':
            inputs.append(CHECKOUT/'HPXMLtoOpenStudio/resources/schedule_files/occupancy-stochastic.csv')
        cmd=[str(cli),str(CHECKOUT/'workflow/run_simulation.rb'),'-x',str(xml),'-o',str(output),'-d']
        for variable in ['enduses','hotwater','airflows','Schedule Value',
                         'Electric Equipment Electricity Energy','Electric Equipment Convective Heating Energy',
                         'Electric Equipment Radiant Heating Energy','Electric Equipment Latent Gain Energy',
                         'Electric Equipment Lost Heat Energy']:
            cmd+=['--timestep',variable]
    before={str(p.relative_to(ROOT)):sha(p) for p in inputs}
    start=time.monotonic()
    with (output/'stdout.log').open('w') as stdout,(output/'stderr.log').open('w') as stderr:
        p=subprocess.run(cmd,cwd=CHECKOUT,stdout=stdout,stderr=stderr,timeout=300)
    unchanged=all(sha(ROOT/path)==value for path,value in before.items())
    receipt={'case':name,'command':cmd,'exit_code':p.returncode,'seconds':time.monotonic()-start,
        'source_inputs_sha256':before,'source_inputs_unchanged':unchanged,
        'uses_original_public_US_example':True,'Chinese_housing_admitted':False,
        'family_generation_or_AB_called':False,'stochastic_generation_requested':False,
        'scope':'Source calculation/native component validation only; not an EB-controlled or Chinese-household run'}
    save(output/'RECEIPT.json',receipt)
    print(name,'exit',p.returncode,'seconds',round(receipt['seconds'],1),'inputs unchanged',unchanged)
    require(p.returncode==0 and unchanged,'SOURCE_REFERENCE_RUN_FAILED',name)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('case',choices=['author_test_base','source_base','source_published_schedule'])
    run(parser.parse_args().case)
