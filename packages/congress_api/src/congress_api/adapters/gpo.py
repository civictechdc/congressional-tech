"""Adapt retained GPO rows without acquiring text or inventing proceedings."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from committee_meeting.common import Identifier, Ref
from committee_meeting.issues import DataIssue
from committee_meeting.materials import (
    DocumentDetails, Material, MaterialLink, MaterialLocation, MaterialVersion,
    Representation,
)
from committee_meeting.provenance import AlternativeValue, FieldEvidence, Method

from .common import AdapterContext, reported_time, web_url


def records(
    rows: Iterable[Mapping[str, Any]],
    context: AdapterContext,
    *,
    meetings: Mapping[tuple[int, str, str], Ref] | None = None,
):
    """Yield source observations and materials for every package, including errata.

    ``meetings`` contains verified, unambiguous native identifier lookups supplied
    by the application. A package's dates, title or committee never create a
    meeting or establish a match. CSV ingestion dates are retained as evidence;
    they are not promoted to original publication dates.
    """
    for original in rows:
        row = dict(original)
        package = str(row.get("package_id") or "").strip()
        if not package:
            raise ValueError("a retained GPO row requires package_id")
        key = f"govinfo:{package}"
        source = context.source(key, row)
        evidence = context.evidence(source)
        material_id = context.ids("material", key)
        material_ref = Ref(kind="material", id=material_id)

        def issue(code, category, summary, *, explanation=None, field_path=None):
            return DataIssue(
                id=context.ids("data_issue", f"{key}:{code}"), subject=material_ref,
                category=category, summary=summary, explanation=explanation,
                field_path=field_path, detected_at=context.now,
                provenance=evidence,
            )

        issues = []

        def date_value(value, field):
            try:
                return reported_time(value)
            except (ValueError, TypeError):
                issues.append(issue(
                    f"invalid-{field}", "unverified", "A retained date could not be interpreted.",
                    explanation=f"The original {field} value remains in the source row.",
                ))
                return None

        held = date_value(row.get("held_date"), "held_date")
        header_dates = []
        for value in str(row.get("hearing_dates") or "").split(";"):
            if value.strip():
                parsed = date_value(value.strip(), "hearing_dates")
                if parsed and parsed.date not in {d.date for d in header_dates}:
                    header_dates.append(parsed)
        dates = tuple(header_dates or ([held] if held else []))
        date_evidence = ()
        if header_dates:
            selected = context.evidence(source, selector="/hearing_dates")
            alternatives = ()
            if held and held.date not in {d.date for d in header_dates}:
                alternatives = (AlternativeValue(
                    value=[held.model_dump(mode="json")],
                    provenance=context.evidence(source, selector="/held_date"),
                ),)
                issues.append(issue(
                    "date-disagreement", "conflicting",
                    "The reported held date differs from the transcript's retained day headers.",
                    explanation="Both dates remain available; neither establishes a new meeting or proves the other is incorrect.",
                    field_path="/proceeding_dates",
                ))
            date_evidence = (FieldEvidence(
                path="/proceeding_dates", selected=selected, alternatives=alternatives,
                selection_reason="Use the retained transcript day headers when supplied; otherwise use held_date.",
            ),)
        modified = date_value(row.get("last_modified"), "last_modified")
        if modified:
            source = source.model_copy(update={"source_modified_at": modified})
        yield source

        congress_raw = row.get("congress")
        try:
            congress = int(congress_raw) if congress_raw not in (None, "") else None
            if congress is not None and (isinstance(congress_raw, bool) or congress <= 0):
                raise ValueError
        except (ValueError, TypeError):
            congress = None
            issues.append(issue("invalid-congress", "unverified", "The retained Congress number could not be interpreted."))
        chamber = str(row.get("chamber") or "").lower()
        chamber = chamber if chamber in ("house", "senate", "joint") else "unknown"
        category = "errata" if row.get("record_type") == "errata" else "transcript"
        yield Material(
            id=material_id,
            identifiers=(Identifier(scheme="govinfo.package", value=package),),
            title=row.get("title") or None, congress=congress, chamber=chamber,
            proceeding_dates=dates, details=DocumentDetails(category=category),
            provenance=evidence, field_evidence=date_evidence,
        )
        # A metadata refresh does not prove that the publisher issued a new edition.
        version_id = context.ids("material_version", f"{key}:published")
        version_ref = Ref(kind="material_version", id=version_id)
        yield MaterialVersion(
            id=version_id, material=material_ref, source_modified_at=modified,
            provenance=evidence,
        )
        for field, media_type, label in (
            ("html_url", "text/html", "HTML"),
            ("pdf_url", "application/pdf", "PDF"),
        ):
            value = row.get(field)
            url = web_url(value)
            if url:
                yield Representation(
                    id=context.ids("representation", f"{key}:{field}"),
                    version=version_ref,
                    locations=(MaterialLocation(url=url, role="download"),),
                    media_type=media_type, format_label=label,
                    provenance=context.evidence(source, selector=f"/{field}"),
                )
            elif value:
                issues.append(issue(
                    f"invalid-{field}", "unverified", "A reported document URL is not an absolute HTTP(S) URL.",
                    explanation=f"The original {field} value remains in the source row; no replacement URL was guessed.",
                ))

        event_id = str(row.get("event_id") or "").strip()
        meeting = (meetings or {}).get((congress, chamber, event_id)) if event_id else None
        if meeting:
            if meeting.kind != "meeting":
                raise ValueError("GPO meeting lookup must contain meeting references")
            yield MaterialLink(
                id=context.ids("material_link", f"{key}:meeting:{meeting.id}"),
                material=material_ref, version=version_ref, subject=meeting,
                role="supporting" if category == "errata" else "transcript",
                provenance=context.evidence(
                    source, basis="derived", selector="/event_id",
                    method=Method(name="congress_api.adapters.gpo.exact-event", version="1"),
                ),
            )
        else:
            issues.append(issue(
                "unlinked", "unlinked", "This package has no verified meeting association.",
                explanation="Retained as a document. A title, committee code or hearing date alone does not establish meeting identity.",
            ))
        # One malformed field can produce several rejected values, but one issue.
        yield from {item.id: item for item in issues}.values()
