"""Content-addressed original-50 collection release; bounded case cache."""
import collections
import hashlib
import json
import threading
from pathlib import Path

UI_VERSION='eb.questionnaire50.collection.v69'
CONTRACT_VERSION='eb.required_role_response.v69'
PREFIX='/household50-current'


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):return hashlib.sha256(encoded(value)).hexdigest()


class Release:
    def __init__(self,path,verify_code=True):
        self.root=Path(path).resolve();m=json.loads((self.root/'FORMAL_RELEASE.json').read_text())
        self.signature=digest({k:v for k,v in m.items()if k!='release_sha256'})
        assert self.signature==m['release_sha256']
        assert m['schema'] in ('eb.reference_benchmark.release.v1','eb.reference_benchmark.release.v2')
        if m['schema'].endswith('.v1'):
            assert m['source_case_bytes_modified'] is False and m['new_EP_runs']==0
        else:
            assert m['frozen_A_B_commands_modified'] is False and m['all_source_cases_retained'] is True
            assert m['collection_condition']=='role_judgment_with_version_bound_physics'
            assert 0<m['new_EP_runs']<=2*m['cases']
            assert sum(m['physical_statuses'].values())==m['cases']
        assert m['ui_revision']==UI_VERSION and m['response_contract']==CONTRACT_VERSION
        assert 60<=m['assignment_lease_seconds']<=86400
        self.manifest=m
        for name in m['files']:self.file(name)
        if verify_code:
            for name,h in m['implementation_files'].items():
                assert hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()==h, name
        self.index=json.loads(self.file('INDEX50.json'))
        self.models=json.loads(self.file('DISPLAY_MODELS50.json'))
        self.answer_instructions=json.loads(self.file('ANSWER_INSTRUCTIONS.json'))
        self.households=self.index['households'];self.records={r['case_id']:r for r in self.index['cases']}
        self.by_path={r['path']:r for r in self.records.values()}
        assert len(set(self.households))==len(self.households)==m['households']
        assert len(self.records)==m['cases'] and set(self.records)==set(self.models)
        counts=collections.Counter(r['household_id']for r in self.records.values())
        assert set(counts)==set(self.households) and set(counts.values())=={m['questions_per_household']}
        self.questions_per_household=m['questions_per_household']
        self.lock=threading.RLock();self.cache=collections.OrderedDict()

    def file(self,name):
        expected=self.manifest['files'].get(name)
        path=self.root/name
        if not expected or path.is_symlink()or not path.resolve().is_relative_to(self.root):raise FileNotFoundError(name)
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise RuntimeError('发布内容发生变化，暂时停止采集。')
        return raw

    def case(self,case_id,household):
        row=self.records.get(case_id)
        if not row or row['household_id']!=household:raise PermissionError('此题不属于当前分配的家庭。')
        with self.lock:
            if case_id not in self.cache:
                raw=self.file('public/'+row['path'])
                if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise RuntimeError('案例签名不一致。')
                value=json.loads(raw)
                if self.manifest['schema'].endswith('.v2'):
                    c=value;review=c['physical_review']
                    assert c['outcome_status']==review['status']
                    assert review['source_frozen_pair_sha256']==c['bindings']['source_pair_sha256']
                    assert c['bindings']['label_condition']==self.manifest['collection_condition']
                    if review['status']=='computed':
                        assert c['impact']==review['actual_outcomes'] and c['VPP_results']==review['actual_outcomes']['events']
                    else:assert c['impact'] is None and c['VPP_results'] is None
                self.cache[case_id]=value
                while len(self.cache)>4:self.cache.popitem(last=False)
            else:self.cache.move_to_end(case_id)
            return row,self.cache[case_id]

    def actor_index(self,household,resume_date=None):
        if household not in self.households:raise PermissionError('家庭不属于当前版本。')
        return {**self.index,'release_sha256':self.signature,'households':[household],
                'profiles_sha256':{household:self.index['profiles_sha256'][household]},
                'cases':[r for r in self.records.values()if r['household_id']==household],
                'resume_date':resume_date}
