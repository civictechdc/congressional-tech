"""Import existing transcript JSON bytes; never fetch or generate transcript text.

Validation reuses ``Transcript.from_json`` and checks its schema version. The
typed reader checks declared fields and scalar types while preserving unknown
fields and labels. It does not establish speaker-reference integrity, attendance
or actual times.
``ContentSchema`` names the declared format; it is not a validation certificate.
Each otherwise-readable representation carries this explicit validation limit.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256

from committee_meeting.common import Identifier, Ref
from committee_meeting.issues import DataIssue
from committee_meeting.materials import (
    ContentSchema,
    Material,
    MaterialLink,
    MaterialRelation,
    MaterialVersion,
    Representation,
    TextDetails,
)
from committee_meeting.provenance import Method, RetainedContent

from congress_api.adapters.common import AdapterContext, MeetingLookupKey, meeting_lookup_key, reported_time, web_url
from congress_api.models.transcription import SCHEMA_VERSION, Transcript


@dataclass(frozen=True)
class TranscriptInput:
    """Original bytes and their caller-supplied name and retained location.

    The caller reads or downloads the body. The adapter never accesses ``uri``;
    it records that location as evidence, even when the body is invalid.
    """

    data: bytes
    name: str
    uri: str


def records(
    inputs: Iterable[TranscriptInput],
    context: AdapterContext,
    *,
    meetings: Mapping[MeetingLookupKey, Ref] | None = None,
    source_versions: Mapping[tuple[str, str], Ref] | None = None,
):
    """Yield retained bodies and evidenced associations from explicit lookups.

    A verified ``('govinfo', package_id)`` version receives parsed GPO JSON as
    another representation. Otherwise that body remains a standalone derived
    text product. Generated transcripts are separate materials; known recording
    versions may be supplied under ``('youtube', video_id)`` or
    ``('senate', video_id)``. No participant roster becomes attendance, no local
    speaker key becomes a person, and no header time becomes an actual start.

    Retained URIs locate evidence for the exporter. They are deliberately
    absent from public ``locations``; publishing bytes is a separate operation.
    """
    emitted = set()
    for item in inputs:
        data = item.data
        digest = sha256(data).hexdigest()
        retained = RetainedContent(uri=item.uri, sha256=digest)
        error = None
        try:
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("transcript body is not a JSON object")
        except (ValueError, UnicodeDecodeError) as exc:
            payload = {"filename": item.name}
            error = str(exc)
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        origin = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        producer = str(origin.get("kind") or "unknown")
        package = str(header.get("package_id") or "")
        video = str(origin.get("video_id") or "")
        # Provider IDs establish product identity; filenames only scope otherwise
        # unidentifiable retained artifacts, never establish meeting identity.
        native = package if producer == "gpo_print" and package else video or item.name
        key = f"transcript:{producer}:{native}"
        source = context.source(f"{key}:sha256:{digest}", payload, url=web_url(origin.get("url")))
        source = source.model_copy(update={"retained": retained})
        if source.id in emitted:
            continue
        yield source
        emitted.add(source.id)
        evidence = context.evidence(
            source, basis="derived",
            method=Method(name="congress_api.adapters.transcripts.import", version="1"),
        )
        if error is None:
            try:
                # Reuse the body owner's deserializer; preserve the original
                # bytes rather than reserializing its typed interpretation.
                Transcript.from_json(data.decode("utf-8-sig"))
                if payload.get("schema_version") != SCHEMA_VERSION:
                    raise ValueError(f"unsupported transcript schema version: {payload.get('schema_version')!r}")
            except (ValueError, TypeError, KeyError, AttributeError, UnicodeDecodeError) as exc:
                error = str(exc)

        source_version = None
        if producer == "gpo_print" and package:
            source_version = (source_versions or {}).get(("govinfo", package))
        if source_version and source_version.kind != "material_version":
            raise ValueError("transcript source lookup must contain material_version references")
        material_ref = None
        if source_version:
            version_ref = source_version
        else:
            material_id = context.ids("material", key)
            material_ref = Ref(kind="material", id=material_id)
            try:
                congress = int(header["congress"]) if header.get("congress") else None
                if congress is not None and (isinstance(header["congress"], bool) or congress <= 0):
                    raise ValueError
            except (ValueError, TypeError):
                congress = None
            chamber = str(header.get("chamber") or "").lower()
            chamber = chamber if chamber in ("house", "senate", "joint") else "unknown"
            proceeding_date = None
            try:
                proceeding_date = reported_time(header.get("date"))
            except (ValueError, TypeError):
                yield DataIssue(
                    id=context.ids("data_issue", f"{key}:{digest}:proceeding-date"),
                    subject=Ref(kind="source_record", id=source.id),
                    category="unverified", summary="The retained proceeding date could not be interpreted.",
                    field_path="/payload/header/date", detected_at=context.now,
                    provenance=evidence,
                )
            if material_id not in emitted:
                yield Material(
                    id=material_id,
                    identifiers=(Identifier(scheme="transcript.product", value=native, scope=producer),),
                    title=header.get("title") if isinstance(header.get("title"), str) else None,
                    congress=congress, chamber=chamber,
                    proceeding_dates=(proceeding_date,) if proceeding_date else (),
                    details=TextDetails(
                        category="captions" if producer in ("youtube_captions", "senate_captions") else "transcript",
                        production="automatic" if producer in ("gemini_transcription", "gpo_print") else "unknown",
                    ), provenance=evidence,
                )
                emitted.add(material_id)
            version_id = context.ids("material_version", f"{key}:{digest}")
            version_ref = Ref(kind="material_version", id=version_id)
            generated = None
            try:
                generated = reported_time(origin.get("generated_at"))
            except (ValueError, TypeError):
                yield DataIssue(
                    id=context.ids("data_issue", f"{key}:{digest}:generation-date"),
                    subject=Ref(kind="source_record", id=source.id),
                    category="unverified", summary="The retained generation date could not be interpreted.",
                    field_path="/payload/source/generated_at", detected_at=context.now,
                    provenance=evidence,
                )
            if version_id not in emitted:
                yield MaterialVersion(
                    id=version_id, material=material_ref, generated_at=generated,
                    provenance=evidence,
                )
                emitted.add(version_id)

        representation_id = context.ids("representation", f"{key}:{digest}:json")
        representation_ref = Ref(kind="representation", id=representation_id)
        if representation_id in emitted:
            continue
        yield Representation(
            id=representation_id, version=version_ref, media_type="application/json",
            format_label="Structured transcript JSON", encoding="utf-8", byte_size=len(data),
            sha256=digest, retained=retained,
            content_schema=ContentSchema(name="congress_api.transcribe.Transcript", version=SCHEMA_VERSION) if error is None else None,
            provenance=evidence,
        )
        emitted.add(representation_id)
        if error is not None:
            yield DataIssue(
                id=context.ids("data_issue", f"{key}:{digest}:body-schema"),
                subject=representation_ref, category="unverified", impact="blocks_use",
                summary="The retained transcript body could not be read with the supported body schema.",
                explanation=error, detected_at=context.now, provenance=evidence,
            )
        else:
            yield DataIssue(
                id=context.ids("data_issue", f"{key}:{digest}:validation-limits"),
                subject=representation_ref, category="unverified", field_path="/content_schema",
                summary="Transcript structure is validated; speaker references and source claims remain unverified.",
                explanation="The owner's typed reader validated declared fields and scalar types, and the importer checked schema_version. Unknown fields and role labels are retained. These checks do not establish local speaker-reference integrity, attendance or actual meeting times.",
                detected_at=context.now, provenance=evidence,
            )
        if isinstance(payload.get("participants"), dict) and payload["participants"]:
            yield DataIssue(
                id=context.ids("data_issue", f"{key}:{digest}:contextual-roster"),
                subject=Ref(kind="source_record", id=source.id),
                category="unverified", field_path="/payload/participants",
                summary="The transcript participant roster does not establish meeting attendance.",
                explanation="Participants may include contextual committee or other-hearing rosters. Names, roles and local speaker keys remain in the body; this import creates no attendance, appearance or global person records from them.",
                detected_at=context.now, provenance=context.evidence(source, selector="/participants"),
            )
        notes = origin.get("notes")
        if header.get("time_convened") and isinstance(notes, str) and re.search(r"\btime_convened\s+is\s+(?:the\s+)?scheduled\b", notes, re.IGNORECASE):
            yield DataIssue(
                id=context.ids("data_issue", f"{key}:{digest}:scheduled-time"),
                subject=Ref(kind="source_record", id=source.id),
                category="unverified", field_path="/payload/header/time_convened",
                summary="The transcript's convening time is reported as a scheduled time.",
                explanation="The producer's source.notes explicitly identifies this value as scheduled. The original header and note are retained; this import does not assign an actual meeting start time.",
                detected_at=context.now, provenance=context.evidence(source, selector="/source/notes"),
            )

        if material_ref:
            event_id = str(header.get("event_id") or "")
            meeting = (meetings or {}).get(meeting_lookup_key(congress, chamber, event_id)) if event_id else None
            if meeting:
                if meeting.kind != "meeting":
                    raise ValueError("transcript meeting lookup must contain meeting references")
                yield MaterialLink(
                    id=context.ids("material_link", f"{key}:{digest}:meeting:{meeting.id}"),
                    material=material_ref, version=version_ref, subject=meeting,
                    role="captions" if producer in ("youtube_captions", "senate_captions") else "transcript",
                    provenance=context.evidence(
                        source, basis="derived", selector="/header/event_id",
                        method=Method(name="congress_api.adapters.transcripts.exact-event", version="1"),
                    ),
                )
            else:
                yield DataIssue(
                    id=context.ids("data_issue", f"{key}:{digest}:unlinked"),
                    subject=material_ref, category="unlinked",
                    summary="This retained transcript has no verified meeting association.",
                    explanation="Its header, participants and local speaker keys remain in the original body.",
                    detected_at=context.now, provenance=evidence,
                )

            origin_provider = "senate" if producer == "senate_captions" else "youtube"
            related = (source_versions or {}).get((origin_provider, video)) if video else None
            if related:
                if related.kind != "material_version":
                    raise ValueError("transcript source lookup must contain material_version references")
                yield MaterialRelation(
                    id=context.ids("material_relation", f"{key}:{digest}:derived-from:{related.id}"),
                    subject=version_ref, related=related, relation="derived_from",
                    provenance=evidence,
                )
