#!/bin/sh
# Strictly read-only health check for SpicyEngine; logs structured alerts without restarting services.
set -eu

HEALTH_URL=${SPICYENGINE_HEALTH_URL:-http://127.0.0.1:8090/v1/health}
LOOKBACK=${SPICYENGINE_HEALTHCHECK_LOOKBACK:-15 minutes ago}
MIN_SWAP_FREE_MIB=${SPICYENGINE_HEALTHCHECK_MIN_SWAP_FREE_MIB:-2048}
MIN_DISK_FREE_GIB=${SPICYENGINE_HEALTHCHECK_MIN_DISK_FREE_GIB:-15}
MAX_429_COUNT=${SPICYENGINE_HEALTHCHECK_MAX_429_COUNT:-20}
DISK_PATH=${SPICYENGINE_HEALTHCHECK_DISK_PATH:-/}
MEMINFO_PATH=${SPICYENGINE_HEALTHCHECK_MEMINFO_PATH:-/proc/meminfo}
SERVICE_UNIT=${SPICYENGINE_HEALTHCHECK_UNIT:-spicyengine.service}
JOURNALCTL_BIN=${SPICYENGINE_HEALTHCHECK_JOURNALCTL:-journalctl}
LOGGER_BIN=${SPICYENGINE_HEALTHCHECK_LOGGER:-logger}
if [ -n "${SPICYENGINE_HEALTHCHECK_PYTHON:-}" ]; then
    PYTHON_BIN=$SPICYENGINE_HEALTHCHECK_PYTHON
elif [ -x /opt/spicyengine/congress-prepare/bin/python ]; then
    PYTHON_BIN=/opt/spicyengine/congress-prepare/bin/python
else
    PYTHON_BIN=python3
fi

result=$("$PYTHON_BIN" - "$HEALTH_URL" "$LOOKBACK" "$MIN_SWAP_FREE_MIB" "$MIN_DISK_FREE_GIB" "$MAX_429_COUNT" \
    "$DISK_PATH" "$MEMINFO_PATH" "$SERVICE_UNIT" "$JOURNALCTL_BIN" <<'PY'
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

(
    health_url,
    lookback,
    min_swap_free_mib,
    min_disk_free_gib,
    max_429_count,
    disk_path,
    meminfo_path,
    unit,
    journalctl_bin,
) = sys.argv[1:10]
min_swap_free_mib = int(min_swap_free_mib)
min_disk_free_gib = float(min_disk_free_gib)
max_429_count = int(max_429_count)

alerts = []
payload = {"event": "spicyengine_healthcheck", "health_ok": False}

try:
    req = Request(health_url, headers={"User-Agent": "spicyengine-healthcheck/1"})
    with urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        http_status = getattr(resp, "status", None)
        payload["http_status"] = http_status
        status_ok = (http_status == 200) if health_url.startswith(("http://", "https://")) else True
        if isinstance(data, dict):
            index = data.get("index") if isinstance(data.get("index"), dict) else {}
            serenedb = data.get("serenedb") if isinstance(data.get("serenedb"), dict) else {}
            db_ok = (serenedb.get("connected") is True) if "connected" in serenedb else True
            index_ok = (index.get("ready") is True) if "ready" in index else True
            payload["health_ok"] = bool(status_ok and data.get("ok") is True and db_ok and index_ok)
            payload["release_id"] = data.get("release_id") or index.get("release_id")
            payload["search_type"] = data.get("searchType") or index.get("searchType")
            payload["documents"] = index.get("documents") if "documents" in index else data.get("documents")
            payload["sections"] = index.get("sections") if "sections" in index else data.get("sections")
        if not payload["health_ok"]:
            alerts.append("health_not_ok")
except (OSError, URLError, ValueError) as exc:
    payload["health_error"] = str(exc)
    alerts.append("health_unreachable")

try:
    err_proc = subprocess.run(
        [journalctl_bin, "-u", unit, "-p", "err", "--since", lookback, "--no-pager", "-q"],
        check=True, capture_output=True, text=True,
    )
    err_lines = [line for line in err_proc.stdout.splitlines() if line.strip() and not line.startswith("-- ")]
    payload["err_lines_15m"] = len(err_lines)
    if err_lines:
        alerts.append(f"service_errors:{len(err_lines)}")
except (OSError, subprocess.SubprocessError) as exc:
    payload["journal_err_check_failed"] = str(exc)
    alerts.append("journal_err_unavailable")

try:
    all_proc = subprocess.run(
        [journalctl_bin, "-u", unit, "--since", lookback, "--no-pager", "-q"],
        check=True, capture_output=True, text=True,
    )
    count_429 = sum(1 for line in all_proc.stdout.splitlines() if re.search(r'"\s+429\b|\bHTTP/1\.[01]"\s+429\b|\b429\s+Too Many', line))
    payload["rate_limit_429_15m"] = count_429
    if count_429 >= max_429_count:
        alerts.append(f"rate_limit_429_burst:{count_429}")
except (OSError, subprocess.SubprocessError) as exc:
    payload["journal_429_check_failed"] = str(exc)
    alerts.append("journal_429_unavailable")

mem_file = Path(meminfo_path)
if mem_file.is_file():
    mem = {}
    for line in mem_file.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("SwapTotal:", "SwapFree:", "MemAvailable:"):
            mem[parts[0][:-1]] = int(parts[1]) * 1024
    if "SwapTotal" in mem and "SwapFree" in mem:
        swap_total_mib = round(mem["SwapTotal"] / (1024 ** 2), 1)
        swap_free_mib = round(mem["SwapFree"] / (1024 ** 2), 1)
        payload["swap_total_mib"] = swap_total_mib
        payload["swap_free_mib"] = swap_free_mib
        if mem["SwapTotal"] > 0 and swap_free_mib < min_swap_free_mib:
            alerts.append(f"low_swap_free:{swap_free_mib}MiB")
    if "MemAvailable" in mem:
        payload["mem_available_mib"] = round(mem["MemAvailable"] / (1024 ** 2), 1)

st = os.statvfs(disk_path)
disk_free_gib = round((st.f_bavail * st.f_frsize) / (1024 ** 3), 2)
payload["disk_free_gib"] = disk_free_gib
if disk_free_gib < min_disk_free_gib:
    alerts.append(f"low_disk_free:{disk_free_gib}GiB")

payload["alerts"] = alerts
payload["status"] = "alert" if alerts else "ok"
print(json.dumps(payload, sort_keys=True))
PY
)

status=$(printf '%s\n' "$result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["status"])')
priority=user.info
rc=0
if [ "$status" != "ok" ]; then
    priority=user.err
    rc=1
fi
printf '%s\n' "$result"
if command -v "$LOGGER_BIN" >/dev/null 2>&1; then
    "$LOGGER_BIN" -t spicyengine-healthcheck -p "$priority" -- "$result" || true
fi
exit "$rc"
