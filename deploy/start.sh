#!/usr/bin/env bash
set -euo pipefail
app_root=/opt/energybridge
python_bin="$app_root/.venv/bin/python"
cd "$app_root/realtime_pilot"
: "${EB_PUBLIC_ORIGIN:?Set EB_PUBLIC_ORIGIN to the external HTTPS origin}"
: "${EB_DATA_DIR:=/var/lib/energybridge/jobs}"
: "${EB_PLANNING_ENABLED:=0}"
: "${EB_HUMAN_PILOT:=1}"
: "${EB_WORKERS:=2}"
: "${EB_JOB_TIMEOUT:=300}"
: "${EB_MAX_PENDING:=100}"
: "${EB_MAX_SESSION_JOBS:=3}"
: "${EB_MAX_DAILY_JOBS:=250}"
: "${EB_MAX_SESSION_INTAKES:=5}"
: "${EB_MAX_DAILY_INTAKES:=2000}"
: "${EB_MAX_QUEUE_WAIT:=120}"
: "${EB_ESTIMATED_JOB_SECONDS:=60}"
: "${EB_ADMIN_USER:=}"
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$app_root/upstream_2b17ae6" \
    "$python_bin" "$app_root/scripts/bootstrap_upstream.py" --verify-only
args=(server.py --port 8767 --data-dir "$EB_DATA_DIR" --workers "$EB_WORKERS"
      --timeout "$EB_JOB_TIMEOUT" --public-origin "$EB_PUBLIC_ORIGIN"
      --max-pending "$EB_MAX_PENDING" --max-session-jobs "$EB_MAX_SESSION_JOBS"
      --max-daily-jobs "$EB_MAX_DAILY_JOBS" --max-queue-wait "$EB_MAX_QUEUE_WAIT"
      --max-session-intakes "$EB_MAX_SESSION_INTAKES" --max-daily-intakes "$EB_MAX_DAILY_INTAKES"
      --estimated-job-seconds "$EB_ESTIMATED_JOB_SECONDS")
if [ -n "$EB_ADMIN_USER" ]; then args+=(--admin-user "$EB_ADMIN_USER"); fi
case "$EB_HUMAN_PILOT" in
  1) args+=(--human-pilot) ;;
  0) ;;
  *) echo 'EB_HUMAN_PILOT must be 0 or 1' >&2; exit 1 ;;
esac
case "$EB_PLANNING_ENABLED" in
  0) args+=(--disable-planning) ;;
  1)
    : "${EPLUS_ROOT:?Set EPLUS_ROOT to EnergyPlus 24.1}"
    test -x "$EPLUS_ROOT/energyplus" || { echo 'EnergyPlus executable is missing' >&2; exit 1; }
    "$EPLUS_ROOT/energyplus" --version | grep -q '24.1' || { echo 'EnergyPlus 24.1 is required' >&2; exit 1; }
    "$python_bin" - <<'PY'
import os
from runtime_config import load_model_environment
load_model_environment()
if os.environ.get('USE_LLM','').lower() not in {'1','true','yes','on'}:
    raise SystemExit('Set USE_LLM=true in the external model environment file before enabling planning')
if any(not os.environ.get(k,'').strip() for k in ('LLM_API_KEY','LLM_BASE_URL','LLM_MODEL')):
    raise SystemExit('Complete the external model configuration before enabling planning')
PY
    ;;
  *) echo 'EB_PLANNING_ENABLED must be 0 or 1' >&2; exit 1 ;;
esac
exec "$python_bin" -u "${args[@]}"
