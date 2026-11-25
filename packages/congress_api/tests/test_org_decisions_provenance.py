"""Org decision provenance records validate strictly before raw storage or staging."""
import json

import pytest

from congress_api.cli.provenance import main as cli_main
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import (
    KINDS,
    ORG_VERDICTS,
    apply_staged,
    finish_stage,
    load_stage,
    stage_records,
    validate_provenance,
    write_records,
)

STAMP = '2026-11-22T12:00:00Z'


def org_decision(**overrides):
    row = dict(
        id='org-decision-1',
        subject='bag:' + 'a' * 16,
        verdict='same',
        object='bag:' + 'b' * 16,
        note='Confirmed identical organization across word-order variants',
        reviewer='owner',
        decided_at=STAMP,
        supersedes=None,
    )
    row.update(overrides)
    return row


class NoWrites:
    def put(self, *args, **kwargs):
        raise AssertionError('Malformed org_decisions provenance reached raw storage')


def test_org_decisions_registered_in_provenance_kinds():
    assert 'org_decisions' in KINDS
    assert ORG_VERDICTS == frozenset({'same', 'different', 'unsure', 'withdraw'})


@pytest.mark.parametrize('subject', ['bag:' + 'a' * 16, 'witness:' + 'b' * 16, 'c' * 16])
@pytest.mark.parametrize('obj', ['org:' + 'd' * 16, 'bag:' + 'e' * 16, 'wikidata:Q460173'])
@pytest.mark.parametrize('verdict', ['same', 'different', 'unsure'])
def test_valid_org_decision_shapes_accept(subject, obj, verdict):
    row = org_decision(subject=subject, object=obj, verdict=verdict)
    assert validate_provenance('org_decisions', row) is row


def test_withdraw_org_decision_requires_non_self_supersedes():
    withdrawn = org_decision(id='org-decision-2', verdict='withdraw', supersedes='org-decision-1')
    assert validate_provenance('org_decisions', withdrawn) is withdrawn

    with pytest.raises(ValueError, match='supersedes'):
        write_records(NoWrites(), 'org_decisions', [org_decision(verdict='withdraw', supersedes=None)], timestamp='20261122T120000Z')
    with pytest.raises(ValueError, match='superseded'):
        write_records(
            NoWrites(),
            'org_decisions',
            [org_decision(id='same-id', verdict='withdraw', supersedes='same-id')],
            timestamp='20261122T120000Z',
        )


@pytest.mark.parametrize(
    'field,value',
    [
        ('id', None),
        ('id', ''),
        ('id', '   '),
        ('id', 42),
        ('subject', None),
        ('subject', ''),
        ('subject', 'org:' + 'a' * 16),
        ('subject', 'fr_agency:epa'),
        ('subject', 'bag:' + 'A' * 16),
        ('subject', 'bag:' + 'a' * 15),
        ('subject', 'witness:short'),
        ('subject', 'a' * 15),
        ('subject', 'A' * 16),
        ('verdict', None),
        ('verdict', 'merge'),
        ('verdict', 'hide'),
        ('verdict', ['same']),
        ('object', None),
        ('object', ''),
        ('object', 'fr_agency:epa'),
        ('object', 'fr_agency:1234'),
        ('object', 'agency_alias:u-s-army'),
        ('object', 'a' * 16),
        ('object', 'witness:' + 'a' * 16),
        ('object', 'org:' + 'A' * 16),
        ('object', 'bag:not-hex'),
        ('object', 'wikidata:123'),
        ('object', 'wikidata:q123'),
        ('object', 'wikidata:Q'),
        ('note', None),
        ('note', ''),
        ('note', '   '),
        ('note', 42),
        ('note', ['text']),
        ('reviewer', None),
        ('reviewer', ''),
        ('reviewer', '   '),
        ('reviewer', True),
        ('decided_at', None),
        ('decided_at', '2026-11-22T12:00:00'),
        ('decided_at', 'not-a-timestamp'),
        ('supersedes', ''),
        ('supersedes', '   '),
        ('supersedes', 99),
        ('note', 'See /Users/alice/private/org-notes.txt'),
    ],
)
def test_malformed_org_decision_refuses_before_raw_io(field, value):
    row = org_decision(**{field: value})
    with pytest.raises(ValueError):
        write_records(NoWrites(), 'org_decisions', [row], timestamp='20261122T120000Z')


def test_every_org_decision_field_is_required_and_extra_fields_refused():
    for field in org_decision():
        row = org_decision()
        del row[field]
        with pytest.raises(ValueError, match='Incomplete provenance'):
            write_records(NoWrites(), 'org_decisions', [row], timestamp='20261122T120000Z')

    with pytest.raises(ValueError, match='Incomplete provenance'):
        write_records(
            NoWrites(),
            'org_decisions',
            [org_decision(extra_field='unexpected')],
            timestamp='20261122T120000Z',
        )


def test_duplicate_decision_ids_in_batch_refused():
    rows = [org_decision(id='dup-1'), org_decision(id='dup-1', object='bag:' + 'c' * 16)]
    with pytest.raises(ValueError, match='Duplicate provenance decision ID'):
        write_records(NoWrites(), 'org_decisions', rows, timestamp='20261122T120000Z')


def test_stage_load_apply_and_cli_round_trip(tmp_path, capsys):
    records = [
        org_decision(id='d1', verdict='same'),
        org_decision(id='d2', subject='witness:' + '1' * 16, object='wikidata:Q18247', verdict='different'),
        org_decision(id='d3', verdict='withdraw', supersedes='d1', decided_at='2026-11-22T12:05:00Z'),
    ]
    stage_dir = tmp_path / 'stage-direct'
    key, count = stage_records(stage_dir, 'org_decisions', records, decided_at=STAMP)
    assert count == 3 and key == 'provenance/org_decisions/20261122T120000+0000.jsonl'
    manifest = finish_stage(stage_dir, kind='org_decisions', provenance=key, records=count, inputs=dict(source='test'))
    assert manifest['kind'] == 'org_decisions'

    loaded_root, loaded = load_stage(stage_dir)
    assert loaded_root == stage_dir.resolve()
    assert loaded['records'] == 3

    store = BodyStore(LocalAdapter(tmp_path / 'raw'))
    applied = apply_staged(stage_dir, store)
    assert applied == dict(objects=1, records=3)
    assert [json.loads(line) for line in (tmp_path / 'raw' / key).read_text().splitlines()] == records

    # CLI staging flow
    source = tmp_path / 'authored.jsonl'
    source.write_text(''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in records))
    cli_stage = tmp_path / 'cli-stage'
    cli_main(['--records', str(source), '--kind', 'org_decisions', '--decided-at', STAMP, '--stage', str(cli_stage)])
    out = json.loads(capsys.readouterr().out)
    assert out['kind'] == 'org_decisions' and out['records'] == 3
    _, cli_loaded = load_stage(cli_stage)
    assert cli_loaded['provenance'] == key
    cli_main(['--stage', str(cli_stage)])
    inspect_out = json.loads(capsys.readouterr().out)
    assert inspect_out == dict(kind='org_decisions', records=3, objects=1, apply=False)
