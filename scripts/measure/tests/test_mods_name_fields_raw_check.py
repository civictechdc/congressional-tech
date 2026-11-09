"""The MODS name-fields raw check passes a faithful re-read and flags each planted wrong value, in both directions."""
import gzip
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('mods_name_fields_raw_check', ROOT / 'scripts/measure/mods_name_fields_raw_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

LINES = ['American Legion',
         'Vietnam Veterans of America, Richard F. Weidman, Executive Director for Policy',
         'Hon. Eleanor Holmes Norton, a Delegate in Congress from the District of Columbia',
         'Herrera Beutler, Hon. Jaime, a Representative in Congress from the State of Washington']
DIGEST = 'ab' * 32


def occurrence(locator, name, position=None, organization=None):
    return dict(source_locator=locator, name=name, position=position, organization=organization, on_behalf_of=None)


DELEGATE = 'a Delegate in Congress from the District of Columbia'
WASHINGTON = 'a Representative in Congress from the State of Washington'
BEFORE = [occurrence('mods:witness[1]', 'American Legion'),
          occurrence('mods:witness[2]', 'Vietnam Veterans of America', 'Richard F. Weidman', 'Executive Director for Policy'),
          occurrence('mods:witness[3]', 'Eleanor Holmes Norton', DELEGATE),
          occurrence('mods:witness[4]', 'Herrera Beutler', 'Hon. Jaime', WASHINGTON)]
AFTER = [occurrence('mods:witness[1]', None, None, 'American Legion'),
         occurrence('mods:witness[2]', 'Richard F. Weidman', 'Executive Director for Policy', 'Vietnam Veterans of America'),
         BEFORE[2],
         occurrence('mods:witness[4]', 'Jaime Herrera Beutler', WASHINGTON)]


def write(tmp_path, before=BEFORE, after=AFTER, lines=LINES):
    body = ('<mods xmlns="http://www.loc.gov/mods/v3"><extension>'
            + ''.join(f'<witness>{line}</witness>' for line in lines) + '</extension></mods>').encode()
    (tmp_path / 'raw' / DIGEST[:2]).mkdir(parents=True)
    (tmp_path / 'raw' / DIGEST[:2] / f'{DIGEST}.gz').write_bytes(gzip.compress(body))
    for name, appearances in (('before', before), ('after', after)):
        rows = [dict(source='mods', record_sha=bytes.fromhex(DIGEST), package_id='CHRG-1', appearances=appearances),
                dict(source='mods', record_sha=bytes.fromhex('cd' * 32), package_id='CHRG-2', appearances=[])]
        pq.write_table(pa.Table.from_pylist(rows), tmp_path / f'{name}.parquet')
    people = [dict(source=s, name=n) for s in ('congress_gov', 'house_xml')
              for n in ('Richard Roe', 'Eleanor Smith', 'Hon. Jaime Herrera Beutler')]
    people.append(dict(source='mods', name='American Legion'))  # MODS names never teach a name
    pq.write_table(pa.Table.from_pylist(people), tmp_path / 'people.parquet')


def run(tmp_path, *extra):
    args = ['--before', str(tmp_path / 'before.parquet'), '--after', str(tmp_path / 'after.parquet'),
            '--raw-root', str(tmp_path / 'raw'), '--people', str(tmp_path / 'people.parquet'),
            '--output', str(tmp_path / 'out.json'), *extra]
    code = check.main(args)
    return code, json.loads((tmp_path / 'out.json').read_text())


def test_a_faithful_reread_passes_and_names_the_unreadable_body(tmp_path):
    write(tmp_path)
    code, out = run(tmp_path)
    assert code == 0 and out['status'] == 'passed'
    assert out['counts'] == {'bodies': 2, 'occurrences': 4, 'changed': 3, 'no_name': 1, 'name_read': 1, 'reordered': 1}
    assert [i['body'] for i in out['not_read']] == ['cd' * 32]


@pytest.mark.parametrize('kind, flags, locator, planted', [
    ('person-moved', {'person_moved': 1}, 'mods:witness[3]', None),
    ('reversed-name', {'reorder_unsupported': 1, 'name_not_person': 1}, 'mods:witness[4]', 'Beutler Jaime Herrera'),
    # The organization before the person read as the name: it also loses the person's words.
    ('previous-segment', {'name_not_person': 1, 'words_lost': 1}, 'mods:witness[2]', 'Vietnam Veterans of America'),
])
def test_each_planted_wrong_value_is_flagged(tmp_path, kind, flags, locator, planted):
    write(tmp_path)
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted']['flagged'] and out['planted']['planted'] == planted
    assert out['failed'] == flags
    assert all([i['locator'] for i in out[flag]] == [locator] for flag in flags)


def test_a_place_read_as_the_name_is_flagged(tmp_path):
    after = [*AFTER[:3], occurrence('mods:witness[4]', 'Washington', WASHINGTON)]
    write(tmp_path, after=after)
    code, out = run(tmp_path)
    assert code == 1 and [i['locator'] for i in out['name_not_person']] == ['mods:witness[4]']


def test_a_person_left_in_the_organization_a_lost_word_and_a_dropped_row_are_flagged(tmp_path):
    after = [AFTER[0], occurrence('mods:witness[2]', None, None, 'Vietnam Veterans of America, Richard F. Weidman'), AFTER[3]]
    write(tmp_path, after=after)
    code, out = run(tmp_path)
    assert code == 1
    assert [i['locator'] for i in out['person_left_in_organization']] == ['mods:witness[2]']
    assert out['words_lost'][0]['words'] == ['director', 'executive', 'for', 'policy']
    assert [i['locator'] for i in out['removed']] == ['mods:witness[3]']


def fields(item):
    return {f: item[f] for f in ('name', 'position', 'organization', 'on_behalf_of')}


def test_a_reviewed_flag_is_accepted_and_an_accept_the_run_no_longer_flags_fails(tmp_path):
    left = occurrence('mods:witness[2]', None, None, 'Vietnam Veterans of America, Richard F. Weidman')
    write(tmp_path, after=[AFTER[0], left, *AFTER[2:]])
    accept = [dict(body=DIGEST, locator='mods:witness[2]', flag=flag, after=fields(left), reason='read')
              for flag in ('words_lost', 'person_left_in_organization')]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 0 and [(i['locator'], i['flag']) for i in out['accepted']] == [
        ('mods:witness[2]', 'words_lost'), ('mods:witness[2]', 'person_left_in_organization')]
    stale = accept + [dict(body=DIGEST, locator='mods:witness[1]', flag='person_moved', after=fields(AFTER[0]), reason='read')]
    (tmp_path / 'accept.json').write_text(json.dumps(stale))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 1 and out['failed'] == {'stale_accept': 1}


def test_an_accept_covers_only_the_value_read(tmp_path):
    """A later wrong value under the same flag and occurrence is not covered by an earlier accept."""
    after = [*AFTER[:3], occurrence('mods:witness[4]', 'Washington', WASHINGTON)]
    write(tmp_path, after=after)
    accept = [dict(body=DIGEST, locator='mods:witness[4]', flag='name_not_person', after=fields(AFTER[3]), reason='read')]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 1 and out['failed'] == {'name_not_person': 1, 'words_lost': 1, 'stale_accept': 1}


@pytest.mark.parametrize('dropped', ['position', 'organization'])
def test_an_accepted_lost_word_does_not_cover_a_dropped_position_or_organization(tmp_path, dropped):
    """Same name, same flag: dropping a whole position or organization on an accepted row still fails."""
    read = occurrence('mods:witness[2]', 'Richard F. Weidman', 'Director for Policy', 'Vietnam Veterans of America')
    write(tmp_path, after=[AFTER[0], read, *AFTER[2:]])
    accept = [dict(body=DIGEST, locator='mods:witness[2]', flag='words_lost', after=fields(read), reason='read')]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 0 and [i['flag'] for i in out['accepted']] == ['words_lost']
    dropped_row = dict(read, **{dropped: None})
    (tmp_path / 'raw').rename(tmp_path / 'raw-old')  # write() lays the raw body out afresh
    write(tmp_path, after=[AFTER[0], dropped_row, *AFTER[2:]])
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 1 and out['failed'] == {'words_lost': 1, 'stale_accept': 1}


# ct-zs48 and ct-3aap: a joined line read as two people, and organizations' own documents typed as statements.
RECORD_LINES = ['Hon. Eleanor Smith, of the District of Columbia.. Hon. Richard Roe, of Illinois',
                'Paralyzed Veterans of America, statement', 'Blinded Veterans Association, New York, Inc']


def typed(item, witness_type):
    return dict(item, witness_type=witness_type)


RECORD_BEFORE = [occurrence('mods:witness[1]', 'Eleanor Smith', 'of the District of Columbia.. Hon. Richard Roe', 'of Illinois'),
                 typed(occurrence('mods:witness[2]', None, None, RECORD_LINES[1]), None),
                 typed(occurrence('mods:witness[3]', None, None, RECORD_LINES[2]), None)]
RECORD_AFTER = [occurrence('mods:witness[1]', 'Eleanor Smith', 'of the District of Columbia'),
                occurrence('mods:witness[1]/part[2]', 'Richard Roe', 'of Illinois'),
                typed(RECORD_BEFORE[1], 'statement_for_record'), RECORD_BEFORE[2]]


def test_a_split_that_moves_the_second_persons_words_and_a_typed_document_pass(tmp_path):
    write(tmp_path, before=RECORD_BEFORE, after=RECORD_AFTER, lines=RECORD_LINES)
    code, out = run(tmp_path)
    assert code == 0 and out['status'] == 'passed'
    assert [i['locator'] for i in out['split']] == ['mods:witness[1]/part[2]']
    assert out['counts']['typed'] == 1 and not out['words_lost'] and not out['untyped_record']


@pytest.mark.parametrize('kind, flag, locator', [
    ('split-untrimmed', 'split_unsupported', 'mods:witness[1]/part[2]'),
    ('typed-organization', 'type_unsupported', 'mods:witness[3]'),
])
def test_each_planted_split_or_type_is_flagged(tmp_path, kind, flag, locator):
    write(tmp_path, before=RECORD_BEFORE, after=RECORD_AFTER, lines=RECORD_LINES)
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted']['flagged'] and out['failed'] == {flag: 1}
    assert [i['locator'] for i in out[flag]] == [locator]


def test_an_added_row_that_is_not_a_split_a_person_typed_and_an_untyped_document_are_seen(tmp_path):
    after = [typed(RECORD_AFTER[0], 'statement_for_record'), dict(RECORD_AFTER[1], source_locator='mods:witness[4]'),
             RECORD_BEFORE[1], RECORD_AFTER[3]]
    write(tmp_path, before=RECORD_BEFORE, after=after, lines=RECORD_LINES)
    code, out = run(tmp_path)
    assert code == 1 and out['failed'] == {'added': 1, 'type_unsupported': 1, 'words_lost': 1}
    assert [i['locator'] for i in out['untyped_record']] == ['mods:witness[2]']


def test_an_accept_is_bound_to_the_type(tmp_path):
    """An accept read on one witness_type does not cover another."""
    after = [*RECORD_AFTER[:3], typed(RECORD_BEFORE[2], 'statement_for_record')]
    write(tmp_path, before=RECORD_BEFORE, after=after, lines=RECORD_LINES)
    read = {f: after[3].get(f) for f in check.KEYED}
    accept = [dict(body=DIGEST, locator='mods:witness[3]', flag='type_unsupported', after=read, reason='read')]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 0 and [i['flag'] for i in out['accepted']] == ['type_unsupported']
    accept[0]['after'] = dict(read, witness_type='record_material')
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 1 and out['failed'] == {'type_unsupported': 1, 'stale_accept': 1}


# ct-zs48 review: a question-for-the-record heading and the Members listed under it are record material.
QUESTION_LINES = ['Responses to questions for the record from the following Representatives: Hon. Richard Roe, of Ohio',
                  'Hon. Eleanor Smith, of Texas', 'Jaime Herrera Beutler, Director, Office of Things: Testimony']
QUESTION_BEFORE = [occurrence('mods:witness[2]', 'Eleanor Smith', 'of Texas'),
                   occurrence('mods:witness[3]', 'Jaime Herrera Beutler', 'Director', 'Office of Things: Testimony')]
QUESTION_AFTER = [typed(occurrence('mods:witness[1]', 'Richard Roe', 'of Ohio'), 'record_material'),
                  typed(QUESTION_BEFORE[0], 'record_material'), QUESTION_BEFORE[1]]


def test_a_restored_heading_and_its_typed_asker_pass(tmp_path):
    write(tmp_path, before=QUESTION_BEFORE, after=QUESTION_AFTER, lines=QUESTION_LINES)
    code, out = run(tmp_path)
    assert code == 0 and [i['locator'] for i in out['restored']] == ['mods:witness[1]']
    assert out['counts']['typed'] == 1


def test_an_asker_left_a_witness_and_a_witness_typed_as_an_asker_fail(tmp_path):
    write(tmp_path, before=QUESTION_BEFORE, after=QUESTION_BEFORE, lines=QUESTION_LINES)
    code, out = run(tmp_path)
    assert code == 1 and out['failed'] == {'question_asker_as_witness': 1}
    assert [i['locator'] for i in out['question_asker_as_witness']] == ['mods:witness[2]']
    (tmp_path / 'raw').rename(tmp_path / 'raw-old')
    write(tmp_path, before=QUESTION_BEFORE, after=[*QUESTION_AFTER[:2], typed(QUESTION_BEFORE[1], 'record_material')],
          lines=QUESTION_LINES)
    code, out = run(tmp_path)
    assert code == 1 and out['failed'] == {'type_unsupported': 1}


def test_a_planted_asker_left_a_witness_is_flagged(tmp_path):
    write(tmp_path, before=QUESTION_BEFORE, after=QUESTION_AFTER, lines=QUESTION_LINES)
    code, out = run(tmp_path, '--plant', 'asker-as-witness')
    assert code == 1 and out['planted']['flagged'] and out['planted']['locator'] == 'mods:witness[2]'
    assert out['failed'] == {'question_asker_as_witness': 1}
