"""Lossless program recipes: constrain coordinates before literal expansion.

The finite grammar is unchanged. A recipe stores a shared machine template and
two handling coordinates; literal rows are expanded only on demand. Serialized
recipes plus templates reproduce the complete domain, including excluded cells.
"""
import copy
from ..common import digest


def prepare_template(template):
    """Compute invariant metadata once, without aliasing per-recipe fields."""
    return dict(meta={k: v for k, v in template.items()
                     if k not in ('patches', 'profiles', 'magnitude', 'construction_issues')},
                patches_sha256=digest(template['patches']))


class ProgramRecipe(dict):
    def __init__(self, template, load, unload, load_min, unload_min, prepared=None):
        self.template = template
        self.load = load
        self.unload = unload
        self.load_min = load_min
        self.unload_min = unload_min
        prepared = prepared if prepared is not None else prepare_template(template)
        meta = copy.deepcopy(prepared['meta'])
        shifts = [abs(load_min-load['start_min']), abs(unload_min-unload['start_min'])]
        magnitude = {**template['magnitude'], 'manual_total_shift_min': sum(shifts),
                     'manual_max_shift_min': max(shifts),
                     'service_slack_min': template['_deadline'] - unload_min -
                     (unload['end_min']-unload['start_min'])}
        magnitude['dose_coordinate'] = max([magnitude['machine_shift_min']] + shifts)
        meta.update(mechanism='retimed_handling_full_grid', magnitude=magnitude,
                    construction_issues=[], recipe=dict(template=prepared['patches_sha256'],
                    load_min=load_min, unload_min=unload_min))
        super().__init__(meta)

    def __getitem__(self, key):
        if key == 'profiles':
            return self.template['profiles']
        if key == 'patches':
            tasks = next(p for p in self.template['patches'] if p.get('collection') == 'tasks')
            ops = [{**o, 'start_min': t, 'end_min': t + o['end_min']-o['start_min']}
                   for o, t in ((self.load,self.load_min),(self.unload,self.unload_min))]
            return [tasks,dict(type='rows',collection='operations',identity='operation_id',rows=ops)]
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self[key] if key in ('patches', 'profiles') or key in self else default

    def hold(self):
        return (self.load_min, self.unload_min + self.unload['end_min']-
                self.unload['start_min'], self.load_min+self.load['end_min']-self.load['start_min'])


def export(values):
    templates = {}
    rows = []
    for group in values:
        encoded = []
        for r in group:
            if isinstance(r, ProgramRecipe):
                key = r['recipe']['template']
                templates[key] = dict(template=r.template, load=r.load, unload=r.unload)
                encoded.append(dict(r))
            else:
                encoded.append(r)
        rows.append(encoded)
    return rows, templates


def expand(encoded, templates):
    if not encoded or 'recipe' not in encoded:
        return encoded
    recipe = encoded['recipe']; t = templates[recipe['template']]
    result = ProgramRecipe(t['template'],t['load'],t['unload'],recipe['load_min'],recipe['unload_min'])
    result.update(encoded)
    return {**dict(result), 'patches': result['patches'], 'profiles': result['profiles']}


def excluded_requests(record):
    """Recover every excluded literal request; never silently discard failures."""
    for a in record['all_loads']:
        for z in record['all_unloads']:
            if a in record['allowed_loads'] and z in record['allowed_unloads']:
                continue
            r=ProgramRecipe(record['template'],record['load'],record['unload'],a,z)
            yield {**dict(r),'patches':r['patches'],'profiles':r['profiles']}
