"""Retired non-EB handling compiler; retained only to reject stale callers."""
def compile_question_day(*args,**kwargs):
    raise ValueError('REMOVED_NON_EB_MANUAL_HANDLING_MODEL;use_v9_date_adapter.generate_day_baseline')
