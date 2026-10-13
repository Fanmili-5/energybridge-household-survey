"""Source-household fold diagnostic and structural holdout manifest.

This is internal coarsened-source validation. Neither synthetic projections,
national joint behavior nor human benchmark performance are validated by it.
"""
import collections,math
from common import *

def independent(features):
    a,b,c,d=features[5:9];counts=collections.Counter()
    for ego in range(a*5,b*5+5):
        for member in range(c*5,d*5+5):counts[(member-ego)//5]+=1
    total=sum(counts.values());return {k:v/total for k,v in counts.items()}

def main():
    school_guard();source=read(OUT/'JOINT_AGE_FOLD_AGGREGATES.json')['records'];results=[]
    for strength in (1,5,20):
        folds=[]
        for fold in range(5):
            trained=collections.defaultdict(lambda:collections.Counter());sample_counts=collections.Counter()
            for r in source:
                if r['fold']==fold:continue
                k=tuple(r['features']);trained[k][r['gap_bin5']]+=r['weight'];sample_counts[k]+=r['source_count']
            log_base=log_joint=weight=0.;count=known=0
            for r in source:
                if r['fold']!=fold:continue
                k=tuple(r['features']);base=independent(k);b=base.get(r['gap_bin5'],0.)
                assert b>0,'target outside coarse source support'
                n=sample_counts[k];learned=trained[k];mix=n/(n+strength)
                prob=(1-mix)*b+mix*learned.get(r['gap_bin5'],0.)/sum(learned.values()) if n else b
                log_base-=r['weight']*math.log(b);log_joint-=r['weight']*math.log(prob);weight+=r['weight'];count+=r['source_count'];known+=r['source_count'] if n else 0
            folds.append({'fold':fold,'heldout_pair_count':count,'direct_context_seen_in_training_count':known,
                'weighted_independent_gap_NLL':log_base/weight,'weighted_joint_gap_NLL':log_joint/weight,'weight':weight})
        total=sum(f['weight'] for f in folds)
        results.append({'prior_strength_given_diagnostic':strength,'folds':folds,
            'weighted_independent_gap_NLL':sum(f['weight']*f['weighted_independent_gap_NLL'] for f in folds)/total,
            'weighted_joint_gap_NLL':sum(f['weight']*f['weighted_joint_gap_NLL'] for f in folds)/total})
    save(OUT/'SOURCE_GAP_FOLD_DIAGNOSTIC.json',{'status':'complete','predeclared_strength_sensitivity':[1,5,20],
        'results':results,'same_source_household_stays_in_one_fold':True,
        'target':'five-year ego-relative source age-gap bin; not exact role ages or response labels',
        'models':'product of uniform coarse ages vs training-fold weighted conditional gap mixture',
        'no_best_strength_selected':True,'not_a_validation_of_projection_or_national_joint_distribution':True,
        'source_co_residence_proxy_not_census_ordinary_joint_observation':True})
    selection=read(OUT/'SELECTION1000.json')['records'];parent={h['household_id']:h['household_id'] for h in selection}
    def root(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    seen={};records=[];quantity=[];facets=collections.Counter()
    for h in selection:
        w=read(OUT/h['world_path']);mh=w['joint_age_evidence']['source_motif_hash']
        coarse=digest(sorted([[m['ego_relation_code'],m['sex'],m['age_bin_reference'],m['current_work_source_proxy']] for m in w['members']],key=canonical))
        for key in ('motif:'+mh,'roster:'+coarse):
            if key in seen:parent[root(h['household_id'])]=root(seen[key])
            else:seen[key]=h['household_id']
        records.append({'household_id':h['household_id'],'source_motif_hash':mh,'coarse_roster_hash':coarse})
        original=w['evidence_layer']['original_housing_facets'];configured=w['layout']['stock_reference_features']
        for k in original:
            if original[k]!=configured[k]:facets[k]+=1
        if w['N']>=7:quantity.append({'household_id':h['household_id'],'N':w['N'],'reference_batch_kg':w['routine']['laundry_batch_kg'],
            'alternative_given_batch_kg':[2.5,4.5],'unchanged_EB_program_duration':True,
            'mass_enters_program_power_equation':False,'a_given_batch_is_not_total_household_laundry_demand':True})
    groups=collections.defaultdict(list)
    for r in records:groups[root(r['household_id'])].append(r)
    manifest={'schema':'eb.connected_source_motif_or_coarse_roster_grouping.v1','formal_split':None,
        'group_count':len(groups),'repeated_group_households':sum(len(v) for v in groups.values() if len(v)>1),
        'records':[{'group_id':digest(sorted(r['household_id'] for r in rs)),
            'diagnostic_fold5':rank(digest(sorted(r['household_id'] for r in rs)),'structural-holdout')%5,
            'members':rs,'whole_household_10dates_both_arms_stay_together':True} for rs in groups.values()],
        'transitive_motif_or_coarse_roster_overlap_kept_together':True,
        'holdout_performance_not_measured':True,'human_answers':0}
    save(OUT/'STRUCTURAL_GROUP_MANIFEST.json',manifest)
    save(OUT/'BATCH_QUANTITY_SENSITIVITY.json',{'records':quantity,
        'conclusion':'EB fixed-program kernel does not identify a mass-dependent cleaning or energy response; mass is a visible given task dose,not calibrated household laundry demand',
        'no_spurious_EP_mass_sensitivity_run':True,'coverage_preserved':True})
    save(OUT/'FIELD_EVIDENCE1000.json',{'households':[{'household_id':h['household_id'],'world_sha256':h['world_sha256'],
        'population_and_housing_controls':'aggregate statistical anchors with stated transport and fitted-control limits',
        'relationship_age_work':'coarsened matched source auxiliary prior; role exact ages and activity scenarios synthesized',
        'six_device_coverage':'given benchmark design,not ownership prevalence',
        'service_bounds_and_assistance':'given experimental contract,not measured household requirements or willingness',
        'subjective_preferences':'unknown until actor expresses them',
        'physical_outcomes':'current reference readback accepted for original50 only' if (OUT/'READBACK_all_REVIEW.json').exists() and read(OUT/'READBACK_all_REVIEW.json').get('acceptance_passed') and h['household_id'] in {x['household_id'] for x in read(OUT/'SELECTION50.json')['records']} else 'current reference outcomes pending; full1000 EP held'} for h in selection],
        'configured_facet_changes':dict(facets),'original_source_facets_preserved':True,
        'no_observed_preferences_or_same_household_actual_energy_claim':True})
    print({'source_fold_diagnostics':[{k:v for k,v in r.items() if k!='folds'} for r in results],
        'connected_structural_groups':len(groups),'quantity_diagnostics':len(quantity),'configured_facet_changes':dict(facets)},flush=True)
if __name__=='__main__':main()
