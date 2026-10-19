"""Prepare paired IDFs from one project; never invoke an EnergyPlus executable."""
from pathlib import Path
from benchmark.ab_generation.common import read, save, seal, sha, digest, verify
from benchmark.ab_generation.life_physics import assemble_life, export_life
from benchmark.housing_simulation.pipeline import compile_pairs
from .pipeline import check


def prepare(project, weather, out, sample_ids=None, progress=None, profile=None):
    project, weather, out = Path(project).resolve(), Path(weather).resolve(), Path(out).resolve()
    check(project); out.mkdir(parents=True, exist_ok=False)
    profile_path = Path(profile) if profile else Path(__file__).parent / 'examples/preparation.json'
    preparation = read(profile_path)
    if preparation['schema'] != 'eb.project.preparation.v1':
        raise ValueError('PROJECT_PREPARATION_PROFILE_REQUIRED')
    save(out / 'PREPARATION_PROFILE.json', preparation)
    view = read(project / 'VIEW.json'); config = read(project / 'INPUT.json')
    selected = {r['sample_id']: r for r in read(project / 'SELECTION.json')['records']}
    available = {p['id']: (h, p) for h in view['households'] for p in h['previews']}
    if sample_ids is None:
        sample_ids = []
        for h in view['households']:
            choices = sorted(h['previews'], key=lambda p: (not p['static_valid'], p['features']['scope'] == 'control', p['id']))
            if choices:
                sample_ids.append(choices[0]['id'])
    if not sample_ids or len(set(sample_ids)) != len(sample_ids) or not set(sample_ids) <= available.keys():
        raise ValueError('UNKNOWN_OR_DUPLICATE_PROJECT_PREPARATION_SAMPLE')
    if len({available[s][0]['id'] for s in sample_ids}) != len(sample_ids):
        raise ValueError('PREPARE_ONE_B_PER_HOUSEHOLD_PER_JOB')
    emit = progress or (lambda stage, text: print(stage + ': ' + text, flush=True))
    records = []
    for sid in sample_ids:
        household, preview = available[sid]; hid = household['id']; folder = out / hid; folder.mkdir()
        emit('prepare_idf', '准备 ' + hid + ' 的同住房、同天气A/B模型')
        record = {'household_id': hid, 'sample_id': sid, 'new_engine_runs': 0,
                  'known_static_issues': preview['static_issues'], 'physical_status': 'not_run'}
        try:
            contract = project / 'connected/life_inputs' / hid / 'world_contracts.json'
            experiment = {'schema': 'eb.life_A_experiments.v1', 'settings': preparation['settings'],
                'weather_source': preparation['weather_source'], 'records': [{'household_id': hid,
                'case_id': hid + '-' + config['date'], 'date': config['date'], 'decision_min': 480,
                'horizon_min': [480, 1920], 'events': config['events'], 'tariff': config['tariff'],
                'assignment': {'mode': 'fresh_candidates'}}]}
            save(folder / 'experiments.json', experiment)
            assembled = assemble_life(project / 'connected/life_A' / hid, contract,
                project / 'connected/shells', weather, folder / 'experiments.json', folder / 'assembled')
            if assembled['case_count'] != 1:
                raise ValueError('PROJECT_ASSEMBLY_REJECTED:' + str(assembled['records']))
            context = read(project / 'contexts' / (hid + '.json.gz'))
            batch = {'schema': 'eb.ab_generation.batch.v1', 'records': [{'case_id': context['case_id'], 'context': 'context.json.gz'}]}
            save(folder / 'contexts/context.json.gz', context); save(folder / 'contexts/BATCH.json', batch)
            seal(folder / 'contexts', {'assembled_manifest_sha256': sha(folder / 'assembled/MANIFEST.json')})
            result = read(project / 'generated' / (hid + '.json.gz'))
            save(folder / 'generated/result.json.gz', result)
            seal(folder / 'generated', {'input_batch_sha256': digest(batch),
                'records': [{'case_id': context['case_id'], 'path': 'result.json.gz'}]})
            sample = selected[sid]
            override = sample['aliases'][0]['override']
            export_life(folder / 'assembled', folder / 'contexts', folder / 'generated', 'known_profile_vpp',
                folder / 'export', request_overrides={context['case_id']: override})
            compiled = compile_pairs((folder / 'export/physics_job.json').resolve(), folder / 'compiled')
            if not all(r['status'] == 'compiled' for r in compiled['records']):
                raise ValueError('PAIRED_IDF_COMPILATION_REJECTED;retain_original_request')
            pair_id = compiled['records'][0]['id']
            record.update(status='paired_idf_prepared', weather_sha256=sha(weather),
                A_idf=str((folder / 'compiled' / pair_id / 'A/model.idf').relative_to(out)),
                B_idf=str((folder / 'compiled' / pair_id / 'B/model.idf').relative_to(out)),
                shared_shell_weather_and_case=True, simulation_started=False)
        except (ValueError, KeyError, TypeError, OSError) as error:
            record.update(status='preparation_rejected', reason=str(error), replacement_B_selected=False)
        records.append(record)
        save(out / 'PROGRESS.json', records)
    report = {'schema': 'eb.project.idf_preparation.v1', 'records': records,
        'project_manifest_sha256': sha(project / 'MANIFEST.json'), 'new_engine_runs': 0,
        'physical_results': 'not_run', 'failures_retained': True, 'replacement_B_selected': False,
        'prepared': sum(r['status'] == 'paired_idf_prepared' for r in records), 'requested': len(sample_ids)}
    save(out / 'SUMMARY.json', report); seal(out, {'schema': report['schema'], 'new_engine_runs': 0})
    return report
