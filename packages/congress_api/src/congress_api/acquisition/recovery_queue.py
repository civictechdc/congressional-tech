"""Finite selection for a frozen failed-URL recovery campaign."""

from collections import Counter
from datetime import datetime
from urllib.parse import urlsplit


def plan_recovery(rows, completed, now, *, max_cycles=2):
    """Admit untouched URLs once, plus one due follow-up for generating ZIPs.

    `completed` contains verified per-run URL states, never the submitted list:
    a URL waiting at an admission deadline has not consumed a cycle. Saved and
    other unsuccessful outcomes stop. This does not reschedule general failures.
    """
    if max_cycles not in (1, 2) or now.tzinfo is None:
        raise ValueError("Recovery needs an aware clock and at most two cycles")
    states = {row["url"]: row for row in rows}
    cycles = Counter()
    for run in completed:
        for url, item in run.items():
            if url not in states or not 0 <= item["attempts"] <= 4:
                raise ValueError("Completed attempts fall outside the frozen campaign")
            state = item["latest_state"]
            if state["url"] != url:
                raise ValueError("Receipt URL differs from saved state")
            states[url] = state
            cycles[url] += 1
    due, waiting, finished = [], [], []
    for url, state in states.items():
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
