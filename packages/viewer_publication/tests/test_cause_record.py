"""The one manual step left in the nightly: a record drafted from the stopped run's own evidence."""
import json
from pathlib import Path

import pytest

from viewer_publication import cause_record
from viewer_publication.release_gate import load_causes

ROOT = Path(__file__).parents[3]
NIGHT = ROOT / 'packages/viewer_publication/tests/fixtures/data-only-night/larger-capture-night-20261117-2ec7ae83a852.json'
BODY, NEWER, OTHER = 'a' * 64, 'b' * 64, 'c' * 64


def rule(**found):
    value = dict(ok=not found, missing=0, missing_keys=[], dangling=0, dangling_keys=[], published_and_retired=0,
                 published_and_retired_keys=[], unchecked=[])
    for prefix in ('', 'lookup_', 'address_'):
        value.update({prefix + 'changed': 0, prefix + 'changed_answers': []})
    value.update(found)
    return value


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A checkout's two folders the tool writes, with the real publish spec; evidence pins are relative to it."""
    (tmp_path / 'model/jobs').mkdir(parents=True)
    spec = json.loads((ROOT / 'model/jobs/publish.json').read_text())
    spec.pop('release_causes', None)
    (tmp_path / 'model/jobs/publish.json').write_text(json.dumps(spec, indent=2) + '\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_stopped_real_night_becomes_a_pinned_record_the_publisher_can_read(checkout):
    report = dict(json.loads(NIGHT.read_text()), link_rule=rule(), automatic_reasons=['data-only night: one removal'], reasons=[])
    path = cause_record.draft(report, cause='Capture night; one person key went ambiguous.', tickets=['ct-pz32'], root=checkout)
    spec = json.loads((checkout / 'model/jobs/publish.json').read_text())
    assert spec['release_causes']['path'] == f'release-causes/{path.name}' == 'release-causes/95f4e73e859d-2ec7ae83a852.json'
    record = load_causes(dict(spec['release_causes'], path=str(checkout / path)))
    assert {(e['id'], e['count']) for e in record['groups']} == {(f"{g['file']}|{g['group']}|{g['cause']}", g['count']) for g in report['failing']}
    assert len(record['groups']) == 57 and 'corrections' not in record
    assert all(e['cause'] == 'Capture night; one person key went ambiguous.' and e['tickets'] == ['ct-pz32'] for e in record['groups'])
    kept = json.loads((checkout / record['groups'][0]['evidence'][0]['path']).read_text())
    assert kept['stopped_for'] == ['data-only night: one removal'] and len(kept['failing_groups']) == 57
    # Editing the record by hand changes its bytes: `pin` makes the spec name the edited record.
    edited = json.loads((checkout / path).read_text())
    edited['groups'][0]['cause'] = 'Its own words.'
    (checkout / path).write_text(json.dumps(edited, indent=1) + '\n')
    with pytest.raises(ValueError):
        load_causes(dict(spec['release_causes'], path=str(checkout / path)))
    assert cause_record.pin_record(checkout) == path
    again = json.loads((checkout / 'model/jobs/publish.json').read_text())['release_causes']
    assert load_causes(dict(again, path=str(checkout / path)))['groups'][0]['cause'] == 'Its own words.'


def test_moved_links_need_their_own_reason_and_proven_ones_are_left_out(checkout):
    moved = rule(changed=1, changed_answers=[dict(key='1a56' * 4, live_body=BODY, candidate_body=NEWER)],
                 address_changed=2, address_changed_answers=[
                     dict(key='https://example.test/a', live_body=BODY, candidate_bodies=[NEWER]),
                     dict(key='https://example.test/b', live_body=BODY, candidate_bodies=[NEWER, OTHER])],
                 proven_corrections=[dict(kind='address', key='https://example.test/a', live_body=BODY, candidate_body=NEWER)])
    report = dict(base_release='1' * 64, candidate_release='2' * 64, link_rule=moved, failing=[], reasons=['link rule: stopped'])
    with pytest.raises(ValueError, match='2 live links would open another file; say why with --correction'):
        cause_record.draft(report, cause='c', tickets=['ct-pz32'], root=checkout)
    path = cause_record.draft(report, cause='c', tickets=['ct-pz32'], correction='The publisher replaced the page.', root=checkout)
    named = json.loads((checkout / path).read_text())['corrections']
    assert [(c['kind'], c['key'], c['candidate_body']) for c in named] == [
        ('link_key', '1a56' * 4, NEWER), ('address', 'https://example.test/b', [NEWER, OTHER])]
    assert all(c['decision'] == 'The publisher replaced the page.' for c in named)


@pytest.mark.parametrize('found', [dict(missing=2, missing_keys=['k1', 'k2']), dict(dangling=1, dangling_keys=['k']),
                                   dict(published_and_retired=1, published_and_retired_keys=['k']), dict(unchecked=['links.parquet absent']),
                                   dict(changed=3, changed_answers=[dict(key='k', live_body=BODY, candidate_body=NEWER)])])
def test_a_night_the_gate_would_still_refuse_cannot_be_recorded_away(checkout, found):
    # The last case: three keys moved but the report samples one, so no record can name the other two.
    report = dict(base_release='1' * 64, candidate_release='2' * 64, link_rule=rule(**found), failing=[], reasons=['link rule: stopped'])
    with pytest.raises(ValueError, match='No record can pass this night'):
        cause_record.draft(report, cause='c', tickets=['ct-pz32'], correction='d', root=checkout)
    assert not (checkout / 'model/jobs/release-causes').exists()


def test_the_command_reads_one_report_from_a_downloaded_folder_and_says_what_stopped(checkout, tmp_path, capsys, monkeypatch):
    night = tmp_path / 'night/archive-publish-evidence-1-1/output/archive-publish/candidate-x'
    night.mkdir(parents=True)
    report = dict(json.loads(NIGHT.read_text()), link_rule=rule(), automatic_reasons=['data-only night: stopped for a removal'], reasons=[])
    (night / 'release-gate.json').write_text(json.dumps(report))
    monkeypatch.chdir(tmp_path)  # run from anywhere: the evidence folder is relative to here, the pins to the checkout
    assert cause_record.main(['draft', '--evidence', 'night', '--cause', 'Capture night.', '--ticket', 'ct-pz32'], root=checkout) == 0
    out = capsys.readouterr().out
    assert 'data-only night: stopped for a removal' in out and 'with 57 groups and pinned it' in out
    # A night the publisher passed by itself needs no record, and gets none.
    (night / 'release-gate.json').write_text(json.dumps(dict(report, automatic_reasons=[])))
    assert cause_record.main(['draft', '--evidence', 'night', '--cause', 'c', '--ticket', 'ct-pz32'], root=checkout) == 2
    assert 'did not stop this run' in capsys.readouterr().err
    assert cause_record.main(['draft', '--evidence', str(tmp_path / 'absent'), '--cause', 'c', '--ticket', 'ct-pz32'], root=checkout) == 2
