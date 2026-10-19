"""Triangulate specific coarse constructs in existing independent raw surveys."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = Path('/tmp/eb_external_followup_20261019')
sys.path.insert(0,str(RAW/'pydeps'))
import pyreadstat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw-dir', type=Path, default=RAW)
    raw_dir = parser.parse_args().raw_dir
    d,m = pyreadstat.read_sav(str(raw_dir/'dutch.sav'))
    assert len(d)==1678
    assert hashlib.md5((raw_dir/'dutch.sav').read_bytes()).hexdigest() == 'd02356236f6ea71fd178f8d5950a7f38'
    branches = {'EV':('Q29_5','Q34_7'), 'laundry':('Q48_5','Q53_7'), 'dishwasher':('Q63_5','Q68_7')}
    out = {'dutch':{'source':'https://doi.org/10.4121/4e223727-d29b-4ffb-80fa-9087f0d29766.v1', 'n':len(d),'branches':{},
        'interpretation':'Actual low regularity and perceived loss of freedom due to automatic control can be co-observed. Control-barrier items are conditional on HEMS and randomized item routing. No population weights; no EB six prevalence claimed.'},
        'iFlex2020':{}, 'production_changes':False, 'EP_runs':0}
    combined_seen = pd.Series(0,index=d.index)
    combined_positive = pd.Series(False,index=d.index)
    for name,(routine,control) in branches.items():
        valid = d[routine].isin([1,2,3,4,5]) & d[control].isin([1,2,3,4,5,6,7])
        positive = valid & d[routine].isin([4,5]) & d[control].isin([5,6,7])
        assert not (d[control].notna() & d.Q15.ne(1)).any(), name
        combined_seen += valid.astype(int)
        combined_positive |= positive
        out['dutch']['branches'][name]={'routine_field':routine,'control_field':control,
            'routine_original_label':m.column_names_to_labels[routine], 'control_original_label':m.column_names_to_labels[control],
            'routine_valid_n':int(d[routine].notna().sum()), 'routine_low_regularity4or5_n':int(d[routine].isin([4,5]).sum()),
            'control_valid_n':int(d[control].notna().sum()),'control_concern5to7_n':int(d[control].isin([5,6,7]).sum()),
            'both_observed_n':int(valid.sum()),'both_positive_n':int(positive.sum())}
    assert combined_seen.max()<=1
    out['dutch']['both_observed_unique_n']=int(combined_seen.gt(0).sum())
    out['dutch']['both_positive_unique_n']=int(combined_positive.sum())
    # Same real participants may be joined between iFlex waves using original ID.
    a=pd.read_csv(raw_dir/'survey1_answers.csv'); b=pd.read_csv(raw_dir/'survey2_answers.csv')
    assert a.ID.is_unique and b.ID.is_unique
    joined=b.merge(a,on='ID',validate='one_to_one',suffixes=('','_baseline'))
    assert len(joined)==800
    cost=joined.Aq3_1.ne('-'); comfort=joined.Aq3_4.ne('-'); automatic=joined.Aq3_3.ne('-'); grid=joined.Aq3_7.ne('-')
    positive_auto=joined.Aq5N2.isin(['Likely','Very likely'])
    out['iFlex2020']={'source':'https://zenodo.org/records/8248802', 'same_participants_joined_n':len(joined),
        'bills_motivation_n':int(cost.sum()),'comfort_protection_motivation_n':int(comfort.sum()),
        'automatic_action_motivation_n':int(automatic.sum()),'grid_development_motivation_n':int(grid.sum()),
        'bills_and_comfort_same_person_n':int((cost & comfort).sum()),
        'comfortable_conditions_and_usually_home_n':int((comfort & joined.q23.eq('Yes')).sum()),
        'grid_and_automation_investment_willingness_n':int((grid & positive_auto).sum()),
        'interpretation':'Direct same-person motives for four-hour winter DR are stronger evidence than ECA cost pressure alone. Motives are multi-select, not six classes. No population weights; no Chinese or EB six proportions. Aq2 English blank combines a legitimate Norwegian neutral category with other possible blanks, so it is not recoded as measured comfort priority.'}
    paths=[raw_dir/'dutch.sav',raw_dir/'dutch_dictionary.docx',raw_dir/'survey1_answers.csv',raw_dir/'survey1_questions.csv',raw_dir/'survey2_answers.csv',raw_dir/'survey2_questions.csv']
    out['input_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (ROOT/'EXTERNAL_CONSTRUCTS.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(out,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
