"""Resume missing captures and explicit related files using injected storage/HTTP."""

from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import time

import pyarrow.compute as pc

from congress_api.models.content import RawContent
from congress_api.parsers.archive_links import inspect_capture
from congress_api.retention.raw_archive import BodyLimitExceeded
from congress_api.retention import raw_progress as progress
from congress_api.retention.capture_metadata import CaptureMetadata


def run_sync(
    archive,
    seeds,
    *,
    fetch,
    limit=5000,
    workers=8,
    max_seconds=5400,
    stop=None,
    max_bytes=64 * 1024**2,
):
    context = {}
    for item in seeds:
        url = archive.seed(item)
        if url:
            context.setdefault(url, []).append(item)
    now = datetime.now(timezone.utc)
    queue = deque(
        sorted(
            (
                s
                for s in archive.state.values()
                if s["outcome"] not in {"saved", "excluded_media"}
                and (
                    not s.get("next_attempt_at")
                    or datetime.fromisoformat(s["next_attempt_at"]) <= now
                )
            ),
            key=lambda s: (
                s["outcome"] == "retained",
                s.get("checked_at") or "",
                s["url"],
            ),
        )
    )
    scheduled = {s["url"] for s in queue}
    deadline = time.monotonic() + max_seconds
    counts = Counter()
    active = {}
    submitted = 0
    fatal = False
    collector_error = None
    metadata = CaptureMetadata(archive.store, archive.run_id)
    archive.metadata = metadata

    def acquire(state):
        if state.get("body_key") and not state.get("links_scanned"):
            try:
                body = archive.body(state, max_bytes=max_bytes)
            except BodyLimitExceeded:
                return dict(
                    requested_url=state["url"],
                    url=state["url"],
                    retrieved_at=state.get("retrieved_at"),
                    http_status=state.get("http_status"),
                    complete=False,
                    error="retained_body_limit",
                    retained_body_key=state["body_key"],
                ), "replay"
            return dict(
                requested_url=state["url"],
                url=state["url"],
                http_status=state.get("http_status"),
                complete=True,
                retrieved_at=state.get("retrieved_at"),
                content=RawContent.from_bytes(
                    body, state.get("media_type") or ""
                ).source_dict(),
            ), "replay"
        return fetch(state["url"]), "fetch"

    progress.report('acquire_sources', completed=0, unit='capture_attempts')
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while queue or active:
                while (
                    queue
                    and not fatal
                    and len(active) < workers
                    and submitted < limit
                    and time.monotonic() < deadline
                    and not (stop and stop.is_set())
                ):
                    state = queue.popleft()
                    active[pool.submit(acquire, state)] = state
                    submitted += 1
                    progress.advance("capture_tasks_submitted")
                if not active:
                    break
                done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
                if metadata.flush_due():
                    archive.flush()
                if not done:
                    continue
                # Consume one completion, then refill its slot immediately.
                # A slow upload must not delay scheduling every completed slot.
                future = next(iter(done))
                state = active.pop(future)
                try:
                    response, mode = future.result()
                except Exception as error:
                    # Drain successes already in flight before saving and failing.
                    collector_error = collector_error or error
                    fatal = True
                    counts["collector_failed_tasks"] += 1
                    progress.advance("collector_failed_tasks")
                    continue
                outcome, links = inspect_capture(response, replay=mode == "replay")
                for link in links:
                    link["parent_url"] = state["url"]
                    link["parent_sha256"] = response.get("content", {}).get(
                        "sha256"
                    )
                archive.record(
                    response,
                    outcome=outcome,
                    links=links,
                    mode=mode,
                    context={"observations": context.get(state["url"], [])},
                    scanned=outcome != "inspection_deferred",
                )
                if metadata.flush_due():
                    archive.flush()
                counts[outcome] += 1
                counts[mode] += 1
                progress.advance("capture_tasks_completed")
                progress.advance("usable_capture_results", int(outcome == "saved"))
                progress.report('acquire_sources', completed=counts['fetch'] + counts['replay'],
                                unit='capture_attempts')
                counts["zyte_fallbacks"] += bool(response.get("prior_attempts"))
                for link in links:
                    child = archive.state.get(link["url"])
                    if (
                        child
                        and child["outcome"] == "pending"
                        and child["url"] not in scheduled
                    ):
                        queue.append(child)
                        scheduled.add(child["url"])
                if response.get("provider_http_status") in (401, 403):
                    fatal = True
    finally:
        progress.report('save_capture_indexes')
        try:
            archive.save()
        finally:
            try:
                metadata.writer.close()
            finally:
                archive.metadata = None
    if collector_error is not None:
        raise collector_error
    if stop and stop.is_set():
        raise InterruptedError("Capture stopped; completed receipts and state were saved.")
    if fatal:
        raise RuntimeError(
            "Zyte authorization failed; in-flight captures were retained before stopping."
        )
    return dict(
        counts,
        body_metadata=dict(metadata.counts),
        accounting={
            "known_urls": len(archive.state),
            "known_urls_basis": "distinct normalized URLs in download state; includes source pages and retryable failures",
            "urls_by_source_family": dict(Counter(row.get("family") or "unknown" for row in archive.state.values())),
            "usable_capture_results_basis": "this run's completed tasks classified saved; includes linked source pages",
            "unique_retained_body_keys_basis": "distinct nonempty body keys referenced by the saved capture index; includes error/provider bytes and does not check storage existence",
            "excluded_media_urls": sum(row["outcome"] == "excluded_media" for row in archive.state.values()),
            "capture_tasks_submitted": submitted,
            "capture_tasks_completed": counts["fetch"] + counts["replay"],
            "fetch_tasks_completed": counts["fetch"],
            "retained_replays_completed": counts["replay"],
            "usable_capture_results": counts["saved"],
            "unique_retained_body_keys": pc.count_distinct(pc.filter(
                archive.captures["body_key"], pc.not_equal(archive.captures["body_key"], "")
            )).as_py(),
            "url_outcomes": dict(Counter(row["outcome"] for row in archive.state.values())),
        },
        attempted=submitted,
        known_urls=len(archive.state),
        remaining=sum(
            s["outcome"] not in {"saved", "excluded_media"}
            for s in archive.state.values()
        ),
        limit=limit,
        transport_budget_seconds=max_seconds,
    )
