"""Commit household-derived tasks before plan generation; no physics or labels."""
from contextlib import contextmanager
from pathlib import Path
import datetime as dt
import hashlib
import json
import os

from .common import digest
from .task_context import POLICY, VERSION, derive_tasks, frozen_tasks


def commit_cases(cases, dates, reference, out, source_manifest_sha256):
    dates = list(dates)
    if not dates or len(set(dates)) != len(dates):
        raise ValueError("UNIQUE_NONEMPTY_TASK_DATES_REQUIRED")
    for date in dates:
        dt.date.fromisoformat(date)
    if len({case["case_id"] for case in cases}) != len(cases) or not cases:
        raise ValueError("UNIQUE_NONEMPTY_TASK_CASES_REQUIRED")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for case in cases:
        # A case ID is a file component, never a caller-controlled path.
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or Path(case_id).name != case_id or case_id in (".", ".."):
            raise ValueError("UNSAFE_TASK_CASE_ID")
        for date in dates:
            task = derive_tasks(case, date, reference)
            path = out / "tasks" / case_id / (date + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(task, ensure_ascii=False, separators=(",", ":")))
            rows.append(dict(case_id=case_id, date=date, sha256=task["sha256"],
                             path=str(path.relative_to(out))))
    index = out / "TASK_INDEX.jsonl"
    index.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = dict(schema=VERSION, households=len(cases), tasks=len(rows),
                    household_source_sha256=source_manifest_sha256,
                    reference_sha256=digest(reference), policy_sha256=digest(POLICY),
                    task_index_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),
                    plans_generated=False, physical_outcomes_computed=False,
                    human_answers_generated=False)
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


@contextmanager
def committed_tasks(cases, dates, reference, out, source_manifest_sha256):
    """Reuse validated explicit commitments or create a new isolated task set."""
    inherited = os.environ.get("EB_FROZEN_TASK_ROOT")
    if inherited:
        # Verify every requested commitment before the caller can generate A.
        for case in cases:
            for date in dates:
                frozen_tasks(case, date, reference)
        yield Path(inherited)
        return
    commit_cases(cases, dates, reference, out, source_manifest_sha256)
    os.environ["EB_FROZEN_TASK_ROOT"] = str(Path(out).resolve())
    try:
        yield Path(out)
    finally:
        os.environ.pop("EB_FROZEN_TASK_ROOT", None)
