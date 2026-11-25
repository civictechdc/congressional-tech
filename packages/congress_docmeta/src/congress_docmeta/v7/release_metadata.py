"""MLCommons Croissant 1.0 + RAI JSON-LD and W3C DCAT 3 JSON-LD release descriptors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from pathlib import Path
import re
from typing import Any

from .codebook import CODEBOOK_PATH, codebook_version
from .crosswalk import CROSSWALK_PATH, LCGFT_TERMS

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CROISSANT_SPEC_URL = "http://mlcommons.org/croissant/1.0"
CROISSANT_RAI_SPEC_URL = "http://mlcommons.org/croissant/RAI/1.0"
DCAT3_SPEC_URL = "https://www.w3.org/TR/vocab-dcat-3/"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_sha256(digest: str, label: str) -> str:
    norm = digest.strip().lower()
    if not _SHA256_RE.fullmatch(norm):
        raise ValueError(f"{label} must be a 64-character lowercase hex SHA-256 digest; got {digest!r}.")
    return norm


def build_croissant_manifest(
    *,
    dataset_id: str = "https://congressional.tech/releases/docmeta-v7",
    name: str = "congressional-tech-docmeta-v7",
    description: str = (
        "Per-document structured metadata for U.S. Congressional committee hearings, "
        "witness statements, Truth-in-Testimony disclosures, transcripts, QFRs, "
        "oversight letters, legislation, and fiscal estimates with span-grounded actors "
        "and outward Congress.gov / docs.house.gov / LCGFT crosswalks. FRBR/ELI-DL cross-document "
        "lifecycle classes are retained in code as unpopulated future scaffolding while "
        "archive SQL owns document editions and committee sittings."
    ),
    version: str = "7.1.0",
    date_published: str = "2026-11-22",
    url: str = "https://congressional.tech/datasets/docmeta-v7",
    license_url: str = "https://creativecommons.org/publicdomain/zero/1.0/",
    parquet_filename: str = "docmeta_v7.parquet",
    parquet_url: str = "https://congressional.tech/releases/docmeta-v7/docmeta_v7.parquet",
    parquet_sha256: str = "0" * 64,
    parquet_byte_size: int | None = None,
    crosswalk_url: str = "https://congressional.tech/releases/docmeta-v7/crosswalk_v7_0.yaml",
    crosswalk_sha256: str | None = None,
    codebook_url: str = "https://congressional.tech/releases/docmeta-v7/codebook_v7_0.yaml",
    codebook_sha256: str | None = None,
    codebook_ver: str | None = None,
    record_count: int | None = None,
    extra_distributions: list[dict[str, Any]] | None = None,
    fields_spec: Sequence[tuple[str, str, str, bool]] | None = None,
    annotation_protocol: str | None = None,
    limitations: str | None = None,
    data_collection_raw: str | None = None,
) -> dict[str, Any]:
    """Generate an MLCommons Croissant 1.0 + Responsible AI (RAI) JSON-LD dataset manifest."""
    cb_ver = codebook_ver or codebook_version()
    pq_sha = _validate_sha256(parquet_sha256, "parquet_sha256")
    cw_sha = _validate_sha256(crosswalk_sha256 or _file_sha256(CROSSWALK_PATH), "crosswalk_sha256")
    cb_sha = _validate_sha256(codebook_sha256 or _file_sha256(CODEBOOK_PATH), "codebook_sha256")

    parquet_file_obj: dict[str, Any] = {
        "@type": "cr:FileObject",
        "@id": "docmeta-v7-parquet",
        "name": parquet_filename,
        "description": "Primary Parquet table containing CoreEnvelopeExtraction and specialist payloads.",
        "contentUrl": parquet_url,
        "encodingFormat": "application/vnd.apache.parquet",
        "sha256": pq_sha,
    }
    if parquet_byte_size is not None:
        parquet_file_obj["contentSize"] = f"{parquet_byte_size} B"

    distributions: list[dict[str, Any]] = [
        parquet_file_obj,
        {
            "@type": "cr:FileObject",
            "@id": "docmeta-v7-codebook",
            "name": "codebook_v7_0.yaml",
            "description": f"Frozen V7.0 annotation codebook specification (canonical sha256={cb_ver}).",
            "contentUrl": codebook_url,
            "encodingFormat": "application/yaml",
            "sha256": cb_sha,
        },
        {
            "@type": "cr:FileObject",
            "@id": "docmeta-v7-crosswalk",
            "name": "crosswalk_v7_0.yaml",
            "description": "Outward interoperability crosswalk to Congress.gov v3, docs.house.gov, LCGFT, and V6.5.",
            "contentUrl": crosswalk_url,
            "encodingFormat": "application/yaml",
            "sha256": cw_sha,
        },
    ]
    if extra_distributions:
        distributions.extend(extra_distributions)

    effective_fields_spec: Sequence[tuple[str, str, str, bool]] = (
        fields_spec
        if fields_spec is not None
        else [
            ("doc_key", "sc:Text", "Stable content-addressed document identifier.", False),
            ("body_sha256", "sc:Text", "Lowercase SHA-256 hex digest of captured source manifestation bytes when retained.", False),
            ("status", "sc:Text", "Orthogonal V7 DocStatus triage label (usable vs wrapper/error/blank).", False),
            ("media_format", "sc:Text", "Orthogonal medium layout (prose, slides, web_page, table_or_form).", False),
            ("is_packet", "sc:Boolean", "Whether the captured file bundles multiple distinct substantive documents.", False),
            ("contains_genres", "sc:Text", "Ordered list of component PrimaryGenre values when is_packet is true.", True),
            ("primary_genre", "sc:Text", "One of 14 orthogonal V7 PrimaryGenre values when status='usable'.", False),
            ("specialist_family", "sc:Text", "Assigned Stage-2 specialist extractor family.", False),
            ("subkind", "sc:Text", "Optional fine-grained document subtype.", False),
            ("verbatim_title", "sc:Text", "Verbatim heading anchored in document text.", False),
            ("doc_date", "sc:Text", "Document's stated ISO date (YYYY, YYYY-MM, or YYYY-MM-DD).", False),
            ("chamber", "sc:Text", "Institutional chamber stated in document text.", False),
            ("congress", "sc:Integer", "Congress number (1..130) explicitly stated in document text.", False),
            ("committees", "sc:Text", "Authoring or jurisdictional congressional committees.", True),
            ("gist", "sc:Text", "Concise factual summary (<= 220 chars).", False),
            ("topics", "sc:Text", "Normalized policy subject tags.", True),
            ("specialist_payload_json", "sc:Text", "JSON serialization of the Stage-2 specialist extraction model.", False),
            ("codebook_version", "sc:Text", "Canonical SHA-256 hex digest of codebook_v7_0.yaml.", False),
            ("crosswalk_congress_gov_types", "sc:Text", "Mapped Congress.gov v3 committee-meeting documentType values.", True),
            ("crosswalk_docs_house_codes", "sc:Text", "Mapped docs.house.gov XML document codes.", True),
            ("crosswalk_lcgft_uris", "sc:Text", "Mapped Library of Congress LCGFT genre/form URIs.", True),
        ]
    )

    record_fields: list[dict[str, Any]] = []
    for col_name, data_type, col_desc, repeated in effective_fields_spec:
        field_obj: dict[str, Any] = {
            "@type": "cr:Field",
            "@id": f"docmeta_v7_records/{col_name}",
            "name": col_name,
            "description": col_desc,
            "dataType": data_type,
            "source": {
                "fileObject": {"@id": "docmeta-v7-parquet"},
                "extract": {"column": col_name},
            },
        }
        if repeated:
            field_obj["repeated"] = True
        record_fields.append(field_obj)

    record_set_obj: dict[str, Any] = {
        "@type": "cr:RecordSet",
        "@id": "docmeta_v7_records",
        "name": "docmeta_v7_records",
        "description": "DocMeta V7 document metadata records with span-grounded Stage-1 and Stage-2 extractions.",
        "key": {"@id": "docmeta_v7_records/doc_key"},
        "field": record_fields,
    }
    if record_count is not None:
        record_set_obj["data"] = [{"recordCount": record_count}]

    return {
        "@context": {
            "@language": "en",
            "@vocab": "https://schema.org/",
            "citeAs": "cr:citeAs",
            "column": "cr:column",
            "conformsTo": "dct:conformsTo",
            "cr": "http://mlcommons.org/croissant/",
            "data": {"@id": "cr:data", "@type": "@json"},
            "dataType": {"@id": "cr:dataType", "@type": "@id"},
            "dct": "http://purl.org/dc/terms/",
            "examples": {"@id": "cr:examples", "@type": "@json"},
            "extract": "cr:extract",
            "field": "cr:field",
            "fileObject": "cr:fileObject",
            "fileProperty": "cr:fileProperty",
            "fileSet": "cr:fileSet",
            "format": "cr:format",
            "includes": "cr:includes",
            "isLiveDataset": "cr:isLiveDataset",
            "jsonPath": "cr:jsonPath",
            "key": "cr:key",
            "md5": "cr:md5",
            "parentField": "cr:parentField",
            "path": "cr:path",
            "rai": "http://mlcommons.org/croissant/RAI/",
            "recordSet": "cr:recordSet",
            "references": "cr:references",
            "regex": "cr:regex",
            "repeated": "cr:repeated",
            "replace": "cr:replace",
            "sc": "https://schema.org/",
            "separator": "cr:separator",
            "source": "cr:source",
            "subField": "cr:subField",
            "transform": "cr:transform",
        },
        "@type": "sc:Dataset",
        "@id": dataset_id,
        "name": name,
        "description": description,
        "url": url,
        "version": version,
        "datePublished": date_published,
        "license": license_url,
        "conformsTo": [CROISSANT_SPEC_URL, CROISSANT_RAI_SPEC_URL],
        "citeAs": f"@dataset{{congressional_tech_docmeta_v7_{version.replace('.', '_')}, title={{DocMeta V7 Congressional Document Metadata}}, version={{{version}}}, year={{{date_published[:4]}}}}}",
        "rai:dataCollection": (
            "Public U.S. Congressional committee documents harvested from docs.house.gov, "
            "api.congress.gov/v3, Senate committee websites, and GovInfo/GPO archives, "
            "stored under SHA-256 content-addressed custody."
        ),
        "rai:dataCollectionType": ["Official API", "Web scraping", "Document harvesting"],
        "rai:dataCollectionRawData": (
            data_collection_raw
            or "Retained PDF, HTML, and XML congressional documents with immutable body_sha256 digests when present."
        ),
        "rai:dataAnnotationProtocol": (
            annotation_protocol
            or (
                f"Versioned codebook_v7.0 (sha256={cb_ver}); blind multi-family LLM consensus "
                "(Gemini, Claude CLI, Codex CLI) for Stage-1 triage with CheckEval binary arbitration, "
                "deterministic character-offset SpanRef grounding, single-teacher Stage-2 specialist "
                "extraction where applicable, and Cleanlab OOF auditing."
            )
        ),
        "rai:dataAnnotationPlatform": "DocMeta V7 3-Family Consensus Factory (deterministic pre-extract + pydantic v2 validation)",
        "rai:dataPreprocessingProtocol": (
            "Text-only slice extraction stripping filenames, URLs, and upstream hints; "
            "deterministic citation, date-span, and HTML CMS cleaning prior to classification."
        ),
        "rai:dataUseCases": (
            "Congressional hearing research, legislative provenance tracking, witness/organization "
            "network analysis, and fine-tuning compact structured extraction models."
        ),
        "rai:dataBiases": (
            "House committees publish standardized HHRG XML/PDF bundles via docs.house.gov while "
            "Senate committees publish heterogeneous HTML/PDF feeds; historical pre-2013 scans exhibit "
            "higher OCR noise than recent born-digital filings."
        ),
        "rai:dataLimitations": (
            limitations
            or (
                "Emits per-document extraction observations only; FRBR/ELI-DL cross-document lifecycle classes "
                "are retained as unpopulated future scaffolding while archive SQL owns editions and sittings. "
                "Truncated/garbled OCR scans and error pages are segregated under non-usable DocStatus "
                "values; outward crosswalks to Congress.gov v3, docs.house.gov, and LCGFT are many-to-one "
                "approximations where external vocabularies are coarser than V7."
            )
        ),
        "rai:personalSensitiveInformation": (
            "Source records are official public congressional materials. Private residential street "
            "addresses, personal phone numbers, and personal email addresses are excluded from "
            "extracted metadata."
        ),
        "rai:dataSocialImpact": (
            "Improves public transparency, auditability, and structured search across U.S. "
            "congressional oversight, hearings, and legislative activity."
        ),
        "rai:dataReleaseMaintenancePlan": (
            "Published as immutable WAP-lite SHA-256 sealed Parquet releases; codebook edits "
            "bump canonical codebook_version and trigger counterfactual regression verification."
        ),
        "distribution": distributions,
        "recordSet": [record_set_obj],
    }


def validate_croissant_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_columns: Sequence[str] | None = None,
) -> list[str]:
    """Validate structural conformance of an MLCommons Croissant 1.0 + RAI JSON-LD manifest."""
    errors: list[str] = []
    ctx = manifest.get("@context")
    if not isinstance(ctx, Mapping):
        errors.append("Croissant @context must be a mapping.")
    else:
        if ctx.get("cr") != "http://mlcommons.org/croissant/":
            errors.append("Croissant @context['cr'] must equal 'http://mlcommons.org/croissant/'.")
        if ctx.get("rai") != "http://mlcommons.org/croissant/RAI/":
            errors.append("Croissant @context['rai'] must equal 'http://mlcommons.org/croissant/RAI/'.")
        if ctx.get("sc") != "https://schema.org/":
            errors.append("Croissant @context['sc'] must equal 'https://schema.org/'.")

    if manifest.get("@type") != "sc:Dataset":
        errors.append(f"Croissant @type must be 'sc:Dataset'; got {manifest.get('@type')!r}.")

    for key in ("@id", "name", "description", "version", "datePublished", "license"):
        val = manifest.get(key)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"Croissant missing or empty required field {key!r}.")

    conforms_to = manifest.get("conformsTo")
    conforms_list = [conforms_to] if isinstance(conforms_to, str) else list(conforms_to or [])
    for spec in (CROISSANT_SPEC_URL, CROISSANT_RAI_SPEC_URL):
        if spec not in conforms_list:
            errors.append(f"Croissant conformsTo missing {spec!r}.")

    required_rai = (
        "rai:dataCollection",
        "rai:dataCollectionType",
        "rai:dataAnnotationProtocol",
        "rai:dataPreprocessingProtocol",
        "rai:dataBiases",
        "rai:dataLimitations",
        "rai:personalSensitiveInformation",
        "rai:dataReleaseMaintenancePlan",
    )
    for rkey in required_rai:
        rval = manifest.get(rkey)
        if not rval:
            errors.append(f"Croissant missing required RAI field {rkey!r}.")

    distributions = manifest.get("distribution")
    file_ids: set[str] = set()
    if not isinstance(distributions, list) or not distributions:
        errors.append("Croissant distribution must be a non-empty list.")
    else:
        for idx, dist in enumerate(distributions):
            if not isinstance(dist, Mapping):
                errors.append(f"distribution[{idx}] must be a mapping.")
                continue
            if dist.get("@type") != "cr:FileObject":
                errors.append(f"distribution[{idx}].@type must be 'cr:FileObject'.")
            fid = dist.get("@id")
            if not isinstance(fid, str) or not fid:
                errors.append(f"distribution[{idx}].@id must be non-empty.")
            else:
                file_ids.add(fid)
            for req in ("name", "contentUrl", "encodingFormat"):
                if not dist.get(req):
                    errors.append(f"distribution[{idx}] missing {req!r}.")
            sha = dist.get("sha256")
            if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
                errors.append(f"distribution[{idx}].sha256 must be 64 lowercase hex chars.")

    record_sets = manifest.get("recordSet")
    if not isinstance(record_sets, list) or not record_sets:
        errors.append("Croissant recordSet must be a non-empty list.")
    else:
        for rs_idx, rs in enumerate(record_sets):
            if not isinstance(rs, Mapping):
                errors.append(f"recordSet[{rs_idx}] must be a mapping.")
                continue
            if rs.get("@type") != "cr:RecordSet":
                errors.append(f"recordSet[{rs_idx}].@type must be 'cr:RecordSet'.")
            fields = rs.get("field")
            if not isinstance(fields, list) or not fields:
                errors.append(f"recordSet[{rs_idx}].field must be a non-empty list.")
                continue
            field_ids: set[str] = set()
            for f_idx, field in enumerate(fields):
                if not isinstance(field, Mapping):
                    errors.append(f"recordSet[{rs_idx}].field[{f_idx}] must be a mapping.")
                    continue
                if field.get("@type") != "cr:Field":
                    errors.append(f"recordSet[{rs_idx}].field[{f_idx}].@type must be 'cr:Field'.")
                field_id = field.get("@id")
                if isinstance(field_id, str) and field_id:
                    field_ids.add(field_id)
                dtype = field.get("dataType")
                if not isinstance(dtype, str) or not dtype.startswith("sc:"):
                    errors.append(f"recordSet[{rs_idx}].field[{f_idx}].dataType must be an 'sc:' type.")
                src = field.get("source")
                if not isinstance(src, Mapping):
                    errors.append(f"recordSet[{rs_idx}].field[{f_idx}].source missing.")
                else:
                    fo_ref = (src.get("fileObject") or {}).get("@id") if isinstance(src.get("fileObject"), Mapping) else None
                    if fo_ref not in file_ids:
                        errors.append(
                            f"recordSet[{rs_idx}].field[{f_idx}] references unknown fileObject {fo_ref!r}."
                        )
                    col = (src.get("extract") or {}).get("column") if isinstance(src.get("extract"), Mapping) else None
                    if not col:
                        errors.append(f"recordSet[{rs_idx}].field[{f_idx}] missing source.extract.column.")
            key_ref = rs.get("key")
            if isinstance(key_ref, Mapping) and key_ref.get("@id") not in field_ids:
                errors.append(f"recordSet[{rs_idx}].key references unknown field {key_ref.get('@id')!r}.")
            if expected_columns is not None:
                extracted_cols = [
                    str((f.get("source") or {}).get("extract", {}).get("column"))
                    for f in fields
                    if isinstance(f, Mapping)
                ]
                expected_set = set(expected_columns)
                actual_set = set(extracted_cols)
                missing_cols = sorted(expected_set - actual_set)
                extra_cols = sorted(actual_set - expected_set)
                if missing_cols:
                    errors.append(f"recordSet[{rs_idx}] missing expected Parquet columns: {missing_cols}")
                if extra_cols:
                    errors.append(f"recordSet[{rs_idx}] contains unexpected Parquet columns: {extra_cols}")

    return errors


def build_dcat3_catalog(
    *,
    catalog_id: str = "https://congressional.tech/catalog",
    catalog_title: str = "Congressional Tech Open Legislative Metadata Catalog",
    catalog_description: str = (
        "W3C DCAT 3 catalog of immutable congressional hearing, committee document, "
        "and interoperability crosswalk releases."
    ),
    dataset_id: str = "https://congressional.tech/releases/docmeta-v7",
    dataset_title: str = "DocMeta V7 Congressional Committee & Hearing Metadata",
    dataset_description: str = (
        "Per-document structured metadata for U.S. Congressional committee "
        "documents with span-grounded actors and outward Congress.gov v3, docs.house.gov, "
        "and Library of Congress LCGFT crosswalks (FRBR/ELI-DL cross-document classes unpopulated in V7.3)."
    ),
    series_id: str = "https://congressional.tech/releases/docmeta-series",
    version: str = "7.1.0",
    previous_version_url: str | None = None,
    issued: str = "2026-11-22",
    modified: str = "2026-11-22",
    publisher_name: str = "Congressional Tech",
    publisher_url: str = "https://congressional.tech",
    license_url: str = "https://creativecommons.org/publicdomain/zero/1.0/",
    parquet_url: str = "https://congressional.tech/releases/docmeta-v7/docmeta_v7.parquet",
    parquet_sha256: str = "0" * 64,
    parquet_byte_size: int | None = None,
    croissant_url: str = "https://congressional.tech/releases/docmeta-v7/croissant.jsonld",
    croissant_sha256: str | None = None,
    crosswalk_url: str = "https://congressional.tech/releases/docmeta-v7/crosswalk_v7_0.yaml",
    crosswalk_sha256: str | None = None,
    codebook_ver: str | None = None,
    version_notes: str | None = None,
    keywords: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Generate a W3C DCAT 3 conformant JSON-LD catalog descriptor."""
    cb_ver = codebook_ver or codebook_version()
    pq_sha = _validate_sha256(parquet_sha256, "parquet_sha256")
    cw_sha = _validate_sha256(crosswalk_sha256 or _file_sha256(CROSSWALK_PATH), "crosswalk_sha256")

    parquet_dist: dict[str, Any] = {
        "@id": f"{dataset_id}#dist-parquet",
        "@type": "dcat:Distribution",
        "dcterms:title": {"en": "DocMeta V7 Parquet Release"},
        "dcterms:format": "http://publications.europa.eu/resource/authority/file-type/PARQUET",
        "dcat:mediaType": "application/vnd.apache.parquet",
        "dcat:accessURL": parquet_url,
        "dcat:downloadURL": parquet_url,
        "dcterms:license": license_url,
        "spdx:checksum": {
            "@type": "spdx:Checksum",
            "spdx:algorithm": "spdx:checksumAlgorithm_sha256",
            "spdx:checksumValue": pq_sha,
        },
    }
    if parquet_byte_size is not None:
        parquet_dist["dcat:byteSize"] = parquet_byte_size

    crosswalk_dist: dict[str, Any] = {
        "@id": f"{dataset_id}#dist-crosswalk",
        "@type": "dcat:Distribution",
        "dcterms:title": {"en": "DocMeta V7 Outward Crosswalk (Congress.gov v3, docs.house.gov, LCGFT)"},
        "dcterms:format": "http://publications.europa.eu/resource/authority/file-type/YAML",
        "dcat:mediaType": "application/yaml",
        "dcat:accessURL": crosswalk_url,
        "dcat:downloadURL": crosswalk_url,
        "dcterms:license": license_url,
        "spdx:checksum": {
            "@type": "spdx:Checksum",
            "spdx:algorithm": "spdx:checksumAlgorithm_sha256",
            "spdx:checksumValue": cw_sha,
        },
    }

    distributions: list[dict[str, Any]] = [parquet_dist, crosswalk_dist]
    if croissant_sha256 is not None:
        cr_sha = _validate_sha256(croissant_sha256, "croissant_sha256")
        distributions.append(
            {
                "@id": f"{dataset_id}#dist-croissant",
                "@type": "dcat:Distribution",
                "dcterms:title": {"en": "MLCommons Croissant 1.0 + RAI Metadata"},
                "dcterms:format": "http://publications.europa.eu/resource/authority/file-type/JSON_LD",
                "dcat:mediaType": "application/ld+json",
                "dcat:accessURL": croissant_url,
                "dcat:downloadURL": croissant_url,
                "dcterms:license": license_url,
                "spdx:checksum": {
                    "@type": "spdx:Checksum",
                    "spdx:algorithm": "spdx:checksumAlgorithm_sha256",
                    "spdx:checksumValue": cr_sha,
                },
            }
        )

    dataset_entry: dict[str, Any] = {
        "@id": dataset_id,
        "@type": "dcat:Dataset",
        "dcterms:title": {"en": dataset_title},
        "dcterms:description": {"en": dataset_description},
        "dcat:version": version,
        "adms:versionNotes": {
            "en": version_notes or f"DocMeta {version} schema locked to codebook_v7.0 sha256={cb_ver}"
        },
        "dcterms:issued": issued,
        "dcterms:modified": modified,
        "dcterms:publisher": publisher_url,
        "dcterms:license": license_url,
        "dcat:inSeries": series_id,
        "dcterms:conformsTo": [
            DCAT3_SPEC_URL,
            CROISSANT_SPEC_URL,
            CROISSANT_RAI_SPEC_URL,
            *sorted(LCGFT_TERMS.keys()),
        ],
        "dcat:keyword": (
            list(keywords)
            if keywords is not None
            else [
                "united-states-congress",
                "congressional-hearings",
                "committee-documents",
                "legislative-metadata",
                "truth-in-testimony",
            ]
        ),
        "dcat:theme": [
            "http://publications.europa.eu/resource/authority/data-theme/GOVE",
            "http://publications.europa.eu/resource/authority/data-theme/JUST",
        ],
        "dcterms:spatial": "http://publications.europa.eu/resource/authority/country/USA",
        "dcat:distribution": distributions,
    }
    if previous_version_url is not None:
        dataset_entry["dcat:previousVersion"] = previous_version_url

    series_entry: dict[str, Any] = {
        "@id": series_id,
        "@type": "dcat:DatasetSeries",
        "dcterms:title": {"en": "Congressional Tech DocMeta Release Series"},
        "dcterms:description": {"en": "Chronological series of immutable DocMeta metadata releases."},
        "dcat:version": version,
        "dcat:last": dataset_id,
    }

    return {
        "@context": {
            "adms": "http://www.w3.org/ns/adms#",
            "dcat": "http://www.w3.org/ns/dcat#",
            "dcterms": "http://purl.org/dc/terms/",
            "foaf": "http://xmlns.com/foaf/0.1/",
            "prov": "http://www.w3.org/ns/prov#",
            "spdx": "http://spdx.org/rdf/terms#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
        },
        "@id": catalog_id,
        "@type": "dcat:Catalog",
        "dcterms:title": {"en": catalog_title},
        "dcterms:description": {"en": catalog_description},
        "dcterms:issued": issued,
        "dcterms:modified": modified,
        "dcterms:license": license_url,
        "dcterms:conformsTo": DCAT3_SPEC_URL,
        "dcat:version": version,
        "dcterms:publisher": {
            "@id": publisher_url,
            "@type": "foaf:Organization",
            "foaf:name": publisher_name,
            "foaf:homepage": publisher_url,
        },
        "dcat:dataset": [dataset_entry, series_entry],
    }


def validate_dcat3_catalog(catalog: Mapping[str, Any]) -> list[str]:
    """Validate structural conformance of a W3C DCAT 3 JSON-LD catalog descriptor."""
    errors: list[str] = []
    ctx = catalog.get("@context")
    if not isinstance(ctx, Mapping):
        errors.append("DCAT 3 @context must be a mapping.")
    else:
        for prefix, uri in (
            ("dcat", "http://www.w3.org/ns/dcat#"),
            ("dcterms", "http://purl.org/dc/terms/"),
            ("spdx", "http://spdx.org/rdf/terms#"),
        ):
            if ctx.get(prefix) != uri:
                errors.append(f"DCAT 3 @context[{prefix!r}] must equal {uri!r}.")

    if catalog.get("@type") != "dcat:Catalog":
        errors.append(f"DCAT 3 @type must be 'dcat:Catalog'; got {catalog.get('@type')!r}.")

    for req in ("@id", "dcterms:title", "dcterms:description", "dcat:version"):
        if not catalog.get(req):
            errors.append(f"DCAT 3 catalog missing {req!r}.")

    conforms = catalog.get("dcterms:conformsTo")
    conforms_list = [conforms] if isinstance(conforms, str) else list(conforms or [])
    if DCAT3_SPEC_URL not in conforms_list:
        errors.append(f"DCAT 3 catalog dcterms:conformsTo missing {DCAT3_SPEC_URL!r}.")

    datasets = catalog.get("dcat:dataset")
    if not isinstance(datasets, list) or not datasets:
        errors.append("DCAT 3 catalog dcat:dataset must be a non-empty list.")
        return errors

    primary_datasets = [d for d in datasets if isinstance(d, Mapping) and d.get("@type") == "dcat:Dataset"]
    if not primary_datasets:
        errors.append("DCAT 3 catalog must contain at least one 'dcat:Dataset'.")

    for idx, ds in enumerate(datasets):
        if not isinstance(ds, Mapping):
            errors.append(f"dcat:dataset[{idx}] must be a mapping.")
            continue
        dtype = ds.get("@type")
        if dtype not in ("dcat:Dataset", "dcat:DatasetSeries"):
            errors.append(f"dcat:dataset[{idx}].@type must be 'dcat:Dataset' or 'dcat:DatasetSeries'; got {dtype!r}.")
            continue
        for req in ("@id", "dcterms:title", "dcterms:description", "dcat:version"):
            if not ds.get(req):
                errors.append(f"dcat:dataset[{idx}] missing {req!r}.")
        if dtype == "dcat:Dataset":
            dists = ds.get("dcat:distribution")
            if not isinstance(dists, list) or not dists:
                errors.append(f"dcat:dataset[{idx}] missing non-empty 'dcat:distribution'.")
                continue
            for d_idx, dist in enumerate(dists):
                if not isinstance(dist, Mapping):
                    errors.append(f"dcat:dataset[{idx}].dcat:distribution[{d_idx}] must be a mapping.")
                    continue
                if dist.get("@type") != "dcat:Distribution":
                    errors.append(f"dcat:dataset[{idx}].dcat:distribution[{d_idx}].@type must be 'dcat:Distribution'.")
                for dreq in ("@id", "dcat:accessURL", "dcat:mediaType"):
                    if not dist.get(dreq):
                        errors.append(f"dcat:dataset[{idx}].dcat:distribution[{d_idx}] missing {dreq!r}.")
                chk = dist.get("spdx:checksum")
                if not isinstance(chk, Mapping):
                    errors.append(f"dcat:dataset[{idx}].dcat:distribution[{d_idx}] missing spdx:checksum.")
                else:
                    val = chk.get("spdx:checksumValue")
                    if not isinstance(val, str) or not _SHA256_RE.fullmatch(val):
                        errors.append(
                            f"dcat:dataset[{idx}].dcat:distribution[{d_idx}] spdx:checksumValue must be 64 lowercase hex chars."
                        )

    return errors


__all__ = [
    "CROISSANT_RAI_SPEC_URL",
    "CROISSANT_SPEC_URL",
    "DCAT3_SPEC_URL",
    "build_croissant_manifest",
    "build_dcat3_catalog",
    "validate_croissant_manifest",
    "validate_dcat3_catalog",
]
