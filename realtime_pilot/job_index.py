"""Lightweight job index; large historical records remain authoritative in SQLite."""
from collections.abc import MutableMapping
import threading

TERMINAL_STATUSES=frozenset({'complete','failed','timeout','cancelled','interrupted','expired'})
# Only scalar routing, quota, recovery and participant status fields belong here.
SUMMARY_FIELDS=(
    'id','owner','request_id','request_hash','status','created_at','flow','task',
    'admin_test','data_origin','household_id','respondent_id','household_submission_id',
    'started_at','finished_at','end_to_end_seconds','queue_seconds','queue_deadline_at','message',
    'decision_saved','rating_saved','attempts','recovery_count','run_directory',
    'replay_source','questionnaire_version','questionnaire_hash',
)


def summarize_job(job):
    return {key:job[key] for key in SUMMARY_FIELDS if key in job and job[key] is not None}


class LazyJobIndex(MutableMapping):
    """Mapping-compatible reads with no long-lived cache of terminal job payloads.

    Callers still persist through Database.save before assigning an updated job.
    Nonterminal reads share object identity until a terminal assignment evicts it.
    summaries() is a small detached snapshot, not a replacement for a mutable job:
    load self[id] before modifying and persisting a record.
    """
    def __init__(self,database):
        self.database=database
        self._lock=threading.RLock()
        self._summaries={row['id']:row for row in database.job_summaries()}
        self._active={}

    def __getitem__(self,key):
        with self._lock:
            if key not in self._summaries:raise KeyError(key)
            if key in self._active:return self._active[key]
            job=self.database.job(key)
            if job is None:raise KeyError(key)
            if job['status'] not in TERMINAL_STATUSES:self._active[key]=job
            return job

    def __setitem__(self,key,job):
        if key!=job.get('id'):raise ValueError('Job index key does not match job id')
        with self._lock:
            self._summaries[key]=summarize_job(job)
            if job['status'] in TERMINAL_STATUSES:self._active.pop(key,None)
            else:self._active[key]=job

    def __delitem__(self,key):
        # This is an in-memory index operation, never deletion of research evidence.
        with self._lock:
            del self._summaries[key]
            self._active.pop(key,None)

    def __iter__(self):
        with self._lock:return iter(tuple(self._summaries))

    def __len__(self):
        with self._lock:return len(self._summaries)

    def __contains__(self,key):
        with self._lock:return key in self._summaries

    def summary(self, key):
        with self._lock:
            row=self._summaries.get(key)
            return dict(row) if row is not None else None

    def summaries(self):
        with self._lock:return iter([dict(row) for row in self._summaries.values()])

    @property
    def cached_count(self):
        with self._lock:return len(self._active)
