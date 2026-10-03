"""Resume missing captures and explicit related files using injected storage/HTTP."""

from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import time

from congress_api.models.content import RawContent
from congress_api.parsers.archive_links import inspect_capture
from congress_api.retention.raw_archive import BodyLimitExceeded
from congress_api.retention import raw_progress as progress


def run_sync(
    archive,
    seeds,
    *,
    fetch,
    limit=5000,
    workers=8,
    max_seconds=5400,
    stop=None,
    publish=None,
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
                if not active:
                    break
                done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
                for future in done:
                    state = active.pop(future)
                    response, mode = future.result()
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
                    counts[outcome] += 1
                    counts[mode] += 1
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
        archive.save()
        catalog = publish(archive) if publish else None
    if fatal:
        raise RuntimeError(
            "Zyte authorization failed; in-flight captures were retained before stopping."
        )
    return dict(
        counts,
        attempted=submitted,
        known_urls=len(archive.state),
        remaining=sum(
            s["outcome"] not in {"saved", "excluded_media"}
            for s in archive.state.values()
        ),
        limit=limit,
        transport_budget_seconds=max_seconds,
        catalog=catalog,
    )
