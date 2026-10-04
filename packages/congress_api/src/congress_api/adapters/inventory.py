"""Retained caption, archive-probe and recovered-witness observations.

No media is acquired and no caption track is invented. The caller supplies
known recording identities and filters recovered rows already represented by
native or committee-source appearances. Convert a separate recovered CSV with
its own AdapterContext so its input_snapshot_id names that artifact.
"""

from collections import defaultdict

from committee_meeting.assessments import Assessment
from committee_meeting.common import ReportedTime
from committee_meeting.issues import DataIssue
from committee_meeting.meetings import Affiliation, Appearance, RecordedName
from committee_meeting.provenance import Method

from congress_api.adapters.common import digest, ref, witness_roles
from congress_api.models.base import SourceModel
from congress_api.parsers.observations import caption_observations, source_check
from congress_api.parsers.senate_probes import probe_observation


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
            for observation in caption_observations(provider, kind, receipt, context.now):
                checked, scope = observation.observed_at, observation.scope
                status, positive = observation.status, observation.positive
                suffix, selector = observation.suffix, observation.selector
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
                    provenance=context.evidence(source, selector=selector),
                )

    for native_key, observation in sorted((state.get("probes") or {}).items()):
        if isinstance(observation, SourceModel):
            observation = observation.source_dict()
        source = context.source("probe|" + native_key, observation if observation is not None else {"unparsed_value": None})
        yield source
        if not isinstance(observation, dict):
            yield issue(source, "invalid-probe", "unverified", "A retained probe row could not be interpreted.")
            continue
        probe = probe_observation(native_key, observation, context.now)
        checked = ReportedTime(date=probe.observed_day, original=observation["checked"]) if probe.observed_day else None
        if checked is None:
            yield issue(source, "unverified-probe-date", "unverified", "The probe has no supported live check date.",
                        "Research HEAD cache dates come from the imported file's modification time. They are not source observation times.")
        targets = {}
        if not probe.valid_urls:
            yield issue(source, "invalid-probe-urls", "unverified", "The retained probe has no interpretable complete URL list.")
        for filename, url in probe.positive_players:
            if target := materials.get(("senate", filename)):
                targets[target.id] = (target, True, url)
        for filename, scope in probe.tested_players:
            target = materials.get(("senate", filename))
            if target and target.id not in targets:
                targets[target.id] = (target, False, scope)
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
            check = source_check(observation, source.url, context.now)
            checked, successful = check.observed_at, check.successful
            if successful and check.status_code == 200:
                source = source.model_copy(update={"retrieved_at": checked})
            retained_people[family, native_key] = source
            yield source
            if not successful:
                yield issue(source, "unverified-retrieval", "unverified", "The retained witness source has no supported live retrieval check.",
                            "Its checked day and any import time are preserved in the payload and are not promoted to retrieval timestamps.")
            if check.latest_failed:
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
