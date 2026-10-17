"""Read-only V22 review on school Linux; isolated counterexamples never run EP."""
import argparse, ast, collections, concurrent.futures, contextlib, copy, datetime, hashlib
import io, json, pathlib, runpy, shutil, sys, tempfile, types

def read(p):
    return json.loads(pathlib.Path(p).read_text())

def sha(p):
    h = hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def snapshot(prod):
    names = ['WORLD_BUILD_REVIEW.json', 'STATIC_REVIEW.json', 'INPUT_AUDIT.json',
             'CALENDAR_AUDIT.json', 'BATH_COMMITMENT_AUDIT.json',
             'IDF_INPUT_AUDIT.json', 'PHYSICAL_INPUT_AUDIT.json',
             'MECHANISM_NEGATIVE_CONTROLS.json', 'VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json',
             'REFERENCE_MODEL_AUDIT.json', 'MATERIALS_AUDIT.json',
             'FRONTEND_CLOCK_REVIEW.json', 'FRONTEND_BINDINGS_REVIEW.json',
             'PRE_EP_SCIENTIFIC_REVIEW.json', 'FRONTEND_BROWSER_REVIEW.json',
             'SCIENTIFIC_REVIEW_REPORT.json', 'DELIVERY.json', 'EXECUTION_BOARD.json']
    return {n: {'exists': (prod / n).exists(),
                'sha256': sha(prod / n) if (prod / n).exists() else None,
                'report': read(prod / n) if (prod / n).exists() else None}
            for n in names}

def bindings(prod):
    selection = read(prod / 'SELECTION1000.json')
    worlds = [read(prod / h['world_path']) for h in selection['records']]
    checks = []
    for h in selection['records']:
        checks.append(('world', h['world_path'], h['world_sha256']))
        checks += [('pair', c['pair_path'], c['pair_sha256']) for c in h['rounds']]
    for h in read(prod / 'IDF_BINDINGS20000.json')['households']:
        for c in h['records']:
            for side in ('A', 'B'):
                b = c[side]
                checks += [('idf', b['IDF_path'], b['IDF_sha256']),
                           ('input_ledger', b['signal_ledger_path'], b['signal_ledger_sha256'])]
    for r in read(prod / 'ACTOR_BINDINGS.json')['records']:
        checks.append(('actor', r['actor_path'], r['actor_sha256']))
    for r in read(prod / 'CONSUMER_BINDINGS.json')['records']:
        checks.append(('consumer', r['consumer_path'], r['consumer_sha256']))
    def one(r):
        kind, path, expected = r
        try:
            actual = sha(prod / path)
            return kind, path, expected == actual, actual
        except Exception as e:
            return kind, path, False, repr(e)
    counts = collections.Counter(); fails = []; idf_hashes = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for kind, path, ok, actual in pool.map(one, checks):
            counts[kind] += 1
            if not ok:
                fails.append({'kind': kind, 'path': path, 'actual': actual})
            if kind == 'idf':
                idf_hashes.add(actual)
    classes = collections.Counter(); coverage = collections.Counter(); assets = 0
    for w in worlds:
        present = {k for d in w['parameter_pack']['devices'] for k in d['types']}
        classes.update(present); coverage[len(present)] += 1
        assets += len(w['parameter_pack']['devices'])
    return {'counts': dict(counts), 'failures': fails, 'unique_IDF_bytes': len(idf_hashes),
            'members': sum(w['N'] for w in worlds), 'class_households': dict(classes),
            'classes_per_household': dict(coverage), 'physical_asset_instances': assets,
            'round_counts': dict(collections.Counter(len(h['rounds']) for h in selection['records'])),
            'legacy_compatible_rounds': dict(collections.Counter(h.get('compatible_rounds') for h in selection['records'])),
            'legacy_compatible_input_dates': dict(collections.Counter(h.get('compatible_input_dates') for h in selection['records']))}

def signature_probe(prod, out):
    ns = runpy.run_path(str(prod / 'code/ep_gate.py'))
    tree = ast.parse((prod / 'code/ep_gate.py').read_text())
    signature_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'input_signature')
    files = ast.literal_eval(signature_fn.body[0].value)
    files += [str(p.relative_to(prod)) for p in (prod / 'code').glob('*.py')]
    files += [str(p.relative_to(prod)) for p in (prod / 'frontend_release/households').glob('*/*.js')]
    missing = [rel for rel in files if not (prod / rel).exists()]
    hid = read(prod / 'SELECTION1000.json')['records'][0]
    with tempfile.TemporaryDirectory(prefix='eb-v22-review-signature-') as tmp:
        isolated = pathlib.Path(tmp)
        for rel in files:
            target = isolated / rel; target.parent.mkdir(parents=True, exist_ok=True)
            source = prod / rel if (prod / rel).exists() else out / rel
            # The current UI proof remains in the review folder. It is never
            # installed into production or treated as an accepted EP review.
            shutil.copy2(source, target)
        ns['input_signature'].__globals__['OUT'] = isolated
        f = isolated / hid['world_path']; f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prod / hid['world_path'], f)
        before, _ = ns['input_signature'](); old = sha(f)
        w = read(f); w['members'][0]['age_years'] += 1
        f.write_text(json.dumps(w, ensure_ascii=False))
        after, _ = ns['input_signature']()
        return {'synthetic_isolated_copy': True, 'production_files_changed': False,
                'missing_current_production_signature_inputs': missing,
                'review_proof_used_only_in_isolated_copy': bool(missing), 'signature_before': before,
                'signature_after_world_mutation': after, 'world_bytes_changed': sha(f) != old,
                'world_mutation_detected': before != after,
                'scope': 'input_signature function only; no accepted review forged and no EP launched'}

class ImmediatePool:
    def __init__(self, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def submit(self, fn, *args):
        f = concurrent.futures.Future()
        try: f.set_result(fn(*args))
        except Exception as e: f.set_exception(e)
        return f

def readback_probes(prod):
    ns = runpy.run_path(str(prod / 'code/physics.py'))
    fn = ns['read_all']; g = fn.__globals__
    g['concurrent'] = types.SimpleNamespace(futures=types.SimpleNamespace(
        ProcessPoolExecutor=ImmediatePool, as_completed=concurrent.futures.as_completed))
    c = copy.deepcopy(read(prod / 'COMPILED50.json')['records'][0])
    result = {'household_id': c['household_id'], 'round_index': c['round_index'],
              'variant': c['variant'], 'pre_notice_max_difference': 0.,
              'meter_residual_J': {'A': 0., 'B': 0.}, 'spatial_SQL_max_difference': {'A': 0., 'B': 0.},
              'services': {}}
    for side in ('A', 'B'):
        result['services'][side] = {'hot_water': [], 'EV': {'goals': [], 'trips': []},
            'AC_curve_boundary': {'status': 'within_original_boundary'},
            'power_limits': {'circuit_exceeded': ['AC'] if side == 'A' else [], 'home_exceeded': side == 'A'}}
    g['pair_readback'] = lambda *_: copy.deepcopy(result)
    probes = []
    for kind in ('missing_all_run_records', 'A_power_boundary_exceeded'):
        with tempfile.TemporaryDirectory(prefix='eb-v22-review-readback-') as tmp:
            p = pathlib.Path(tmp); g['OUT'] = p
            (p / 'COMPILED50.json').write_text(json.dumps({'records': [c]}))
            runs = [] if kind == 'missing_all_run_records' else [
                {'household_id': c['household_id'], 'round_index': c['round_index'],
                 'variant': c['variant'], 'arm': side, 'warnings':
                 {'psychrometric_domain': False, 'DX_airflow_domain': False, 'AHRI_curve_domain': False}}
                for side in ('A', 'B')]
            (p / 'EP_all_REVIEW.json').write_text(json.dumps({'records': runs}))
            error = None
            try:
                with contextlib.redirect_stdout(io.StringIO()): fn('all', 1)
            except Exception as e: error = repr(e)
            report = read(p / 'READBACK_all_REVIEW.json') if (p / 'READBACK_all_REVIEW.json').exists() else None
            probes.append({'kind': kind, 'rejected': error is not None, 'error': error,
                           'report': report, 'synthetic_isolated_copy': True, 'EP_runs': 0})
    return probes

def main():
    if sys.platform != 'linux': raise RuntimeError('Review checks run on school Linux')
    ap = argparse.ArgumentParser(); ap.add_argument('--production', required=True)
    ap.add_argument('--output', required=True); a = ap.parse_args()
    prod = pathlib.Path(a.production).resolve(); out = pathlib.Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True); sys.path.insert(0, str(prod / 'code'))
    def save(n, d):
        (out / n).write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')
    save('SERVER_REPORT_SNAPSHOT.json', snapshot(prod))
    fresh = bindings(prod); save('FRESH_BINDING_REVIEW.json', fresh)
    print('FRESH_BINDINGS', json.dumps(fresh, ensure_ascii=False), flush=True)
    signature = signature_probe(prod, out); save('SIGNATURE_MUTATION_CONTROL.json', signature)
    print('SIGNATURE_CONTROL', json.dumps(signature), flush=True)
    probes = readback_probes(prod); save('READBACK_NEGATIVE_CONTROLS.json', probes)
    print('READBACK_CONTROLS', json.dumps(probes), flush=True)
    save('EXECUTION_RECEIPT.json', {'date_UTC': datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'production': str(prod), 'school_linux': True, 'review_code_sha256': sha(__file__),
         'EP_runs': 0, 'production_files_changed': False, 'human_answers_generated': 0})

if __name__ == '__main__': main()
