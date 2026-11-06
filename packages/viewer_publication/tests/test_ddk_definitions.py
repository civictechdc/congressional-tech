"""Frozen source semantics and direct admission through maintained DDK APIs.

Captured from git a06eb64bf3caa4a44e12a89bdd08939323de3092 before the migration.
These are inert regression facts, not a second production definition owner.
"""
import json
import re
from hashlib import sha256
from pathlib import Path
import shutil

import pytest

NAMESPACE = "urn:congressional-tech:archive:"
ASSEMBLY = "urn:ddk:catalog:assembly"
CURRENT_CAPTURE_FIELDS = [
    {'name': 'capture_disposition', 'type': 'string', 'nullable': False, 'meaning': 'Eligibility under the pinned recovery and capture scope policy'},
    {'name': 'capture_reason', 'type': 'string', 'nullable': False, 'meaning': 'Reason for the capture eligibility decision'},
    {'name': 'capture_decision_id', 'type': 'string', 'nullable': True, 'meaning': 'Qualified recovery decision supporting satisfaction, when present'},
]

BASELINE = json.loads(r'''
{
  "source_commit": "a06eb64bf3caa4a44e12a89bdd08939323de3092",
  "registry_sha256": "4afb316675b38fc163e34a43d2ebb3c85ea22bdd933ec94318d1c08ea7db1ba2",
  "registry_bytes": 134651,
  "reference_sha256": "0c30daff52744691af3d47a478c651ecba509e9923ba092cf788669c08bea9a5",
  "semantic_sha256": "e20aaae7ce7efdf856b3d349079680a0c9884781f68165d7a30fb9d845676a36",
  "table_columns": {
    "list.parquet": [
      "filename",
      "title",
      "document_kind",
      "document_family",
      "committee_keys",
      "chambers",
      "congress",
      "format",
      "document_date",
      "first_captured",
      "date_kind",
      "saved_kind",
      "hidden",
      "meeting_keys",
      "measure_keys",
      "bioguide_ids",
      "witness_keys",
      "version_keys"
    ],
    "detail.parquet": [
      "link_key",
      "saved_body",
      "saved_suffix",
      "saved_media_type",
      "saved_bytes",
      "document_date_source",
      "document_date_status",
      "in_archive_since",
      "removed_on",
      "review_note",
      "review_decided_at",
      "src_start",
      "src_len",
      "rec_start",
      "rec_len",
      "alternates",
      "package_id",
      "facts",
      "description",
      "published_on",
      "modified_on",
      "publisher_labels",
      "page_metadata",
      "main_content",
      "selected_text",
      "filename",
      "title",
      "document_kind",
      "document_family",
      "committee_keys",
      "chambers",
      "congress",
      "format",
      "document_date",
      "first_captured",
      "date_kind",
      "saved_kind",
      "hidden",
      "meeting_keys",
      "measure_keys",
      "bioguide_ids",
      "witness_keys",
      "version_keys"
    ],
    "links.parquet": [
      "link_key",
      "list_row"
    ],
    "retired_links.parquet": [
      "link_key",
      "successor_key",
      "last_release_id",
      "last_filename",
      "address_versions"
    ],
    "urls.parquet": [
      "lookup_key",
      "list_row"
    ],
    "sources.parquet": [
      "list_row",
      "ordinal",
      "url",
      "member_path",
      "is_saved",
      "first_seen",
      "listed_on",
      "link_text",
      "doc_type",
      "posted"
    ],
    "recoveries.parquet": [
      "list_row",
      "ordinal",
      "kind",
      "body",
      "suffix",
      "bytes",
      "imported_at",
      "recovered_url",
      "identity_note"
    ],
    "meetings.parquet": [
      "event_id",
      "chamber",
      "chamber_basis",
      "title",
      "meeting_date",
      "meeting_type",
      "session",
      "status",
      "sittings",
      "committees",
      "subject_keys",
      "transcripts",
      "videos",
      "congress",
      "congress_gov_updated",
      "house_xml_updated",
      "congress_gov_meeting_type",
      "access",
      "access_basis",
      "not_held",
      "rescheduled_to",
      "rescheduled_basis",
      "document_references"
    ],
    "witnesses.parquet": [
      "witness_key",
      "occasion",
      "source",
      "record_sha",
      "source_locator",
      "context_key",
      "event_id",
      "package_id",
      "page_url",
      "name",
      "position",
      "organization",
      "on_behalf_of",
      "location",
      "panel",
      "panel_order",
      "display_order",
      "witness_type",
      "testified",
      "bioguide_id",
      "superseded_by"
    ],
    "witness_key_map.parquet": [
      "old_key",
      "witness_key",
      "status",
      "basis",
      "candidate_keys",
      "occasion",
      "source"
    ],
    "recordings.parquet": [
      "video_key",
      "event_ids",
      "tracks"
    ],
    "committees.parquet": [
      "system_code",
      "name",
      "chamber",
      "committee_type",
      "parent_system_code",
      "names",
      "website",
      "is_current"
    ],
    "members.parquet": [
      "bioguide_id",
      "name",
      "terms",
      "cross_ids"
    ],
    "rosters.parquet": [
      "congress",
      "system_code",
      "bioguide_id",
      "title",
      "rank",
      "party"
    ],
    "bills.parquet": [
      "bill_id",
      "title",
      "short_title",
      "sponsor_bioguide_id",
      "introduced",
      "latest_action_date",
      "latest_action_text",
      "stage",
      "policy_area",
      "public_law_number",
      "cosponsor_count",
      "related_bills",
      "committees",
      "cbo_estimates",
      "floor_votes",
      "amendments",
      "committee_activities"
    ],
    "nominations.parquet": [
      "nomination_id",
      "description",
      "organization",
      "received",
      "latest_action_date",
      "latest_action_text",
      "committees",
      "committee_activities",
      "transcripts",
      "floor_votes"
    ],
    "url_state.parquet": [
      "requested_url",
      "attempts",
      "last_attempt",
      "last_status",
      "last_outcome",
      "last_good_at",
      "next_attempt_at"
    ],
    "url_variants.parquet": [
      "canonical_url",
      "variant_url"
    ],
    "videos.parquet": [
      "video_key",
      "handle",
      "channel_id",
      "system_code",
      "title",
      "source_description",
      "published_at",
      "video_published_at",
      "duration_seconds",
      "available",
      "has_caption",
      "details_checked_at",
      "stated_event_ids",
      "record_sha"
    ],
    "channels.parquet": [
      "handle",
      "channel_id",
      "system_code",
      "committee_label",
      "role",
      "title",
      "custom_url",
      "uploads_scan_complete",
      "mapping_basis",
      "record_sha"
    ],
    "recording_matches.parquet": [
      "match_id",
      "subject_kind",
      "subject_id",
      "event_id",
      "package_id",
      "video_key",
      "url",
      "basis",
      "decision",
      "score",
      "recording_scope",
      "status",
      "note",
      "source_ref",
      "meeting_links"
    ],
    "committee_records.parquet": [
      "record_key",
      "event_id",
      "kind",
      "bill",
      "number",
      "sponsor_bioguide",
      "amendment_type",
      "enbloc",
      "source_description",
      "url",
      "record_sha",
      "ordinal"
    ],
    "meeting_coverage.parquet": [
      "event_id",
      "aspect",
      "state",
      "basis",
      "count",
      "reason"
    ]
  },
  "recipe_sha256": {
    "bill_documents": "9eb14405082b19acbd051fc3c7dee8c430c2b091ab6ec503d705c423b549ddc6",
    "bill_hearing_transcripts": "e8819e1a745f5ff61553b0d79bd0a80a5868d2c687db0b5121983b67b64187fc",
    "hearing_documents": "9bdaf105d4a056b5f2e99e0b9ee48063038017351fc4759fcfb9ebe668628023",
    "hearing_dossier": "d74fac322475f6fb6a865a892f3c8579a8cc36d4daec77cd5c57bb699e85f2af",
    "witness_documents": "0eaed03bc3a81e19faf980cf3af835f357b6eb773388c4336b787e7f3e5bd3fa",
    "witness_transcripts": "6302f2c34ba6a1a0323c70944a7f93a6acd3be0d6c0e7c55304c900cdb20dfb9",
    "witness_by_any_key": "74ae59736fafd210ec618080f90f6f1bcd4b3a4bfc12545271f25802967045f8",
    "committee_roster": "7341e9763e3141b76de28ebea5743ef6a6e27178ab3f934466325fe907694873",
    "nomination_transcripts": "3763481ea648e263be18d45e0995716922d74146669d0ba108eb2708d0ae5729",
    "bill_votes": "504bdc85dc5713d2adc909230e01c2a52c1af92a76666a84db07bf6b6b3c9eef",
    "nomination_votes": "d32283a51982833eedf537bbac7fa37a77fc0fa66ab9fdd602d0680ea2e32751",
    "recording_tracks": "2e8962df8e90efca07f03e672f5a680d170e78aec9870d0d70a90f822dadba03",
    "document_editions": "571b53f193f598c4fa8888a9fd8ed07eb5a75ea91eaaeccf367b7e3000b16ca2",
    "meeting_recordings": "00bd57544ac9d19cb38fa310cb18dea4c7920e32ba4bbe38b720d2519a0bef36",
    "channel_unmatched_videos": "9c7a0b37e531749271210b10ef9ee9c634add3893860e984f8fba0111451831c",
    "coverage_counts": "7b64e73a167ccc62e91fe0a749283e1f484055178b24331c67d949ceb8b665c5"
  }
}
''')


BASELINE_RECIPE_ACCESS = json.loads(r'''
{
  "bill_documents": {
    "requires": [
      "list",
      "detail"
    ],
    "relationships": [
      "document_bills",
      "document_detail"
    ]
  },
  "bill_hearing_transcripts": {
    "requires": [
      "meetings",
      "list",
      "detail"
    ],
    "relationships": [
      "meeting_bills",
      "meeting_transcript_documents",
      "document_detail"
    ]
  },
  "hearing_documents": {
    "requires": [
      "list",
      "detail",
      "meetings"
    ],
    "relationships": [
      "document_meetings",
      "document_detail"
    ]
  },
  "hearing_dossier": {
    "requires": [
      "meetings",
      "witnesses",
      "list",
      "detail",
      "recording_matches"
    ],
    "relationships": [
      "witness_meeting",
      "document_meetings",
      "document_detail",
      "match_meeting_associations"
    ]
  },
  "witness_documents": {
    "requires": [
      "list",
      "detail",
      "witnesses"
    ],
    "relationships": [
      "witness_submitted_documents",
      "document_detail"
    ]
  },
  "witness_transcripts": {
    "requires": [
      "witnesses",
      "detail",
      "list"
    ],
    "relationships": [
      "witness_transcript_documents",
      "document_detail"
    ]
  },
  "witness_by_any_key": {
    "requires": [
      "witnesses",
      "witness_key_map"
    ],
    "relationships": [
      "witness_key_map_successor"
    ]
  },
  "committee_roster": {
    "requires": [
      "rosters",
      "committees",
      "members"
    ],
    "relationships": [
      "roster_committee",
      "roster_member"
    ]
  },
  "nomination_transcripts": {
    "requires": [
      "nominations",
      "detail",
      "list"
    ],
    "relationships": [
      "nomination_transcript_documents",
      "document_detail"
    ]
  },
  "bill_votes": {
    "requires": [
      "bills"
    ],
    "relationships": [
      "bills_votes"
    ]
  },
  "nomination_votes": {
    "requires": [
      "nominations"
    ],
    "relationships": [
      "nominations_votes"
    ]
  },
  "recording_tracks": {
    "requires": [
      "recordings"
    ],
    "relationships": [
      "recording_meetings",
      "recording_tracks"
    ]
  },
  "document_editions": {
    "requires": [
      "list"
    ],
    "relationships": [
      "document_editions"
    ]
  },
  "meeting_recordings": {
    "requires": [
      "recording_matches"
    ],
    "relationships": [
      "match_meeting_associations"
    ]
  },
  "channel_unmatched_videos": {
    "requires": [
      "videos",
      "recording_matches"
    ],
    "relationships": [
      "match_recording"
    ]
  },
  "coverage_counts": {
    "requires": [
      "meeting_coverage"
    ],
    "relationships": [
      "coverage_meeting"
    ]
  }
}
''')

ROOT = Path(__file__).parents[3]


def metadata_copy(tmp_path):
    shutil.copytree(ROOT / 'model/ddk', tmp_path / 'model/ddk')
    return tmp_path


def assemble_catalog(project):
    from ddk.catalog import assemble_catalog as assemble
    return assemble(project)


def edit_json(path, change):
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def frozen_metadata():
    data = (ROOT / 'model/registries/release-schema.json').read_bytes()
    assert sha256(data).hexdigest() == BASELINE['registry_sha256']
    return json.loads(data)


def field_path(path):
    return ''.join('[]' if part == {'each': True} else ('.' if index else '') + part['field']
                   for index, part in enumerate(path))


def test_authored_odcs_preserves_all_frozen_physical_fields_and_table_meaning():
    baseline = frozen_metadata()
    odcs = json.loads((ROOT / 'model/ddk/archive.odcs.json').read_text())
    project = json.loads((ROOT / 'model/ddk/project.ddk.json').read_text())
    aliases = {row['object']: alias for alias,row in project['artifacts'].items() if row['kind'] == 'dataset'}
    definitions = {item['name']: item for item in odcs['schema']}
    assert len(definitions) == 23
    count = 0
    for table in baseline['files']:
        name = table['name'].removesuffix('.parquet')
        definition = definitions[name]
        assert definition['businessName'] == table['purpose']
        assert definition['dataGranularityDescription'] == table['row_meaning']
        assert table['nullability'] in definition['description']
        assert all(gap in definition['description'] for gap in table['gaps'])
        properties = {item['name']: item for item in definition['properties']}
        columns = table['columns'] + (CURRENT_CAPTURE_FIELDS if name == 'url_state' else [])
        for column in columns:
            field = properties[column['name']]
            assert field['physicalType'] == column['type']
            meaning = column.get('meaning', '')
            if (name, column['name']) == ('recording_matches', 'meeting_links'):
                assert meaning == 'Supported meeting links ordered by event ID. Empty means no supported link. Absent on older releases.'
                meaning = 'Supported meeting links ordered by event ID. Empty means no supported link.'
            assert field.get('description', '').startswith(meaning)
            assert field['required'] is not column['nullable']
            count += 1
        assert set(properties) == {item['name'] for item in columns}
        from ddk.catalog_access import field_at
        for text,note in table.get('notes', {}).items():
            path = [{'field': field} if field else {'each': True}
                    for field,each in re.findall(r'([^\.\[\]]+)|(\[\])', text)]
            field = field_at(definition, path)
            if field is None:
                assert any(item['dataset'] == aliases[name] and item['kind'] == 'row_position'
                           and any(key['virtual'] and key['path'] == path for key in item['fields'])
                           and note.replace(' on new releases', '') in item['meaning'] for item in project['catalog']['identities'])
            else:
                assert note in field['description']
    assert count == 254 + 3
    assert 'legacyKeys' not in json.dumps(odcs)


def test_authored_catalog_preserves_frozen_relationships_and_recipe_semantics():
    baseline = frozen_metadata()
    project = json.loads((ROOT / 'model/ddk/project.ddk.json').read_text())
    names = {alias: item['object'] for alias, item in project['artifacts'].items() if item['kind'] == 'dataset'}
    relationships = {item['id'].removeprefix(NAMESPACE + 'relationship:'): item
                     for item in project['catalog']['relationships']}
    for table in baseline['files']:
        name = table['name'].removesuffix('.parquet')
        expected = table['identity']
        candidates = [item for item in project['catalog']['identities']
                      if names[item['dataset']] == name
                      and list(map(field_path, [field['path'] for field in item['fields']])) == expected['fields']
                      and item['kind'] == ('key' if expected['kind'] == 'primary_key' else 'row_position')]
        assert len(candidates) == 1
        identity = candidates[0]
        assert identity['scope'] == ('dataset_version' if expected['scope'] == 'published identifier' else 'release')
        assert expected['scope'] in identity['meaning']
        assert expected['validation'] in identity['meaning']
        if 'note' in expected:
            note = expected['note'].replace(' Older releases carry only the detail columns; their rows pair with list by list_row.', '')
            assert note in identity['meaning']
    assert len(relationships) == 70
    for expected in baseline['relationships']:
        actual = relationships[expected['id']]
        assert actual['meaning'].startswith(expected['meaning'])
        assert actual['cardinality'].replace('_', '-') == expected['cardinality']
        assert actual['resolution'] == expected['resolution']
        assert actual['nulls'] == ('skip' if expected['nullable'] else 'reject')
        assert actual['scopeDescription'] == expected['scope']
        for side in ('source', 'target'):
            endpoint = actual[side]
            if 'external' in expected[side]:
                assert expected[side]['external'] in actual['meaning']
            else:
                assert names[endpoint['dataset']] == expected[side]['table']
                assert list(map(field_path, endpoint['paths'])) == expected[side]['fields']
        if expected['match'] == 'equal':
            assert actual['match'] == 'equal'
        else:
            assert actual['match'] == 'project_rule'
            assert actual['rule']['id'].rsplit(':', 1)[-1] == expected['match']
    recipes = {item['id'].removeprefix(NAMESPACE + 'recipe:'): item for item in project['catalog']['recipes']}
    assert len(recipes) == 16
    for expected in baseline['recipes']:
        recipe = recipes[expected['id']]
        assert recipe['title'] == expected['title']
        # Coordinated greenfield readers require meeting_links; only the old-reader
        # compatibility sentence is retired from this independently frozen oracle.
        notes = [note.replace(' Older releases may omit meeting_links and publish their original recipes.', '')
                 for note in expected['notes']]
        assert recipe['notes'] == notes
        assert recipe['dialect'] == expected['dialect']
        assert recipe['resultGrain'] == expected['result_row']
        assert {names[alias] for alias in recipe['inputs'].values()} == set(BASELINE_RECIPE_ACCESS[expected['id']]['requires'])
        assert {rid.removeprefix(NAMESPACE + 'relationship:') for rid in
                recipe['relationships'] + recipe['contextualRelationships']} == set(BASELINE_RECIPE_ACCESS[expected['id']]['relationships'])
        assert recipe['parameterOrder'] == [item['name'] for item in expected['parameters']]
        assert recipe['parameters']['required'] == recipe['parameterOrder']
        for parameter in expected['parameters']:
            declared = recipe['parameters']['properties'][parameter['name']]
            assert declared['type'] == ('integer' if type(parameter['example']) is int else 'string')
            assert declared['examples'] == [parameter['example']]
        assert sha256((ROOT / 'model/ddk' / recipe['sql']).read_bytes()).hexdigest() == BASELINE['recipe_sha256'][expected['id']]
    assert set(project['extensions']) == {NAMESPACE + 'upstream-relations'}
    assert project['extensions'][NAMESPACE + 'upstream-relations'] == baseline['upstream_relations']


def test_real_ddk_admits_catalog_without_promoting_required_unknowns():
    result = assemble_catalog(ROOT / 'model/ddk/project.ddk.json')
    assert result.catalog is not None, result.report
    assert result.report['decision'] == 'incomplete'
    assert any(check.get('required') and check['status'] == 'unknown' for check in result.report['checks'])
    assert len(result.catalog['relationships']) == 70
    assert len(result.catalog['recipes']) == 16
    assert len(result.catalog['extensions'][ASSEMBLY]['datasetDefinitions']) == 23
    for recipe in result.catalog['recipes']:
        name = recipe['id'].removeprefix(NAMESPACE + 'recipe:')
        assert sha256(result.companions[recipe['sql']]).hexdigest() == BASELINE['recipe_sha256'][name]
        assert len(recipe['parameterOrder']) == result.companions[recipe['sql']].decode('utf-8').count('?')


@pytest.mark.parametrize('change', [
    lambda value: value['catalog']['recipes'][0].update(sql='queries/missing.sql'),
    lambda value: value['catalog']['relationships'][0]['source'].update(paths=[[{'field': 'missing'}]]),
    lambda value: value['catalog']['recipes'][0].update(contextualRelationships=['urn:missing:relationship']),
    lambda value: value['catalog']['recipes'][0].update(contextualRelationships=None),
    lambda value: value['catalog']['recipes'][0].update(parameterOrder=['missing']),
])
def test_real_ddk_refuses_invalid_definition_before_consumer_use(tmp_path, change):
    root = metadata_copy(tmp_path)
    admitted = assemble_catalog(root / 'model/ddk/project.ddk.json')
    assert admitted.catalog is not None, admitted.report
    edit_json(root / 'model/ddk/project.ddk.json', change)
    result = assemble_catalog(root / 'model/ddk/project.ddk.json')
    assert result.report['decision'] != 'passed'
    assert result.catalog is None
