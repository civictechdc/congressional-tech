"""Finite selection for a frozen failed-URL recovery campaign."""

from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlsplit

import pyarrow as pa


def completed_from_tables(rows, *, fetch_outcomes=None, states=None, captures=None, snapshot=None):
    """Build a verified per-run ``completed`` mapping directly from raw_archive tables without scanning .jsonl.gz."""
    campaign_urls = {row["url"] for row in rows if isinstance(row, Mapping) and row.get("url")}
    result = {}

    if snapshot is not None and hasattr(snapshot, "states_for"):
        for url, state_row in snapshot.states_for(campaign_urls).items():
            if url in campaign_urls:
                result[url] = dict(
                    attempts=int(state_row.get("attempts") or 0),
                    latest_state=dict(state_row, url=url),
                )

    for src in (fetch_outcomes, states):
        if src is None:
            continue
        rows_iter = src.to_pylist() if isinstance(src, pa.Table) else list(src)
        for state_row in rows_iter:
            url = state_row.get("url") or state_row.get("context_url")
            if url not in campaign_urls:
                continue
            attempts = int(state_row.get("attempts") if state_row.get("attempts") is not None else 1)
            normalized = dict(state_row, url=url)
            if "outcome" not in normalized and "resolution" in normalized:
                normalized["outcome"] = normalized["resolution"]
            result[url] = dict(
                attempts=attempts,
                latest_state=normalized,
            )

    if captures is not None:
        rows_iter = captures.to_pylist() if isinstance(captures, pa.Table) else list(captures)
        counts = Counter()
        latest_by_url = {}
        for cap_row in rows_iter:
            url = cap_row.get("context_url") or cap_row.get("url")
            if url not in campaign_urls:
                continue
            counts[url] += 1
            prev = latest_by_url.get(url)
            if prev is None or (cap_row.get("retrieved_at") or "") >= (prev.get("retrieved_at") or ""):
                latest_by_url[url] = cap_row
        for url, cap_row in latest_by_url.items():
            if url not in result:
                result[url] = dict(
                    attempts=counts[url],
                    latest_state=dict(
                        url=url,
                        outcome=cap_row.get("resolution") or cap_row.get("outcome"),
                        next_attempt_at=cap_row.get("next_attempt_at"),
                        http_status=cap_row.get("http_status"),
                        retrieved_at=cap_row.get("retrieved_at"),
                        body_key=cap_row.get("body_key"),
                        attempts=counts[url],
                    ),
                )
    return result


def _normalize_completed_run(run, campaign_rows):
    if isinstance(run, pa.Table):
        return completed_from_tables(campaign_rows, fetch_outcomes=run)
    if hasattr(run, "states_for"):
        return completed_from_tables(campaign_rows, snapshot=run)
    if isinstance(run, (list, tuple)):
        return completed_from_tables(campaign_rows, fetch_outcomes=run)
    return run


def plan_recovery(rows, completed=(), now=None, *, max_cycles=2, fetch_outcomes=None, states=None, captures=None):
    """Admit untouched URLs once, plus one due follow-up for generating ZIPs.

    `completed` contains verified per-run URL states (or `fetch_outcomes` / `state`
    Arrow tables), never the submitted list: a URL waiting at an admission deadline
    has not consumed a cycle. Saved and other unsuccessful outcomes stop. This does
    not reschedule general failures.
    """
    if now is None or max_cycles not in (1, 2) or now.tzinfo is None:
        raise ValueError("Recovery needs an aware clock and at most two cycles")
    rows = list(rows)
    states_map = {row["url"]: row for row in rows}
    cycles = Counter()
    runs = [_normalize_completed_run(run, rows) for run in (completed or ())]
    if fetch_outcomes is not None or states is not None or captures is not None:
        table_run = completed_from_tables(
            rows,
            fetch_outcomes=fetch_outcomes,
            states=states,
            captures=captures,
        )
        if table_run:
            runs.append(table_run)
    for run in runs:
        for url, item in run.items():
            if url not in states_map or not 0 <= item["attempts"] <= 4:
                raise ValueError("Completed attempts fall outside the frozen campaign")
            state = item["latest_state"]
            if state["url"] != url:
                raise ValueError("Receipt URL differs from saved state")
            states_map[url] = state
            cycles[url] += 1
    due, waiting, finished = [], [], []
    for url, state in states_map.items():
        if not cycles[url]:
            due.append(url)
            continue
        parsed = urlsplit(url)
        generating = (
            state["outcome"] == "retry_later"
            and parsed.hostname == "www.govinfo.gov"
            and parsed.path.startswith("/content/pkg/")
            and parsed.path.endswith(".zip")
        )
        if not generating or cycles[url] >= max_cycles:
            finished.append(url)
            continue
        when = datetime.fromisoformat(state["next_attempt_at"])
        if when.tzinfo is None:
            raise ValueError("A generation follow-up needs an aware retry time")
        if when <= now:
            due.append(url)
        else:
            waiting.append({"url": url, "next_attempt_at": when.isoformat()})
    return dict(
        due=sorted(due),
        waiting=sorted(waiting, key=lambda x: (x["next_attempt_at"], x["url"])),
        finished=sorted(finished),
        cycles=dict(cycles),
    )
