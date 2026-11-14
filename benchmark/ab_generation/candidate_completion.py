"""Materialize missing predeclared root cells using the same frozen action grammar.

This ports the two bounded searches used by the historical native10000 recipe.
No energy outcomes, acceptance labels, or new device actions enter the search.
"""
import argparse,copy,hashlib,json,math
from collections import Counter,defaultdict
from pathlib import Path
from .cohort_coverage import load,write_gzip
from .common import digest
from .eb_alignment import bind_household,verify_native_target
from .generate_native import record_raw_cells
from .generate_cohort import save
from .model import apply
from .unified.candidates import prepare,catalogue_domains,request,Oracle

DEFAULT=dict(schema='eb.raw_cell_completion.config.v1',rows_per_unit=128,queries_per_row=64,
    oracle_deterministic_time=0.5,oracle_native_encoding_budget=30000,oracle_forward_node_budget=16384,
    attempts_per_country=3,attempts_per_cell=8)

def configuration(path=None):
    value=load(path) if path else {}
    if set(value)-set(DEFAULT):raise ValueError('UNKNOWN_COMPLETION_CONFIGURATION')
    c={**DEFAULT,**value}
    if c['schema']!=DEFAULT['schema']:raise ValueError('COMPLETION_CONFIGURATION_SCHEMA')
    for name in set(c)-{'schema','oracle_deterministic_time'}:
        if type(c[name]) is not int or c[name]<1:raise ValueError('INVALID_COMPLETION_BUDGET:'+name)
    t=c['oracle_deterministic_time']
    if type(t) not in (int,float) or not math.isfinite(t) or t<=0:raise ValueError('INVALID_COMPLETION_DETERMINISTIC_TIME')
    return c

def qualified(row):
    return not row.get('engineering_diagnostic') and not row.get('relevance_diagnostic')

class CompletionContext:
    def __init__(self,root,households,native_source):
        self.root=Path(root);self.households=Path(households);self.native=str(native_source)
        self.pre=load(self.root/'PRE_RUN.json');self.cfg=self.pre['configuration']
        raw=self.households.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.pre['source_sha256']:raise ValueError('COMPLETION_HOUSEHOLD_MANIFEST_CHANGED')
        self.cases=[json.loads(line) for line in raw.splitlines() if line.strip()]
        self.cases.sort(key=lambda c:(c['household']['country'],c['household']['role_id'],c['case_id']))
        self.status=load(self.root/'STATUS.json')['rows'];self.cache={}
        if len(self.cases)!=len(self.status):raise ValueError('COMPLETION_SOURCE_COUNT_CHANGED')
        for row in self.status:
            if digest(self.cases[row['index']])!=row['source_household_sha256']:raise ValueError('COMPLETION_SOURCE_ORDER_OR_CASE_CHANGED')
        self.target=verify_native_target(self.native)
    def context(self,index,date):
        key=(index,date)
        if key not in self.cache:
            baseline=load(self.root/str(index).zfill(4)/(date+'_A.json.gz'))
            bound=bind_household(baseline['context'],self.cases[index],self.pre['source_sha256'])
            bound['native_execution_contract']['native_target']=self.target
            bound=bind_household(bound,self.cases[index],self.pre['source_sha256'])
            c=prepare(bound,self.cfg);self.cache[key]=(c,catalogue_domains(c,self.cfg))
        return self.cache[key]
    def cell(self,index,date,key):
        c,g=self.context(index,date);family,label=json.loads(key)
        matches=[(i,d) for i,descs in enumerate(g['descriptors']) for d in descs if d['label']==label and any(r and r['family']==family for r in g['values'][i])]
        if len(matches)!=1:raise ValueError('DECLARED_RAW_CELL_NOT_REPRODUCED')
        return c,g,*matches[0]
    def append(self,index,date,key,g,row):
        if not row['native_execution']['passed']:raise ValueError('UNQUALIFIED_COMPLETION_WITNESS')
        record_raw_cells(dict(factors=g['descriptors'],native_domains=g['values'],rows=[row]))
        if key not in row['raw_root_cells']:raise ValueError('COMPLETION_WRONG_CELL')
        path=self.root/str(index).zfill(4)/'COVERAGE_EXTRA_CANDIDATES.json.gz'
        return append_witness(path,date,row)
    def verify_source(self):
        if hashlib.sha256(self.households.read_bytes()).hexdigest()!=self.pre['source_sha256']:raise ValueError('COMPLETION_SOURCE_CHANGED_DURING_SEARCH')

def append_witness(path,date,row):
    path=Path(path);extra=load(path) if path.exists() else []
    day=next((d for d in extra if d['date']==date),None)
    if day is None:day=dict(date=date,rows=[]);extra.append(day)
    if any(v['id']==row['id'] for v in day['rows']):return False
    day['rows'].append(row);write_gzip(path,extra);return True

def complete_roots(root,households,native_source,completion_config=None):
    ctx=CompletionContext(root,households,native_source);root=ctx.root
    effort=configuration(completion_config);search=copy.deepcopy(ctx.cfg)
    search.update({k:effort[k] for k in ('rows_per_unit','queries_per_row','oracle_deterministic_time','oracle_native_encoding_budget','oracle_forward_node_budget')})
    ledger=load(root/'COHORT_COVERAGE_LEDGER.json.gz')
    targets=[(role,cell) for role,cells in ledger.items() for cell in cells if not cell['pool_goal_met']]
    needed={(role,cell['key']):set(cell['raw_countries'])-set(cell['witness_countries']) for role,cell in targets}
    opportunities=defaultdict(list)
    for h in ctx.status:
        keys={k for k,countries in needed.items() if k[0]==h['role'] and h['country'] in countries}
        if not keys:continue
        for day in load(root/str(h['index']).zfill(4)/'CATALOGUES.json.gz'):
            for cell in day['declared_raw_root_cells']:
                k=(h['role'],cell['key'])
                if k in keys and cell['admissible_raw_alternatives']:
                    opportunities[k].append(dict(index=h['index'],date=day['date'],country=h['country'],factor=cell['factor']))
    logs=[];added=0
    for role,cell in targets:
        key=cell['key'];countries=set(cell['witness_countries']);attempts=[]
        for op in opportunities[(role,key)]:
            if len(countries)>=cell['target_countries']:break
            if op['country'] in countries or sum(a['country']==op['country'] for a in attempts)>=effort['attempts_per_country']:continue
            c,g,factor,desc=ctx.cell(op['index'],op['date'],key)
            eligible=[j for j in desc['ids'] if not g['values'][factor][j].get('_intrinsic_issues')]
            found=None;diagnostics=Counter()
            for j in eligible:
                row=request(c,[g['values'][factor][j]],ctx.cfg,None)
                if qualified(row):found=row;break
                diagnostics.update(row.get('issues',[]))
            answer=None
            if found is None:
                oracle=Oracle(c,g,search,None);answer=oracle({},native_required={factor:eligible})
                if answer[0]=='feasible':found=oracle.rows[answer[2]]
            attempts.append(dict(**op,singleton_alternatives=len(eligible),singletons_diagnostics=dict(diagnostics),oracle_answer=answer,found=found is not None))
            if found is not None:
                added+=ctx.append(op['index'],op['date'],key,g,found);countries.add(op['country'])
            if len(attempts)>=effort['attempts_per_cell']:break
        logs.append(dict(role=role,key=key,countries=sorted(countries),target=cell['target_countries'],attempts=attempts,goal_met=len(countries)>=cell['target_countries']))
        print(json.dumps(dict(phase='root_completion',done=len(logs),targets=len(targets),added=added)),flush=True)
    ctx.verify_source()
    result=dict(schema='eb.targeted_raw_cell_search.v2',configuration=search,completion_effort=effort,
        original_generation_configuration=ctx.cfg,source_sha256=ctx.pre['source_sha256'],domain_changed=False,
        outcomes_used=False,human_answers_used=False,unresolved_is_unknown=True,added=added,logs=logs,completed=True)
    save(root/'COVERAGE_TARGETED_SEARCH.json',result);return result

def complete_programme_dependencies(root,households,native_source):
    ctx=CompletionContext(root,households,native_source);root=ctx.root;logs=[];added=0
    for target in load(root/'COVERAGE_TARGETED_SEARCH.json')['logs']:
        if target['goal_met']:continue
        family,_=json.loads(target['key']);countries=set(target['countries'])
        if family not in ('washer','dryer'):
            logs.append(dict(key=target['key'],status='unresolved',reason='not_a_wash_dry_dependency_target'));continue
        for op in target['attempts']:
            if op['country'] in countries:continue
            c,g,factor,desc=ctx.cell(op['index'],op['date'],target['key'])
            candidates=[g['values'][factor][j] for j in desc['ids']]
            allraw=[row for values in g['values'] for row in values if row]+list(g['support_domain'])
            companions={row['id']:row for row in allraw if row['family'] in ('washer','dryer') and row['family']!=family}
            found=None;tried=0;issues=Counter()
            for primary in candidates:
                for support in companions.values():
                    plan=apply(c['A'],primary['patches']+support['patches']);times={t['need_id']:t for t in plan['tasks']}
                    if any(t.get('depends_on_need_id') and times[t['depends_on_need_id']]['end_min']>t['start_min'] for t in plan['tasks']):continue
                    tried+=1;row=request(c,[primary,support],ctx.cfg,None)
                    if qualified(row):found=row;break
                    issues.update(row.get('issues',[]))
                    if row.get('relevance_diagnostic'):issues['RELEVANCE_SUPPORT_NOT_WITNESSED']+=1
                if found is not None:break
            record=dict(index=op['index'],date=op['date'],country=op['country'],key=target['key'],
                raw_root_alternatives=len(candidates),existing_companion_alternatives=len(companions),
                literal_joint_trials=tried,issues=dict(issues),found=found is not None)
            if found is not None:
                added+=ctx.append(op['index'],op['date'],target['key'],g,found);countries.add(op['country'])
            logs.append(record)
    ctx.verify_source()
    result=dict(schema='eb.programme_dependency_completion.v1',outcomes_used=False,human_answers_used=False,
        action_domain_changed=False,unresolved_is_unknown=True,added=added,logs=logs,completed=True)
    save(root/'COVERAGE_PROGRAMME_COMPLETION.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['batch','households','native-source']:parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--phase',choices=['roots','programme'],required=True);parser.add_argument('--configuration',type=Path)
    a=parser.parse_args()
    result=complete_roots(a.batch,a.households,a.native_source,a.configuration) if a.phase=='roots' else complete_programme_dependencies(a.batch,a.households,a.native_source)
    print(json.dumps({k:v for k,v in result.items() if k not in {'logs','configuration','original_generation_configuration'}}))
if __name__=='__main__':main()
