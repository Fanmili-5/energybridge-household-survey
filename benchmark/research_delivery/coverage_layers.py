"""Independent accounting of semantic cells and literal numeric commands.

The numeric Cartesian universe is a syntactic upper bound, not a proven
conditional-feasibility denominator. Count it exactly without materializing
its products. Only independently checked complete proposals supply witnesses.
No generator admission/relevance predicate or oracle proof is imported.
"""
import itertools
import math
from collections import defaultdict

from benchmark.ab_generation.common import digest
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.independent import audit
from .causal_audit import check_case


def literal_domains(catalogue, context):
    by_unit=defaultdict(set); metadata={}; identities={}
    for group in catalogue.get('native_domains',[])+[catalogue.get('support_native_domain',[])]:
        for item in group:
            if not item:continue
            unit=item['unit']; identity=(item['asset_id'],item.get('service_need_id'))
            if unit in identities and identities[unit]!=identity:
                raise ValueError('LITERAL_UNIT_CHANGES_SERVICE_IDENTITY')
            identities[unit]=identity;by_unit[unit].add(item['id'])
            metadata[unit]=dict(asset_id=identity[0],need_id=identity[1],family=item['family'])
    result=[]
    for unit in sorted(by_unit):
        meta=metadata[unit];nid=meta['need_id']
        resources={'asset:'+meta['asset_id']}
        for operation in context['A']['operations']:
            if nid and operation['need_id']==nid:
                resources.update(('person:'+operation['operator_id'],'room:'+operation['room_id']))
        result.append(dict(unit=unit,ids=by_unit[unit],resources=resources,**meta))
    return result


def axes_for(domains):
    """Audit singletons too; this does not redefine IPOG's interaction target."""
    for strength in (1,2,3):
        for axes in itertools.combinations(range(len(domains)),strength):
            if strength<3 or any(domains[i]['resources']&domains[j]['resources']
                                 for i,j in itertools.combinations(axes,2)):
                yield axes


def count_numeric(domains, assignments, selected_assignments):
    records=[];totals=defaultdict(lambda:dict(syntactic_upper_bound=0,known_feasible=0,selected=0))
    for axes in axes_for(domains):
        size=math.prod(1+len(domains[i]['ids']) for i in axes)
        witnesses={tuple(row[i] for i in axes) for row in assignments}
        chosen={tuple(row[i] for i in axes) for row in selected_assignments}
        if not chosen<=witnesses:raise ValueError('SELECTED_NUMERIC_TARGET_LACKS_CHECKED_WITNESS')
        record=dict(units=[domains[i]['unit'] for i in axes],strength=len(axes),
                    syntactic_upper_bound=size,known_feasible=len(witnesses),selected=len(chosen),
                    feasibility_unclassified=size-len(witnesses),
                    witness_projection_sha256=digest(sorted(witnesses)),
                    selected_projection_sha256=digest(sorted(chosen)))
        records.append(record)
        for name in ('syntactic_upper_bound','known_feasible','selected'):
            totals[len(axes)][name]+=record[name]
    for record in totals.values():
        size,f,s=(record[name] for name in ('syntactic_upper_bound','known_feasible','selected'))
        record.update(feasibility_unclassified=size-f,
            selected_coverage_bounds=dict(lower=s/size if size else None,upper=s/f if f else None))
    return dict(by_strength=dict(totals),groups=records,
        scope='literal_command_singletons_pairs_and_shared_resource_triples;includes_support_units_and_no_change',
        feasibility_denominator_exact=False,infeasible_targets_subtracted=0,
        numeric_cartesian_counts_exact=True,integer_reader_requires_arbitrary_precision=True,
        warning='Upper universe includes unknown and potentially impossible combinations. Bounds are conservative; not full control-space coverage.')


def analyse(catalogue,context,selected_ids=()):
    domains=literal_domains(catalogue,context);positions={r['unit']:i for i,r in enumerate(domains)}
    selected_ids=set(selected_ids);assignments=[];chosen=[];case_checks=[];causal_records=[]
    for row in catalogue.get('rows',[]):
        assignment=['']*len(domains);errors=[]
        for component in row['components']:
            i=positions.get(component['unit'])
            if i is None or component['id'] not in domains[i]['ids']:
                errors.append('COMPONENT_OUTSIDE_COMPLETE_NATIVE_DOMAIN');continue
            if assignment[i]:errors.append('MULTIPLE_ALTERNATIVES_FOR_SAME_UNIT')
            assignment[i]=component['id']
        B=apply(context['A'],row['patches'])
        errors+=audit(context,context['A'],B)
        causal=check_case(context,row,context['A'],B);causal_records+=causal
        errors+=['ACTION_WITHOUT_INDEPENDENT_CAUSAL_WITNESS:'+r['component_id'] for r in causal if not r['passed']]
        if any(row.get(k) is not None for k in ('human_acceptance','human_score','human_reason','actual_outcomes')):
            errors.append('ANSWER_OR_ACTUAL_OUTCOME_PRESENT')
        case_checks.append(dict(case_id=row['id'],selected=row['id'] in selected_ids,errors=sorted(set(errors))))
        if errors:continue
        assignments.append(tuple(assignment))
        if row['id'] in selected_ids:chosen.append(tuple(assignment))
    numeric=count_numeric(domains,assignments,chosen)
    numeric.update(domain_units=[{k:v for k,v in d.items() if k not in ('ids','resources')}|
        dict(literal_changed_commands=len(d['ids']),including_no_change=len(d['ids'])+1,
             literal_id_set_sha256=digest(sorted(d['ids']))) for d in domains],
        complete_candidate_assignments=len(set(assignments)),complete_selected_assignments=len(set(chosen)))
    # These are the actual IPOG factor cells, not the literal command values.
    semantic=[]
    for values,cells in zip(catalogue.get('native_domains',[]),catalogue.get('factors',[])):
        ownership={};unit=next(v['unit'] for v in values if v)
        for cell in cells:
            for index in cell['ids']:
                if index in ownership:raise ValueError('NATIVE_INDEX_IN_MULTIPLE_SEMANTIC_CELLS')
                ownership[index]=cell['label']
        if set(ownership)!=set(range(len(values))):raise ValueError('SEMANTIC_PARTITION_OMITS_NATIVE_VALUE')
        semantic.append(dict(unit=unit,cells=len(cells),native_values=len(values),
            partition_sha256=digest(sorted((v['id'] if v else '',ownership[i]) for i,v in enumerate(values)))))
    return dict(schema='eb.coverage_layers.v1',numeric=numeric,semantic_partition=semantic,
        all_candidate_checks=dict(cases=len(case_checks),components=len(causal_records),
            passed=all(not c['errors'] for c in case_checks),cases_with_errors=[c for c in case_checks if c['errors']],
            records=case_checks,causal_records=causal_records),
        candidate_generation_or_selection_changed=False,physical_validity_claimed=False)
