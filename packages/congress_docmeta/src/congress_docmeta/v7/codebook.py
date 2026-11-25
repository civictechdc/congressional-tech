"""DocMeta V7.0 codebook loader, canonical SHA-256 versioner, and text-only prompt builders."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .models import (
    GENRE_TO_FAMILY,
    CoreEnvelopeExtraction,
    DocStatus,
    MediaFormat,
    PrimaryGenre,
    SpecialistFamily,
)

CODEBOOK_PATH = Path(__file__).resolve().parent / "codebook_v7_0.yaml"


@lru_cache(maxsize=1)
def _load_codebook_cached() -> dict[str, Any]:
    raw_text = CODEBOOK_PATH.read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw_text)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping at root of {CODEBOOK_PATH}.")
    return loaded


def get_codebook() -> dict[str, Any]:
    """Return a deep copy of the frozen V7.0 YAML codebook specification."""
    return deepcopy(_load_codebook_cached())


def canonical_codebook_json(codebook: Mapping[str, Any] | None = None) -> str:
    """Serialize a codebook mapping deterministically for canonical hashing."""
    spec = codebook if codebook is not None else _load_codebook_cached()
    return json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def codebook_version(codebook: Mapping[str, Any] | None = None) -> str:
    """Compute the deterministic lowercase SHA-256 hex digest of the normalized codebook."""
    payload = canonical_codebook_json(codebook).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_codebook_consistency(codebook: Mapping[str, Any] | None = None) -> list[str]:
    """Verify the YAML codebook aligns 1-to-1 with V7 Pydantic enums and specialist models."""
    cb = codebook if codebook is not None else _load_codebook_cached()
    errors: list[str] = []

    orth = cb.get("orthogonal_attributes", {})
    status_vals = set((orth.get("status") or {}).get("values", {}).keys())
    expected_statuses = {s.value for s in DocStatus}
    if status_vals != expected_statuses:
        errors.append(f"Status mismatch: yaml={sorted(status_vals)} vs model={sorted(expected_statuses)}")

    format_vals = set((orth.get("media_format") or {}).get("values", {}).keys())
    expected_formats = {m.value for m in MediaFormat}
    if format_vals != expected_formats:
        errors.append(f"MediaFormat mismatch: yaml={sorted(format_vals)} vs model={sorted(expected_formats)}")

    families_yaml = set((cb.get("specialist_families") or {}).keys())
    expected_families = {f.value for f in SpecialistFamily}
    if families_yaml != expected_families:
        errors.append(f"SpecialistFamily mismatch: yaml={sorted(families_yaml)} vs model={sorted(expected_families)}")

    genres_yaml = cb.get("genres") or {}
    expected_genres = {g.value for g in PrimaryGenre}
    if set(genres_yaml.keys()) != expected_genres:
        errors.append(f"PrimaryGenre mismatch: yaml={sorted(genres_yaml.keys())} vs model={sorted(expected_genres)}")
    else:
        for genre_val, spec in genres_yaml.items():
            expected_fam = GENRE_TO_FAMILY[PrimaryGenre(genre_val)].value
            if spec.get("family") != expected_fam:
                errors.append(f"Genre {genre_val!r} family {spec.get('family')!r} != {expected_fam!r}")

    return errors


def _format_bullets(items: list[str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}- {item}" for item in items)


def render_core_prompt(
    doc_text: str,
    doc_id: str,
    codebook: dict[str, Any] | None = None,
) -> str:
    """Render a clean, text-only Stage 1 Core Envelope prompt with zero upstream metadata hints."""
    cb = codebook if codebook is not None else _load_codebook_cached()
    cb_hash = codebook_version(cb)
    principles = cb["governing_principles"]
    orth = cb["orthogonal_attributes"]
    genres = cb["genres"]
    core_fields = cb["core_fields"]

    status_lines = [
        f"- `{name}`: {spec['definition']} | Positive: {'; '.join(spec.get('positive_indicators', ()))} | Boundaries: {'; '.join(spec.get('negative_boundaries', ()))}"
        for name, spec in orth["status"]["values"].items()
    ]
    format_lines = [
        f"- `{name}`: {spec['definition']} | Positive: {'; '.join(spec.get('positive_indicators', ()))} | Boundaries: {'; '.join(spec.get('negative_boundaries', ()))}"
        for name, spec in orth["media_format"]["values"].items()
    ]
    genre_lines: list[str] = []
    for genre_name, spec in genres.items():
        neg = "; ".join(spec["negative_boundaries"])
        null_rule = "; ".join(spec["null_and_abstention_rules"])
        genre_lines.append(
            f"- `{genre_name}` (family=`{spec['family']}`): {spec['definition']}\n"
            f"  Positive: {'; '.join(spec['positive_indicators'])}\n"
            f"  Boundaries: {neg}\n"
            f"  Abstention: {null_rule}"
        )

    core_field_lines = [
        f"- `{fname}`: {fspec['definition']} | Abstain: {'; '.join(fspec['null_and_abstention_rules'])}"
        for fname, fspec in core_fields.items()
    ]

    return "\n".join(
        [
            f"Task: DocMeta V7.1 Stage 1 Core Envelope Extraction (codebook={cb['codebook_id']}, sha256={cb_hash[:16]})",
            "Output ONLY valid JSON conforming to CoreEnvelopeExtraction. Emit `rationale` FIRST (<= 280 chars).",
            "",
            "Governing Rules (TEXT-ONLY TRUTH):",
            f"1. {principles['text_is_sole_source_of_truth'].strip()}",
            f"2. {principles['interpret_do_not_invent'].strip()}",
            f"3. {principles['exact_span_grounding'].strip()}",
            f"4. {principles['concise_rationale_first'].strip()}",
            "",
            "Orthogonal `status` (non-usable statuses MUST set primary_genre=null, specialist_family=null, is_packet=false, contains_genres=[]):",
            *status_lines,
            "",
            "Orthogonal `media_format` (required when status='usable'):",
            *format_lines,
            "",
            "Orthogonal `is_packet` / `contains_genres`:",
            f"- {orth['is_packet']['definition'].strip()}",
            f"- Positive: {'; '.join(orth['is_packet']['positive_indicators'])}",
            f"- Boundaries: {'; '.join(orth['is_packet']['negative_boundaries'])}",
            f"- Abstention: {'; '.join(orth['is_packet']['null_and_abstention_rules'])}",
            "",
            "14 Orthogonal `primary_genre` Definitions & Negative Boundaries:",
            *genre_lines,
            "",
            "Core Field Grounding & Abstention Rules:",
            *core_field_lines,
            "",
            f"DOC_ID: {doc_id}",
            "<<<DOC_TEXT>>>",
            doc_text,
            "<<<END_DOC_TEXT>>>",
        ]
    )


def render_specialist_prompt(
    family: SpecialistFamily | str,
    doc_text: str,
    core_result: CoreEnvelopeExtraction | Mapping[str, Any],
    codebook: dict[str, Any] | None = None,
) -> str:
    """Render a tight Stage 2 Specialist prompt scoped strictly to one family and text slice."""
    target_family = family if isinstance(family, SpecialistFamily) else SpecialistFamily(family)
    if isinstance(core_result, CoreEnvelopeExtraction):
        core_dict = core_result.model_dump(mode="json")
    elif isinstance(core_result, Mapping):
        core_dict = dict(core_result)
    else:
        raise TypeError("core_result must be a CoreEnvelopeExtraction or mapping.")

    status_val = core_dict.get("status")
    if status_val != DocStatus.usable.value:
        raise ValueError(f"Specialist prompt refused for non-usable status={status_val!r}.")

    core_family = core_dict.get("specialist_family")
    if core_family is not None and core_family != target_family.value:
        raise ValueError(
            f"Specialist family mismatch: requested {target_family.value!r} but core_result has {core_family!r}."
        )

    cb = codebook if codebook is not None else _load_codebook_cached()
    cb_hash = codebook_version(cb)
    principles = cb["governing_principles"]
    family_spec = cb["specialist_families"][target_family.value]
    field_specs = cb["specialist_fields"][target_family.value]
    persona_specs = cb["persona_fields"]

    field_lines: list[str] = []
    for fname, fspec in field_specs.items():
        field_lines.append(
            f"- `{fname}`: {fspec['definition']}\n"
            f"  Positive: {'; '.join(fspec['positive_indicators'])}\n"
            f"  Boundaries: {'; '.join(fspec['negative_boundaries'])}\n"
            f"  Abstention: {'; '.join(fspec['null_and_abstention_rules'])}"
        )

    persona_lines = [
        f"- `{pname}`: {pspec['definition']} | Boundaries: {'; '.join(pspec['negative_boundaries'])} | Abstain: {'; '.join(pspec['null_and_abstention_rules'])}"
        for pname, pspec in persona_specs.items()
    ]

    stage1_context = {
        "primary_genre": core_dict.get("primary_genre"),
        "subkind": core_dict.get("subkind"),
        "media_format": core_dict.get("media_format"),
        "is_packet": core_dict.get("is_packet", False),
        "contains_genres": core_dict.get("contains_genres", []),
    }

    return "\n".join(
        [
            (
                f"Task: DocMeta V7.1 Stage 2 Specialist Extraction — `{target_family.value}` "
                f"(model={family_spec['model']}, codebook={cb['codebook_id']}, sha256={cb_hash[:16]})"
            ),
            f"Family Scope: {family_spec['description']}",
            f"Output ONLY valid JSON conforming to `{family_spec['model']}`. Emit `rationale` FIRST (<= 280 chars).",
            "",
            "Governing Rules (TEXT-ONLY & EXACT SPAN GROUNDING):",
            f"1. {principles['text_is_sole_source_of_truth'].strip()}",
            f"2. {principles['interpret_do_not_invent'].strip()}",
            f"3. {principles['exact_span_grounding'].strip()}",
            "",
            f"Stage 1 Context (text-derived only): {json.dumps(stage1_context, ensure_ascii=False)}",
            "",
            f"Fields for `{target_family.value}`:",
            *field_lines,
            "",
            "Shared PersonaEntry Grounding Rules (every PersonaEntry MUST include name_span anchored in DOC_TEXT):",
            *persona_lines,
            "",
            "<<<DOC_TEXT>>>",
            doc_text,
            "<<<END_DOC_TEXT>>>",
        ]
    )


__all__ = [
    "CODEBOOK_PATH",
    "canonical_codebook_json",
    "codebook_version",
    "get_codebook",
    "render_core_prompt",
    "render_specialist_prompt",
    "validate_codebook_consistency",
]
