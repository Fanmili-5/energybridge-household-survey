"""Participant reports are review metadata, never training labels or retry commands."""
import json
import math
import os
import re
import secrets
import time
from pathlib import Path
from common import digest

CATEGORIES = {'generation_failed', 'waiting', 'schedule', 'display', 'other'}
REVIEW_STATES = {'open', 'confirmed', 'not_bug', 'fixed'}


def text_field(value, limit, label, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(label + '格式无效或过长')
    value = value.strip()
    if required and not value:
        raise ValueError('请填写' + label)
    return value


def submit(store, owner, payload):
    kind, target = payload.get('target_type'), payload.get('target_id')
    category = payload.get('category')
    if not isinstance(kind,str) or not isinstance(category,str) or kind not in {'case', 'household'} or category not in CATEGORIES:
        raise ValueError('请选择问题类型和对应记录')
    if not isinstance(target,str) or not re.fullmatch(r'[a-f0-9]{32}',target):
        raise ValueError('记录编号无效')
    nonce = payload.get('request_id', '')
    if not isinstance(nonce, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', nonce):
        raise ValueError('报告提交标识无效')
    description = text_field(payload.get('description', ''), 2000, '问题说明', required=True)
    with store.lock, store.db.lock, store.db.conn:
        row = store.owned(target, owner) if kind == 'case' else store.household_owned(target, owner)
        previous = store.db.conn.execute('SELECT payload FROM case_reports WHERE owner=? AND request_id=?', (owner, nonce)).fetchone()
        if previous:
            report = json.loads(previous[0])
            if report['request_hash'] != digest(payload):
                raise ValueError('同一次报告不能修改内容，请重新提交')
            return {'saved': True, 'report_id': report['id'], 'duplicate': True}
        count = store.db.conn.execute('SELECT COUNT(*) FROM case_reports WHERE owner=? AND created>=?', (owner, time.time()-86400)).fetchone()[0]
        if count >= 20:
            raise OverflowError('今天已收到多条问题报告，请稍后再提交')
        report = {'id': secrets.token_hex(16), 'target_type': kind, 'target_id': target,
                  'case_id': target if kind == 'case' else None,
                  'household_submission_id': row.get('household_submission_id') if kind == 'case' else target,
                  'category': category, 'description': description, 'created_at': time.time(),
                  'reported_stage': (row.get('progress') or {}).get('stage'),
                  'reported_status': row.get('status', 'intake_saved'),
                  'ui_version': text_field(payload.get('ui_version', ''), 80, '页面版本'),
                  'runtime_version': store.runtime_version,
                  'target_runtime_version': row.get('runtime_version'),
                  'request_hash': digest(payload), 'review_status': 'open', 'review_history': []}
        store.db.conn.execute('INSERT INTO case_reports VALUES(?,?,?,?,?)',
                              (report['id'], owner, nonce, report['created_at'], json.dumps(report, ensure_ascii=False)))
    return {'saved': True, 'report_id': report['id']}


def list_reports(store, status=None, before=None):
    if status and status not in REVIEW_STATES:
        raise ValueError('核查状态无效')
    if before and not re.fullmatch(r'[a-f0-9]{32}', before):
        raise ValueError('分页标识无效')
    clauses, args = [], []
    if status:
        clauses.append("json_extract(payload,'$.review_status')=?"); args.append(status)
    if before:
        clauses.append('rowid < COALESCE((SELECT rowid FROM case_reports WHERE id=?),0)'); args.append(before)
    sql = 'SELECT payload FROM case_reports' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY rowid DESC LIMIT 101'
    with store.db.lock:
        reports = [json.loads(r[0]) for r in store.db.conn.execute(sql, args)]
        for report in reports:
            report.pop('request_hash', None)
            intake = store.db.household(report['household_submission_id']) if report['household_submission_id'] else None
            report['participant_name'] = (intake or {}).get('participant_name', '')
    return {'reports': reports[:100], 'next_cursor': reports[99]['id'] if len(reports)>100 else None}


def review(store, rid, payload, admin):
    status = payload.get('status')
    if not isinstance(status,str) or status not in REVIEW_STATES:
        raise ValueError('请选择核查状态')
    note = text_field(payload.get('note', ''), 2000, '核查备注')
    with store.db.lock, store.db.conn:
        found = store.db.conn.execute('SELECT payload FROM case_reports WHERE id=?', (rid,)).fetchone()
        if not found:
            raise KeyError('找不到问题报告')
        report = json.loads(found[0])
        report['review_status'] = status
        report['review_history'].append({'status': status, 'note': note, 'at': time.time(), 'reviewer': admin})
        store.db.conn.execute('UPDATE case_reports SET payload=? WHERE id=?', (json.dumps(report, ensure_ascii=False), rid))
    return {'saved': True, 'report_id': rid, 'review_status': status}


PRIVATE_KEYS = re.compile(r'^(owner|request_id|request_hash|participant_name|cookie|authorization|password|api[_-]?key|key|headers|environment_variables|.*token.*|.*secret.*)$', re.I)


def scrub(value):
    """Conservative diagnostic redaction; never exports environment/config files."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not PRIVATE_KEYS.fullmatch(k)}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):
        return '[NONFINITE VALUE]'
    if not isinstance(value, str):
        return value
    value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[REDACTED]', value)
    value = re.sub(r'(?i)(Bearer\s+)[^\s"\',]+', r'\1[REDACTED]', value)
    value = re.sub(r'(?i)((?:api[_-]?key|password|token|secret|cookie|authorization)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', value)
    value = re.sub(r'https?://[^\s"\'<>]+', '[URL REDACTED]', value)
    value = re.sub(r'/(?:Users|home|opt|etc|var|private|tmp)/[^\s"\'<>]+', '[PATH REDACTED]', value)
    return value


def diagnostic(store, kind, target):
    if kind not in {'case', 'household'} or not re.fullmatch(r'[a-f0-9]{32}', target):
        raise KeyError('记录编号无效')
    with store.lock, store.db.lock:
        job = store.db.job(target) if kind == 'case' else None
        intake_id = job.get('household_submission_id') if job else target if kind == 'household' else None
        intake = store.db.household(intake_id) if intake_id else None
        if (kind == 'case' and not job) or (kind == 'household' and not intake):
            raise KeyError('找不到记录')
        documents = {name: json.loads(payload) for name, payload in store.db.conn.execute('SELECT name,payload FROM documents WHERE job_id=?', (target,))} if job else {}
        reports = [json.loads(r[0]) for r in store.db.conn.execute("SELECT payload FROM case_reports WHERE json_extract(payload,'$.target_id')=? OR json_extract(payload,'$.household_submission_id')=?", (target, intake_id))]
        linked = [r['id'] for r in store.jobs.summaries() if intake_id and r.get('household_submission_id') == intake_id]
    output = {'schema_version': 'eb.case_diagnostic.v1', 'exported_at': time.time(), 'target_type': kind,
              'target_id': target, 'job': job, 'household_submission': intake, 'linked_case_ids': linked,
              'documents': documents, 'reports': reports, 'artifacts': {}, 'artifact_manifest': [],
              'missing_documents': [n for n in ('request.json','outcome.json','decision.json') if n not in documents] if job else [],
              'scope': 'Administrator diagnostic snapshot, not SFT. Only locally available text artifacts; remote-only or binary files are not embedded. Running files may change during export.'}
    budget = 16*1024*1024
    base = store.root / target
    if job and base.is_dir() and not base.is_symlink():
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink())
            for name in sorted(files):
                path = Path(directory)/name
                relative = path.relative_to(base).as_posix()
                entry = {'path': relative}
                output['artifact_manifest'].append(entry)
                if len(output['artifact_manifest'])>2000:
                    entry['status']='file_limit';return scrub(output)
                if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {'.json','.log','.txt','.err','.csv'} or re.search(r'(secret|token|credential|\.env|password)', relative, re.I):
                    entry['status']='excluded';continue
                try:
                    size=path.stat().st_size;entry['bytes']=size
                    if size>2*1024*1024 or size>budget:
                        entry['status']='size_limit';continue
                    with path.open('rb') as stream:raw=stream.read(min(2*1024*1024,budget)+1)
                    budget-=len(raw)
                    if len(raw)>2*1024*1024 or budget<0:
                        entry['status']='size_limit';continue
                    text=raw.decode('utf-8')
                    if '-----BEGIN ' in text and 'PRIVATE KEY-----' in text:
                        entry['status']='excluded';continue
                    output['artifacts'][relative]=json.loads(text) if path.suffix=='.json' else text
                    entry['status']='included'
                except (OSError, UnicodeError, ValueError):
                    entry['status']='unavailable_or_incomplete'
    return scrub(output)
