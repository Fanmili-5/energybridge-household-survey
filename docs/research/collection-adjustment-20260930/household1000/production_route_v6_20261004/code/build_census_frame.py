"""Reconstruct the ordinary-city frame using direct NBS counts/moments.

All-city province x size x generation is a modeled completion of observed
margins. Ordinary size x generation remains unidentified; a bounded entropy
completion is constrained by observed ordinary generations AND resident counts.
No under20-singleton exclusion, no relabeling of previous nonordinary cases.
"""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import brentq, Bounds, LinearConstraint, milp
from scipy.special import expit
from scipy.sparse import lil_matrix

OUT = Path(__file__).resolve().parent.parent
BASE = OUT.parent
OLD = BASE / 'evidence_contract_20261001/raw'
RAW = OUT / 'raw'


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def normalized(value):
    return ''.join(str(value).split())


def table(key):
    path = RAW / (key + '.xls')
    if not path.exists(): path = OLD / (key + '.xls')
    data = pd.read_excel(path, header=None).fillna('')
    rows = {normalized(r[0]): list(r) for r in data.values.tolist()
            if isinstance(r[1], (int, float)) and not isinstance(r[1], bool)}
    return data, rows, {'key': key, 'url': 'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/' + key + '.xls',
                        'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'title': data.iloc[0, 0], 'notes': [str(x) for x in data[0] if str(x).startswith('注')]}


def apportion(total, weights):
    x = np.asarray(weights, float); x = x / x.sum() * total
    y = np.floor(x).astype(int)
    for j in sorted(range(len(x)), key=lambda i: (-(x[i]-y[i]), i))[:total-y.sum()]: y[j] += 1
    return y


def subset_entropy(capacity, ordinary_generation, resident_target, sizes):
    """Bernoulli entropy completion of ordinary/nonordinary within each G.

Capacity is itself an explicit full-city IPF completion. This is one admissible
point, NOT an observed ordinary size-generation table or an identification CI.
"""
    def allocation(beta):
        output = np.zeros_like(capacity)
        for g in range(capacity.shape[1]):
            c = capacity[:, g]; desired = ordinary_generation[g]
            if desired <= 0: continue
            if abs(desired - c.sum()) < 1e-6:
                output[:, g] = c; continue
            if desired > c.sum() + 1e-5: raise ValueError('ordinary_exceeds_all_city_generation')
            f = lambda alpha: np.sum(c * expit(alpha + beta*sizes)) - desired
            alpha = brentq(f, -5000, 5000, xtol=1e-12)
            output[:, g] = c * expit(alpha + beta*sizes)
        return output
    low, high = allocation(-100), allocation(100)
    min_people, max_people = np.sum(low * sizes[:, None]), np.sum(high * sizes[:, None])
    if not min_people-1e-3 <= resident_target <= max_people+1e-3:
        raise ValueError('ordinary_resident_moment_infeasible_under_this_completion')
    f = lambda beta: np.sum(allocation(beta) * sizes[:, None]) - resident_target
    beta = brentq(f, -100, 100, xtol=1e-12)
    result = allocation(beta)
    assert np.max(np.abs(result.sum(0)-ordinary_generation)) < 1e-3
    assert abs(np.sum(result*sizes[:, None])-resident_target) < 1e-3
    return result, {'beta': beta, 'min_resident_count_conditional_on_IPF_and_tail_mean': min_people,
                    'max_resident_count_conditional_on_IPF_and_tail_mean': max_people,
                    'observed_resident_count': resident_target}


def integer_slots(expected, provinces, ordinary_hh, ordinary_people, tail_means):
    """Balanced1000 allocation; N targets below are modeled, G/P are official."""
    province_quota = apportion(1000, ordinary_hh)
    gen_quota = apportion(1000, expected.sum((0,1)))
    size_expected = expected.sum((0,2))
    cells = []
    for p in range(len(provinces)):
        for n in range(10):
            for g in range(5):
                if expected[p,n,g] <= 0: continue
                choices = [n+1] if n < 9 else sorted({math.floor(tail_means[p]), math.ceil(tail_means[p])})
                for exact in choices:
                    cells.append((p,n,g,exact,float(expected[p,n,g]) / len(choices)))
    count = len(cells)
    # x_j integer; d_j is absolute deviation from fractional target.
    matrix = lil_matrix((31+10+5+31*5+31+1+2*count, 2*count))
    lower, upper = [], []
    row = 0
    for p in range(31):
        for j,c in enumerate(cells):
            if c[0] == p: matrix[row,j] = 1
        lower.append(province_quota[p]); upper.append(province_quota[p]); row += 1
    for n in range(10):
        for j,c in enumerate(cells):
            if c[1] == n: matrix[row,j] = 1
        lower.append(math.floor(size_expected[n])); upper.append(math.ceil(size_expected[n])); row += 1
    for g in range(5):
        for j,c in enumerate(cells):
            if c[2] == g: matrix[row,j] = 1
        lower.append(gen_quota[g]); upper.append(gen_quota[g]); row += 1
    for p in range(31):
        for g in range(5):
            for j,c in enumerate(cells):
                if c[0] == p and c[2] == g: matrix[row,j] = 1
            target = expected[p,:,g].sum()
            lower.append(math.floor(target)); upper.append(math.ceil(target)); row += 1
    for p in range(31):
        for j,c in enumerate(cells):
            if c[0] == p: matrix[row,j] = c[3]
        target = province_quota[p] * ordinary_people[p] / ordinary_hh[p]
        # One integer resident of allowance around the rounded-cohort moment.
        # This is finite-cohort discretization, not an empirical accuracy gate.
        lower.append(math.floor(target)-1); upper.append(math.ceil(target)+1); row += 1
    for j,c in enumerate(cells): matrix[row,j] = c[3]
    national_people_target = round(ordinary_people.sum()/ordinary_hh.sum()*1000)
    lower.append(national_people_target); upper.append(national_people_target); row += 1
    for j,c in enumerate(cells):
        matrix[row,j] = 1; matrix[row,count+j] = -1
        lower.append(-np.inf); upper.append(c[4]); row += 1
        matrix[row,j] = -1; matrix[row,count+j] = -1
        lower.append(-np.inf); upper.append(-c[4]); row += 1
    assert row == matrix.shape[0]
    objective = np.r_[np.zeros(count), np.ones(count)]
    fit = milp(objective, integrality=np.r_[np.ones(count), np.zeros(count)],
               bounds=Bounds(np.zeros(2*count), np.full(2*count, np.inf)),
               constraints=LinearConstraint(matrix.tocsr(), lower, upper),
               options={'time_limit': 90, 'mip_rel_gap': 0.001})
    if fit.x is None: raise ValueError('integer_allocation_failed:' + fit.message)
    x = np.rint(fit.x[:count]).astype(int)
    residual = matrix[:31+10+5+31*5+31+1,:count] @ x
    check_lower = np.array(lower[:len(residual)]); check_upper = np.array(upper[:len(residual)])
    assert np.all(residual >= check_lower-1e-7) and np.all(residual <= check_upper+1e-7)
    slots = []
    for c, multiplicity in zip(cells, x):
        p,n,g,exact,_ = c
        for _ in range(multiplicity):
            slots.append({'slot_id': f'ordinary-v6-{len(slots)+1:04}', 'province': provinces[p],
                          'size_category': str(n+1) if n < 9 else '10+',
                          'generation_category': str(g+1) if g < 4 else '5+',
                          'exact_member_count': exact,
                          'size_joint_evidence': 'bounded_entropy_completion_of_ordinary_frame_not_observed_joint',
                          'tail_exact_is_design': n == 9,
                          'relative_population_weight': ordinary_hh[p]/province_quota[p]/sum(ordinary_hh)*1000})
    assert len(slots) == 1000
    actual_size = [sum(m for c,m in zip(cells,x) if c[1] == n) for n in range(10)]
    return slots, {'province_quota': dict(zip(provinces,map(int,province_quota))),
                   'national_generation_quotas': gen_quota.tolist(), 'modeled_national_size_quotas': list(map(int,actual_size)),
                   'modeled_size_targets_each_floor_or_ceil': True,
                   'national_resident_count_nearest_integer_target': national_people_target,
                   'solver_status': int(fit.status), 'solver_message': fit.message,
                   'mip_gap': float(fit.mip_gap), 'resident_count': sum(s['exact_member_count'] for s in slots),
                   'population_weights_sum': sum(s['relative_population_weight'] for s in slots)}


def main():
    authority = json.loads((BASE/'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json').read_text())
    provinces = authority['modeled_population_completion']['province_order']
    keys = ['A0101a','A0108a','A0109a','A0501a','A0112a','A0801a','A0802a','A0803a',
            'A0804a','A0805a','B0907a','B0909a','B0911a','B0912a']
    books = {k:table(k) for k in keys}; frames = []
    for key,(data,rows,lock) in books.items():
        national = rows.get('全国',rows.get('总计'))
        frames.append({**lock, 'national_first_numeric_count': int(national[1]) if national else None,
                       'scope_policy': 'full_ordinary_city' if key in ['A0112a','A0801a','A0802a','A0803a'] else
                       'full_all_city_family' if key in ['A0108a','A0109a','A0501a'] else
                       'all_city_including_collective_population; select_family_fields' if key == 'A0101a' else
                       'conditional_head_education_or_employment_frame; not_full_ordinary_city'})
    get = lambda k,p: books[k][1][p]
    all_size = np.array([get('A0108a',p)[2::2] for p in provinces],float)
    all_gen = np.array([get('A0109a',p)[2::2] for p in provinces],float)
    data = books['A0501a'][0]
    national_ng = np.array([r[2:7] for r in data.values.tolist() if isinstance(r[1],(int,float)) and normalized(r[0]) != '总计'],float)
    assert national_ng.shape == (10,5)
    assert np.array_equal(national_ng.sum(1), all_size.sum(0))
    assert np.array_equal(national_ng.sum(0), all_gen.sum(0))
    ordinary_hh = np.array([get('A0112a',p)[1] for p in provinces],float)
    ordinary_people = np.array([get('A0112a',p)[2] for p in provinces],float)
    all_people = np.array([get('A0101a',p)[8] for p in provinces],float)
    ordinary_gr = np.array([get('A0803a',p)[2:] for p in provinces],float).reshape(31,5,5)
    ordinary_g = ordinary_gr.sum(2)
    assert np.array_equal(ordinary_g.sum(1), ordinary_hh)
    room10 = np.array([get('A0801a',p)[2:] for p in provinces],float)
    area10 = np.array([get('A0802a',p)[2:] for p in provinces],float)
    assert np.array_equal(room10.sum(1),ordinary_hh) and np.array_equal(area10.sum(1),ordinary_hh)
    assert np.array_equal(np.c_[room10[:,:4],room10[:,4:].sum(1)],ordinary_gr.sum(1))
    tail_means = (all_people-all_size[:,:9]@np.arange(1,10))/all_size[:,9]
    assert np.all(tail_means >= 10)
    x = np.broadcast_to(national_ng[None,:,:], (31,10,5)).copy()
    for iteration in range(20000):
        for desired, axis in [(all_size[:,:,None],2),(all_gen[:,None,:],1),(national_ng[None,:,:],0)]:
            denominator = x.sum(axis,keepdims=True)
            x *= np.divide(desired,denominator,out=np.zeros_like(denominator),where=denominator>0)
        error = max(np.abs(x.sum(2)-all_size).max(),np.abs(x.sum(1)-all_gen).max(),np.abs(x.sum(0)-national_ng).max())
        if error < 1e-4: break
    assert error < 1e-4
    ordinary = np.zeros_like(x); moment_checks = []
    for p,province in enumerate(provinces):
        sizes = np.r_[np.arange(1,10),tail_means[p]]
        ordinary[p], report = subset_entropy(x[p], ordinary_g[p], ordinary_people[p], sizes)
        moment_checks.append({'province':province, **report})
    expected = ordinary / ordinary_hh.sum() * 1000
    slots, integer_report = integer_slots(expected,provinces,ordinary_hh,ordinary_people,tail_means)
    result = {'target':'China_city_ordinary_residential_family_households; all_ages; town_rural_collective_households_excluded',
              'is_new_proposed_frame_not_relabelled_V5':True, 'population_reference_date':'2020-11-01',
              'source_housing_H5_code':1, 'official_households':int(ordinary_hh.sum()),
              'official_residents':int(ordinary_people.sum()), 'official_mean_residents':float(ordinary_people.sum()/ordinary_hh.sum()),
              'observed_controls':['province_x_ordinary_household_count','province_x_ordinary_resident_count','province_x_ordinary_generation_x_H7bin','province_x_ordinary_H7exact_bin','province_x_ordinary_percap_area_bin'],
              'latent_ordinary_NG_policy':'bounded_binary_entropy_with_known_ordinary_generation_and_person_moments; NOT_identified_joint',
              'tail_mean_transport_assumption':'ordinary10plus_mean_size_borrows_observed_allcity_province_tail_mean; exact_role_tail_is_minimum_variance_design',
              'allcity_completion_iterations':iteration+1,'allcity_completion_max_count_error':float(error),
              'frames':frames,'provinces':provinces,'ordinary_household_counts':ordinary_hh.astype(int).tolist(),
              'ordinary_resident_counts':ordinary_people.astype(int).tolist(),'ordinary_generation_room_counts':ordinary_gr.astype(int).tolist(),
              'ordinary_room10_counts':room10.astype(int).tolist(),'ordinary_percap_area10_counts':area10.astype(int).tolist(),
              'ordinary_mean_building_area_m2':[float(get('A0112a',p)[3]) for p in provinces],
              'ordinary_mean_room_count':[float(get('A0112a',p)[4]) for p in provinces],
              'allcity_size_generation_completion':x.tolist(),'ordinary_size_generation_completion':ordinary.tolist(),
              'allcity_tail_mean_size':tail_means.tolist(),'ordinary_frame_moment_checks':moment_checks,
              'integer_allocation':integer_report,'complete_benchmark_approved':False}
    save('ORDINARY_CITY_FRAME.json',result)
    save('ORDINARY_ALLOCATION1000.json',{'target':result['target'],'slots':slots,'report':integer_report,
                                      'household_gen_complete':False,'IDFs_generated':0,'benchmark_release':False})
    print(json.dumps({k:result[k] for k in ['official_households','official_residents','official_mean_residents','integer_allocation']},ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
