"""Actual-output feature projection and label-blind mature R PAM diagnostics."""
import csv,copy,collections,os,subprocess,itertools,math
from common import *
from audit_pilot import FEATURE_GROUPS
from type_model import TYPES


def match(features,groups):
    # Numeric EB crosswalk uses explicit adapted instruction/service conditions.
    # The record never enters clustering;readability/type tags are excluded.
    base={'daytime_home_fraction':.08,'workday_departure_variation':0.,'temporary_cooling_delta':.5,
          'maximum_change_duration':1.,'allowed_reschedule_fraction':120/210,
          'cost_priority':1,'saving_explanation_required':1,'automatic_within_bounds':0,
          'same_day_confirmation':0,'protected_service_veto':0,'booked_protection_load':0,
          'mobility_priority_with_actual_trips':0}
    refs={t:copy.deepcopy(base)for t in TYPES}
    refs['B'].update(daytime_home_fraction=.9,temporary_cooling_delta=.25,allowed_reschedule_fraction=30/210,cost_priority=0,saving_explanation_required=0)
    refs['C'].update(daytime_home_fraction=.5,workday_departure_variation=1,allowed_reschedule_fraction=10/210,cost_priority=0,same_day_confirmation=1)
    refs['D'].update(temporary_cooling_delta=1,allowed_reschedule_fraction=180/210,automatic_within_bounds=1,saving_explanation_required=0)
    refs['E'].update(daytime_home_fraction=.9,temporary_cooling_delta=.25,allowed_reschedule_fraction=10/210,cost_priority=0,saving_explanation_required=0,protected_service_veto=1,booked_protection_load=1)
    refs['F'].update(allowed_reschedule_fraction=90/210,automatic_within_bounds=1,saving_explanation_required=0,mobility_priority_with_actual_trips=1)
    distances={t:sum(sum(abs(features[k]-refs[t][k])for k in names)/len(names)for names in groups.values())/len(groups)for t in TYPES}
    ordered=sorted(distances,key=distances.get)
    return {'nearest_reference':ordered[0],'distance':distances[ordered[0]],'second':ordered[1],
            'margin':distances[ordered[1]]-distances[ordered[0]],'all_distances':distances}


def main():
    school_guard();rows=read(OUT/'ACTUAL_FEATURES1000.json')['rows'];names=[k for group in FEATURE_GROUPS.values()for k in group]
    labels=[read(OUT/'worlds'/f'{r["household_id"]}.json')['eb_reference_type_assignment']for r in rows]
    root=BASE.parents[4]/'tools_v27' # overridden by explicit env to avoid host path assumptions
    root=Path(os.environ['EB_V27_TOOLS']);rhome=root/'r/usr/lib/R'
    env={**os.environ,'R_HOME':str(rhome),'R_SHARE_DIR':str(root/'r/usr/share/R/share'),
         'LD_LIBRARY_PATH':':'.join(str(x)for x in [rhome/'lib',root/'r/usr/lib/x86_64-linux-gnu',root/'r/usr/lib/x86_64-linux-gnu/blas',root/'r/usr/lib/x86_64-linux-gnu/lapack'])}
    directory=OUT/'development/clustering';directory.mkdir(parents=True,exist_ok=True)
    input_file=directory/'actual_numeric_features.csv'
    with input_file.open('w')as f:
        writer=csv.DictWriter(f,fieldnames=names);writer.writeheader();writer.writerows(r['features']for r in rows)
    # One original weighting and one preregistered doubled-schedule sensitivity.
    results={}
    for lane in ('equal_groups','schedule_double'):
        weights=[(2 if lane=='schedule_double'and group=='schedule'else 1)/len(columns)for group,columns in FEATURE_GROUPS.items()for k in columns]
        prefix=directory/lane;command=[str(rhome/'bin/exec/R'),'--slave','--no-save','--file='+str(OUT/'code/cluster_actual.R'),'--args',str(input_file),str(prefix),','.join(map(str,weights))]
        proc=subprocess.run(command,env=env,capture_output=True,text=True);(directory/(lane+'.log')).write_text(proc.stdout+proc.stderr)
        if proc.returncode:raise RuntimeError(proc.stderr)
        assignments=list(csv.DictReader(Path(str(prefix)+'_assignments.csv').open()));quality=list(csv.DictReader(Path(str(prefix)+'_quality.csv').open()))
        clusters=[int(x['k6'])for x in assignments];cont=collections.defaultdict(collections.Counter)
        for k,t in zip(clusters,labels):cont[k][t]+=1
        best=max(itertools.permutations(TYPES),key=lambda order:sum(cont[k][order[k-1]]for k in range(1,7)))
        correct=sum(cont[k][best[k-1]]for k in range(1,7))
        results[lane]={'contingency_after_blind_clustering':{str(k):dict(v)for k,v in cont.items()},
            'best_one_to_one_overlap_descriptive_only':correct/len(rows),'k_diagnostics':quality,
            'cluster_labels_used_as_features':False,'source_actor_counts_used':False}
    mapping=[{'household_id':r['household_id'],**match(r['features'],FEATURE_GROUPS)}for r in rows]
    agree=sum(a['nearest_reference']==t for a,t in zip(mapping,labels))
    ambiguous=[a for a in mapping if a['margin']<.025]
    # Semantic coverage is audited independently;PAM overlap is reported,not
    # promoted to empirical role validity or forced to 100% by reseeding.
    report={'schema':'eb.actual_type_coverage_pilot.v27','source':'actual dated worlds/services/explicit policies',
        'households':len(rows),'semantic_input_gate':read(OUT/'INPUT_AUDIT.json')['status'],
        'actual_type_counts':dict(collections.Counter(labels)),
        'reference_nearest_agreement_descriptive':agree/len(rows),'reference_ambiguity_threshold_design':.025,
        'ambiguous':ambiguous,'reference_mapping':mapping,'clustering':results,
        'feature_scaling':'fixed0..1 via excluded daisy anchors;manual L1 crosscheck within1e-12',
        'protocol_seeds':{'matching_world_seed':2026101401,'R_PAM':'deterministic BUILD/SWAP;no random restarts'},
        'human_validity_proven':False,'national_type_prevalence_estimated':False,'full1000_EP_allowed':False,
        'accepted_for_frozen1000_reference_production':read(OUT/'INPUT_AUDIT.json')['status']=='pass'and agree==len(rows) and not ambiguous}
    save(OUT/'CLUSTER_COVERAGE1000_REVIEW.json',report)
    print({k:v for k,v in report.items()if k not in ('reference_mapping','ambiguous')},flush=True)
    if not report['accepted_for_frozen1000_reference_production']:raise RuntimeError('source semantic/reference coverage needs review')


if __name__=='__main__':main()
