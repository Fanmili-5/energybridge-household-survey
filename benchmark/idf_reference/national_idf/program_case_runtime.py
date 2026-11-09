"""Execute CASE program starts with existing EB task state and native coupling."""
import csv
from pathlib import Path
import sys
import time
import traceback

from .case_commands import CaseTimeline, CommandClock
from .common import ROOT, read, require, save, sha, verify
from .idf import Fields, objects
from .program_resources import DEVICES, bind_program_domain, plan_resources
from .source_adapter import source_file
from .thermal_case_runtime import load_module


class WhitegoodsEbCommands:
    """Frozen profiles + CASE starts. No powers or phase fractions from life."""
    def __init__(self, suite_class, timeline, plan, rows, fields, selected):
        bind_program_domain(plan, timeline.domain)
        self.timeline, self.plan, self.selected = timeline, plan, tuple(selected)
        config = {name: {'present': False} for name in (*DEVICES, 'water_heater', 'ev', 'refrigerator')}
        for device in self.selected:
            program = plan['values']['programs'][device]
            equipment = next(row for row in objects(rows, 'ElectricEquipment')
                             if row[1] == plan['definition']['programs'][device]['equipment'])
            config[device] = {'present': True, 'power_kw': float(fields.get(equipment, 'design_level')) / 1000,
                'duration_h': program['duration_min'] / 60, 'earliest_h': 0, 'latest_h': 48}
        self.suite = suite_class(config, timeline.days, [], explicit_only=True)
        self.active, self.starts, self.next_index = {}, [], 0

    def step(self, frame):
        require(frame == self.timeline.frame(self.next_index), 'PROGRAM_CASE_FRAME_ORDER_OR_CONTENT')
        for task in frame['program_starts']:
            device = task['device']
            require(device in self.selected, 'PROGRAM_CASE_UNSELECTED_DEVICE')
            require(self.suite.shift_appliance(device, frame['day_index'], frame['elapsed_start_min'] / 60),
                    'PROGRAM_CASE_EB_TASK_REJECTED', device)
            self.active[device] = self.next_index
            self.starts.append(task)
        gates = self.suite.step(frame['elapsed_start_min'] / 60, frame['duration_min'] / 60)
        result = {}
        for device in self.selected:
            program = self.plan['values']['programs'][device]
            index = self.next_index - self.active[device] if device in self.active else -1
            result[device] = {name: values[index] if 0 <= index < len(values) else 0.0
                              for name, values in program['channels'].items()}
            require(not any(result[device].values()) or gates[device] > 0, 'PROGRAM_CASE_EB_GATE_TRUNCATION', device)
        self.next_index += 1
        return result

    def report(self):
        return {'executed_steps': self.next_index, 'expected_steps': self.timeline.steps,
            'starts': self.starts, 'EB_results': {key: self.suite._shiftable[key].all_results() for key in self.selected},
            'service_unit': 'published_source_resource_window', 'cleaning_or_dryness_verified': False,
            'new_electricity_added_by_Python': False, 'formal_admitted': False, 'whole_CASE_executed': False}


def run_reference_case(compiled, out, *, mode, root=ROOT):
    require(mode == 'engineering_reference', 'PROGRAM_REFERENCE_MODE_REQUIRED')
    compiled, out = Path(compiled).absolute(), Path(out).absolute()
    receipt = verify(compiled)
    if receipt.get('schema') == 'national_idf.compiled_six_reference_CASE.v1':
        from .joint_case_runtime import run_joint_case
        return run_joint_case(compiled, out, mode=mode, root=root)
    require(receipt['schema'] == 'national_idf.compiled_program_reference_CASE.v1'
            and receipt['execution_mode'] == mode and not receipt['formal_admitted'], 'PROGRAM_REFERENCE_COMPILED_SCOPE')
    spec = read(compiled / 'FIXTURE.json')
    case, domain = read(compiled / 'CASE.json'), read(compiled / 'RUNTIME_SUPPORT_DOMAIN.json')
    timeline = CaseTimeline(case, domain, root=root)
    from .idf import parse
    rows = parse((compiled / 'in.idf').read_text())
    if spec.get('whole_plug_load_replacement'):
        from .load_replacement import apply as replace_plugs
        source_rows = parse(source_file(spec['model'], root).read_text())
        expected, replacement, dependencies = replace_plugs(source_rows, spec['whole_plug_load_replacement'], spec['engine_schema'], root=root)
        require(expected == rows and replacement == read(compiled / 'LOAD_REPLACEMENT.json'),
                'PROGRAM_CASE_LOAD_REPLACEMENT_NOT_REPRODUCIBLE')
        for dep in dependencies:
            require(sha(compiled / dep['output_path']) == dep['source']['sha256'], 'PROGRAM_CASE_REPLACEMENT_DEPENDENCY_CHANGED')
    if spec.get('installation_pack'):
        from .installation import installation_receipt, plan_installation
        source_rows = parse(source_file(spec['model'], root).read_text())
        installation = plan_installation(spec['installation_pack'], spec['model'], source_rows,
                                         source_rows, spec['engine_schema'], root=root)
        require(installation['ready'] and installation['new_model_rows'] == rows
                and installation_receipt(installation) == read(compiled / 'INSTALLATION.json'),
                'PROGRAM_CASE_INSTALLATION_NOT_REPRODUCIBLE')
    plan = plan_resources(rows, spec['engine_schema'], spec['resource_pack'], root=root)
    require(read(compiled / 'program_resources/PACK.json') == plan['definition']
            and read(compiled / 'program_resources/PROFILE.json') == plan['values'], 'PROGRAM_CASE_PACKAGED_RESOURCE_CHANGED')
    for ref in spec['official_engine_files'] + list(spec['EB_modules'].values()):
        source_file(ref, root)
    engine = next(source_file(ref, root).parent for ref in spec['official_engine_files']
                  if Path(ref['path']).name == 'energyplus')
    require(source_file(spec['engine_schema'], root).parent == engine, 'PROGRAM_CASE_ENGINE_SCHEMA')
    fields = Fields(engine / 'Energy+.schema.epJSON')
    suite_module = load_module(source_file(spec['EB_modules']['suite'], root), 'program_CASE_EB_suite')
    binding_module = load_module(source_file(spec['EB_modules']['binding'], root), 'program_CASE_EB_binding')
    commands = WhitegoodsEbCommands(suite_module.ApplianceSuite, timeline, plan, rows, fields, spec['applied_devices'])
    mapping = spec['EB_mapping']
    binding = binding_module.ApplianceBinding((compiled / 'in.idf').read_text(), engine / 'Energy+.schema.epJSON',
                                             commands.suite, mapping)
    require(not out.exists(), 'OUTPUT_EXISTS', str(out))
    out.mkdir(parents=True)
    save(out / 'IMPLEMENTATION.json', {name: sha(root / name) for name in
        ('national_idf/program_resources.py', 'national_idf/program_case_runtime.py',
         'national_idf/case_commands.py', 'national_idf/request_support.py', 'national_idf/installation.py')})
    if spec.get('whole_plug_load_replacement'):
        identity = read(out / 'IMPLEMENTATION.json')
        identity['national_idf/load_replacement.py'] = sha(root / 'national_idf/load_replacement.py')
        save(out / 'IMPLEMENTATION.json', identity)
    sys.path.insert(0, str(engine))
    from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI(); state = api.state_manager.new_state()
    binding.request_outputs(api.exchange, state)
    clock, trace, handles = CommandClock(timeline), [], {}
    progress = {'zone_steps': 0, 'writes': 0, 'initialized': False, 'errors': []}

    def active(s):
        return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s) == 3

    def before(s):
        if not active(s):
            return
        try:
            if not progress['initialized']:
                binding.initialize(api.exchange, s)
                for device in spec['applied_devices']:
                    definition = plan['definition']['programs'][device]
                    for name in definition['schedules']:
                        handle = binding.handles[device] if name == definition['electric_schedule'] else api.exchange.get_actuator_handle(
                            s, 'Schedule:File', 'Schedule Value', name)
                        require(handle >= 0, 'PROGRAM_CASE_ACTUATOR_MISSING', name)
                        handles[name] = handle
                progress['initialized'] = True
            frame = clock.take_exchange(api.exchange, s)
            values = commands.step(frame)
            for device, channels in values.items():
                for name, value in channels.items():
                    api.exchange.set_actuator_value(s, handles[name], value)
                    trace.append({'frame_index': frame['frame_index'], 'device': device, 'schedule': name, 'value': value})
                    progress['writes'] += 1
        except Exception:
            progress['errors'].append(traceback.format_exc()); api.runtime.stop_simulation(s)

    def after(s):
        if active(s):
            progress['zone_steps'] += 1

    api.runtime.callback_begin_zone_timestep_before_init_heat_balance(state, before)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, after)
    start = time.monotonic()
    try:
        code = api.runtime.run_energyplus(state, ['-w', str(compiled / 'weather.epw'), '-d', str(out / 'output'),
                                                str(compiled / 'in.idf')])
    finally:
        api.state_manager.delete_state(state)
    with (out / 'COMMANDS.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['frame_index', 'device', 'schedule', 'value'])
        writer.writeheader(); writer.writerows(trace)
    result = {'exit_code': code, 'wall_seconds': time.monotonic() - start, 'progress': progress,
        'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json'), 'CASE_input_sha256': timeline.input_sha256,
        'tasks': commands.report(), 'source_reference_context_only': True, 'source_EMS_unchanged': True,
        'applied_channels': spec['applied_devices'], 'other_source_channels_actuated': False,
        'formal_admitted': False, 'whole_CASE_executed': False}
    save(out / 'RUNTIME.json', result)
    require(code == 0 and not progress['errors'] and progress['zone_steps'] == timeline.steps,
            'PROGRAM_CASE_RUNTIME_FAILED', progress)
    return result
