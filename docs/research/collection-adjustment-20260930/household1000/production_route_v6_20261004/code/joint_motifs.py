"""Private local source -> weighted coarsened whole-household motifs.

Never export raw source IDs, birth years, monetary values, or source rows.
Observed ego relationship, sex, and coarse age intervals travel together.
"""
import collections
import hashlib
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / 'chfs_census_bridge_20261003'))
import run_bridge as rb
from bridge_rules import LEVEL, integer, number

AGE_WIDTH = 5
INCOME_EDGES = [-math.inf,0,20000,40000,60000,100000,150000,250000,500000,1000000,math.inf]


def income_bin(value):
    value = number(value)
    if value is None: return None
    for i,(a,b) in enumerate(zip(INCOME_EDGES,INCOME_EDGES[1:])):
        if a <= value < b: return i
    return None


def load_source():
    frame = rb.load_bridge_pool()
    people = rb.read('ind', ['hhid','a2000c','a2001','a2003','a2005','a3100a'])
    members = {hid:g.drop(columns=['hhid']).to_dict('records') for hid,g in people.groupby('hhid')}
    choices = [f'c8001ab_{k}_mc' for k in [1,2,5,6,9,12,19,7777,7788]]
    hh = rb.read('hh',['hhid']+choices)
    master = rb.read('master_hh',['hhid','total_income'])
    assets = {r['hhid']:r for r in hh.to_dict('records')}
    incomes = {r['hhid']:r['total_income'] for r in master.to_dict('records')}
    records, qc = [], collections.Counter()
    for r in frame.to_dict('records'):
        if number(r['weight']) is None or r['weight'] <= 0:
            qc['nonpositive_or_unknown_weight'] += 1; continue
        if not r['residence_complete'] or not r['reported_roster_consistent_or_unasked'] or r['active_member_conflict']:
            qc['roster_proxy_quality_issue'] += 1; continue
        co = [p for p in members[r['_local_hhid']] if integer(p['a2000c']) in [1,2]]
        if not co or sum(integer(p['a2001']) == 1 for p in co) != 1:
            qc['no_coresident_ego'] += 1; continue
        if any(integer(p['a2001']) not in LEVEL or integer(p['a2003']) not in [1,2]
               or integer(p['a2005']) is None or not 1900 <= integer(p['a2005']) <= int(r['visit_year']) for p in co):
            qc['relation_sex_or_birth_quality_unknown'] += 1; continue
        atom = []
        for p in co:
            age = int(r['visit_year']) - integer(p['a2005'])
            lower = max(0,age-1)//AGE_WIDTH; upper = age//AGE_WIDTH
            atom.append((integer(p['a2001']),integer(p['a2003']),lower,upper,integer(p['a3100a'])))
        atom.sort(key=lambda x:(x[0],x[2],x[3],x[1],-1 if x[4] is None else x[4]))
        n = len(atom); g = len({LEVEL[a[0]] for a in atom})
        a = assets[r['_local_hhid']]
        answered = any(integer(a[c]) == 1 for c in choices)
        conflict = integer(a['c8001ab_7788_mc']) == 1 and any(integer(a[c]) == 1 for c in choices[:-1])
        group = tuple(integer(a[f'c8001ab_{k}_mc']) if answered and not conflict else None for k in [2,5,19])
        records.append({'_private_id':r['_local_hhid'], 'province':r['province'], 'N':n, 'G':g,
                        'weight':float(r['weight']), 'visit_year':int(r['visit_year']),
                        'atom':tuple(atom),'economic_member_count':int(r['economic_member_count']),
                        'income_bin':income_bin(incomes[r['_local_hhid']]),'asset_groups':group,
                        'tenure_code':r['tenure_code'], 'area_proxy':number(r['area_candidate_m2']),
                        'area_whole_scope_supported':bool(r['area_scope_supported']),
                        'source_scope':'CHFS_co_residence_proxy_not_observed_census_equivalence',
                        'raw_birthyears':[(integer(p['a2001']),integer(p['a2005'])) for p in co]})
    qc['accepted_source_proxy_households'] = len(records)
    qc['accepted_samevisit2021'] = sum(r['visit_year'] == 2021 for r in records)
    qc['accepted_visit2022_not_synchronous_asset_prior'] = sum(r['visit_year'] == 2022 for r in records)
    qc['singleton_under20_not_automatically_excluded'] = sum(r['N'] == 1 and max(a[3] for a in r['atom'])*5 < 20 for r in records)
    return records, dict(qc)


def fold(record):
    salt = 'EB_JOINT_MOTIF_GAP_OUTER_FOLDS_20261004_V1'
    return int(hashlib.sha256((salt+'|'+str(record['_private_id'])).encode()).hexdigest(),16)%5


def weighted_choice(rng, values, weights):
    u = rng.random()*sum(weights)
    for value,w in zip(values,weights):
        u -= w
        if u <= 0: return value
    return values[-1]


def coarse_age_pmf(atom_member):
    _,_,lower,upper,_ = atom_member
    result = collections.Counter()
    for b,mass in [(lower,.5),(upper,.5)]:
        for age in range(b*5,b*5+5): result[age] += mass/5
    return result
