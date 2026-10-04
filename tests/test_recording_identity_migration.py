"""Provider interpretation preserves already published recording identities."""
import json

import pytest

from committee_explorer.export import export
from committee_explorer.ids import IdRegistry
from congress_api.adapters.meetings import meeting_key
from test_explorer_export import NOW, native, write_meetings

URL = 'https://www.youtube-nocookie.com/embed/abcdefghijk'
WATCH = 'https://www.youtube.com/watch?v=abcdefghijk'
CANONICAL = 'youtube|abcdefghijk'


@pytest.mark.parametrize('canonical_exists', [False, True])
def test_existing_native_recording_ids_survive_provider_recognition(tmp_path, canonical_exists):
    row = {**native(), 'videos': [{'url': URL}]}
    if canonical_exists:
        row['videos'].append({'url': WATCH})
    state = tmp_path / 'state'
    ids = IdRegistry(state / 'ids.json')
    meeting = ids('meeting', meeting_key(row))
    legacy = meeting_key(row) + '|videos|' + URL
    suffixes = [('material', ''), ('material_version', '|reported-edition'),
                ('representation', '|' + URL), ('material_link', '|meeting|' + meeting + '|recording')]
    before = {(kind, ids(kind, legacy + suffix)) for kind, suffix in suffixes}
    canonical_suffixes = [(kind, suffix.replace(URL, WATCH)) for kind, suffix in suffixes]
    canonical_before = {kind: ids(kind, CANONICAL + suffix) for kind, suffix in canonical_suffixes} if canonical_exists else {}
    ids.save()
    registry_before = dict(ids.values)
    path = write_meetings(tmp_path, [row])
    options = dict(meetings=path, output_dir=tmp_path / 'public', state_dir=state, as_of=NOW)
    _, catalog = export(**options)
    assert before <= {(record.kind, record.id) for record in catalog.records}
    recording = next(record for record in catalog.records if record.kind == 'material' and record.details.type == 'recording')
    assert recording.details.provider == 'youtube'
    assert recording.identifiers[0].value == 'abcdefghijk'
    after = IdRegistry(state / 'ids.json')
    assert all(after.values[key] == value for key, value in registry_before.items())
    if canonical_exists:
        assert all(after.existing(kind, CANONICAL + suffix) == canonical_before[kind] for kind, suffix in canonical_suffixes)
        assert set(canonical_before.items()) <= {(record.kind, record.id) for record in catalog.records}
    else:
        assert all(after.existing(kind, CANONICAL + suffix) == after.existing(kind, legacy + suffix) for kind, suffix in suffixes)
    manifest, replay = export(**options)
    assert before <= {(record.kind, record.id) for record in replay.records}
    report = json.loads((tmp_path / 'public' / 'releases' / manifest.publication_id / 'coverage.json').read_text())
    receipt = next(item for item in report['input_reconciliation'] if item.get('migration') == 'native-recording-provider-keys')
    assert receipt['version'] == 1


def test_distinct_published_native_recordings_are_not_merged(tmp_path):
    from committee_explorer.recording_ids import retain_recording_ids

    rows = [{**native(), 'eventId': str(event), 'videos': [{'url': URL}]}
            for event in (106245, 106246)]
    ids = IdRegistry(tmp_path / 'ids.json')
    keys = [meeting_key(row) + '|videos|' + URL for row in rows]
    before = [ids('material', key) for key in keys]
    ids.save()
    ids = IdRegistry(tmp_path / 'ids.json')
    overrides, receipt = retain_recording_ids(rows, ids)
    assert overrides == {key: key for key in keys}
    assert ids.existing('material', CANONICAL) is None
    assert [ids.existing('material', key) for key in keys] == before
    assert receipt['conflicting_provider_keys'] == 1


def test_known_provider_material_does_not_prove_new_url_was_previously_published(tmp_path):
    from committee_explorer.recording_ids import retain_recording_ids

    ids = IdRegistry(tmp_path / 'ids.json')
    ids('material', CANONICAL)
    before = dict(ids.values)
    row = {**native(), 'videos': [{'url': 'https://other.gov/player?next=' + WATCH}]}
    overrides, receipt = retain_recording_ids([row], ids)
    assert not overrides and not receipt['corrected_provider_references']
    assert ids.values == before


@pytest.mark.parametrize(('url', 'old_key', 'real_url'), [
    ('https://other.gov/player?next=https://youtube.com/watch?v=abcdefghijk', CANONICAL, WATCH),
    ('https://www.youtube.com/watch?v=abcdefghijkl', CANONICAL, WATCH),
    ('https://other.gov/isvp/?comm=ag&filename=ag100126', 'senate|ag|ag100126',
     'https://www.senate.gov/isvp/?comm=ag&filename=ag100126'),
])
@pytest.mark.parametrize('include_real_provider', [False, True])
def test_corrected_provider_associations_publish_explicit_id_migration(tmp_path, url, old_key, real_url, include_real_provider):
    row = {**native(), 'videos': [{'url': url}]}
    if include_real_provider:
        row['videos'].append({'url': real_url})
    state = tmp_path / 'state'
    ids = IdRegistry(state / 'ids.json')
    meeting = ids('meeting', meeting_key(row))
    suffixes = [('material', ''), ('material_version', '|reported-edition'),
                ('representation', '|' + url), ('material_link', '|meeting|' + meeting + '|recording')]
    before = {kind: ids(kind, old_key + suffix) for kind, suffix in suffixes}
    registry_before = dict(ids.values)
    ids.save()
    options = dict(meetings=write_meetings(tmp_path, [row]), output_dir=tmp_path / 'public', state_dir=state, as_of=NOW)
    manifest, catalog = export(**options)
    corrected = next(record for record in catalog.records if record.kind == 'representation'
                     and any(location.url == url for location in record.locations))
    assert corrected.id != before['representation']
    version = next(record for record in catalog.records if record.kind == 'material_version' and record.id == corrected.version.id)
    material = next(record for record in catalog.records if record.kind == 'material' and record.id == version.material.id)
    assert material.details.provider is None
    assert material.id != before['material'] and version.id != before['material_version']
    link = next(record for record in catalog.records if record.kind == 'material_link' and record.material.id == material.id)
    assert link.id != before['material_link']
    after = IdRegistry(state / 'ids.json')
    assert all(after.values[key] == value for key, value in registry_before.items())
    if include_real_provider:
        assert any(record.kind == 'material' and record.id == before['material'] and record.details.provider
                   for record in catalog.records)
    coverage = json.loads((tmp_path / 'public' / 'releases' / manifest.publication_id / 'coverage.json').read_text())
    receipt = next(item for item in coverage['input_reconciliation'] if item.get('migration') == 'native-recording-provider-keys')
    change, = receipt['corrected_provider_references']
    assert change['old_ids'] == before
    assert change['new_ids']['material'] == material.id
    assert change['new_ids']['representation'] == corrected.id
    assert change['new_ids']['material_link'] == link.id
    assert change['reason']
    if include_real_provider:
        real_representation = next(record for record in catalog.records if record.kind == 'representation'
                                   and any(location.url == real_url for location in record.locations))
        assert real_representation.version.id == before['material_version']
        assert all(location.url != url for record in catalog.records if record.kind == 'representation'
                   and record.version.id == before['material_version'] for location in record.locations)
    _, replay = export(**options)
    assert {(record.kind, record.id) for record in catalog.records} <= {(record.kind, record.id) for record in replay.records}
