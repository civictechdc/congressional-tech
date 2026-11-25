"""Tests for DocMeta V7.1 schemas, codebook, FRBR/ELI-DL models, crosswalks, and release metadata."""

from __future__ import annotations

import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

import congress_docmeta.v7 as v7
from congress_docmeta.v7 import (
    CONGRESS_GOV_ALL_DOC_TYPES,
    CONGRESS_GOV_MEETING_DOC_TYPES,
    CONGRESS_GOV_WITNESS_DOC_TYPES,
    CROISSANT_RAI_SPEC_URL,
    CROISSANT_SPEC_URL,
    DCAT3_SPEC_URL,
    DOCS_HOUSE_GOV_CODES,
    FAMILY_TO_GENRES,
    GENRE_TO_FAMILY,
    LCGFT_TERMS,
    SPECIALIST_MODELS,
    V65_DOC_KINDS,
    V65_STATUSES,
    Chamber,
    CoreEnvelopeExtraction,
    CorrespondenceDirection,
    CorrespondenceQfrOversightExtraction,
    DocStatus,
    EntityType,
    EventLogisticsExtraction,
    EventType,
    ExpressionRecord,
    ForeseenActivity,
    LegislationReportFiscalExtraction,
    ManifestationRecord,
    MediaFormat,
    PersonaEntry,
    PersonaRole,
    PrimaryGenre,
    RealizedActivity,
    SpanRef,
    SpecialistFamily,
    SubmissionRecord,
    TestimonyBioDisclosureExtraction as BioDisclosureExtraction,
    TranscriptVoteAttendanceExtraction,
    VenueKind,
    WorkRecord,
    build_croissant_manifest,
    build_dcat3_catalog,
    codebook_version,
    get_codebook,
    map_congress_gov_doc_type_to_v7,
    map_docs_house_code_to_v7,
    map_genre_to_congress_gov,
    map_genre_to_docs_house_gov,
    map_genre_to_document_kind,
    map_genre_to_lcgft,
    migrate_v65_to_v7,
    outward_crosswalk,
    render_core_prompt,
    render_specialist_prompt,
    strict_json_schema,
    validate_codebook_consistency,
    validate_croissant_manifest,
    validate_crosswalk_consistency,
    validate_dcat3_catalog,
    verify_grounded_extraction,
    verify_span_in_text,
)


def _walk_schema_objects(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            found.append((path, node))
        for key, val in node.items():
            found.extend(_walk_schema_objects(val, f"{path}.{key}"))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            found.extend(_walk_schema_objects(item, f"{path}[{idx}]"))
    return found


def _walk_schema_refs(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if "$ref" in node:
            found.append((path, node))
        for key, val in node.items():
            found.extend(_walk_schema_refs(val, f"{path}.{key}"))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            found.extend(_walk_schema_refs(item, f"{path}[{idx}]"))
    return found


def _span_for(text: str, needle: str) -> SpanRef:
    start = text.index(needle)
    return SpanRef(quote=needle, start=start, end=start + len(needle))


def _walk_unsupported_openai_keys(node: Any, path: str = "$") -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    unsupported = {
        "default",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
    if isinstance(node, dict):
        for key, val in node.items():
            if key in unsupported:
                bad.append((path, key))
            bad.extend(_walk_unsupported_openai_keys(val, f"{path}.{key}"))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            bad.extend(_walk_unsupported_openai_keys(item, f"{path}[{idx}]"))
    return bad


def test_package_exports_do_not_touch_factory() -> None:
    init_source = Path(v7.__file__).read_text(encoding="utf-8")
    tree = ast.parse(init_source)
    import_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.module != "__future__"
    }
    assert import_modules == {"codebook", "models", "crosswalk", "release_metadata"}
    assert "factory" not in init_source
    assert len(v7.__all__) >= 40
    allowed_modules = {
        "congress_docmeta.v7.codebook",
        "congress_docmeta.v7.models",
        "congress_docmeta.v7.crosswalk",
        "congress_docmeta.v7.release_metadata",
    }
    for symbol in v7.__all__:
        obj = getattr(v7, symbol)
        if isinstance(obj, type) or callable(obj):
            assert getattr(obj, "__module__", None) in allowed_modules, (
                f"Unexpected export module {getattr(obj, '__module__', None)!r} for {symbol!r}"
            )


def test_taxonomy_14_genres_5_families_bijection() -> None:
    assert len(PrimaryGenre) == 14
    assert len(SpecialistFamily) == 5
    assert len(DocStatus) == 8
    assert len(MediaFormat) == 4
    assert set(GENRE_TO_FAMILY.keys()) == set(PrimaryGenre)
    assert set(GENRE_TO_FAMILY.values()) == set(SpecialistFamily)
    assert set(SPECIALIST_MODELS.keys()) == set(SpecialistFamily)
    assert len(set(SPECIALIST_MODELS.values())) == 5

    partitioned: list[PrimaryGenre] = []
    for family, genres in FAMILY_TO_GENRES.items():
        assert len(genres) >= 2
        for genre in genres:
            assert GENRE_TO_FAMILY[genre] == family
            partitioned.append(genre)
    assert len(partitioned) == 14
    assert set(partitioned) == set(PrimaryGenre)


def test_span_ref_and_persona_validation() -> None:
    text = "Testimony of Dr. Jane Doe, Director, IRS, before the Committee."
    name_span = _span_for(text, "Dr. Jane Doe")
    org_span = _span_for(text, "IRS")

    persona = PersonaEntry(
        name="Jane Doe",
        name_span=name_span,
        role=PersonaRole.witness,
        entity_type=EntityType.gov_official,
        title="Director",
        org="IRS",
        org_span=org_span,
        creds="Ph.D.",
    )
    assert verify_span_in_text(persona.name_span, text)  # type: ignore[arg-type]
    assert verify_span_in_text(persona.org_span, text)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        SpanRef(quote="abc", start=-1, end=2)
    with pytest.raises(ValidationError):
        SpanRef(quote="abc", start=3, end=3)
    with pytest.raises(ValidationError):
        SpanRef(quote="   ", start=0, end=3)

    # Reject acronym expansion not grounded in org_span.
    with pytest.raises(ValidationError):
        PersonaEntry(
            name="Jane Doe",
            name_span=name_span,
            role=PersonaRole.witness,
            entity_type=EntityType.gov_official,
            org="Internal Revenue Service",
            org_span=org_span,
        )

    # Reject hallucinated persona name mismatching name_span.
    with pytest.raises(ValidationError):
        PersonaEntry(
            name="John Hallucinated",
            name_span=name_span,
            role=PersonaRole.witness,
            entity_type=EntityType.non_gov_person,
        )

    # Reject extra unexpected field.
    with pytest.raises(ValidationError):
        PersonaEntry.model_validate(
            {
                "name": "Jane Doe",
                "role": "witness",
                "entity_type": "gov_official",
                "unknown_key": 123,
            }
        )


def test_core_envelope_invariants_valid_and_invalid() -> None:
    text = (
        "UNITED STATES HOUSE OF REPRESENTATIVES\n"
        "Committee on Energy and Commerce\n"
        "Hearing on Artificial Intelligence Safety\n"
        "May 10, 2023\n"
        "118th Congress\n"
        "Written Testimony of Alice Smith\n"
    )
    title_span = _span_for(text, "Hearing on Artificial Intelligence Safety")
    date_span = _span_for(text, "May 10, 2023")

    core = CoreEnvelopeExtraction(
        rationale="Written witness testimony with committee header, title, and date in text.",
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        is_packet=False,
        contains_genres=[],
        primary_genre=PrimaryGenre.witness_testimony,
        specialist_family=SpecialistFamily.testimony_bio_disclosure,
        verbatim_title="Hearing on Artificial Intelligence Safety",
        title_span=title_span,
        doc_date="2023-05-10",
        date_spans=[date_span],
        chamber=Chamber.house,
        congress=118,
        committees=["House Committee on Energy and Commerce"],
        gist="Alice Smith testifies on artificial intelligence safety before House Energy and Commerce.",
        topics=["artificial intelligence"],
    )
    assert verify_grounded_extraction(core, None, text) == []

    # Valid packet document.
    packet_core = CoreEnvelopeExtraction(
        rationale="Bundled PDF starting with witness testimony followed by biography and Rule XI form.",
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        is_packet=True,
        contains_genres=[
            PrimaryGenre.witness_testimony,
            PrimaryGenre.witness_biography,
            PrimaryGenre.truth_in_testimony,
        ],
        primary_genre=PrimaryGenre.witness_testimony,
        specialist_family=SpecialistFamily.testimony_bio_disclosure,
    )
    assert packet_core.is_packet is True

    # Valid non-usable document.
    for non_usable in (
        DocStatus.cover_or_toc,
        DocStatus.govinfo_wrapper,
        DocStatus.index_or_listing,
        DocStatus.catalog_xml,
        DocStatus.stub_or_blank,
        DocStatus.error_or_block,
        DocStatus.ocr_unreadable,
    ):
        refused = CoreEnvelopeExtraction(
            rationale=f"Detected {non_usable.value} artifact with no substantive body text.",
            status=non_usable,
        )
        assert refused.primary_genre is None
        assert refused.specialist_family is None
        assert refused.is_packet is False

    # Reject non-usable with primary_genre or specialist_family or is_packet.
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="HTTP 403 block page.",
            status=DocStatus.error_or_block,
            primary_genre=PrimaryGenre.witness_testimony,
            specialist_family=SpecialistFamily.testimony_bio_disclosure,
        )
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="Blank stub.",
            status=DocStatus.stub_or_blank,
            is_packet=True,
            contains_genres=[PrimaryGenre.witness_testimony],
        )

    # Reject usable missing primary_genre, media_format, or mismatched family.
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="Usable doc missing genre.",
            status=DocStatus.usable,
            media_format=MediaFormat.prose,
        )
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="Usable doc missing media_format.",
            status=DocStatus.usable,
            primary_genre=PrimaryGenre.witness_testimony,
            specialist_family=SpecialistFamily.testimony_bio_disclosure,
        )
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="Wrong specialist family.",
            status=DocStatus.usable,
            media_format=MediaFormat.prose,
            primary_genre=PrimaryGenre.witness_testimony,
            specialist_family=SpecialistFamily.event_logistics,
        )

    # Reject packet rule violations and title_span mismatch.
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="Non-packet cannot populate contains_genres.",
            status=DocStatus.usable,
            media_format=MediaFormat.prose,
            is_packet=False,
            contains_genres=[PrimaryGenre.witness_testimony],
            primary_genre=PrimaryGenre.witness_testimony,
            specialist_family=SpecialistFamily.testimony_bio_disclosure,
        )
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="Packet must include primary_genre in contains_genres.",
            status=DocStatus.usable,
            media_format=MediaFormat.prose,
            is_packet=True,
            contains_genres=[PrimaryGenre.witness_biography],
            primary_genre=PrimaryGenre.witness_testimony,
            specialist_family=SpecialistFamily.testimony_bio_disclosure,
        )
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="Title span mismatch.",
            status=DocStatus.usable,
            media_format=MediaFormat.prose,
            primary_genre=PrimaryGenre.witness_testimony,
            specialist_family=SpecialistFamily.testimony_bio_disclosure,
            verbatim_title="Different Title",
            title_span=title_span,
        )
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale="x" * 481,
            status=DocStatus.stub_or_blank,
        )


def test_five_specialist_models_valid_grounded_and_rejections() -> None:
    # 1. EventLogisticsExtraction
    ev_text = (
        "NOTICE OF HEARING\n"
        "Oversight of Federal Cloud Procurement\n"
        "Wednesday, June 14, 2023 at 10:00 a.m. EDT\n"
        "2125 Rayburn House Office Building\n"
        "Witness: Elena Vance\n"
        "H.R. 4010\n"
    )
    ev = EventLogisticsExtraction(
        rationale="Hearing notice listing title, date, time, Rayburn room, and witness.",
        event_type=EventType.hearing,
        event_title="Oversight of Federal Cloud Procurement",
        event_title_span=_span_for(ev_text, "Oversight of Federal Cloud Procurement"),
        event_date="2023-06-14",
        event_date_span=_span_for(ev_text, "June 14, 2023"),
        event_time="10:00 a.m. EDT",
        venue_kind=VenueKind.capitol_room,
        venue="2125 Rayburn House Office Building",
        venue_span=_span_for(ev_text, "2125 Rayburn House Office Building"),
        witnesses=[
            PersonaEntry(
                name="Elena Vance",
                name_span=_span_for(ev_text, "Elena Vance"),
                role=PersonaRole.witness,
                entity_type=EntityType.non_gov_person,
            )
        ],
        bill_refs=["bill:H.R. 4010"],
    )
    ev_core = CoreEnvelopeExtraction(
        rationale="Notice of Hearing with time and Rayburn room.",
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        primary_genre=PrimaryGenre.hearing_or_markup_notice,
        specialist_family=SpecialistFamily.event_logistics,
    )
    assert verify_grounded_extraction(ev_core, ev, ev_text) == []

    # Reject ungrounded witness name_span in specialist model.
    with pytest.raises(ValidationError):
        EventLogisticsExtraction(
            rationale="Missing witness span.",
            witnesses=[
                PersonaEntry(
                    name="Elena Vance",
                    role=PersonaRole.witness,
                    entity_type=EntityType.non_gov_person,
                )
            ],
        )

    # 2. BioDisclosureExtraction (TestimonyBioDisclosureExtraction)
    ttf_text = (
        "Truth in Testimony Disclosure Form\n"
        "Witness: Marcus Chen, Acme Labs\n"
        "Federal grants received: Yes — $450,000 NSF Grant 21-001\n"
    )
    ttf = BioDisclosureExtraction(
        rationale="Rule XI TTF form with witness, org, and disclosed NSF grant.",
        personas=[
            PersonaEntry(
                name="Marcus Chen",
                name_span=_span_for(ttf_text, "Marcus Chen"),
                role=PersonaRole.witness,
                entity_type=EntityType.non_gov_person,
                org="Acme Labs",
                org_span=_span_for(ttf_text, "Acme Labs"),
            )
        ],
        issuer_org="Acme Labs",
        issuer_org_span=_span_for(ttf_text, "Acme Labs"),
        disclosure_has_grants_or_contracts=True,
        disclosure_amounts=["$450,000 NSF Grant 21-001"],
        disclosure_spans=[_span_for(ttf_text, "$450,000 NSF Grant 21-001")],
    )
    ttf_core = CoreEnvelopeExtraction(
        rationale="Truth in Testimony form.",
        status=DocStatus.usable,
        media_format=MediaFormat.table_or_form,
        primary_genre=PrimaryGenre.truth_in_testimony,
        specialist_family=SpecialistFamily.testimony_bio_disclosure,
    )
    assert verify_grounded_extraction(ttf_core, ttf, ttf_text) == []
    with pytest.raises(ValidationError):
        BioDisclosureExtraction(
            rationale="Amounts without spans.",
            disclosure_amounts=["$450,000"],
        )

    # 3. TranscriptVoteAttendanceExtraction
    tr_text = (
        "Markup of H.R. 2670\n"
        "Present: Representatives Rogers, Smith.\n"
        "Staff Present: John Adams.\n"
        "The CHAIRMAN. The committee will come to order.\n"
        "Roll Call #4: Agreed to 29-27.\n"
    )
    tr = TranscriptVoteAttendanceExtraction(
        rationale="Transcript/vote record with Present line, Staff Present line, and tally.",
        event_type=EventType.markup,
        event_title="Markup of H.R. 2670",
        event_title_span=_span_for(tr_text, "Markup of H.R. 2670"),
        event_date="2023-06-21",
        members_present=["Rogers", "Smith"],
        members_present_spans=[_span_for(tr_text, "Present: Representatives Rogers, Smith.")],
        staff_present=["John Adams"],
        staff_present_spans=[_span_for(tr_text, "Staff Present: John Adams.")],
        action_summary="Roll Call #4: Agreed to 29-27",
        vote_tallies=["29-27"],
        bill_refs=["bill:H.R. 2670"],
    )
    tr_core = CoreEnvelopeExtraction(
        rationale="Markup transcript with speaker turns and roll call.",
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        primary_genre=PrimaryGenre.hearing_transcript,
        specialist_family=SpecialistFamily.transcript_vote_attendance,
    )
    assert verify_grounded_extraction(tr_core, tr, tr_text) == []
    with pytest.raises(ValidationError):
        TranscriptVoteAttendanceExtraction(
            rationale="Missing attendance span.",
            members_present=["Rogers"],
        )

    # 4. CorrespondenceQfrOversightExtraction
    qfr_text = (
        "U.S. Department of Energy\n"
        "Dear Chairman Westerman,\n"
        "Please find responses from Dr. Alan Grant due May 30, 2024.\n"
    )
    qfr = CorrespondenceQfrOversightExtraction(
        rationale="Agency response letter addressed to Chairman Westerman with due date.",
        correspondence_direction=CorrespondenceDirection.agency_to_congress,
        senders=[
            PersonaEntry(
                name="Alan Grant",
                name_span=_span_for(qfr_text, "Dr. Alan Grant"),
                role=PersonaRole.sender,
                entity_type=EntityType.gov_official,
                org="U.S. Department of Energy",
                org_span=_span_for(qfr_text, "U.S. Department of Energy"),
            )
        ],
        recipients=[
            PersonaEntry(
                name="Westerman",
                name_span=_span_for(qfr_text, "Chairman Westerman"),
                role=PersonaRole.recipient,
                entity_type=EntityType.member,
            )
        ],
        issuer_org="U.S. Department of Energy",
        issuer_org_span=_span_for(qfr_text, "U.S. Department of Energy"),
        due_date="2024-05-30",
        due_date_span=_span_for(qfr_text, "May 30, 2024"),
        subpoena_or_compelled=False,
    )
    qfr_core = CoreEnvelopeExtraction(
        rationale="Oversight response letter.",
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        primary_genre=PrimaryGenre.oversight_or_committee_letter,
        specialist_family=SpecialistFamily.correspondence_qfr_oversight,
    )
    assert verify_grounded_extraction(qfr_core, qfr, qfr_text) == []

    # 5. LegislationReportFiscalExtraction
    leg_text = (
        "Congressional Budget Office\n"
        "This Act may be cited as the 'Stop Senior Scams Act'.\n"
        "Offered by Rep. Blunt Rochester for FY2025-FY2029.\n"
        "H.R. 444 | P.L. 117-58\n"
    )
    leg = LegislationReportFiscalExtraction(
        rationale="CBO fiscal/legislative document citing short title and FY2025-2029.",
        short_titles=["Stop Senior Scams Act"],
        short_title_spans=[_span_for(leg_text, "Stop Senior Scams Act")],
        issuer_org="Congressional Budget Office",
        issuer_org_span=_span_for(leg_text, "Congressional Budget Office"),
        sponsors_or_offerors=[
            PersonaEntry(
                name="Blunt Rochester",
                name_span=_span_for(leg_text, "Rep. Blunt Rochester"),
                role=PersonaRole.sponsor,
                entity_type=EntityType.member,
            )
        ],
        fiscal_years=["FY2025", "FY2029"],
        bill_refs=["bill:H.R. 444"],
        statute_or_rule_refs=["law:P.L. 117-58"],
    )
    leg_core = CoreEnvelopeExtraction(
        rationale="CBO budget/cost estimate.",
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        primary_genre=PrimaryGenre.budget_or_cost_estimate,
        specialist_family=SpecialistFamily.legislation_report_fiscal,
    )
    assert verify_grounded_extraction(leg_core, leg, leg_text) == []

    # Grounding mismatch helper catches off-slice spans and mismatched family.
    bad_span = SpanRef(quote="Nonexistent", start=0, end=11)
    bad_ev = ev.model_copy(update={"event_title_span": bad_span})
    errs = verify_grounded_extraction(ev_core, bad_ev, ev_text)
    assert any("Ungrounded span" in e for e in errs)
    wrong_fam_errs = verify_grounded_extraction(ev_core, leg, ev_text)
    assert any("does not match" in e for e in wrong_fam_errs)


def test_strict_json_schema_claude_and_codex_compatibility() -> None:
    models_to_check = [CoreEnvelopeExtraction, *SPECIALIST_MODELS.values()]
    for model_cls in models_to_check:
        claude_schema = strict_json_schema(model_cls, openai_strict=False)
        codex_schema = strict_json_schema(model_cls, openai_strict=True)

        jsonschema.Draft202012Validator.check_schema(claude_schema)
        jsonschema.Draft202012Validator.check_schema(codex_schema)

        #rationale must be the first property emitted in every model schema.
        assert list(claude_schema["properties"].keys())[0] == "rationale"
        assert list(codex_schema["properties"].keys())[0] == "rationale"

        for path, obj_node in _walk_schema_objects(claude_schema):
            assert obj_node.get("additionalProperties") is False, f"{model_cls.__name__} {path}"

        for path, obj_node in _walk_schema_objects(codex_schema):
            assert obj_node.get("additionalProperties") is False, f"{model_cls.__name__} {path}"
            props = obj_node.get("properties")
            if isinstance(props, dict):
                assert set(obj_node.get("required") or []) == set(props.keys()), (
                    f"{model_cls.__name__} {path} missing required keys under openai_strict=True"
                )
                for pval in props.values():
                    for unsupported in ("default", "minLength", "maxLength", "minimum", "maximum", "pattern", "format"):
                        assert unsupported not in pval

        assert _walk_unsupported_openai_keys(codex_schema) == []
        for path, ref_node in _walk_schema_refs(codex_schema):
            assert list(ref_node.keys()) == ["$ref"], f"{model_cls.__name__} {path} has sibling keys: {ref_node}"

    # Verify real serialized payloads validate against both Claude and Codex JSON schemas.
    sample_core = CoreEnvelopeExtraction(
        rationale="Stub body.",
        status=DocStatus.stub_or_blank,
    ).model_dump(mode="json")
    jsonschema.validate(sample_core, strict_json_schema(CoreEnvelopeExtraction, openai_strict=False))
    jsonschema.validate(sample_core, strict_json_schema(CoreEnvelopeExtraction, openai_strict=True))

    sample_spec = EventLogisticsExtraction(
        rationale="Notice with no witnesses listed.",
        event_type=EventType.markup,
    ).model_dump(mode="json")
    jsonschema.validate(sample_spec, strict_json_schema(EventLogisticsExtraction, openai_strict=False))
    jsonschema.validate(sample_spec, strict_json_schema(EventLogisticsExtraction, openai_strict=True))


def test_codebook_consistency_version_determinism_and_prompts() -> None:
    assert validate_codebook_consistency() == []
    cb = get_codebook()
    v1 = codebook_version()
    v2 = codebook_version(cb)
    assert len(v1) == 64
    assert all(ch in "0123456789abcdef" for ch in v1)
    assert v1 == v2

    # Key order variation must yield identical canonical hash; semantic edits must change hash.
    reordered = {k: cb[k] for k in reversed(list(cb.keys()))}
    assert codebook_version(reordered) == v1

    mutated = deepcopy(cb)
    mutated["genres"]["witness_testimony"]["definition"] += " (edited)"
    assert codebook_version(mutated) != v1

    # Verify every genre, core field, persona field, and specialist field has boundary & abstention rules.
    for genre in PrimaryGenre:
        gspec = cb["genres"][genre.value]
        for req in ("definition", "positive_indicators", "negative_boundaries", "null_and_abstention_rules"):
            assert gspec.get(req), f"Genre {genre.value} missing {req}"

    for fname in CoreEnvelopeExtraction.model_fields:
        assert fname in cb["core_fields"], f"Core field {fname} missing from codebook"
    for fname in PersonaEntry.model_fields:
        assert fname in cb["persona_fields"], f"Persona field {fname} missing from codebook"
    for fam, model_cls in SPECIALIST_MODELS.items():
        fam_fields = cb["specialist_fields"][fam.value]
        for fname in model_cls.model_fields:
            assert fname in fam_fields, f"Specialist field {fam.value}.{fname} missing from codebook"
            for req in ("definition", "positive_indicators", "negative_boundaries", "null_and_abstention_rules"):
                assert fam_fields[fname].get(req), f"{fam.value}.{fname} missing {req}"

    # Verify prompt builders accept strictly text-only arguments and leak zero metadata headers.
    core_params = set(inspect.signature(render_core_prompt).parameters)
    spec_params = set(inspect.signature(render_specialist_prompt).parameters)
    assert core_params == {"doc_text", "doc_id", "codebook"}
    assert spec_params == {"family", "doc_text", "core_result", "codebook"}

    doc_text = "Testimony of Dr. Jane Doe before the Committee on Energy and Commerce."
    core_prompt = render_core_prompt(doc_text=doc_text, doc_id="doc-001")
    assert "DOC_ID: doc-001" in core_prompt
    assert doc_text in core_prompt
    assert "Advisory known metadata" not in core_prompt
    assert "Filename:" not in core_prompt

    core_res = CoreEnvelopeExtraction(
        rationale="Written testimony.",
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        primary_genre=PrimaryGenre.witness_testimony,
        specialist_family=SpecialistFamily.testimony_bio_disclosure,
    )
    spec_prompt = render_specialist_prompt(SpecialistFamily.testimony_bio_disclosure, doc_text, core_res)
    assert "TestimonyBioDisclosureExtraction" in spec_prompt
    assert doc_text in spec_prompt

    with pytest.raises(ValueError):
        render_specialist_prompt(
            SpecialistFamily.event_logistics,
            doc_text,
            CoreEnvelopeExtraction(rationale="404 error", status=DocStatus.error_or_block),
        )
    with pytest.raises(ValueError):
        render_specialist_prompt(SpecialistFamily.event_logistics, doc_text, core_res)


def test_crosswalk_47_v65_kinds_and_8_statuses_exhaustive() -> None:
    assert validate_crosswalk_consistency() == []

    assert len(V65_DOC_KINDS) == 47
    assert len(V65_STATUSES) == 8

    # Exhaustively migrate all 47 primary_kinds.
    for kind in V65_DOC_KINDS:
        res = migrate_v65_to_v7(primary_kind=kind, status="usable")
        status, media_format, is_packet, primary_genre, specialist_family, _subkind = res.as_tuple()
        if kind == "error_or_non_document":
            assert status == DocStatus.stub_or_blank
            assert primary_genre is None
            assert specialist_family is None
            assert is_packet is False
        else:
            assert status == DocStatus.usable
            assert media_format is not None
            assert primary_genre is not None
            assert specialist_family == GENRE_TO_FAMILY[primary_genre]

    # Exhaustively migrate all 8 statuses.
    for st in V65_STATUSES:
        if st == "usable":
            res = migrate_v65_to_v7(primary_kind="hearing_transcript", status=st)
            assert res.status == DocStatus.usable
            assert res.primary_genre == PrimaryGenre.hearing_transcript
        else:
            res = migrate_v65_to_v7(primary_kind=None, status=st)
            assert res.status == DocStatus(st)
            assert res.primary_genre is None
            assert res.specialist_family is None
            assert res.is_packet is False

    # Specific container/format decoupling checks.
    slides_res = migrate_v65_to_v7("slides_or_visual", "usable")
    assert slides_res.media_format == MediaFormat.slides
    assert slides_res.status == DocStatus.usable

    web_res = migrate_v65_to_v7("event_web_page", "usable")
    assert web_res.media_format == MediaFormat.web_page

    pkt_res = migrate_v65_to_v7(
        "multi_doc_packet",
        "usable",
        secondary_kinds=["witness_statement", "witness_biography", "truth_in_testimony_disclosure"],
    )
    assert pkt_res.is_packet is True
    assert pkt_res.primary_genre == PrimaryGenre.witness_testimony
    assert pkt_res.contains_genres == [
        PrimaryGenre.witness_testimony,
        PrimaryGenre.witness_biography,
        PrimaryGenre.truth_in_testimony,
    ]


def test_outward_crosswalks_congress_gov_house_and_lcgft() -> None:
    assert len(CONGRESS_GOV_MEETING_DOC_TYPES) == 18
    assert len(CONGRESS_GOV_WITNESS_DOC_TYPES) == 4
    assert len(CONGRESS_GOV_ALL_DOC_TYPES) == 22

    expected_house_codes = {
        "WS", "WT", "WB", "WD", "SD", "HM", "BR", "BL",
        "AM", "CA", "FA", "ANS", "CR", "CV", "HT", "NT",
    }
    assert set(DOCS_HOUSE_GOV_CODES) == expected_house_codes

    expected_lcgft = {
        "http://id.loc.gov/authorities/genreForms/gf2013025047",
        "http://id.loc.gov/authorities/genreForms/gf2011026360",
        "http://id.loc.gov/authorities/genreForms/gf2011026362",
    }
    assert set(LCGFT_TERMS.keys()) == expected_lcgft

    seen_cg: set[str] = set()
    seen_house: set[str] = set()
    seen_lcgft: set[str] = set()
    for genre in PrimaryGenre:
        entry = outward_crosswalk(genre)
        assert entry.congress_gov_meeting_doc_types == map_genre_to_congress_gov(genre)
        assert entry.docs_house_gov_codes == map_genre_to_docs_house_gov(genre)
        assert entry.lcgft_uris == map_genre_to_lcgft(genre)
        seen_cg.update(entry.congress_gov_meeting_doc_types)
        seen_house.update(entry.docs_house_gov_codes)
        seen_lcgft.update(entry.lcgft_uris)

    assert seen_house == expected_house_codes
    assert seen_lcgft == expected_lcgft
    # 18 + 4 minus the 2 non-usable cover/TOC types = 20 usable types covered outward.
    assert seen_cg == set(CONGRESS_GOV_ALL_DOC_TYPES) - {"Hearing: Cover Page", "Hearing: Table of Contents"}

    # Bidirectional mapping checks for all 22 Congress.gov types and all 16 docs.house.gov codes.
    for cg_type in CONGRESS_GOV_ALL_DOC_TYPES:
        mapped = map_congress_gov_doc_type_to_v7(cg_type)
        if cg_type in ("Hearing: Cover Page", "Hearing: Table of Contents"):
            assert mapped["status"] == DocStatus.cover_or_toc
            assert mapped["primary_genre"] is None
        else:
            assert mapped["status"] == DocStatus.usable
            assert isinstance(mapped["primary_genre"], PrimaryGenre)

    assert map_congress_gov_doc_type_to_v7("Witness Support Document")["source_doc_type"] == "Witness Supporting Document"

    for hcode in expected_house_codes:
        mapped = map_docs_house_code_to_v7(hcode)
        assert mapped["source_code"] == hcode
        assert mapped["status"] == DocStatus.usable
        assert isinstance(mapped["primary_genre"], PrimaryGenre)

    assert map_docs_house_code_to_v7("ANS")["subkind"] == "amendment_in_nature_of_substitute"


def test_frbr_and_elidl_conceptual_models() -> None:
    work = WorkRecord(
        work_id="work:testimony-001",
        title="Testimony on Clean Grid Reliability",
        primary_genre=PrimaryGenre.witness_testimony,
        status=DocStatus.usable,
        congress=119,
        chamber=Chamber.senate,
        committees=["Senate Committee on Energy and Natural Resources"],
        activity_id="act:realized-2026-03-12",
    )
    expr = ExpressionRecord(
        expression_id="expr:testimony-001-v1",
        work_id=work.work_id,
        media_format=MediaFormat.prose,
        version_label="as_prepared",
        doc_date="2026-03-12",
    )
    manif = ManifestationRecord(
        manifestation_id="manif:sha256-aaa",
        expression_id=expr.expression_id,
        body_sha256="a" * 64,
        media_type="application/pdf",
        byte_size=102400,
    )
    foreseen = ForeseenActivity(
        activity_id="act:foreseen-2026-03-12",
        event_id="326051",
        event_type=EventType.hearing,
        title="Clean Grid Reliability Hearing",
        scheduled_date="2026-03-12",
        foreseen_status="scheduled",
        notice_work_ids=["work:notice-001"],
    )
    realized = RealizedActivity(
        activity_id="act:realized-2026-03-12",
        foreseen_activity_id=foreseen.activity_id,
        event_id="326051",
        event_type=EventType.hearing,
        realized_date="2026-03-12",
        outcome_status="held",
        transcript_work_ids=["work:transcript-001"],
    )
    submission = SubmissionRecord(
        submission_id="sub:001",
        work_id=work.work_id,
        submission_kind="written_testimony",
        demand_type="invitation",
        activity_id=realized.activity_id,
        disposition="entered_in_record",
    )
    assert manif.body_sha256 == "a" * 64
    assert realized.foreseen_activity_id == foreseen.activity_id
    assert submission.disposition == "entered_in_record"

    with pytest.raises(ValidationError):
        WorkRecord(work_id="bad", status=DocStatus.stub_or_blank, primary_genre=PrimaryGenre.witness_testimony)
    with pytest.raises(ValidationError):
        ExpressionRecord(expression_id="e1", work_id="w1", is_packet=False, contains_genres=[PrimaryGenre.witness_testimony])
    with pytest.raises(ValidationError):
        ManifestationRecord(manifestation_id="m1", expression_id="e1", body_sha256="not-a-sha256")


def test_croissant_and_dcat3_release_metadata_generation_and_validation() -> None:
    sample_sha = "b" * 64
    croissant = build_croissant_manifest(
        parquet_sha256=sample_sha,
        parquet_byte_size=1234567,
        record_count=320629,
    )
    assert validate_croissant_manifest(croissant) == []
    assert CROISSANT_SPEC_URL in croissant["conformsTo"]
    assert CROISSANT_RAI_SPEC_URL in croissant["conformsTo"]
    assert codebook_version() in croissant["rai:dataAnnotationProtocol"]
    # Ensure pure JSON round-trip.
    assert json.loads(json.dumps(croissant))["@type"] == "sc:Dataset"

    broken_croissant = deepcopy(croissant)
    broken_croissant["recordSet"][0]["field"][0]["source"]["fileObject"]["@id"] = "missing-file-id"
    assert any("missing-file-id" in err for err in validate_croissant_manifest(broken_croissant))

    dcat3 = build_dcat3_catalog(
        parquet_sha256=sample_sha,
        parquet_byte_size=1234567,
        croissant_sha256="c" * 64,
    )
    assert validate_dcat3_catalog(dcat3) == []
    assert dcat3["dcterms:conformsTo"] == DCAT3_SPEC_URL
    assert json.loads(json.dumps(dcat3))["@type"] == "dcat:Catalog"

    broken_dcat3 = deepcopy(dcat3)
    broken_dcat3["dcat:dataset"][0]["dcat:distribution"][0]["spdx:checksum"]["spdx:checksumValue"] = "bad"
    assert any("spdx:checksumValue" in err for err in validate_dcat3_catalog(broken_dcat3))


def test_persona_entry_ocr_fuzzy_span_and_rationale_length_bounds() -> None:
    ocr_text = "Statement of Richand Muniz, President, IRS Advocacy Group."
    ocr_span = _span_for(ocr_text, "Richand Muniz")
    irs_span = _span_for(ocr_text, "IRS")

    # Clean OCR repair anchored to verified SpanRef passes.
    repaired = PersonaEntry(
        name="Richard Muniz",
        name_span=ocr_span,
        role=PersonaRole.witness,
        entity_type=EntityType.non_gov_person,
        org="IRS",
        org_span=irs_span,
    )
    assert repaired.name == "Richard Muniz"

    # Acronym expansion still rejected even when anchored to IRS span.
    with pytest.raises(ValidationError):
        PersonaEntry(
            name="Richard Muniz",
            name_span=ocr_span,
            role=PersonaRole.witness,
            entity_type=EntityType.non_gov_person,
            org="Internal Revenue Service",
            org_span=irs_span,
        )

    # Unrelated person name still rejected against OCR span.
    with pytest.raises(ValidationError):
        PersonaEntry(
            name="John Smith",
            name_span=ocr_span,
            role=PersonaRole.witness,
            entity_type=EntityType.non_gov_person,
        )

    rationale_350 = "R" * 350
    rationale_481 = "R" * 481

    core_ok = CoreEnvelopeExtraction(
        rationale=rationale_350,
        status=DocStatus.usable,
        media_format=MediaFormat.prose,
        primary_genre=PrimaryGenre.witness_testimony,
        specialist_family=SpecialistFamily.testimony_bio_disclosure,
    )
    assert len(core_ok.rationale) == 350
    with pytest.raises(ValidationError):
        CoreEnvelopeExtraction(
            rationale=rationale_481,
            status=DocStatus.usable,
            media_format=MediaFormat.prose,
            primary_genre=PrimaryGenre.witness_testimony,
            specialist_family=SpecialistFamily.testimony_bio_disclosure,
        )

    for cls in (
        EventLogisticsExtraction,
        BioDisclosureExtraction,
        TranscriptVoteAttendanceExtraction,
        CorrespondenceQfrOversightExtraction,
        LegislationReportFiscalExtraction,
    ):
        obj = cls(rationale=rationale_350)
        assert len(obj.rationale) == 350
        with pytest.raises(ValidationError):
            cls(rationale=rationale_481)


def test_render_core_prompt_surfaces_a1_a2_a3_boundaries() -> None:
    prompt = render_core_prompt("Sample text body.", "doc-boundary-check")
    assert "Markup of: H.R. 9772" in prompt
    assert "before/after site photographs" in prompt
    assert "Bill Status: Passed by Full Committee" in prompt
    assert "THOMAS Home" in prompt
    assert "NIH Biographical Sketch" in prompt
    assert "Table of Exhibits" in prompt
    assert "S. Rept." in prompt


def test_crosswalk_decoupled_v65_document_kind_and_croissant_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    from house_naming.categories import _known_document_kinds
    import congress_docmeta.v7.crosswalk as cw_mod

    # Crosswalk enum loading comes directly from crosswalk_v7_0.yaml.
    cw_mod._load_v65_schema_enums.cache_clear()
    kinds, statuses = cw_mod._load_v65_schema_enums()
    assert kinds == V65_DOC_KINDS
    assert statuses == V65_STATUSES
    cw_mod._load_v65_schema_enums.cache_clear()

    known_house_kinds = _known_document_kinds()
    for genre in PrimaryGenre:
        arch_dk = map_genre_to_document_kind(genre)
        assert arch_dk in known_house_kinds
        assert outward_crosswalk(genre).archive_document_kind == arch_dk

    assert map_genre_to_document_kind(PrimaryGenre.bill_or_amendment, subkind="committee_amendment") == "committee-amendment"
    assert map_genre_to_document_kind(PrimaryGenre.bill_or_amendment, subkind="floor_amendment") == "floor-amendment"
    assert map_genre_to_document_kind(PrimaryGenre.qfr_correspondence, subkind="qfr_response") == "questions-for-record-response"
    assert map_genre_to_document_kind(PrimaryGenre.hearing_memo_or_witness_list, subkind="witness_list") == "witness-list"
    assert map_genre_to_document_kind(PrimaryGenre.budget_or_cost_estimate, subkind="budget_views_and_estimates") == "budget-views-and-estimates"

    sample_croissant = build_croissant_manifest(parquet_sha256="b" * 64, record_count=10)
    expected_cols = [
        f["source"]["extract"]["column"] for f in sample_croissant["recordSet"][0]["field"]
    ]
    assert validate_croissant_manifest(sample_croissant, expected_columns=expected_cols) == []
    column_errs = validate_croissant_manifest(sample_croissant, expected_columns=[*expected_cols, "extra_col"])
    assert any("extra_col" in e for e in column_errs)
