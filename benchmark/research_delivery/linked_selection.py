"""Apply a versioned judgment-link mapping to a frozen candidate bank.

No native actions, sources, dates or outcomes are regenerated. Legacy array
order is accepted only for the two inspected, archived generator versions.
The new collection records generation and selection provenance separately.
"""
import argparse
import copy
from pathlib import Path

from benchmark.ab_generation.common import read,save,sha,digest,seal
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.contract import config,code_hash
from benchmark.ab_generation.unified.selection import assign,concepts,goals


ORDERED_WRITER_CORES={
    '15da534dc25be0ad659d65bde27c6aabf74ae09be5fa9eacac378afc5fa593b4',
    '08e2be0b6b143266334c14a5efdb6d902e46ad0a1c909194790fa5b6e689b318',
}


def attach_links(row):
    from benchmark.ab_generation.unified.semantics import LINK_VERSION,linked_contexts
    result=copy.deepcopy(row)
    if result.get('judgment_context_version') is not None:
        if result['judgment_context_version']!=LINK_VERSION:
            raise ValueError('UNKNOWN_EXISTING_JUDGMENT_LINK_VERSION')
        linked_contexts(result)
        return result
    cs=result.get('components',[]);js=result.get('judgment_context',[])
    if len(cs)!=len(js):raise ValueError('LEGACY_COMPONENT_COUNT_MISMATCH')
    for c,j in zip(cs,js):
        if j.get('asset_id')!=c['asset_id']:
            raise ValueError('LEGACY_ORDERED_ASSET_MISMATCH')
        if any(k in j for k in ('component_id','service_need_id')):
            raise ValueError('UNVERSIONED_EXPLICIT_LINKS_REQUIRE_SEPARATE_REVIEW')
        j.update(component_id=c['id'],service_need_id=c.get('service_need_id'))
    result['judgment_context_version']=LINK_VERSION
    linked_contexts(result)
    stripped=copy.deepcopy(result);stripped.pop('judgment_context_version')
    for j in stripped['judgment_context']:
        j.pop('component_id');j.pop('service_need_id')
    if stripped!=row:raise ValueError('LINK_MAPPING_CHANGED_ORIGINAL_CASE')
    return result


def build(collection,out):
    from benchmark.ab_generation.unified.semantics import LINK_VERSION,LINKED_SIGNATURE_VERSION
    from benchmark.ab_generation.unified.materials import project
    from benchmark.family_generation.portrait_v3 import render
    collection,out=Path(collection).resolve(),Path(out).resolve()
    pre=read(collection/'PRE_GENERATION.json')
    if pre['code_sha256'] not in ORDERED_WRITER_CORES:
        raise ValueError('LEGACY_WRITER_NOT_REVIEWED_FOR_ORDERED_LINK_MIGRATION')
    if out==collection or out.is_relative_to(collection):
        raise ValueError('OUTPUT_INSIDE_ORIGINAL_COLLECTION')
    pins=dict(pre['source_sha256'])
    for filename in ('PRE_GENERATION.json','GENERATION.json','SELECTION.json'):
        pins[str(collection/filename)]=sha(collection/filename)
    if any(sha(p)!=h for p,h in pins.items()):raise ValueError('ORIGINAL_SOURCE_CHANGED')
    roster=[]
    for p in pre['source_sha256']:
        record=read(p)
        if isinstance(record,dict) and record.get('schema')=='eb.unified.inputs.v1':
            roster=copy.deepcopy(record['records'])
            for item in roster:
                for key in ('context_path','portrait_path'):
                    if item.get(key) and not Path(item[key]).is_absolute():
                        item[key]=str((Path(p).parent/item[key]).resolve())
            break
    if not roster:raise ValueError('ORIGINAL_DATE_ROSTER_NOT_FOUND')
    generation=read(collection/'GENERATION.json')
    if {(r['household_id'],r['date']) for r in roster}!={(r['household_id'],r['date']) for r in generation}:
        raise ValueError('GENERATION_ROSTER_MISMATCH')
    frozen_core=code_hash();cfg=config({**pre['configuration'],'method_revision':'delivery_v2_9'})
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(original_collection=str(collection),generation_code_sha256=pre['code_sha256'],
        selection_code_sha256=frozen_core,helper_sha256=sha(__file__),
        original_configuration=pre['configuration'],selection_configuration=cfg,
        explicit_link_version=LINK_VERSION,signature_version=LINKED_SIGNATURE_VERSION,
        old_writer_order_reviewed=True,native_generation_repeated=False,
        prior_case_ids_preserved=True,source_pins=pins,physical_runs=0,online_changed=False)
    save(out/'LINK_MAPPING_PROTOCOL.json',protocol)
    rows=[];old_rows=[];mapping=[]
    for slot in generation:
        source=collection/slot['path'];pins[str(source)]=sha(source)
        data=read(source);original=data.get('rows',[])
        converted=[attach_links(r) for r in original]
        old_other=digest({k:v for k,v in data.items() if k!='rows'})
        data['rows']=converted
        target=out/slot['path']
        if not target.is_relative_to(out):raise ValueError('UNEXPECTED_LEGACY_CATALOGUE_PATH')
        save(target,data)
        if digest({k:v for k,v in data.items() if k!='rows'})!=old_other:
            raise ValueError('NATIVE_GENERATION_FIELDS_CHANGED')
        if slot['status']=='candidate_catalogue' and not slot['independent_engineering_errors']:
            rows.extend(converted);old_rows.extend(original)
        mapping.append(dict(path=slot['path'],rows=len(original),old_sha256=sha(source),new_sha256=sha(target),
            non_row_fields_sha256=old_other,old_rows_sha256=digest(original),new_rows_sha256=digest(converted)))
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('DUPLICATE_CASE_ID')
    old_views=[concepts(r) for r in old_rows];views=[concepts(r) for r in rows]
    unchanged=all(all(a[k]==b[k] for k in ('tokens','families','composition','action')) for a,b in zip(old_views,views))
    if not unchanged or goals(old_rows,old_views)!=goals(rows,views):
        raise ValueError('LINK_MAPPING_CHANGED_COVERAGE_TARGETS_OR_ACTIONS')
    save(out/'LINK_MAPPING.json',mapping)
    save(out/'CANDIDATE_ROWS.json.gz',rows)
    selection=assign(rows,cfg);save(out/'SELECTION.json',selection)
    selected=set(selection['selected_ids']);bydate={}
    for row in rows:
        if row['id'] in selected:bydate[(row['household_id'],row['date'])]=row
    materials=[]
    for item in roster:
        row=bydate.get((item['household_id'],item['date']))
        if row is None:continue
        c=read(item['context_path']);profile=read(item['portrait_path']) if item.get('portrait_path') else None
        b=apply(c['A'],row['patches'])
        materials.append(dict(household_id=item['household_id'],date=item['date'],id=row['id'],
            A=c['A'],B=b,household_profile=profile,proposal=row,
            participant_family_text=render(profile) if profile else None,
            binding=dict(full_A_sha256=digest(c['A']),full_B_sha256=digest(b),context_sha256=digest(c),portrait_sha256=digest(profile)),
            presentation='proposal_before_outcomes;not_executed;confirmation_required',
            physical_outcomes=None,human_acceptance=None,human_score=None,human_reason=None,
            physical_status='not_computed;old_results_not_reused',questionnaire_context=project(c,profile,row,b)))
    save(out/'MATERIALS.json.gz',materials);save(out/'GENERATION.json',generation)
    # code_sha256 continues to identify the original native generator. The
    # selector/mapping provenance is separate, never relabelled as a new run.
    derived={**pre,'post_generation_mapping':dict(protocol='LINK_MAPPING_PROTOCOL.json',
        selector_code_sha256=frozen_core,configuration=cfg,old_case_ids_preserved=True)}
    save(out/'PRE_GENERATION.json',derived)
    old_selection=read(collection/'SELECTION.json')
    old_bydate={(r['household_id'],r['date']):r['id'] for r in old_rows if r['id'] in set(old_selection['selected_ids'])}
    changed=[dict(household_id=h,date=d,old=old_bydate.get((h,d)),new=row['id'])
             for (h,d),row in bydate.items() if old_bydate.get((h,d))!=row['id']]
    report=dict(given_slots=len(roster),eligible_candidates=len(rows),selected=len(materials),
        unselected_slots=[dict(household_id=r['household_id'],date=r['date']) for r in roster if (r['household_id'],r['date']) not in bydate],
        changed_selected_dates=changed,coverage_targets_weights_and_actions_unchanged=True,
        native_generation_repeated=False,new_acceptance_labels=False,physical_runs=0,
        generation_code_sha256=pre['code_sha256'],selector_code_sha256=frozen_core,
        signature_version=LINKED_SIGNATURE_VERSION,source_files_unchanged=True)
    if code_hash()!=frozen_core or any(sha(p)!=h for p,h in pins.items()):
        raise ValueError('SOURCE_CHANGED_DURING_LINKED_SELECTION')
    save(out/'SOURCE_PINS.json',pins);save(out/'REPORT.json',report)
    seal(out,dict(schema='eb.frozen_catalogue_linked_selection.v1',physical_runs=0,
        original_generation_code_sha256=pre['code_sha256'],selection_code_sha256=frozen_core))
    return {k:v for k,v in report.items() if k not in ('changed_selected_dates','unselected_slots')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(build(a.collection,a.out))
