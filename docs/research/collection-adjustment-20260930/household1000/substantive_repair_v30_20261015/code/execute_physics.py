"""An explicit scope only. Never automatically advance from50 to950."""
from common import *
from cohort_gate import review
from run_cohort import run
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['original50','other950','weather_sensitivity'],default='original50');p.add_argument('--workers',type=int,default=32);a=p.parse_args()
    review(a.scope);run(a.scope,a.workers)
