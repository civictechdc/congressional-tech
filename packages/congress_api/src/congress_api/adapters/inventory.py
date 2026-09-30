"""Retained caption, archive-probe and recovered-witness observations.

No media is acquired and no caption track is invented. The caller supplies
known recording identities and filters recovered rows already represented by
native or committee-source appearances. Convert a separate recovered CSV with
its own AdapterContext so its input_snapshot_id names that artifact.
"""

import json
from collections import defaultdict
from datetime import date, datetime

from committee_meeting.assessments import Assessment
from committee_meeting.common import ReportedTime
from committee_meeting.issues import DataIssue
from committee_meeting.meetings import Affiliation, Appearance, RecordedName
from committee_meeting.provenance import Method

from congress_api.adapters.common import digest, observed_time, ref, web_url, witness_roles
from congress_api.models.base import SourceModel
from congress_api.parsers.senate_player import LIVE_ID, STREAM, archive_url, live_url, parse_player_url


def records(state, context, *, meetings, materials=None, recovered_witnesses=()):
    """Adapt current inventory.json.gz plus optional already-recovered CSV rows."""
    materials = materials or {}
    if any(target.kind != "material" for target in materials.values()):
        raise ValueError("Inventory material lookup must contain material references")
    by_event = defaultdict(list)
    for (_, _, event), meeting in meetings.items():
        if meeting.kind != "meeting":
            raise ValueError("Inventory meeting lookup must contain meeting references")
        by_event[str(event)].append(meeting)
    recovered_witnesses = list(recovered_witnesses)
    owned_sources = {
        ({"gpo": "mods", "witness list document": "witness_lists"}[row["source"]], row["from"])
        for row in recovered_witnesses
        if isinstance(row, dict) and row.get("source") in ("gpo", "witness list document")
        and isinstance(row.get("from"), str) and row["from"]
        and isinstance(row.get("name"), str) and row["name"].strip()
        and len(by_event.get(str(row.get("event_id") or ""), [])) == 1
        and all(row.get(field) is None or isinstance(row[field], str) for field in ("position", "organization"))
    }

    def issue(source, code, category, summary, explanation=None):
        return DataIssue(
            id=context.ids("data_issue", source.id + "|" + code), subject=ref(source),
            category=category, summary=summary, explanation=explanation,
            detected_at=context.now, provenance=context.evidence(source),
        )

    for provider in ("youtube", "senate"):
        kinds = state.get(provider) or {}
        observations = (state.get('caption_observations') or {}).get(provider) or {}
        for native_id in sorted(set(kinds) | set(observations)):
            kind = kinds.get(native_id)
            receipt = observations.get(native_id)
            if isinstance(receipt, SourceModel):
                receipt = receipt.source_dict()
            payload = {"provider": provider, "recording_id": native_id, "kind": kind}
            if receipt is not None:
                payload['receipt'] = receipt
            source = context.source(f"captions|{provider}|{native_id}", payload)
            yield source
            target = materials.get((provider, native_id))
            if target is None:
                yield issue(source, "unlinked-caption-observation", "unlinked", "This caption observation has no known recording identity.")
            checks = [(receipt, '', '/receipt')]
            if isinstance(receipt, dict) and isinstance(receipt.get('last_successful'), dict):
                checks.append((receipt['last_successful'], '|last-successful', '/receipt/last_successful'))
            for check, suffix, selector in checks:
                checked, scope = None, None
                if isinstance(check, dict):
                    try:
                        parsed = datetime.fromisoformat(check.get('observed_at', '').replace('Z', '+00:00'))
                        if parsed.tzinfo is not None and parsed <= context.now:
                            checked = parsed
                    except (TypeError, ValueError, AttributeError):
                        pass
                    raw_scope = check.get('scope')
                    if isinstance(raw_scope, dict) and raw_scope:
                        scope = json.dumps(raw_scope, sort_keys=True, ensure_ascii=False)
                    elif isinstance(raw_scope, str) and raw_scope.strip():
                        scope = raw_scope
                    reported = check.get('outcome') or check.get('kind')
                    positive = reported in ('available', 'manual', 'auto', 'webvtt')
                    status = ('error' if reported == 'error' else 'available' if positive else
                              'not_found' if reported in ('none', 'not_found') and checked and scope else 'unknown')
                else:
                    positive = isinstance(kind, str) and kind in ({'manual', 'auto'} if provider == 'youtube' else {'webvtt'})
                    status = 'available' if positive else 'unknown'
                if checked is None:
                    yield issue(source, 'undated-caption-observation' + suffix, 'unverified',
                        'The caption observation has no supported observation date.',
                        'Index-only observations remain undated. Import time and file modification time are not capture times.')
                if target is None:
                    continue
                explanation = ('The latest caption check failed; its error is retained separately from any earlier successful capture.' if status == 'error'
                    else 'The retained receipt reports captions within its recorded source scope.' if status == 'available' and checked
                    else 'The retained check found no captions within its recorded source scope.' if status == 'not_found'
                    else 'The retained index reports captions, but its original observation time and track contents are not retained.' if positive
                    else 'The retained value does not establish a dated negative caption check.')
                if suffix:
                    explanation = 'Earlier successful observation retained after a failed refresh. ' + explanation
                yield Assessment(
                    id=context.ids('assessment', f'captions|{provider}|{native_id}' + suffix), subject=target,
                    aspect='captions', status=status, evaluated_at=context.now, observed_at=checked,
                    provider=provider, scope=scope or f'Retained caption index for {provider}:{native_id}',
                    explanation=explanation,
                    provenance=context.evidence(source, selector=selector if isinstance(check, dict) else None),
                )

    for native_key, observation in sorted((state.get("probes") or {}).items()):
        if isinstance(observation, SourceModel):
            observation = observation.source_dict()
        source = context.source("probe|" + native_key, observation if observation is not None else {"unparsed_value": None})
        yield source
        if not isinstance(observation, dict):
            yield issue(source, "invalid-probe", "unverified", "A retained probe row could not be interpreted.")
            continue
        checked = None
        if observation.get("source") == "HEAD":
            try:
                parsed = date.fromisoformat(observation["checked"])
                if parsed <= context.now.date():
                    checked = ReportedTime(date=parsed, original=observation["checked"])
            except (KeyError, TypeError, ValueError):
                pass
        if checked is None:
            yield issue(source, "unverified-probe-date", "unverified", "The probe has no supported live check date.",
                        "Research HEAD cache dates come from the imported file's modification time. They are not source observation times.")
        targets = {}
        raw_urls = observation.get("urls") or []
        valid_urls = isinstance(observation.get("urls"), list) and all(web_url(url) and parse_player_url(url) for url in raw_urls)
        if not valid_urls:
            yield issue(source, "invalid-probe-urls", "unverified", "The retained probe has no interpretable complete URL list.")
        for url in raw_urls if isinstance(raw_urls, list) else []:
            player = parse_player_url(url) if web_url(url) else None
            if player and (target := materials.get(("senate", player[1]))):
                targets[target.id] = (target, True, url)
        # Only a source explicitly marked HEAD establishes that this producer
        # tested all four names. Intersect that scope with existing materials.
        if observation.get("source") == "HEAD" and valid_urls:
            try:
                comm, day = native_key.split("|", 1)
                held = date.fromisoformat(day)
            except (ValueError, TypeError):
                comm = ""
            if comm in STREAM and comm in LIVE_ID:
                for filename in (f"{comm}{held:%m%d%y}", f"{comm}A{held:%m%d%y}", f"{comm}B{held:%m%d%y}", f"{comm}{held:%m%d%y}p"):
                    target = materials.get(("senate", filename))
                    if target and target.id not in targets:
                        targets[target.id] = (target, False, f"HEAD {archive_url(comm, filename)} and {live_url(comm, filename)}")
        for target, positive, scope in targets.values():
            yield Assessment(
                id=context.ids("assessment", "probe|" + native_key + "|" + target.id), subject=target,
                aspect="recording", status="available" if positive else "not_found" if checked else "unknown",
                evaluated_at=context.now, observed_at=checked, provider="senate", scope=scope,
                explanation="The retained probe reports an available player." if positive else "No recording was found within the retained archive/live HEAD probe's scope.",
                provenance=context.evidence(source, basis="derived", method=Method(name="congress_api.inventory.captions.probe_day", version="1")),
            )
        if not targets:
            yield issue(source, "unlinked-probe", "unlinked", "This committee/day probe has no known recording association.",
                        "Its source scope is retained. A committee and date alone do not establish a meeting identity.")

    retained_people = {}
    for family in ("mods", "witness_lists"):
        for native_key, observation in sorted((state.get(family) or {}).items()):
            if isinstance(observation, SourceModel):
                observation = observation.source_dict()
            source = context.source(f"{family}|{native_key}", observation if observation is not None else {"unparsed_value": None}, observation.get("url") if isinstance(observation, dict) else None)
            check = (observation.get("observation_check") or observation.get("last_check") or {}) if isinstance(observation, dict) else {}
            checked = observed_time(check.get("completed_at"), context.now) if isinstance(check, dict) and check.get("mode") == "live" and check.get("url") == source.url else None
            successful = checked is not None and (check.get("status_code"), check.get("outcome")) in ((200, "present"), (404, "not_found"))
            if successful and check["status_code"] == 200:
                source = source.model_copy(update={"retrieved_at": checked})
            retained_people[family, native_key] = source
            yield source
            if not successful:
                yield issue(source, "unverified-retrieval", "unverified", "The retained witness source has no supported live retrieval check.",
                            "Its checked day and any import time are preserved in the payload and are not promoted to retrieval timestamps.")
            latest = observation.get("last_check") if isinstance(observation, dict) else None
            if isinstance(latest, dict) and latest.get("outcome") == "error":
                yield issue(source, "witness-source-check-failed", "unverified", "The latest witness source check failed.",
                            "Earlier successful witness data is retained when available; the failure is preserved separately in last_check.")
            if (not isinstance(observation, dict) or observation.get("people")) and (family, native_key) not in owned_sources:
                yield issue(source, "unlinked-witness-source", "unlinked", "Witness rows have no meeting ownership in this source record.",
                            "A recovered row with an explicit, unique event association is required before creating an appearance.")

    seen_rows = set()
    for row in recovered_witnesses:
        row_key = digest(row)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        source = context.source("recovered-witness|" + row_key, row if row is not None else {"unparsed_value": None}, row.get("from") if isinstance(row, dict) else None)
        yield source
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
            yield issue(source, "invalid-witness", "unverified", "A recovered witness row has no usable name.")
            continue
        candidates = by_event.get(str(row.get("event_id") or ""), [])
        if len(candidates) != 1:
            yield issue(source, "unlinked-witness", "unlinked", "The recovered row has no unique meeting association.",
                        f"Its event identifier resolves to {len(candidates)} entries in the supplied meeting lookup.")
            continue
        origin = row.get("source")
        if origin not in ("gpo", "witness list document", "docs.house.gov", "senate committee page", "meeting title (nominees)") or not isinstance(row.get("from"), str) or not row["from"].strip():
            yield issue(source, "unsupported-witness-source", "unverified", "The recovered row lacks a supported source reference.")
            continue
        if any(row.get(field) is not None and not isinstance(row[field], str) for field in ("position", "organization")):
            yield issue(source, "invalid-affiliation", "unverified", "The recovered affiliation fields could not be interpreted.")
            continue
        nominee = origin == "meeting title (nominees)"
        provenance = context.evidence(source, basis="inferred" if nominee else "derived",
                                      method=Method(name="congress_api.inventory.completeness.nominees" if nominee else "congress_api.inventory.completeness.build", version="1"))
        family = {"gpo": "mods", "witness list document": "witness_lists"}.get(origin)
        underlying = retained_people.get((family, row["from"])) if family else None
        if underlying:
            provenance = provenance.model_copy(update={"citations": provenance.citations + context.evidence(underlying).citations})
        yield Appearance(
            id=context.ids("appearance", "recovered-witness|" + row_key), meeting=candidates[0], name=RecordedName(display=row["name"]),
            roles=("nominee",) if nominee else witness_roles(row.get("position")), participation="listed",
            affiliation=Affiliation(position=row.get("position") or None, organization_name=row.get("organization") or None),
            provenance=provenance,
        )
