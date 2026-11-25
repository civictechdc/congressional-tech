"""DocMeta V7.0 outward interoperability crosswalks and exhaustive V6.5 -> V7 migration."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
import yaml

from .models import (
    GENRE_TO_FAMILY,
    STRICT_CONFIG,
    DocStatus,
    MediaFormat,
    PrimaryGenre,
    SpecialistFamily,
)

CROSSWALK_PATH = Path(__file__).resolve().parent / "crosswalk_v7_0.yaml"


@lru_cache(maxsize=1)
def _load_crosswalk_cached() -> dict[str, Any]:
    raw = yaml.safe_load(CROSSWALK_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping at root of {CROSSWALK_PATH}.")
    return raw


def get_crosswalk() -> dict[str, Any]:
    """Return a deep copy of the frozen V7.0 crosswalk YAML specification."""
    return deepcopy(_load_crosswalk_cached())


@lru_cache(maxsize=1)
def _load_v65_schema_enums() -> tuple[tuple[str, ...], tuple[str, ...]]:
    legacy = _load_crosswalk_cached()["standards"]["v65_legacy"]
    kinds = tuple(legacy["doc_kinds"])
    statuses = tuple(legacy["statuses"])
    return kinds, statuses


V65_DOC_KINDS, V65_STATUSES = _load_v65_schema_enums()

_STD = _load_crosswalk_cached()["standards"]
ARCHIVE_DOCUMENT_KINDS: tuple[str, ...] = tuple(_STD["archive_document_kind"]["canonical_kinds"])
CONGRESS_GOV_MEETING_DOC_TYPES: tuple[str, ...] = tuple(_STD["congress_gov_v3"]["meeting_document_types"])
CONGRESS_GOV_WITNESS_DOC_TYPES: tuple[str, ...] = tuple(_STD["congress_gov_v3"]["witness_document_types"])
CONGRESS_GOV_ALL_DOC_TYPES: tuple[str, ...] = CONGRESS_GOV_MEETING_DOC_TYPES + CONGRESS_GOV_WITNESS_DOC_TYPES
DOCS_HOUSE_GOV_CODES: tuple[str, ...] = tuple(_STD["docs_house_gov"]["codes"].keys())
LCGFT_TERMS: dict[str, str] = dict(_STD["lcgft"])


class OutwardCrosswalkEntry(BaseModel):
    """Outward standard mappings for one V7 PrimaryGenre."""

    model_config = STRICT_CONFIG

    primary_genre: PrimaryGenre
    specialist_family: SpecialistFamily
    archive_document_kind: str
    congress_gov_meeting_doc_types: list[str]
    docs_house_gov_codes: list[str]
    lcgft_uris: list[str]


class V65MigrationResult(BaseModel):
    """Deterministic mapping from V6.5 (status, primary_kind) to V7 core fields."""

    model_config = STRICT_CONFIG

    status: DocStatus
    media_format: MediaFormat | None = None
    is_packet: bool = False
    contains_genres: list[PrimaryGenre] = Field(default_factory=list)
    primary_genre: PrimaryGenre | None = None
    specialist_family: SpecialistFamily | None = None
    subkind: str | None = None
    requires_v7_relabel: bool = False

    def as_tuple(
        self,
    ) -> tuple[DocStatus, MediaFormat | None, bool, PrimaryGenre | None, SpecialistFamily | None, str | None]:
        """Return (status, media_format, is_packet, primary_genre, specialist_family, subkind)."""
        return (
            self.status,
            self.media_format,
            self.is_packet,
            self.primary_genre,
            self.specialist_family,
            self.subkind,
        )


def map_genre_to_document_kind(genre: PrimaryGenre | str, *, subkind: str | None = None) -> str:
    """Map a V7 PrimaryGenre (+ optional subkind) to the canonical release list.parquet document_kind."""
    target = genre if isinstance(genre, PrimaryGenre) else PrimaryGenre(genre)
    cw = _load_crosswalk_cached()
    spec = cw["v7_to_document_kind"][target.value]
    if subkind:
        norm_sub = "_".join(subkind.strip().lower().replace("-", "_").split())
        overrides = spec.get("subkind_overrides") or {}
        if norm_sub in overrides:
            return str(overrides[norm_sub])
        if target == PrimaryGenre.bill_or_amendment and "amend" in norm_sub:
            return "floor-amendment" if "floor" in norm_sub else "committee-amendment"
        if target == PrimaryGenre.qfr_correspondence and "response" in norm_sub:
            return "questions-for-record-response"
        if target == PrimaryGenre.hearing_memo_or_witness_list:
            if "witness_list" in norm_sub:
                return "witness-list"
            if "member_roster" in norm_sub:
                return "member-roster"
            if "rules" in norm_sub:
                return "rules-memorandum"
        if target == PrimaryGenre.budget_or_cost_estimate and "views" in norm_sub:
            return "budget-views-and-estimates"
    return str(spec["document_kind"])


def outward_crosswalk(genre: PrimaryGenre | str) -> OutwardCrosswalkEntry:
    """Return outward Congress.gov v3, docs.house.gov, LCGFT, and archive document_kind mappings for a V7 PrimaryGenre."""
    target = genre if isinstance(genre, PrimaryGenre) else PrimaryGenre(genre)
    cw = _load_crosswalk_cached()
    entry = cw["v7_to_external"][target.value]
    return OutwardCrosswalkEntry(
        primary_genre=target,
        specialist_family=GENRE_TO_FAMILY[target],
        archive_document_kind=map_genre_to_document_kind(target),
        congress_gov_meeting_doc_types=list(entry["congress_gov_meeting_doc_types"]),
        docs_house_gov_codes=list(entry["docs_house_gov_codes"]),
        lcgft_uris=list(entry["lcgft_uris"]),
    )


def map_genre_to_congress_gov(genre: PrimaryGenre | str) -> list[str]:
    """Map a V7 PrimaryGenre to Congress.gov v3 meeting/witness documentType values."""
    return outward_crosswalk(genre).congress_gov_meeting_doc_types


def map_genre_to_docs_house_gov(genre: PrimaryGenre | str) -> list[str]:
    """Map a V7 PrimaryGenre to docs.house.gov XML document type codes."""
    return outward_crosswalk(genre).docs_house_gov_codes


def map_genre_to_lcgft(genre: PrimaryGenre | str) -> list[str]:
    """Map a V7 PrimaryGenre to Library of Congress LCGFT genre/form URIs."""
    return outward_crosswalk(genre).lcgft_uris


def map_congress_gov_doc_type_to_v7(doc_type: str) -> dict[str, Any]:
    """Map a Congress.gov v3 meetingDocuments/witnessDocuments documentType to V7 triage/genre."""
    cw = _load_crosswalk_cached()
    aliases = {k.casefold(): v for k, v in cw["standards"]["congress_gov_v3"].get("aliases", {}).items()}
    mapping = cw["congress_gov_to_v7"]
    lookup = {k.casefold(): (k, v) for k, v in mapping.items()}

    norm = " ".join(doc_type.split()).casefold()
    if norm in aliases:
        norm = aliases[norm].casefold()
    if norm not in lookup:
        raise ValueError(f"Unknown Congress.gov v3 documentType: {doc_type!r}.")

    canonical_label, target = lookup[norm]
    genre = PrimaryGenre(target["primary_genre"]) if target["primary_genre"] is not None else None
    return {
        "source_doc_type": canonical_label,
        "status": DocStatus(target["status"]),
        "primary_genre": genre,
        "specialist_family": GENRE_TO_FAMILY[genre] if genre is not None else None,
        "subkind": target["subkind"],
    }


def map_docs_house_code_to_v7(code: str) -> dict[str, Any]:
    """Map a docs.house.gov XML document type code (e.g. WS, WT, ANS, NT) to V7 triage/genre."""
    cw = _load_crosswalk_cached()
    norm = code.strip().upper()
    mapping = cw["docs_house_gov_to_v7"]
    if norm not in mapping:
        raise ValueError(f"Unknown docs.house.gov document code: {code!r}.")
    target = mapping[norm]
    genre = PrimaryGenre(target["primary_genre"]) if target["primary_genre"] is not None else None
    return {
        "source_code": norm,
        "label": cw["standards"]["docs_house_gov"]["codes"][norm],
        "status": DocStatus(target["status"]),
        "primary_genre": genre,
        "specialist_family": GENRE_TO_FAMILY[genre] if genre is not None else None,
        "subkind": target["subkind"],
    }


def migrate_v65_to_v7(
    primary_kind: str | None = None,
    status: str = "usable",
    *,
    secondary_kinds: list[str] | None = None,
) -> V65MigrationResult:
    """Deterministically migrate a V6.5 (status, primary_kind, secondary_kinds) tuple to V7."""
    cw = _load_crosswalk_cached()
    status_map = cw["v65_statuses_to_v7"]
    kind_map = cw["v65_kinds_to_v7"]

    if status not in status_map:
        raise ValueError(f"Unknown V6.5 status: {status!r}.")

    mapped_status = DocStatus(status_map[status])
    if mapped_status != DocStatus.usable:
        if primary_kind is not None and primary_kind not in kind_map:
            raise ValueError(f"Unknown V6.5 primary_kind: {primary_kind!r}.")
        return V65MigrationResult(
            status=mapped_status,
            media_format=None,
            is_packet=False,
            contains_genres=[],
            primary_genre=None,
            specialist_family=None,
            subkind=None,
            requires_v7_relabel=False,
        )

    if primary_kind is None or primary_kind not in kind_map:
        raise ValueError(f"Valid V6.5 primary_kind is required when status='usable'; got {primary_kind!r}.")

    spec = kind_map[primary_kind]
    out_status = DocStatus(spec["status"])
    media_format = MediaFormat(spec["media_format"]) if spec["media_format"] is not None else None
    is_packet = bool(spec["is_packet"])
    primary_genre = PrimaryGenre(spec["primary_genre"]) if spec["primary_genre"] is not None else None
    subkind = spec["subkind"]
    requires_relabel = bool(spec["requires_v7_relabel"])
    contains_genres: list[PrimaryGenre] = []

    if is_packet:
        mapped_components: list[PrimaryGenre] = []
        for sec in secondary_kinds or ():
            if sec not in kind_map:
                raise ValueError(f"Unknown V6.5 secondary_kind: {sec!r}.")
            sec_genre = kind_map[sec]["primary_genre"]
            if sec_genre is not None:
                g = PrimaryGenre(sec_genre)
                if g not in mapped_components:
                    mapped_components.append(g)
        if mapped_components:
            primary_genre = mapped_components[0]
            contains_genres = mapped_components
        elif primary_genre is not None:
            contains_genres = [primary_genre]

    specialist_family = GENRE_TO_FAMILY[primary_genre] if primary_genre is not None else None
    if out_status != DocStatus.usable:
        primary_genre = None
        specialist_family = None
        is_packet = False
        contains_genres = []

    return V65MigrationResult(
        status=out_status,
        media_format=media_format,
        is_packet=is_packet,
        contains_genres=contains_genres,
        primary_genre=primary_genre,
        specialist_family=specialist_family,
        subkind=subkind,
        requires_v7_relabel=requires_relabel,
    )


def validate_crosswalk_consistency() -> list[str]:
    """Verify full coverage of all V7 genres, Congress.gov 18+4, docs.house.gov 16, LCGFT, and V6.5 47+8."""
    cw = _load_crosswalk_cached()
    errors: list[str] = []

    v7_to_ext = cw.get("v7_to_external", {})
    expected_genres = {g.value for g in PrimaryGenre}
    if set(v7_to_ext.keys()) != expected_genres:
        errors.append(f"v7_to_external genre mismatch: {sorted(set(v7_to_ext.keys()) ^ expected_genres)}")

    valid_cg = set(CONGRESS_GOV_ALL_DOC_TYPES)
    valid_house = set(DOCS_HOUSE_GOV_CODES)
    valid_lcgft = set(LCGFT_TERMS.keys())
    covered_cg: set[str] = set()
    covered_house: set[str] = set()
    covered_lcgft: set[str] = set()

    for genre_name, entry in v7_to_ext.items():
        cg_list = entry.get("congress_gov_meeting_doc_types") or []
        house_list = entry.get("docs_house_gov_codes") or []
        lcgft_list = entry.get("lcgft_uris") or []
        if not cg_list or not house_list or not lcgft_list:
            errors.append(f"Genre {genre_name!r} has empty outward mapping.")
        for val in cg_list:
            if val not in valid_cg:
                errors.append(f"Unknown Congress.gov doc type {val!r} on {genre_name!r}.")
            covered_cg.add(val)
        for val in house_list:
            if val not in valid_house:
                errors.append(f"Unknown docs.house.gov code {val!r} on {genre_name!r}.")
            covered_house.add(val)
        for val in lcgft_list:
            if val not in valid_lcgft:
                errors.append(f"Unknown LCGFT URI {val!r} on {genre_name!r}.")
            covered_lcgft.add(val)

    # Hearing: Cover Page & Hearing: Table of Contents map to non-usable status cover_or_toc.
    cg_to_v7 = cw.get("congress_gov_to_v7", {})
    if set(cg_to_v7.keys()) != valid_cg:
        errors.append(f"congress_gov_to_v7 mismatch: {sorted(set(cg_to_v7.keys()) ^ valid_cg)}")
    expected_usable_cg = {
        k for k, v in cg_to_v7.items() if v.get("status") == DocStatus.usable.value
    }
    if covered_cg != expected_usable_cg:
        errors.append(f"Outward Congress.gov coverage gap: {sorted(expected_usable_cg - covered_cg)}")
    if covered_house != valid_house:
        errors.append(f"Outward docs.house.gov coverage gap: {sorted(valid_house - covered_house)}")
    if covered_lcgft != valid_lcgft:
        errors.append(f"Outward LCGFT coverage gap: {sorted(valid_lcgft - covered_lcgft)}")

    house_to_v7 = cw.get("docs_house_gov_to_v7", {})
    if set(house_to_v7.keys()) != valid_house:
        errors.append(f"docs_house_gov_to_v7 mismatch: {sorted(set(house_to_v7.keys()) ^ valid_house)}")

    v65_statuses = set(cw.get("v65_statuses_to_v7", {}).keys())
    if v65_statuses != set(V65_STATUSES):
        errors.append(f"V6.5 status mismatch: {sorted(v65_statuses ^ set(V65_STATUSES))}")

    v65_kinds = set(cw.get("v65_kinds_to_v7", {}).keys())
    if v65_kinds != set(V65_DOC_KINDS):
        errors.append(f"V6.5 kind mismatch: {sorted(v65_kinds ^ set(V65_DOC_KINDS))}")

    v7_to_dk = cw.get("v7_to_document_kind", {})
    if set(v7_to_dk.keys()) != expected_genres:
        errors.append(f"v7_to_document_kind genre mismatch: {sorted(set(v7_to_dk.keys()) ^ expected_genres)}")
    else:
        valid_arch_kinds = set(ARCHIVE_DOCUMENT_KINDS)
        for gname, dspec in v7_to_dk.items():
            dk = dspec.get("document_kind")
            if not isinstance(dk, str) or not dk.strip():
                errors.append(f"v7_to_document_kind[{gname!r}] missing canonical document_kind.")
            elif dk not in valid_arch_kinds:
                errors.append(f"v7_to_document_kind[{gname!r}].document_kind {dk!r} not in archive_document_kind.")
            for ov_sub, ov_dk in (dspec.get("subkind_overrides") or {}).items():
                if not isinstance(ov_dk, str) or ov_dk not in valid_arch_kinds:
                    errors.append(
                        f"v7_to_document_kind[{gname!r}].subkind_overrides[{ov_sub!r}]={ov_dk!r} not in archive_document_kind."
                    )

    return errors


__all__ = [
    "ARCHIVE_DOCUMENT_KINDS",
    "CONGRESS_GOV_ALL_DOC_TYPES",
    "CONGRESS_GOV_MEETING_DOC_TYPES",
    "CONGRESS_GOV_WITNESS_DOC_TYPES",
    "CROSSWALK_PATH",
    "DOCS_HOUSE_GOV_CODES",
    "LCGFT_TERMS",
    "OutwardCrosswalkEntry",
    "V65MigrationResult",
    "V65_DOC_KINDS",
    "V65_STATUSES",
    "get_crosswalk",
    "map_congress_gov_doc_type_to_v7",
    "map_docs_house_code_to_v7",
    "map_genre_to_congress_gov",
    "map_genre_to_docs_house_gov",
    "map_genre_to_document_kind",
    "map_genre_to_lcgft",
    "migrate_v65_to_v7",
    "outward_crosswalk",
    "validate_crosswalk_consistency",
]
