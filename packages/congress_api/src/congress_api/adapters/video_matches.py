"""Import retained GPO recording decisions without rerunning their matcher.

Legacy rows aggregate methods, maximum score, durations and channels across
videos. Those fields remain source evidence; they are neither a probability nor
an explanation for each individual recording-to-meeting association.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlsplit

from committee_meeting.assessments import Assessment
from committee_meeting.common import Identifier, Ref
from committee_meeting.issues import DataIssue
from committee_meeting.materials import (
    Material,
    MaterialLink,
    MaterialLocation,
    MaterialVersion,
    RecordingDetails,
    Representation,
)
from committee_meeting.provenance import Method, Provenance

from congress_api.adapters.common import AdapterContext, web_url
from congress_api.adapters.recordings import offsite_reference


def records(
    rows: Iterable[Mapping[str, Any]],
    context: AdapterContext,
    *,
    packages: Mapping[str, Ref],
    recordings: Mapping[str, tuple[Ref, Ref]] | None = None,
    package_meetings: Mapping[str, Sequence[Ref]] | None = None,
    package_evidence: Mapping[tuple[str, str], Sequence[Provenance]] | None = None,
):
    """Yield source rows, package assessments and supported recording links.

    The application supplies existing package and recording identities. A single
    supported package-to-meeting association can support a conservative link;
    multi-meeting or multiple-date volumes need individual association evidence.
    A legacy absence has no reliable observation time and is never ``not_found``.
    """
    known_recordings = dict(recordings or {})
    for original in rows:
        row = dict(original)
        package_id = str(row.get("package_id") or "").strip()
        if not package_id:
            raise ValueError("a retained video-match row requires package_id")
        key = f"gpo-match|{package_id}"
        source = context.source(key, row)
        yield source
        reported = context.evidence(source)
        basis = "curated" if row.get("source") == "research" else "derived"
        evidence = context.evidence(
            source, basis=basis,
            method=Method(name="congress_api.adapters.video_matches.import", version="1"),
        )
        package = packages.get(package_id)
        if package is None:
            yield DataIssue(
                id=context.ids("data_issue", key + "|missing-package"),
                subject=Ref(kind="source_record", id=source.id), category="unlinked",
                summary="The recording decision's package is not present in this catalog.",
                explanation="The original decision is retained without inventing a document or meeting.",
                detected_at=context.now, provenance=reported,
            )
            continue
        if package.kind != "material":
            raise ValueError("video-match packages must contain material references")

        status = str(row.get("status") or "")
        tokens = list(dict.fromkeys(str(row.get("video_ids") or "").split()))
        accepted = status in ("full_recording", "full_recording_offsite") or (status == "clips_only" and bool(tokens))
        results = []
        association_versions = []
        if accepted:
            for token in tokens:
                offsite = status == "full_recording_offsite" or (status == "clips_only" and bool(web_url(token)))
                if offsite:
                    url = web_url(token)
                    if url:
                        recording_key, url, _, identifiers = offsite_reference(url)
                        provider = urlsplit(url).hostname
                    else:
                        recording_key, provider, identifiers = None, None, ()
                else:
                    valid_id = bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", token))
                    url = "https://www.youtube.com/watch?v=" + quote(token, safe="") if valid_id else None
                    provider = "youtube"
                    recording_key = "youtube|" + token
                    identifiers = (Identifier(scheme="youtube.video", value=token),)
                if not url:
                    yield DataIssue(
                        id=context.ids("data_issue", key + "|invalid-video|" + token),
                        subject=package, category="unverified",
                        summary="An accepted recording identifier could not be interpreted.",
                        explanation="The original video_ids value remains in the decision; no replacement URL was guessed.",
                        detected_at=context.now, provenance=reported,
                    )
                    continue
                existing = known_recordings.get(token)
                if existing is None:
                    material = Ref(kind="material", id=context.ids("material", recording_key))
                    version = Ref(kind="material_version", id=context.ids("material_version", recording_key + "|reported-edition"))
                    yield Material(
                        id=material.id, identifiers=identifiers,
                        details=RecordingDetails(medium="unknown" if offsite else "video", provider=provider),
                        provenance=evidence,
                    )
                    yield MaterialVersion(
                        id=version.id, material=material,
                        provenance=evidence,
                    )
                    yield Representation(
                        id=context.ids("representation", recording_key + "|player"), version=version,
                        locations=(MaterialLocation(url=url, role="player"),),
                        format_label="Player link" if offsite else "YouTube player", provenance=evidence,
                    )
                    known_recordings[token] = (material, version)
                else:
                    material, version = existing
                    if material.kind != "material" or version.kind != "material_version":
                        raise ValueError("recording lookups require material and material_version references")
                if material not in results:
                    results.append(material)
                    association_versions.append((material, version))

        assessment_id = context.ids("assessment", key + "|recording")
        if accepted:
            outcome = "available"
            explanation = "The retained matcher accepted recording resources for this package; individual meeting coverage remains unverified."
        elif status == "not_public" or row.get("record_type") == "errata":
            outcome = "not_applicable"
            explanation = "The retained decision treats this item as outside public-proceeding recording coverage; it does not establish that no recording exists."
        else:
            outcome = "unknown"
            explanation = (
                "The retained clips_only verdict does not identify its clips."
                if status == "clips_only" else
                "The retained matcher has no accepted recording for this package and provides no dated, exhaustive availability check."
            )
        yield Assessment(
            id=assessment_id, subject=package, aspect="recording", status=outcome,
            evaluated_at=context.now, provider="gpo-match",
            scope="Public recordings represented by the retained package-level GPO matcher output and its curated overrides.",
            explanation=explanation, results=tuple(results), provenance=evidence,
        )

        if accepted:
            yield DataIssue(
                id=context.ids("data_issue", key + "|aggregate-evidence"),
                subject=Ref(kind="assessment", id=assessment_id), category="unverified",
                summary="The retained decision aggregates its recording evidence.",
                explanation="Its method, maximum score, channels and total minutes cannot be assigned to each video. The score is a matcher rank, not a probability; the producer revision and original check time are unavailable.",
                detected_at=context.now, provenance=reported,
            )
            if not results:
                yield DataIssue(
                    id=context.ids("data_issue", key + "|missing-identifiers"),
                    subject=Ref(kind="assessment", id=assessment_id), category="missing",
                    summary="The accepted recording decision has no usable recording identifiers.",
                    expected="Identifiers for the recordings asserted by the retained accepted decision.",
                    detected_at=context.now, provenance=reported,
                )
            supported = list({m.id: m for m in (package_meetings or {}).get(package_id, ())}.values())
            if any(m.kind != "meeting" for m in supported):
                raise ValueError("package meeting associations must contain meeting references")
            dates = {value.strip() for value in str(row.get("hearing_dates") or "").split(";") if value.strip()}
            if row.get("held_date"):
                dates.add(str(row["held_date"]).strip())
            if len(supported) == 1 and len(dates) <= 1:
                meeting = supported[0]
                association = (package_evidence or {}).get((package_id, meeting.id), ())
                link_evidence = evidence
                if association:
                    citations = {c.model_dump_json(): c for ev in (evidence, *association) for c in ev.citations}
                    link_evidence = evidence.model_copy(update={
                        "citations": tuple(citations[k] for k in sorted(citations)),
                        "basis": "inferred" if all(ev.basis == "inferred" for ev in association) else evidence.basis,
                    })
                for material, version in association_versions:
                    yield MaterialLink(
                        id=context.ids("material_link", key + "|" + material.id + "|" + meeting.id),
                        material=material, version=version, subject=meeting, role="recording",
                        coverage="partial" if status == "clips_only" else "unknown", provenance=link_evidence,
                    )
            elif results:
                yield DataIssue(
                    id=context.ids("data_issue", key + "|unlinked-recordings"), subject=package,
                    category="unlinked", summary="Package-level recordings cannot yet be assigned to individual meetings.",
                    explanation="There is no single supported meeting and date combination. Shared or multiple-date volume results are retained at package level without distributing recordings across meetings.",
                    detected_at=context.now, provenance=reported,
                )
        elif status == "clips_only":
            yield DataIssue(
                id=context.ids("data_issue", key + "|unidentified-clips"), subject=package,
                category="unverified", summary="The retained clips_only verdict omits the clip identifiers.",
                explanation="No clip resources or full-recording coverage were created from this aggregate verdict.",
                detected_at=context.now, provenance=reported,
            )
