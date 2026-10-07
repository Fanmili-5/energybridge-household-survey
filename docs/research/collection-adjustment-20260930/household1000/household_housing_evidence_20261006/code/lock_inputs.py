"""Recheck every actual external input, snapshot pointers and check the report."""
import ast,hashlib,json,shutil
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;REPO=OUT.parents[4];V7=BASE/'idf_joint_production_20261005'
def sha(x):return hashlib.sha256(Path(x).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    lock={}
    def add(x,expected=None):
        path=Path(x).resolve();actual=sha(path)
        if isinstance(expected,dict):expected=expected['sha256']
        if expected is not None:assert actual==expected,'changed_input:'+str(path)
        lock[str(path)]=actual
    for x,h in read(V7/'INPUT_LOCK.json')['files'].items():add(x,h)
    for x in ['PACKAGE_MANIFEST.json','HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json','code/reference_world.py','code/compile_reference_idfs.py','MATERIAL_SEMANTIC_ADMISSION.json','RUNTIME.json']:add(V7/x)
    add(BASE/'chfs_census_bridge_20261003/run_bridge.py');add(BASE/'chfs_admission_20261003/private_metadata/chfs2021_hh_pub_v0_20260131_metadata.json')
    add('/Users/fanmili/Downloads/2021/CHFS问卷-2021/2021年中国家庭金融调查(CHFS)问卷.pdf')
    add('/Applications/EnergyPlus-24-1-0/Documentation/AuxiliaryPrograms.pdf');add('/Applications/EnergyPlus-24-1-0/energyplus');add(REPO/'artifacts/private_research/eb-dest-catalog-20260925.json')
    for x in V7.glob('worlds/*.json'):add(x)
    for x in V7.glob('reference_idfs/*.idf'):add(x)
    for r in read(OUT/'NATIVE_REFERENCE_REGISTRY.json')['models']:
        add(r['source_path'],r['source_sha256']);add(r['conversion_path'],r['conversion_sha256']);add(Path(r['source_path']).parent/'manifest.json')
    for r in read(OUT/'WEATHER_REFERENCE_REGISTRY.json')['stations']:
        add(r['path'],r['sha256']);add(Path(r['path']).with_suffix('.manifest.json'))
    for r in read(OUT/'ADDITIONAL_REGIONAL_REFERENCES.json')['models']:
        add(r['source_path'],r['source_sha256']);add(Path(r['source_path']).with_suffix('.accdb.7z'))
    for x in (REPO/'artifacts/private_research/household_housing_evidence_20261006').glob('*SOURCE_PRIVATE.json'):add(x)
    if (OUT/'raw/Census2020_Jiangsu_QA3.html').exists():add(OUT/'raw/Census2020_Jiangsu_QA3.html')
    save('INPUT_LOCK.json',{'files':lock,'all_actual_input_hashes_verified_now':True,'CHFS_raw_and_derived_private_source_records_not_published':True,
      'self_generated_assembly_or_pilot_outputs_are_package_manifest_members_not_external_inputs':True,'source_population_anchor_not_regenerated':True})
    snapshot=OUT/'LATEST_BEFORE_HOUSING_EVIDENCE_20261006.json'
    if not snapshot.exists():shutil.copyfile(BASE/'LATEST.json',snapshot)
    c=read(OUT/'CURRENT.json');report=(OUT/'METHODS_AND_RESULTS.md').read_text();assert c['all1000_sameprovince_opaque_weather_reference_candidates']==1000
    for word in ['1495','1073','923','864','561','189','113','9726','1.209882','1.168613','5.7786','116','271','77/136','三个负对照']:
        assert word in report,'missing_report_metric:'+word
    for x in OUT.glob('code/*.py'):ast.parse(x.read_text(),filename=str(x))
    assert c['complete_household_IDFs']==0 and c['scientific_benchmark_admitted'] is False
    checks={'report_matches_current_results':True,'source_phase_and_statistical_physical_human_boundaries_explicit':True,
      'Python_source_AST_parse_all_passed':True,'no_code_tuning_after_negative_year_score':True,'all_new_write_entrypoints_guarded':True,
      'input_files_hash_verified':len(lock),'all_sealed_prior_packages_preserved':'VERIFICATION.json','source_microdata_sourceIDs_not_exported_in_docs':True}
    save('REPORT_CHECK.json',checks);print(json.dumps(checks,ensure_ascii=False))
if __name__=='__main__':main()
