"""Export ODCS v3.2.0 DataContracts and RefSpec/spicycongress URN bindings from archive_schema.

`viewer_publication.archive_schema` and `model/registries/release-schema.json` remain
the single schema owner. This module derives deterministic ODCS v3.2.0 DataContract JSON
artifacts, canonical RefSpec/spicycongress URN bindings, Arrow schema conversions, and
offline drift/Parquet schema parity checks without duplicating schema tables.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from viewer_publication.archive_schema import _parts, build_schema, field_types

ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_DIR = ROOT / 'model/contracts'
BUNDLE_CONTRACT_PATH = CONTRACTS_DIR / 'archive-release.odcs.json'
TABLE_CONTRACTS_DIR = CONTRACTS_DIR / 'tables'
URN_BINDINGS_PATH = CONTRACTS_DIR / 'refspec-urn-bindings.json'
REFSPEC_MANIFEST_PATH = ROOT / 'model/jobs/refspec/refspec.json'
REFSPEC_VIEW_MANIFEST_PATH = ROOT / 'model/jobs/refspec/agency-registry-view/view-manifest.json'
SPICY_REGS_MANIFEST_PATH = ROOT / 'model/jobs/spicy-regs/spicy-regs.json'
CAPTURE_ELIGIBILITY_FIELDS_PATH = ROOT / 'model/registries/capture-eligibility-fields.json'

ODCS_API_VERSION = 'v3.2.0'
CONTRACT_VERSION = '1.0.0'
LIVE_VERIFY_USER_AGENT = 'congressional-tech-verify/1.0'

_SIMPLE_SHORTHAND_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_\-]*(\.[A-Za-z_][A-Za-z0-9_\-]*)+$')
_FIXED_TYPE_RE = re.compile(r'^fixed\[([1-9][0-9]*)\]$')
_HEX64_RE = re.compile(r'^[0-9a-f]{64}$')
_SAFE_PARQUET_FILENAME_RE = re.compile(r'^[a-z0-9_]+\.parquet$')

# Canonical spicy-regs family provenance per published table (mirrors archive_format.SPICY_PRODUCER_FAMILIES).
SPICY_PRODUCER_TABLES: dict[str, tuple[str, ...]] = {
    'committees': ('committee-rosters',),
    'members': ('members',),
    'rosters': ('committee-rosters',),
    'bills': ('bill-family', 'roll-call-votes', 'amendments'),
    'nominations': ('nominations', 'roll-call-votes'),
    'bill_actions': ('bill-family',),
    'roll_call_votes': ('roll-call-votes',),
    'member_votes': ('roll-call-votes',),
}

# Canonical cross-stack concept definitions matching spicycongress/datamap/definitions/ and RefSpec.
CANONICAL_CONCEPTS: dict[str, dict[str, Any]] = {
    'urn:ddk:legislative:concept:bill-id': {
        'definitionName': 'bill-id',
        'conceptKind': 'identifier',
        'description': 'Bill or resolution identifier in CongressKey form: congress-type-number, e.g. 119-hr-1.',
        'examples': ['119-hr-1', '117-hr-5376', '118-s-222'],
    },
    'urn:ddk:legislative:concept:bioguide-id': {
        'definitionName': 'bioguide-id',
        'conceptKind': 'identifier',
        'description': 'Biographical Directory of the United States Congress member identifier, e.g. P000197.',
        'examples': ['P000197', 'S000148', 'C001098'],
    },
    'urn:ddk:legislative:concept:committee-code': {
        'definitionName': 'house-committee-code',
        'conceptKind': 'identifier',
        'description': 'Normalized congressional committee system code (e.g. hsju00, hlig00, htzt00, ssev00).',
        'examples': ['hsju00', 'hlig00', 'htzt00', 'ssev00'],
    },
    'urn:ddk:legislative:concept:event-id': {
        'definitionName': 'house-event-id',
        'conceptKind': 'identifier',
        'description': 'Congressional committee meeting event identifier (e.g. 118012).',
        'examples': ['118012', '118001', '326181'],
    },
    'urn:ddk:gpo:concept:package-id': {
        'definitionName': 'govinfo-package-id',
        'conceptKind': 'identifier',
        'description': 'GovInfo package identifier, e.g. CHRG-119hhrg58102, BILLS-119hr1ih, PLAW-118publ50.',
        'examples': ['CHRG-119hhrg58102', 'BILLS-119hr1ih', 'PLAW-118publ50'],
    },
    'urn:ddk:legislative:concept:roll-call-id': {
        'definitionName': 'roll-call-id',
        'conceptKind': 'identifier',
        'description': 'Roll call vote identifier scoped by session: congress-chamber-session-roll, e.g. 119-house-1-12.',
        'examples': ['119-house-1-12', '119-house-2-99', '118-senate-1-450'],
    },
    'urn:ddk:fec:concept:candidate-id': {
        'definitionName': 'fec-candidate-id',
        'conceptKind': 'identifier',
        'description': 'FEC nine-character candidate identifier, e.g. P80001571, H8NY14149.',
        'examples': ['P80001571', 'H8NY14149', 'H8CA05035'],
    },
    'urn:ddk:entity:concept:org-id': {
        'definitionName': 'org-id',
        'conceptKind': 'identifier',
        'description': 'Cross-stack organization identifier. Archive organizations.org_id links to RefSpec via anchor/organization_ids.',
        'examples': ['org:environmental-protection-agency', 'org:3m-company'],
    },
    'urn:ddk:entity:concept:person-id': {
        'definitionName': 'person-id',
        'conceptKind': 'identifier',
        'description': 'Cross-stack person identifier. Archive people.person_key uses Bioguide ID for matched Members or 16-hex hash for non-Member witnesses.',
        'examples': ['person:nancy-pelosi'],
    },
    'urn:refspec:agency-registry:anchor': {
        'definitionName': 'refspec-agency-anchor',
        'conceptKind': 'identifier',
        'description': 'RefSpec federal agency anchor emitted by organizations.sql (fr_agency:<fr_id> or refspec_target:urn:ref:*).',
        'examples': ['fr_agency:150', 'refspec_target:urn:ref:federal-hierarchy-org:500193110'],
    },
    'urn:congressional-tech:concept:link-key': {
        'definitionName': 'archive-link-key',
        'conceptKind': 'identifier',
        'description': 'Stable 8-byte public archive document key (first 8 SHA-256 bytes of body or url:<original_url>).',
        'examples': [],
    },
    'urn:congressional-tech:concept:witness-key': {
        'definitionName': 'archive-witness-key',
        'conceptKind': 'identifier',
        'description': 'Stable 16-hex witness appearance identifier scoped to source, occasion, and occurrence.',
        'examples': [],
    },
    'urn:congressional-tech:concept:video-key': {
        'definitionName': 'archive-video-key',
        'conceptKind': 'identifier',
        'description': 'Provider-prefixed hearing recording key (e.g. youtube:<id>, senate:<id>, house:<id>).',
        'examples': [],
    },
    'urn:congressional-tech:concept:nomination-id': {
        'definitionName': 'congress-nomination-id',
        'conceptKind': 'identifier',
        'description': 'Congress-scoped executive nomination identifier (e.g. 119-pn-12).',
        'examples': ['119-pn-12'],
    },
    'urn:congressional-tech:concept:measure-key': {
        'definitionName': 'archive-measure-key',
        'conceptKind': 'identifier',
        'description': 'Polymorphic legislative measure key covering bill-id, nomination-id, and treaty keys.',
        'examples': ['119-hr-1', '119-pn-12'],
    },
}

# Field path -> (concept_urn, extra_custom_properties)
_DOCUMENT_LIST_URN_BINDINGS: dict[str, tuple[str, dict[str, Any]]] = {
    'committee_keys[]': ('urn:ddk:legislative:concept:committee-code', {}),
    'meeting_keys[]': (
        'urn:ddk:legislative:concept:event-id',
        {'representationNote': 'Decimal string event ID; joins meetings.event_id via integer cast.'},
    ),
    'measure_keys[]': (
        'urn:congressional-tech:concept:measure-key',
        {'relatedConcepts': ['urn:ddk:legislative:concept:bill-id', 'urn:congressional-tech:concept:nomination-id']},
    ),
    'bioguide_ids[]': ('urn:ddk:legislative:concept:bioguide-id', {}),
    'witness_keys[]': ('urn:congressional-tech:concept:witness-key', {}),
}

TABLE_FIELD_URN_BINDINGS: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {
    'list': dict(_DOCUMENT_LIST_URN_BINDINGS),
    'detail': {
        **_DOCUMENT_LIST_URN_BINDINGS,
        'link_key': ('urn:congressional-tech:concept:link-key', {}),
        'package_id': ('urn:ddk:gpo:concept:package-id', {}),
    },
    'links': {
        'link_key': ('urn:congressional-tech:concept:link-key', {}),
    },
    'retired_links': {
        'link_key': ('urn:congressional-tech:concept:link-key', {}),
        'successor_key': ('urn:congressional-tech:concept:link-key', {}),
        'address_versions[]': ('urn:congressional-tech:concept:link-key', {}),
    },
    'videos': {
        'video_key': ('urn:congressional-tech:concept:video-key', {}),
        'system_code': ('urn:ddk:legislative:concept:committee-code', {}),
        'stated_event_ids[]': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
    },
    'channels': {
        'system_code': ('urn:ddk:legislative:concept:committee-code', {}),
    },
    'recording_matches': {
        'video_key': ('urn:congressional-tech:concept:video-key', {}),
        'event_id': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
        'package_id': ('urn:ddk:gpo:concept:package-id', {}),
        'meeting_links[].event_id': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
    },
    'recordings': {
        'video_key': ('urn:congressional-tech:concept:video-key', {}),
        'event_ids[]': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
    },
    'meetings': {
        'event_id': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
        'rescheduled_to': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
        'committees[].system_code': ('urn:ddk:legislative:concept:committee-code', {}),
        'subject_keys[]': (
            'urn:congressional-tech:concept:measure-key',
            {'relatedConcepts': ['urn:ddk:legislative:concept:bill-id', 'urn:congressional-tech:concept:nomination-id']},
        ),
        'unlisted_subjects[].subject_key': (
            'urn:congressional-tech:concept:measure-key',
            {'relatedConcepts': ['urn:ddk:legislative:concept:bill-id', 'urn:congressional-tech:concept:nomination-id']},
        ),
        'transcripts[].package_id': ('urn:ddk:gpo:concept:package-id', {}),
        'transcripts[].video_key': ('urn:congressional-tech:concept:video-key', {}),
        'videos[].video_key': ('urn:congressional-tech:concept:video-key', {}),
    },
    'witnesses': {
        'witness_key': ('urn:congressional-tech:concept:witness-key', {}),
        'event_id': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
        'package_id': ('urn:ddk:gpo:concept:package-id', {}),
        'bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
        'matched_bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
        'superseded_by': ('urn:congressional-tech:concept:witness-key', {}),
        'person_key': (
            'urn:ddk:entity:concept:person-id',
            {'representationNote': 'Archive person_key (Bioguide ID for matched Members, 16-hex hash otherwise).'},
        ),
    },
    'witness_key_map': {
        'old_key': ('urn:congressional-tech:concept:witness-key', {}),
        'witness_key': ('urn:congressional-tech:concept:witness-key', {}),
        'candidate_keys[]': ('urn:congressional-tech:concept:witness-key', {}),
    },
    'people': {
        'person_key': (
            'urn:ddk:entity:concept:person-id',
            {'representationNote': 'Archive person_key (Bioguide ID for matched Members, 16-hex hash otherwise).'},
        ),
        'bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
        'witness_keys[]': ('urn:congressional-tech:concept:witness-key', {}),
    },
    'person_aliases': {
        'old_person_key': (
            'urn:ddk:entity:concept:person-id',
            {'representationNote': 'Archive person_key (Bioguide ID or 16-hex hash).'},
        ),
        'person_key': (
            'urn:ddk:entity:concept:person-id',
            {'representationNote': 'Archive person_key (Bioguide ID or 16-hex hash).'},
        ),
        'candidate_keys[]': (
            'urn:ddk:entity:concept:person-id',
            {'representationNote': 'Archive person_key (Bioguide ID or 16-hex hash).'},
        ),
    },
    'caption_resources': {
        'video_key': ('urn:congressional-tech:concept:video-key', {}),
    },
    'committee_records': {
        'event_id': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
        'sponsor_bioguide': ('urn:ddk:legislative:concept:bioguide-id', {}),
    },
    'meeting_coverage': {
        'event_id': (
            'urn:ddk:legislative:concept:event-id',
            {'representationNote': '64-bit integer event ID.'},
        ),
    },
    'historical_recording_matches': {
        'package_id': ('urn:ddk:gpo:concept:package-id', {}),
        'committee_code': ('urn:ddk:legislative:concept:committee-code', {}),
    },
    'committees': {
        'system_code': ('urn:ddk:legislative:concept:committee-code', {}),
        'parent_system_code': ('urn:ddk:legislative:concept:committee-code', {}),
    },
    'members': {
        'bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
        'cross_ids.fec[]': ('urn:ddk:fec:concept:candidate-id', {}),
    },
    'rosters': {
        'system_code': ('urn:ddk:legislative:concept:committee-code', {}),
        'bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
    },
    'bills': {
        'bill_id': ('urn:ddk:legislative:concept:bill-id', {}),
        'sponsor_bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
        'related_bills[].bill_id': ('urn:ddk:legislative:concept:bill-id', {}),
        'committees[]': ('urn:ddk:legislative:concept:committee-code', {}),
        'floor_votes[].vote_id': ('urn:ddk:legislative:concept:roll-call-id', {}),
        'amendments[].sponsor_bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
        'committee_activities[].system_code': ('urn:ddk:legislative:concept:committee-code', {}),
    },
    'nominations': {
        'nomination_id': ('urn:congressional-tech:concept:nomination-id', {}),
        'committees[]': ('urn:ddk:legislative:concept:committee-code', {}),
        'transcripts[]': ('urn:ddk:gpo:concept:package-id', {}),
        'floor_votes[].vote_id': ('urn:ddk:legislative:concept:roll-call-id', {}),
        'committee_activities[].system_code': ('urn:ddk:legislative:concept:committee-code', {}),
    },
    'bill_actions': {
        'bill_id': ('urn:ddk:legislative:concept:bill-id', {}),
    },
    'roll_call_votes': {
        'vote_id': ('urn:ddk:legislative:concept:roll-call-id', {}),
        'bill_id': ('urn:ddk:legislative:concept:bill-id', {}),
        'bill_references[].bill_id': ('urn:ddk:legislative:concept:bill-id', {}),
    },
    'member_votes': {
        'vote_id': ('urn:ddk:legislative:concept:roll-call-id', {}),
        'bioguide_id': ('urn:ddk:legislative:concept:bioguide-id', {}),
    },
    'organizations': {
        'org_id': (
            'urn:ddk:entity:concept:org-id',
            {'representationNote': 'Archive org_id linked to RefSpec agencies via anchor and organization_ids.'},
        ),
        'parent_org_id': (
            'urn:ddk:entity:concept:org-id',
            {'representationNote': 'Archive org_id of resolved RefSpec parent agency.'},
        ),
        'anchor': ('urn:refspec:agency-registry:anchor', {}),
    },
    'organization_ids': {
        'org_id': (
            'urn:ddk:entity:concept:org-id',
            {'representationNote': 'Archive org_id linked to RefSpec agencies via anchor and organization_ids.'},
        ),
    },
    'witness_organizations': {
        'witness_key': ('urn:congressional-tech:concept:witness-key', {}),
        'org_id': (
            'urn:ddk:entity:concept:org-id',
            {'representationNote': 'Archive org_id linked to RefSpec agencies via anchor and organization_ids.'},
        ),
    },
    'organization_redirects': {
        'old_org_id': (
            'urn:ddk:entity:concept:org-id',
            {'representationNote': 'Retired archive org_id superseded by canonical org_id.'},
        ),
        'org_id': (
            'urn:ddk:entity:concept:org-id',
            {'representationNote': 'Archive org_id linked to RefSpec agencies via anchor and organization_ids.'},
        ),
    },
}

# Empirical Parquet parity findings documented from live release efd7973e200f05a15c5f9d732d343a3b2bab1ac88915d15b7053cba096d8943c.
LIVE_PARQUET_PARITY_NOTES: dict[str, Any] = {
    'verifiedReleaseId': 'efd7973e200f05a15c5f9d732d343a3b2bab1ac88915d15b7053cba096d8943c',
    'nullability': (
        'release-schema.json declares logical write-time nullability enforced by archive_schema.publication_checks. '
        'DataFusion SQL exports emit Arrow Parquet fields with nullable=True on most projected expressions, while '
        'committees.is_current and selected literal/dictionary columns emit nullable=False. '
        'Physical Parquet parity therefore requires check_nullability=False.'
    ),
    'columnOrderDiffersTables': ['bills', 'meetings', 'nominations', 'roll_call_votes'],
    'columnOrderNote': (
        'These four tables are exported via SELECT * FROM *_export without an explicit column list in '
        'archive_format.py, so physical Parquet column order differs from release-schema.json (same column set).'
    ),
    'captureProfileV2Extension': {
        'table': 'url_state',
        'fields': ['capture_disposition', 'capture_reason', 'capture_decision_id'],
        'source': 'model/registries/capture-eligibility-fields.json',
        'note': 'Appended dynamically at write time by archive_format.py when capture_profile.json version == 2.',
    },
    'producerSqlDriftInLiveRelease': {
        'organization_ids': {
            'extraParquetColumns': ['evidence'],
            'note': 'Emitted by archive_model.py organization_ids SQL, absent from release-schema.json.',
        },
        'witness_organizations': {
            'extraParquetColumns': ['method', 'score', 'evidence'],
            'note': 'Emitted by archive_model.py witness_organizations SQL, absent from release-schema.json.',
        },
        'roll_call_votes': {
            'field': 'documents[]',
            'extraStructField': 'nomination_id',
            'note': 'Present in SPICY_SCHEMAS spicy_roll_call_votes.documents, omitted in release-schema.json.',
        },
    },
    'arrowEncodingNuances': [
        'Top-level dict columns read back as string in Parquet footers, while recording_matches.meeting_links[] preserves dictionary<values=string, indices=int32, ordered=0> on basis and scope.',
        'List inner field names vary between item (archive-produced) and element (spicy-regs upstream); videos.stated_event_ids uses element: int64 not null.',
        'meetings.congress_gov_detail_observation nested timestamps use timestamp[us, tz=+00:00] rather than timestamp[us, tz=UTC] (both UTC).',
        'fixed[8] and fixed[32] map to ODCS logicalType="string", logicalTypeOptions={"format": "binary"}, physicalType="fixed[N]".',
    ],
}


def _strip_sha256_prefix(value: str) -> str:
    return value[7:] if value.startswith('sha256:') else value


def _load_upstream_pins(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    refspec = json.loads((root / 'model/jobs/refspec/refspec.json').read_text(encoding='utf-8'))
    view_manifest_rel = (refspec.get('view_manifest') or {}).get('path')
    view_manifest = {}
    if view_manifest_rel:
        view_manifest_path = (root / 'model/jobs/refspec' / view_manifest_rel).resolve()
        if view_manifest_path.is_file():
            view_manifest = json.loads(view_manifest_path.read_text(encoding='utf-8'))
    spicy_regs = json.loads((root / 'model/jobs/spicy-regs/spicy-regs.json').read_text(encoding='utf-8'))
    refspec_pin = {
        'releaseKey': refspec['release']['key'],
        'schemaVersion': refspec['schema_version'],
        'viewId': view_manifest.get('viewId'),
        'viewDigest': _strip_sha256_prefix((refspec.get('view_manifest') or {}).get('sha256', '')),
        'agencyProjectionDigest': _strip_sha256_prefix(refspec['release'].get('agencyProjectionDigest', '')),
        'frRosterReleaseDigest': _strip_sha256_prefix(refspec['release'].get('frRosterReleaseDigest', '')),
        'sourceReleaseDigest': _strip_sha256_prefix(refspec['release'].get('sourceReleaseDigest', '')),
        'decisionRecord': refspec['release'].get('decisionRecord'),
        'tables': {
            name: {
                'path': entry['path'],
                'sha256': _strip_sha256_prefix(entry['sha256']),
                'size': entry['size'],
                'rows': entry['rows'],
            }
            for name, entry in sorted(refspec.get('tables', {}).items())
        },
    }
    spicy_pin = {
        'version': spicy_regs['version'],
        'source': spicy_regs['source'],
        'generations': dict(sorted(spicy_regs.get('generations', {}).items())),
        'tables': {
            name: {
                'family': entry['family'],
                'path': entry['path'],
                'sha256': _strip_sha256_prefix(entry['sha256']),
                'size': entry['size'],
                'rows': entry['rows'],
            }
            for name, entry in sorted(spicy_regs.get('tables', {}).items())
        },
    }
    return refspec_pin, spicy_pin


def _urn_annotations(table_name: str, field_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    binding = TABLE_FIELD_URN_BINDINGS.get(table_name, {}).get(field_path)
    if binding is None:
        return [], []
    concept_urn, extra = binding
    meta = CANONICAL_CONCEPTS[concept_urn]
    custom_props: list[dict[str, Any]] = [
        {'vendor': 'ddk', 'property': 'concept', 'value': concept_urn},
        {'vendor': 'ddk', 'property': 'conceptKind', 'value': meta['conceptKind']},
    ]
    if 'relatedConcepts' in extra:
        custom_props.append({
            'vendor': 'congressional-tech',
            'property': 'relatedConcepts',
            'value': list(extra['relatedConcepts']),
        })
    if 'representationNote' in extra:
        custom_props.append({
            'vendor': 'congressional-tech',
            'property': 'representationNote',
            'value': extra['representationNote'],
        })
    auth_defs = [{'type': 'definition', 'url': concept_urn}]
    return custom_props, auth_defs


def _type_to_odcs(
    kind: str,
    *,
    table_name: str,
    field_path: str,
    notes: dict[str, str],
    synonyms: dict[str, list[list[str]]] | None = None,
) -> dict[str, Any]:
    """Convert an archive_schema type string into an ODCS v3.2.0 property/item dict."""
    kind = kind.strip()
    custom_props: list[dict[str, Any]] = []
    node: dict[str, Any]

    if kind in ('string', 'dict'):
        node = {'logicalType': 'string', 'physicalType': 'Utf8'}
        if kind == 'dict':
            custom_props.append({
                'vendor': 'congressional-tech',
                'property': 'archivePhysicalEncoding',
                'value': 'dictionary',
            })
    elif kind in ('bool', 'boolean'):
        node = {'logicalType': 'boolean', 'physicalType': 'Boolean'}
    elif kind == 'int16':
        node = {'logicalType': 'integer', 'logicalTypeOptions': {'format': 'i16'}, 'physicalType': 'Int16'}
    elif kind == 'int32':
        node = {'logicalType': 'integer', 'logicalTypeOptions': {'format': 'i32'}, 'physicalType': 'Int32'}
    elif kind == 'int64':
        node = {'logicalType': 'integer', 'logicalTypeOptions': {'format': 'i64'}, 'physicalType': 'Int64'}
    elif kind in ('float32', 'float'):
        node = {'logicalType': 'number', 'logicalTypeOptions': {'format': 'f32'}, 'physicalType': 'Float32'}
    elif kind in ('float64', 'double'):
        node = {'logicalType': 'number', 'logicalTypeOptions': {'format': 'f64'}, 'physicalType': 'Float64'}
    elif kind == 'date32':
        node = {'logicalType': 'date', 'logicalTypeOptions': {'format': 'yyyy-MM-dd'}, 'physicalType': 'Date32'}
    elif kind in ('timestamp', 'timestamp<microsecond,UTC>'):
        node = {
            'logicalType': 'timestamp',
            'logicalTypeOptions': {
                'format': "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXX",
                'timezone': True,
                'defaultTimezone': 'UTC',
            },
        }
    elif (match := _FIXED_TYPE_RE.fullmatch(kind)) is not None:
        node = {
            'logicalType': 'string',
            'logicalTypeOptions': {'format': 'binary'},
            'physicalType': f'fixed[{match.group(1)}]',
        }
    elif kind.startswith('list<') and kind.endswith('>'):
        item_path = f'{field_path}[]'
        item_node = _type_to_odcs(kind[5:-1], table_name=table_name, field_path=item_path, notes=notes)
        if item_path in notes and 'description' not in item_node:
            item_node['description'] = notes[item_path]
        node = {
            'logicalType': 'array',
            'items': item_node,
        }
    elif kind.startswith('struct<') and kind.endswith('>'):
        children = []
        for raw_field in _parts(kind[7:-1]):
            child_name, child_kind = raw_field.strip().split(' ', 1)
            child_path = f'{field_path}.{child_name}'
            child_node = _type_to_odcs(child_kind, table_name=table_name, field_path=child_path, notes=notes)
            child_prop: dict[str, Any] = {'name': child_name, **child_node}
            if child_path in notes:
                child_prop['description'] = notes[child_path]
            children.append(child_prop)
        node = {
            'logicalType': 'object',
            'properties': children,
        }
    else:
        raise ValueError(f'Unsupported archive schema type {kind!r} at {table_name}.{field_path}')

    if synonyms and f'{field_path}[]' in synonyms:
        custom_props.append({
            'vendor': 'congressional-tech',
            'property': 'archiveValueSynonyms',
            'value': synonyms[f'{field_path}[]'],
        })

    urn_props, urn_defs = _urn_annotations(table_name, field_path)
    custom_props.extend(urn_props)
    if custom_props:
        node['customProperties'] = [*custom_props, *node.get('customProperties', [])]
    if urn_defs:
        node['authoritativeDefinitions'] = [*urn_defs, *node.get('authoritativeDefinitions', [])]
    return node


def _odcs_relationships_for_table(table_name: str, relationships: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ODCS foreignKey relationships (when scalar shorthand applies) plus full archive metadata."""
    odcs_rels: list[dict[str, Any]] = []
    archive_rels: list[dict[str, Any]] = []
    for rel in relationships:
        if rel['source']['table'] != table_name:
            continue
        archive_rels.append(deepcopy(rel))
        target = rel['target']
        if 'table' not in target:
            continue
        src_fields = rel['source']['fields']
        dst_fields = target['fields']
        if any('[]' in f or '.' in f or f == 'list_row' for f in src_fields + dst_fields):
            continue
        src_refs = [f'{table_name}.{f}' for f in src_fields]
        dst_refs = [f"{target['table']}.{f}" for f in dst_fields]
        if not all(_SIMPLE_SHORTHAND_RE.fullmatch(ref) for ref in src_refs + dst_refs):
            continue
        entry: dict[str, Any] = {
            'id': rel['id'],
            'type': 'foreignKey',
            'from': src_refs[0] if len(src_refs) == 1 else src_refs,
            'to': dst_refs[0] if len(dst_refs) == 1 else dst_refs,
            'customProperties': [
                {'vendor': 'congressional-tech', 'property': 'cardinality', 'value': rel['cardinality']},
                {'vendor': 'congressional-tech', 'property': 'resolution', 'value': rel['resolution']},
                {'vendor': 'congressional-tech', 'property': 'nullable', 'value': rel['nullable']},
            ],
        }
        odcs_rels.append(entry)
    return odcs_rels, archive_rels


def _build_schema_object(
    table: dict[str, Any],
    relationships: list[dict[str, Any]],
    *,
    spicy_pin: dict[str, Any],
) -> dict[str, Any]:
    table_name = table['name'].removesuffix('.parquet')
    identity = table['identity']
    pk_positions = (
        {field: idx for idx, field in enumerate(identity['fields'], start=1)}
        if identity['kind'] == 'primary_key'
        else {}
    )
    notes = table.get('notes', {})
    synonyms = table.get('synonyms')

    properties: list[dict[str, Any]] = []
    for col in table['columns']:
        col_name = col['name']
        prop: dict[str, Any] = {
            'name': col_name,
            **_type_to_odcs(
                col['type'],
                table_name=table_name,
                field_path=col_name,
                notes=notes,
                synonyms=synonyms,
            ),
            'required': not col['nullable'],
            'description': col['meaning'],
        }
        if col_name in pk_positions:
            prop['primaryKey'] = True
            prop['primaryKeyPosition'] = pk_positions[col_name]
        if col_name in notes:
            prop_cp = list(prop.get('customProperties', []))
            prop_cp.append({'vendor': 'congressional-tech', 'property': 'fieldNote', 'value': notes[col_name]})
            prop['customProperties'] = prop_cp
        properties.append(prop)

    odcs_rels, archive_rels = _odcs_relationships_for_table(table_name, relationships)
    producer = 'spicy-regs' if table_name in SPICY_PRODUCER_TABLES else 'archive'
    custom_props: list[dict[str, Any]] = [
        {'vendor': 'congressional-tech', 'property': 'producer', 'value': producer},
        {'vendor': 'congressional-tech', 'property': 'identity', 'value': deepcopy(identity)},
        {'vendor': 'congressional-tech', 'property': 'nullabilityBasis', 'value': table['nullability']},
    ]
    if table.get('gaps'):
        custom_props.append({'vendor': 'congressional-tech', 'property': 'gaps', 'value': list(table['gaps'])})
    if table.get('virtual_columns'):
        custom_props.append({
            'vendor': 'congressional-tech',
            'property': 'virtualColumns',
            'value': deepcopy(table['virtual_columns']),
        })
    if table_name in SPICY_PRODUCER_TABLES:
        families = SPICY_PRODUCER_TABLES[table_name]
        custom_props.append({
            'vendor': 'spicy-regs',
            'property': 'sourceGenerations',
            'value': {f: spicy_pin['generations'][f] for f in families if f in spicy_pin['generations']},
        })
    if archive_rels:
        custom_props.append({
            'vendor': 'congressional-tech',
            'property': 'archiveRelationships',
            'value': archive_rels,
        })

    obj: dict[str, Any] = {
        'id': table_name,
        'name': table_name,
        'logicalType': 'object',
        'physicalType': 'table',
        'physicalName': table['name'],
        'businessName': table['purpose'],
        'dataGranularityDescription': table['row_meaning'],
        'description': table.get('description') or table['purpose'],
        'properties': properties,
        'customProperties': custom_props,
    }
    if odcs_rels:
        obj['relationships'] = odcs_rels
    return obj


def _collect_urn_bindings(
    schema_obj: dict[str, Any],
    *,
    table_name: str,
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []

    def walk_array_items(items: dict[str, Any], item_path: str) -> None:
        _record(items, item_path)
        if items.get('logicalType') == 'object' and items.get('properties'):
            walk(items['properties'], item_path)
        elif items.get('logicalType') == 'array' and isinstance(items.get('items'), dict):
            walk_array_items(items['items'], f'{item_path}[]')

    def walk(props: list[dict[str, Any]], prefix: str) -> None:
        for prop in props:
            path = f"{prefix}.{prop['name']}" if prefix else prop['name']
            _record(prop, path)
            if prop.get('logicalType') == 'object' and prop.get('properties'):
                walk(prop['properties'], path)
            elif prop.get('logicalType') == 'array' and isinstance(prop.get('items'), dict):
                walk_array_items(prop['items'], f'{path}[]')

    def _record(node: dict[str, Any], path: str) -> None:
        concept = None
        concept_kind = None
        extra: dict[str, Any] = {}
        for cp in node.get('customProperties', ()):
            if cp.get('vendor') == 'ddk' and cp.get('property') == 'concept':
                concept = cp['value']
            elif cp.get('vendor') == 'ddk' and cp.get('property') == 'conceptKind':
                concept_kind = cp['value']
            elif cp.get('vendor') == 'congressional-tech' and cp.get('property') in {'relatedConcepts', 'representationNote'}:
                extra[cp['property']] = cp['value']
        if concept:
            bindings.append({
                'table': table_name,
                'path': path,
                'concept': concept,
                'conceptKind': concept_kind,
                'logicalType': node.get('logicalType'),
                'physicalType': node.get('physicalType'),
                'required': bool(node.get('required', False)),
                'primaryKey': bool(node.get('primaryKey', False)),
                **extra,
            })

    walk(schema_obj['properties'], '')
    return bindings


def export_odcs_contracts(
    *,
    registry: dict[str, Any] | None = None,
    root: Path = ROOT,
    include_capture_eligibility: bool = False,
) -> dict[str, Any]:
    """Build deterministic ODCS v3.2.0 contracts and RefSpec URN bindings from archive_schema."""
    schema = build_schema(registry=registry)
    if include_capture_eligibility:
        extra_fields = json.loads((root / 'model/registries/capture-eligibility-fields.json').read_text(encoding='utf-8'))
        url_state = next(item for item in schema['files'] if item['name'] == 'url_state.parquet')
        existing = {col['name'] for col in url_state['columns']}
        url_state['columns'].extend(field for field in extra_fields if field['name'] not in existing)

    refspec_pin, spicy_pin = _load_upstream_pins(root)
    schema_objects = [
        _build_schema_object(table, schema['relationships'], spicy_pin=spicy_pin)
        for table in schema['files']
    ]

    bundle_custom_props: list[dict[str, Any]] = [
        {'vendor': 'congressional-tech', 'property': 'schemaVersion', 'value': schema['schema_version']},
        {'vendor': 'congressional-tech', 'property': 'relationshipsVersion', 'value': schema['relationships_version']},
        {'vendor': 'refspec', 'property': 'agencyRegistryPin', 'value': refspec_pin},
        {'vendor': 'spicy-regs', 'property': 'generationPins', 'value': spicy_pin['generations']},
        {'vendor': 'spicy-regs', 'property': 'sourceOrigin', 'value': spicy_pin['source']},
    ]
    bundle_auth_defs: list[dict[str, Any]] = [
        {
            'type': 'definition',
            'url': 'urn:spicycongress:datamap:linked',
            'description': 'SpicyCongress L3 linked datamap contract',
        },
    ]
    if refspec_pin.get('viewId'):
        bundle_auth_defs.append({
            'type': 'canonicalUrl',
            'url': refspec_pin['viewId'],
            'description': f"Pinned RefSpec agency registry view ({refspec_pin['releaseKey']})",
        })

    bundle_contract: dict[str, Any] = {
        'apiVersion': ODCS_API_VERSION,
        'kind': 'DataContract',
        'id': 'urn:congressional-tech:archive:release',
        'version': CONTRACT_VERSION,
        'name': 'Congressional Tech Published Archive Release',
        'status': 'active',
        'domain': 'congressional-archive',
        'description': {
            'purpose': 'Canonical ODCS v3.2.0 DataContract for all published Congressional Tech archive Parquet tables.',
            'usage': 'Derived directly from viewer_publication.archive_schema and model/registries/release-schema.json.',
            'limitations': (
                'Logical required flags reflect write-time publication_checks invariants; physical Parquet '
                'Arrow schemas mark most DataFusion SQL projected columns nullable=True.'
            ),
        },
        'authoritativeDefinitions': bundle_auth_defs,
        'customProperties': bundle_custom_props,
        'schema': schema_objects,
    }

    table_contracts: dict[str, dict[str, Any]] = {}
    all_bindings: list[dict[str, Any]] = []
    for obj in schema_objects:
        tname = obj['name']
        all_bindings.extend(_collect_urn_bindings(obj, table_name=tname))
        table_custom_props = [
            {'vendor': 'congressional-tech', 'property': 'schemaVersion', 'value': schema['schema_version']},
            {'vendor': 'congressional-tech', 'property': 'relationshipsVersion', 'value': schema['relationships_version']},
        ]
        if tname in {'organizations', 'organization_ids', 'witness_organizations', 'organization_redirects'}:
            table_custom_props.append({'vendor': 'refspec', 'property': 'agencyRegistryPin', 'value': refspec_pin})
        if tname in SPICY_PRODUCER_TABLES:
            table_custom_props.append({
                'vendor': 'spicy-regs',
                'property': 'sourceGenerations',
                'value': {
                    f: spicy_pin['generations'][f]
                    for f in SPICY_PRODUCER_TABLES[tname]
                    if f in spicy_pin['generations']
                },
            })
        table_contracts[tname] = {
            'apiVersion': ODCS_API_VERSION,
            'kind': 'DataContract',
            'id': f'urn:congressional-tech:archive:table:{tname}',
            'version': CONTRACT_VERSION,
            'name': f"Congressional Tech Archive Table: {tname}",
            'status': 'active',
            'domain': 'congressional-archive',
            'description': {
                'purpose': obj['businessName'],
                'usage': obj['description'],
            },
            'authoritativeDefinitions': [
                {'type': 'definition', 'url': 'urn:congressional-tech:archive:release'},
            ],
            'customProperties': table_custom_props,
            'schema': [deepcopy(obj)],
        }

    concepts_summary: dict[str, dict[str, Any]] = {}
    for b in all_bindings:
        urn = b['concept']
        entry = concepts_summary.setdefault(
            urn,
            {
                **CANONICAL_CONCEPTS[urn],
                'bindings': [],
            },
        )
        entry['bindings'].append({
            'table': b['table'],
            'path': b['path'],
            'logicalType': b['logicalType'],
            'physicalType': b['physicalType'],
            'required': b['required'],
            'primaryKey': b['primaryKey'],
            **({k: b[k] for k in ('relatedConcepts', 'representationNote') if k in b}),
        })

    urn_bindings = {
        'version': 1,
        'apiVersion': ODCS_API_VERSION,
        'sourceRegistry': 'model/registries/release-schema.json',
        'refspec': refspec_pin,
        'spicyRegs': spicy_pin,
        'concepts': dict(sorted(concepts_summary.items())),
        'parquetParityNotes': deepcopy(LIVE_PARQUET_PARITY_NOTES),
    }

    return {
        'bundle_contract': bundle_contract,
        'table_contracts': table_contracts,
        'urn_bindings': urn_bindings,
    }


def _collect_property_paths(props: list[dict[str, Any]], prefix: str = '') -> set[str]:
    paths: set[str] = set()
    for prop in props:
        name = prop.get('name')
        if not isinstance(name, str) or not name:
            continue
        path = f'{prefix}.{name}' if prefix else name
        paths.add(path)
        if prop.get('logicalType') == 'object' and isinstance(prop.get('properties'), list):
            paths.update(_collect_property_paths(prop['properties'], path))
    return paths


def validate_odcs_contract(contract: dict[str, Any], *, expected_tables: set[str] | None = None) -> list[str]:
    """Validate structural ODCS v3.2.0 conformance and cross-table binding invariants offline."""
    errors: list[str] = []
    if contract.get('apiVersion') != ODCS_API_VERSION:
        errors.append(f"Expected apiVersion {ODCS_API_VERSION!r}, got {contract.get('apiVersion')!r}")
    if contract.get('kind') != 'DataContract':
        errors.append(f"Expected kind 'DataContract', got {contract.get('kind')!r}")
    for key in ('id', 'version', 'schema'):
        if not contract.get(key):
            errors.append(f'Missing required DataContract field {key!r}')
    allowed_top = {
        'version', 'kind', 'apiVersion', 'id', 'name', 'tenant', 'tags', 'status',
        'servers', 'description', 'domain', 'context', 'schema', 'support', 'price',
        'team', 'roles', 'slaProperties', 'authoritativeDefinitions', 'customProperties',
        'contractCreatedTs',
    }
    if extra_top := sorted(set(contract) - allowed_top):
        errors.append(f'Unexpected top-level ODCS keys: {extra_top}')

    seen_tables: set[str] = set()
    schema_paths: dict[str, set[str]] = {}
    allowed_logical = {'string', 'date', 'timestamp', 'time', 'number', 'integer', 'object', 'array', 'boolean', 'map', 'vector'}
    for obj in contract.get('schema', []):
        name = obj.get('name')
        if not isinstance(name, str) or not name:
            errors.append('SchemaObject missing name')
            continue
        if name in seen_tables:
            errors.append(f'Duplicate SchemaObject {name!r}')
        seen_tables.add(name)
        if obj.get('logicalType') != 'object':
            errors.append(f'SchemaObject {name!r} logicalType must be object')
        props = obj.get('properties')
        if not isinstance(props, list) or not props:
            errors.append(f'SchemaObject {name!r} must have non-empty properties')
            continue
        _validate_properties(props, f'{name}', allowed_logical, errors, require_names=True)
        schema_paths[name] = _collect_property_paths(props)

    for obj in contract.get('schema', []):
        name = obj.get('name')
        if not isinstance(name, str) or not name:
            continue
        for rel in obj.get('relationships', []):
            for endpoint_key in ('from', 'to'):
                val = rel.get(endpoint_key)
                refs = [val] if isinstance(val, str) else list(val or ())
                for ref in refs:
                    if not isinstance(ref, str) or not _SIMPLE_SHORTHAND_RE.fullmatch(ref):
                        errors.append(f'Invalid relationship shorthand reference {ref!r} on {name}')
                        continue
                    ref_table, ref_col = ref.split('.', 1)
                    if endpoint_key == 'from' and ref_table != name:
                        errors.append(
                            f'Relationship from reference {ref!r} on {name} must start with {name!r}'
                        )
                    elif ref_table in schema_paths:
                        if ref_col not in schema_paths[ref_table]:
                            errors.append(
                                f'Relationship {endpoint_key} reference {ref!r} on {name} does not match a declared property on {ref_table}'
                            )
                    elif len(schema_paths) > 1 or endpoint_key == 'from':
                        errors.append(
                            f'Relationship {endpoint_key} reference {ref!r} on {name} targets undeclared table {ref_table!r}'
                        )

    if expected_tables is not None:
        missing = sorted(expected_tables - seen_tables)
        extra = sorted(seen_tables - expected_tables)
        if missing:
            errors.append(f'Missing tables in contract: {missing}')
        if extra:
            errors.append(f'Unexpected tables in contract: {extra}')
    return errors


def _validate_properties(
    props: list[dict[str, Any]],
    prefix: str,
    allowed_logical: set[str],
    errors: list[str],
    *,
    require_names: bool,
) -> None:
    seen_names: set[str] = set()
    for prop in props:
        if require_names:
            pname = prop.get('name')
            if not isinstance(pname, str) or not pname:
                errors.append(f'{prefix}: property missing name')
                continue
            if pname in seen_names:
                errors.append(f'{prefix}: duplicate property {pname!r}')
            seen_names.add(pname)
            path = f'{prefix}.{pname}'
        else:
            path = prefix
        lt = prop.get('logicalType')
        if lt not in allowed_logical:
            errors.append(f'{path}: invalid logicalType {lt!r}')
        if prop.get('primaryKey') and not prop.get('required'):
            errors.append(f'{path}: primaryKey must have required=True')
        for cp in prop.get('customProperties', []):
            if not isinstance(cp, dict) or 'property' not in cp or 'value' not in cp:
                errors.append(f'{path}: invalid customProperty {cp!r}')
        for ad in prop.get('authoritativeDefinitions', []):
            if not isinstance(ad, dict) or not ad.get('type') or not ad.get('url'):
                errors.append(f'{path}: invalid authoritativeDefinition {ad!r}')
        if lt == 'object':
            children = prop.get('properties')
            if not isinstance(children, list) or not children:
                errors.append(f'{path}: object must declare non-empty properties')
            else:
                _validate_properties(children, path, allowed_logical, errors, require_names=True)
        elif lt == 'array':
            items = prop.get('items')
            if not isinstance(items, dict):
                errors.append(f'{path}: array missing items')
            else:
                if 'name' in items:
                    errors.append(f'{path}[]: array items must not set name')
                _validate_properties([items], f'{path}[]', allowed_logical, errors, require_names=False)


def odcs_property_to_pyarrow(prop: dict[str, Any], pa: Any) -> Any:
    """Convert an exported ODCS v3.2.0 property/item dict to an exact PyArrow DataType."""
    logical = prop.get('logicalType')
    physical = (prop.get('physicalType') or '').strip()
    opts = prop.get('logicalTypeOptions') or {}

    if logical == 'string':
        if opts.get('format') == 'binary':
            if (match := _FIXED_TYPE_RE.fullmatch(physical)) is not None:
                return pa.binary(int(match.group(1)))
            return pa.binary()
        return pa.string()
    if logical == 'boolean':
        return pa.bool_()
    if logical == 'date':
        return pa.date32()
    if logical == 'timestamp':
        tz_opt = opts.get('timezone')
        if tz_opt is False:
            return pa.timestamp('us', tz=None)
        return pa.timestamp('us', tz=opts.get('defaultTimezone') or 'UTC')
    if logical == 'integer':
        fmt = str(opts.get('format') or '').lower()
        return {
            'i8': pa.int8(),
            'i16': pa.int16(),
            'i32': pa.int32(),
            'i64': pa.int64(),
            'u8': pa.uint8(),
            'u16': pa.uint16(),
            'u32': pa.uint32(),
            'u64': pa.uint64(),
        }.get(fmt, pa.int64())
    if logical == 'number':
        fmt = str(opts.get('format') or '').lower()
        return pa.float32() if fmt == 'f32' else pa.float64()
    if logical == 'object':
        return pa.struct([
            pa.field(child['name'], odcs_property_to_pyarrow(child, pa), nullable=not bool(child.get('required', False)))
            for child in prop['properties']
        ])
    if logical == 'array':
        items = prop['items']
        elem_type = odcs_property_to_pyarrow(items, pa)
        return pa.list_(pa.field('item', elem_type, nullable=not bool(items.get('required', False))))
    raise ValueError(f"Unsupported ODCS logicalType {logical!r} on {prop.get('name', '<item>')!r}")


def odcs_object_to_arrow_schema(schema_obj: dict[str, Any], pa: Any | None = None) -> Any:
    """Convert an ODCS SchemaObject into a PyArrow Schema."""
    if pa is None:
        import pyarrow as pa
    return pa.schema([
        pa.field(prop['name'], odcs_property_to_pyarrow(prop, pa), nullable=not bool(prop.get('required', False)))
        for prop in schema_obj['properties']
    ])


def _normalize_arrow_type(dtype: Any, pa: Any) -> Any:
    """Normalize Arrow encoding nuances (list item/element name, dictionary<string>, tz=+00:00 vs UTC)."""
    if pa.types.is_dictionary(dtype):
        return _normalize_arrow_type(dtype.value_type, pa)
    if pa.types.is_timestamp(dtype) and dtype.tz == '+00:00':
        return pa.timestamp(dtype.unit, tz='UTC')
    if pa.types.is_list(dtype):
        return pa.list_(pa.field('item', _normalize_arrow_type(dtype.value_type, pa), nullable=True))
    if pa.types.is_struct(dtype):
        return pa.struct([
            pa.field(dtype.field(i).name, _normalize_arrow_type(dtype.field(i).type, pa), nullable=True)
            for i in range(dtype.num_fields)
        ])
    return dtype


def compare_parquet_schema_parity(
    expected_schema_obj: dict[str, Any],
    actual_schema: Any,
    *,
    check_order: bool = True,
    check_nullability: bool = False,
    normalize_arrow_encodings: bool = False,
) -> list[str]:
    """Compare an ODCS SchemaObject against an actual PyArrow Schema or Parquet path."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    exp_schema = odcs_object_to_arrow_schema(expected_schema_obj, pa)
    act_schema = pq.read_schema(actual_schema) if isinstance(actual_schema, (str, Path)) else actual_schema
    expected_fields = {f.name: f for f in exp_schema}
    actual_fields = {f.name: f for f in act_schema}
    issues: list[str] = []

    if missing := [f.name for f in exp_schema if f.name not in actual_fields]:
        issues.append(f'missing columns {missing}')
    if extra := [f.name for f in act_schema if f.name not in expected_fields]:
        issues.append(f'unexpected columns {extra}')
    mismatched = []
    for f in act_schema:
        if f.name not in expected_fields:
            continue
        exp_t = expected_fields[f.name].type
        act_t = f.type
        if normalize_arrow_encodings:
            exp_t = _normalize_arrow_type(exp_t, pa)
            act_t = _normalize_arrow_type(act_t, pa)
        if act_t != exp_t:
            mismatched.append(f'{f.name} (expected {exp_t}, got {act_t})')
    if mismatched:
        issues.append(f'type mismatch on {mismatched}')
    if check_nullability:
        if null_diffs := [
            f'{f.name} (expected nullable={expected_fields[f.name].nullable}, got {f.nullable})'
            for f in act_schema
            if f.name in expected_fields and f.nullable != expected_fields[f.name].nullable
        ]:
            issues.append(f'nullability mismatch on {null_diffs}')
    if not issues and check_order and list(act_schema.names) != list(exp_schema.names):
        issues.append(f'column order differs (expected {list(exp_schema.names)}, got {list(act_schema.names)})')
    return issues


def _render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def expected_contract_files(*, root: Path = ROOT) -> dict[Path, str]:
    """Return mapping of relative output paths under model/contracts to deterministic JSON strings."""
    exported = export_odcs_contracts(root=root)
    files: dict[Path, str] = {
        Path('archive-release.odcs.json'): _render_json(exported['bundle_contract']),
        Path('refspec-urn-bindings.json'): _render_json(exported['urn_bindings']),
    }
    for name, contract in sorted(exported['table_contracts'].items()):
        files[Path('tables') / f'{name}.odcs.json'] = _render_json(contract)
    return files


def write_contracts(output_dir: Path = CONTRACTS_DIR, *, root: Path = ROOT) -> list[Path]:
    """Write deterministic ODCS contracts and URN bindings to disk."""
    expected = expected_contract_files(root=root)
    tables_dir = output_dir / 'tables'
    tables_dir.mkdir(parents=True, exist_ok=True)
    expected_table_files = {p.name for p in expected if p.parent == Path('tables')}
    for existing in tables_dir.glob('*.odcs.json'):
        if existing.name not in expected_table_files:
            existing.unlink()
    written: list[Path] = []
    for rel, content in sorted(expected.items()):
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        written.append(target)
    return written


def check_drift(output_dir: Path = CONTRACTS_DIR, *, root: Path = ROOT) -> list[str]:
    """Detect missing, stale, unexpected, or invalid contract/URN artifacts."""
    errors: list[str] = []
    expected = expected_contract_files(root=root)
    schema = build_schema()
    expected_tables = {f['name'].removesuffix('.parquet') for f in schema['files']}
    exported = export_odcs_contracts(root=root)

    errors.extend(f'bundle_contract: {e}' for e in validate_odcs_contract(exported['bundle_contract'], expected_tables=expected_tables))
    for name, contract in sorted(exported['table_contracts'].items()):
        errors.extend(f'table_contract[{name}]: {e}' for e in validate_odcs_contract(contract, expected_tables={name}))

    for rel, expected_text in sorted(expected.items()):
        target = output_dir / rel
        if not target.is_file():
            errors.append(f'Missing contract artifact: {target}')
        elif target.read_text(encoding='utf-8') != expected_text:
            errors.append(f'Contract drift detected in {target}; regenerate with python -m viewer_publication.archive_odcs')

    tables_dir = output_dir / 'tables'
    if tables_dir.is_dir():
        expected_names = {p.name for p in expected if p.parent == Path('tables')}
        for existing in sorted(tables_dir.glob('*.odcs.json')):
            if existing.name not in expected_names:
                errors.append(f'Unexpected stale table contract: {existing}')
    return errors


def _is_disallowed_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def _validate_release_url(release_id_or_url: str) -> str:
    """Validate and normalize a release SHA-256 ID or public HTTPS release URL."""
    raw = release_id_or_url.strip()
    if _HEX64_RE.fullmatch(raw):
        return f'https://congressional-data.spicygov.ai/viewer-publications/releases/{raw}'
    if '?' in raw or '#' in raw:
        raise ValueError(f'Release URL must not include query or fragment: {release_id_or_url!r}')
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme != 'https':
        raise ValueError(f'Release target must be a 64-char hex ID or https:// URL: {release_id_or_url!r}')
    if parsed.username is not None or parsed.password is not None or '@' in parsed.netloc:
        raise ValueError(f'Release URL must not contain credentials: {release_id_or_url!r}')
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f'Release URL missing valid hostname: {release_id_or_url!r}')
    if parsed.query or parsed.fragment:
        raise ValueError(f'Release URL must not include query or fragment: {release_id_or_url!r}')

    host_clean = hostname.strip('[]')
    try:
        ip_literal = ipaddress.ip_address(host_clean)
    except ValueError:
        ip_literal = None
    if ip_literal is not None:
        if _is_disallowed_ip(ip_literal):
            raise ValueError(f'Release URL resolves to disallowed IP {ip_literal}: {release_id_or_url!r}')
    else:
        port = parsed.port or 443
        addr_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        if not addr_infos:
            raise ValueError(f'Release URL host did not resolve: {hostname!r}')
        for info in addr_infos:
            ip_str = info[4][0].split('%', 1)[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if _is_disallowed_ip(ip_obj):
                raise ValueError(f'Release URL host {hostname!r} resolved to disallowed IP {ip_obj}')

    return raw.rstrip('/')


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise urllib.error.HTTPError(req.full_url, code, f'HTTP redirect refused ({code} -> {newurl})', headers, fp)


def verify_live_release_parity(release_id_or_url: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Read Parquet footers via HTTP Range from a published release and compare against exported ODCS contracts."""
    import pyarrow.parquet as pq

    base_url = _validate_release_url(release_id_or_url)
    opener = urllib.request.build_opener(_NoRedirectHandler())

    def _get(url: str, byte_range: str | None = None) -> bytes:
        headers = {'User-Agent': LIVE_VERIFY_USER_AGENT}
        if byte_range is not None:
            headers['Range'] = byte_range
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=30) as resp:
            status = getattr(resp, 'status', None)
            if byte_range is not None and status != 206:
                raise ValueError(f'Expected HTTP 206 for Range request on {url}, got {status!r}')
            if byte_range is None and status not in (None, 200):
                raise ValueError(f'Expected HTTP 200 for {url}, got {status!r}')
            return resp.read()

    class _HttpRangeFile(io.RawIOBase):
        def __init__(self, url: str, size: int):
            self.url = url
            self.size = size
            self.pos = 0
            self.tail_start = max(0, size - 524288)
            self.tail = _get(url, f'bytes={self.tail_start}-{size - 1}') if size > 0 else b''

        def readable(self) -> bool:
            return True

        def seekable(self) -> bool:
            return True

        def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
            if whence == io.SEEK_SET:
                target = offset
            elif whence == io.SEEK_CUR:
                target = self.pos + offset
            elif whence == io.SEEK_END:
                target = self.size + offset
            else:
                raise ValueError(f'Unsupported whence {whence!r}')
            if target < 0:
                raise ValueError(f'Negative seek position {target}')
            self.pos = target
            return self.pos

        def tell(self) -> int:
            return self.pos

        def read(self, n: int = -1) -> bytes:
            if n == 0 or self.pos >= self.size:
                return b''
            if n < 0:
                n = self.size - self.pos
            end = min(self.size, self.pos + n)
            if end <= self.pos:
                return b''
            if self.pos >= self.tail_start:
                chunk = self.tail[self.pos - self.tail_start : end - self.tail_start]
            else:
                chunk = _get(self.url, f'bytes={self.pos}-{end - 1}')
            self.pos = end
            return chunk

    manifest = json.loads(_get(f'{base_url}/manifest.json').decode('utf-8'))
    files = manifest.get('files')
    if not isinstance(files, list):
        raise ValueError('Remote manifest.json missing files list')
    has_v2_profile = any(isinstance(f, dict) and f.get('name') == 'capture_profile.json' for f in files)
    if has_v2_profile:
        cap_profile = json.loads(_get(f'{base_url}/capture_profile.json').decode('utf-8'))
        include_cap = cap_profile.get('version') == 2
    else:
        include_cap = False

    exported = export_odcs_contracts(root=root, include_capture_eligibility=include_cap)
    by_name = {obj['name']: obj for obj in exported['bundle_contract']['schema']}
    results: dict[str, Any] = {
        'release_url': base_url,
        'capture_profile_v2': include_cap,
        'unexpectedTables': [],
        'tables': {},
    }

    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid manifest file entry: {entry!r}')
        fname = entry.get('name')
        if not isinstance(fname, str):
            raise ValueError(f'Manifest entry missing string name: {entry!r}')
        if not fname.endswith('.parquet'):
            continue
        if not _SAFE_PARQUET_FILENAME_RE.fullmatch(fname):
            raise ValueError(f'Unsafe manifest parquet filename: {fname!r}')
        size = entry.get('size')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f'Invalid manifest parquet size for {fname!r}: {size!r}')
        tname = fname.removesuffix('.parquet')
        if tname not in by_name:
            results['unexpectedTables'].append(tname)
            continue
        actual = pq.read_schema(_HttpRangeFile(f'{base_url}/{fname}', size))
        obj = by_name[tname]
        strict_issues = compare_parquet_schema_parity(obj, actual, check_order=True, check_nullability=False, normalize_arrow_encodings=False)
        norm_issues = compare_parquet_schema_parity(obj, actual, check_order=False, check_nullability=False, normalize_arrow_encodings=True)
        null_diffs = [
            f'{f.name} (declared nullable={not prop["required"]}, parquet nullable={f.nullable})'
            for prop in obj['properties']
            for f in [actual.field(prop['name']) if prop['name'] in actual.names else None]
            if f is not None and f.nullable != (not prop['required'])
        ]
        results['tables'][tname] = {
            'strictIssues': strict_issues,
            'normalizedUnorderedIssues': norm_issues,
            'nullabilityDiffsCount': len(null_diffs),
            'nullabilityDiffs': null_diffs,
        }
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if committed ODCS contracts or URN bindings drift.')
    parser.add_argument('--output-dir', type=Path, default=CONTRACTS_DIR, help='Output directory for ODCS contracts.')
    parser.add_argument('--verify-live', help='Verify Parquet footer parity against a live release ID or HTTPS URL.')
    args = parser.parse_args(argv)

    if args.verify_live:
        report = verify_live_release_parity(args.verify_live)
        print(json.dumps(report, indent=2))
        has_issues = bool(report.get('unexpectedTables')) or any(
            t.get('normalizedUnorderedIssues') for t in report.get('tables', {}).values()
        )
        return 1 if has_issues else 0
    if args.check:
        errors = check_drift(args.output_dir)
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            return 1
        return 0
    written = write_contracts(args.output_dir)
    print(f'Wrote {len(written)} ODCS contract and URN binding files to {args.output_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
