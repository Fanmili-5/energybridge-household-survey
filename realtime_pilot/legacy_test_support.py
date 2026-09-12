"""Explicit fixtures for regression tests of archived v2 controllers only."""
from paired_contract import prepare as current_prepare
from evaluation_window import make_window
from eb_execution import ordinary


def prepare(profile, seed):
    original,scenario=current_prepare(profile,seed)
    original['eb_appliance_config']['ev']['charger_kw']=7
    original['eb_ordinary_plan']=ordinary(original['eb_appliance_config'])
    scenario['tariff']={'cny_per_kwh':.6,'compensation_cny':0}
    scenario['evaluation_window']=make_window(original)
    scenario['event']['day']=4
    scenario.pop('collection_engine',None)
    return original,scenario
