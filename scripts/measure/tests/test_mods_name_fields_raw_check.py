"""The MODS name-fields raw check passes a faithful re-read and flags each planted wrong value, in both directions."""
import gzip
import hashlib
import importlib.util
from datetime import date
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


def write(tmp_path, before=BEFORE, after=AFTER, lines=LINES, members=(), table=(), prints=(), people=()):
    """One print (DIGEST) of the 118th Congress, an unreadable body, and `prints` more as (digest, lines, members,
    before, after); `table` names the Members serving in the 118th by the members table."""
    for digest, print_lines, print_members, _, _ in ((DIGEST, lines, members, None, None), *prints):
        body = ('<mods xmlns="http://www.loc.gov/mods/v3"><extension><congress>118</congress>'
                + ''.join(f'<witness>{line}</witness>' for line in print_lines)
                + ''.join(f'<congMember role="COMMMEMBER"><name type="authority-lnf">{m}</name></congMember>'
                          for m in print_members)
                + '</extension></mods>').encode()
        (tmp_path / 'raw' / digest[:2]).mkdir(parents=True, exist_ok=True)
        (tmp_path / 'raw' / digest[:2] / f'{digest}.gz').write_bytes(gzip.compress(body))
    for side, appearances in ((3, before), (4, after)):
        rows = [dict(source='mods', record_sha=bytes.fromhex(DIGEST), package_id='CHRG-1', appearances=appearances),
                dict(source='mods', record_sha=bytes.fromhex('cd' * 32), package_id='CHRG-2', appearances=[])]
        rows += [dict(source='mods', record_sha=bytes.fromhex(p[0]), package_id=f'CHRG-{p[0][:2]}', appearances=p[side])
                 for p in prints]
        pq.write_table(pa.Table.from_pylist(rows), tmp_path / f"{'before' if side == 3 else 'after'}.parquet")
    term = dict(chamber='house', state='OH', district=1, party='I', start=date(2023, 1, 3), end=date(2025, 1, 3))
    old = dict(term, start=date(1993, 1, 5), end=date(1995, 1, 3))
    pq.write_table(pa.Table.from_pylist([dict(bioguide_id='X', name='Nobody Here', terms=[old])]
                                        + [dict(bioguide_id=f'T{i}', name=n, terms=[term]) for i, n in enumerate(table)]),
                   tmp_path / 'members.parquet')
    people = [dict(source=s, name=n) for s in ('congress_gov', 'house_xml')
              for n in ('Richard Roe', 'Eleanor Smith', 'Hon. Jaime Herrera Beutler', *people)]
    people.append(dict(source='mods', name='American Legion'))  # MODS names never teach a name
    pq.write_table(pa.Table.from_pylist(people), tmp_path / 'people.parquet')


def run(tmp_path, *extra):
    args = ['--before', str(tmp_path / 'before.parquet'), '--after', str(tmp_path / 'after.parquet'),
            '--raw-root', str(tmp_path / 'raw'), '--people', str(tmp_path / 'people.parquet'),
            '--members', str(tmp_path / 'members.parquet'), '--output', str(tmp_path / 'out.json'), *extra]
    code = check.main(args)
    return code, json.loads((tmp_path / 'out.json').read_text())


def test_a_faithful_reread_passes_and_names_the_unreadable_body(tmp_path):
    write(tmp_path)
    code, out = run(tmp_path)
    assert code == 0 and out['status'] == 'passed'
    assert out['counts'] == {'bodies': 2, 'occurrences': 4, 'changed': 3, 'no_name': 1, 'name_read': 1, 'reordered': 1}
    assert [i['body'] for i in out['not_read']] == ['cd' * 32]


@pytest.mark.parametrize('kind, flags, locator, planted', [
    # The name moved into the organization also leaves the organization stopping inside its segment.
    ('person-moved', {'person_moved': 1, 'text_cut': 1}, 'mods:witness[3]', None),
    ('reversed-name', {'reorder_unsupported': 1, 'name_not_person': 1}, 'mods:witness[4]', 'Beutler Jaime Herrera'),
    # The organization before the person read as the name: it also loses the person's words.
    ('previous-segment', {'name_not_person': 1, 'words_lost': 1}, 'mods:witness[2]', 'Vietnam Veterans of America'),
])
def test_each_planted_wrong_value_is_flagged(tmp_path, kind, flags, locator, planted):
    write(tmp_path)
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted'][0]['flagged'] and out['planted'][0]['planted'] == planted
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


def signed(locator, flag, after, line, reviewed_by='a reviewer'):
    """An accept as a person writes it: the values and the raw line they read, a reason, and who read it."""
    return dict(body=DIGEST, locator=locator, flag=flag, after=after, reason='read', reviewed_by=reviewed_by,
                line_sha256=hashlib.sha256(line.strip().encode()).hexdigest())


def test_a_reviewed_flag_is_accepted_and_an_accept_the_run_no_longer_flags_fails(tmp_path):
    left = occurrence('mods:witness[2]', None, None, 'Vietnam Veterans of America, Richard F. Weidman')
    write(tmp_path, after=[AFTER[0], left, *AFTER[2:]])
    accept = [signed('mods:witness[2]', flag, fields(left), LINES[1])
              for flag in ('words_lost', 'person_left_in_organization', 'text_cut')]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 0 and [(i['locator'], i['flag']) for i in out['accepted']] == [
        ('mods:witness[2]', 'words_lost'), ('mods:witness[2]', 'person_left_in_organization'),
        ('mods:witness[2]', 'text_cut')]
    stale = accept + [signed('mods:witness[1]', 'person_moved', fields(AFTER[0]), LINES[0])]
    (tmp_path / 'accept.json').write_text(json.dumps(stale))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 1 and out['failed'] == {'stale_accept': 1}


def test_an_accept_covers_only_the_value_read(tmp_path):
    """A later wrong value under the same flag and occurrence is not covered by an earlier accept."""
    after = [*AFTER[:3], occurrence('mods:witness[4]', 'Washington', WASHINGTON)]
    write(tmp_path, after=after)
    accept = [signed('mods:witness[4]', 'name_not_person', fields(AFTER[3]), LINES[3])]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    # The wrong name also leaves the position printed before any word of it.
    assert code == 1 and out['failed'] == {'name_not_person': 1, 'words_lost': 1, 'stale_accept': 1,
                                           'position_not_in_line': 1}


@pytest.mark.parametrize('dropped', ['position', 'organization'])
def test_an_accepted_lost_word_does_not_cover_a_dropped_position_or_organization(tmp_path, dropped):
    """Same name, same flag: dropping a whole position or organization on an accepted row still fails."""
    read = occurrence('mods:witness[2]', 'Richard F. Weidman', 'Director for Policy', 'Vietnam Veterans of America')
    write(tmp_path, after=[AFTER[0], read, *AFTER[2:]])
    accept = [signed('mods:witness[2]', 'words_lost', fields(read), LINES[1])]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 0 and [i['flag'] for i in out['accepted']] == ['words_lost']
    dropped_row = dict(read, **{dropped: None})
    (tmp_path / 'raw').rename(tmp_path / 'raw-old')  # write() lays the raw body out afresh
    write(tmp_path, after=[AFTER[0], dropped_row, *AFTER[2:]])
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 1 and out['failed'] == {'words_lost': 1, 'stale_accept': 1}


# ct-79j1 and ct-3aap: a joined line read as two people, and organizations' own documents typed as statements.
RECORD_LINES = ['Eleanor Smith, Chair, Rural Committee.. Richard Roe, Superintendent, School District',
                'Paralyzed Veterans of America, statement', 'Blinded Veterans Association, New York, Inc']


def typed(item, witness_type):
    return dict(item, witness_type=witness_type)


RECORD_BEFORE = [occurrence('mods:witness[1]', 'Eleanor Smith', 'Chair', 'Rural Committee.. Richard Roe, Superintendent, School District'),
                 typed(occurrence('mods:witness[2]', None, None, RECORD_LINES[1]), None),
                 typed(occurrence('mods:witness[3]', None, None, RECORD_LINES[2]), None)]
RECORD_AFTER = [occurrence('mods:witness[1]', 'Eleanor Smith', 'Chair', 'Rural Committee'),
                occurrence('mods:witness[1]/part[2]', 'Richard Roe', 'Superintendent', 'School District'),
                typed(RECORD_BEFORE[1], 'statement_for_record'), RECORD_BEFORE[2]]


def test_a_split_that_moves_the_second_persons_words_and_a_typed_document_pass(tmp_path):
    write(tmp_path, before=RECORD_BEFORE, after=RECORD_AFTER, lines=RECORD_LINES)
    code, out = run(tmp_path)
    assert code == 0 and out['status'] == 'passed'
    assert [i['locator'] for i in out['split']] == ['mods:witness[1]/part[2]']
    assert out['counts']['typed'] == 1 and not out['words_lost'] and not out['record_as_witness']


@pytest.mark.parametrize('kind, flag, locator', [
    ('split-untrimmed', 'split_unsupported', 'mods:witness[1]/part[2]'),
    ('typed-organization', 'type_unsupported', 'mods:witness[3]'),
])
def test_each_planted_split_or_type_is_flagged(tmp_path, kind, flag, locator):
    write(tmp_path, before=RECORD_BEFORE, after=RECORD_AFTER, lines=RECORD_LINES)
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted'][0]['flagged'] and out['failed'] == {flag: 1}
    assert [i['locator'] for i in out[flag]] == [locator]


def test_an_added_row_that_is_not_a_split_a_person_typed_and_a_statement_left_a_witness_are_seen(tmp_path):
    after = [typed(RECORD_AFTER[0], 'statement_for_record'), dict(RECORD_AFTER[1], source_locator='mods:witness[4]'),
             RECORD_BEFORE[1], RECORD_AFTER[3]]
    write(tmp_path, before=RECORD_BEFORE, after=after, lines=RECORD_LINES)
    code, out = run(tmp_path)
    # The moved row's line prints nothing, so its name and its position are in no line either.
    assert code == 1 and out['failed'] == {'added': 1, 'name_not_in_line': 1, 'type_unsupported': 1, 'words_lost': 1,
                                           'record_as_witness': 1, 'position_not_in_line': 1}
    assert [i['locator'] for i in out['record_as_witness']] == ['mods:witness[2]']


def test_an_accept_is_bound_to_the_type(tmp_path):
    """An accept read on one witness_type does not cover another."""
    after = [*RECORD_AFTER[:3], typed(RECORD_BEFORE[2], 'statement_for_record')]
    write(tmp_path, before=RECORD_BEFORE, after=after, lines=RECORD_LINES)
    read = {f: after[3].get(f) for f in check.KEYED}
    accept = [signed('mods:witness[3]', 'type_unsupported', read, RECORD_LINES[2])]
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
    # The heading's row is a Member the asking line prints in the House style, in order: an asker.
    assert code == 0 and [i['locator'] for i in out['asker']] == ['mods:witness[1]'] and not out['restored']
    assert out['counts']['typed'] == 1


def test_an_asker_left_a_witness_and_a_witness_typed_as_an_asker_fail(tmp_path):
    write(tmp_path, before=QUESTION_BEFORE, after=QUESTION_BEFORE, lines=QUESTION_LINES)
    code, out = run(tmp_path)
    # The heading that names Richard Roe publishes no row on either side, so no one shows him (member_unnamed).
    assert code == 1 and out['failed'] == {'question_asker_as_witness': 1, 'member_unnamed': 1}
    assert [i['locator'] for i in out['question_asker_as_witness']] == ['mods:witness[2]']
    assert [(i['locator'], i['words']) for i in out['member_unnamed']] == [('mods:witness[1]', ['richard', 'roe'])]
    (tmp_path / 'raw').rename(tmp_path / 'raw-old')
    write(tmp_path, before=QUESTION_BEFORE, after=[*QUESTION_AFTER[:2], typed(QUESTION_BEFORE[1], 'record_material')],
          lines=QUESTION_LINES)
    code, out = run(tmp_path)
    assert code == 1 and out['failed'] == {'type_unsupported': 1}


def test_a_planted_asker_left_a_witness_is_flagged(tmp_path):
    write(tmp_path, before=QUESTION_BEFORE, after=QUESTION_AFTER, lines=QUESTION_LINES)
    code, out = run(tmp_path, '--plant', 'asker-as-witness')
    assert code == 1 and out['planted'][0]['flagged'] and out['planted'][0]['locator'] == 'mods:witness[2]'
    assert out['failed'] == {'question_asker_as_witness': 1}


def test_an_unsigned_accept_or_one_read_on_another_line_covers_nothing(tmp_path):
    """An accept counts only once a reviewer has signed it, on the raw line they read; one generated without a
    reviewer, or whose line digest is another line's, leaves the flag failing."""
    left = occurrence('mods:witness[2]', None, None, 'Vietnam Veterans of America, Richard F. Weidman')
    write(tmp_path, after=[AFTER[0], left, *AFTER[2:]])
    accept = [signed('mods:witness[2]', 'words_lost', fields(left), LINES[1], reviewed_by=None),
              signed('mods:witness[2]', 'person_left_in_organization', fields(left), LINES[0])]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    # An organization reading that stops inside its segment also cuts the line's text short.
    assert code == 1 and out['failed'] == {'words_lost': 1, 'person_left_in_organization': 1, 'stale_accept': 1,
                                           'text_cut': 1}
    assert [a['flag'] for a in out['unsigned_accept']] == ['words_lost'] and not out['accepted']


# Round 2 (ct-zs48, ct-3aap review): every Member a question line names has a row; a restored heading names a
# person; a committee title is not a name; a document's title or an organization's statement left a witness fails.
ASKER_LINES = ['Questions and Answers (Post-Hearing) from: Chairman Richard Roe.......... 36,',
               'Hon. Eleanor Smith.............. 22,32 Hon. Jaime Herrera Beutler',
               'Responses to questions for the record from the following Representatives: Hon. Eleanor Smith, of Texas',
               'Senators Roe and Lautenberg........81,']
# The chairman is a Member by the members table (the print's list names Lautenberg alone).
ASKER_PRINT = dict(lines=ASKER_LINES, members=['Lautenberg, Frank R.'], table=['Richard Roe'])
ASKER_BEFORE = [typed(occurrence('mods:witness[1]', 'Richard Roe'), 'record_material'),
                typed(occurrence('mods:witness[2]', 'Eleanor Smith', 'Hon. Jaime Herrera Beutler'), 'record_material'),
                typed(occurrence('mods:witness[4]', 'Roe'), 'record_material'),
                typed(occurrence('mods:witness[4]/part[2]', 'Lautenberg'), 'record_material')]
ASKER_AFTER = [ASKER_BEFORE[0], typed(occurrence('mods:witness[2]', 'Eleanor Smith'), 'record_material'),
               typed(occurrence('mods:witness[2]/part[2]', 'Jaime Herrera Beutler'), 'record_material'),
               typed(occurrence('mods:witness[3]', 'Eleanor Smith', 'of Texas'), 'record_material'), *ASKER_BEFORE[2:]]


def test_a_faithful_reading_of_several_askers_passes(tmp_path):
    write(tmp_path, before=ASKER_BEFORE, after=ASKER_AFTER, **ASKER_PRINT)
    code, out = run(tmp_path)
    assert code == 0 and out['status'] == 'passed'
    assert [i['locator'] for i in out['split']] == ['mods:witness[2]/part[2]']
    assert [i['locator'] for i in out['asker']] == ['mods:witness[3]']


@pytest.mark.parametrize('kind, flag, locator, missing', [
    # (a) One of two Members a line names as askers dropped (the last further part: Lautenberg).
    ('asker-dropped', 'member_unnamed', 'mods:witness[4]', ['lautenberg']),
    # (d) A restored heading named for its own words (no longer restored), or emptied of its asker.
    ('heading-as-name', 'added', 'mods:witness[3]', None),
    ('name-emptied', 'member_unnamed', 'mods:witness[3]', ['eleanor', 'smith']),
    # (e) The segment before "Chairman Richard Roe" read as the name.
    ('committee-segment', 'name_not_person', 'mods:witness[1]', None),
])
def test_each_planted_asker_value_is_flagged(tmp_path, kind, flag, locator, missing):
    write(tmp_path, before=ASKER_BEFORE, after=ASKER_AFTER, **ASKER_PRINT)
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted'][0]['flagged'] and out['planted'][0]['locator'] == locator
    assert [i['locator'] for i in out[flag]] == [locator]
    if missing:
        assert out[flag][0]['words'] == missing


def test_a_member_named_only_by_the_prints_own_members_list_is_counted(tmp_path):
    """The <congMember> half of member_unnamed sees a Member the line prints without a title."""
    lines = [*ASKER_LINES[:3], 'Roe and Lautenberg........81,']
    after = [*ASKER_AFTER[:4], typed(occurrence('mods:witness[4]', 'Roe'), 'record_material')]
    write(tmp_path, before=ASKER_BEFORE[:3], after=after, **dict(ASKER_PRINT, lines=lines))
    code, out = run(tmp_path)
    assert [(i['locator'], i['words']) for i in out['member_unnamed']] == [('mods:witness[4]', ['lautenberg'])]


TITLE_LINES = ['Association of American Railroads, "AAR Calls for Safety"', 'Paralyzed Veterans of America, statement',
               'Blinded Veterans Association, New York, Inc']
TITLE_BEFORE = [typed(occurrence(f'mods:witness[{n}]', None, None, line), None) for n, line in enumerate(TITLE_LINES, 1)]
TITLE_AFTER = [typed(TITLE_BEFORE[0], 'record_material'), typed(TITLE_BEFORE[1], 'statement_for_record'), TITLE_BEFORE[2]]


@pytest.mark.parametrize('kind, locator', [('title-as-witness', 'mods:witness[1]'), ('statement-as-witness', 'mods:witness[2]')])
def test_a_planted_title_or_statement_left_a_witness_is_flagged(tmp_path, kind, locator):
    """(b, c) A document's title (quoted) or an organization's statement typed a witness fails; an organization alone
    that testified ("Blinded Veterans Association, New York, Inc") stays a witness."""
    write(tmp_path, before=TITLE_BEFORE, after=TITLE_AFTER, lines=TITLE_LINES)
    code, out = run(tmp_path)
    assert not out['record_as_witness']
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted'][0]['flagged'] and [i['locator'] for i in out['record_as_witness']] == [locator]


# Round 3 (owner decisions 2026-11-10): one asker rule keyed on Member identity. The check reads asking lines by their
# words and counts Members as words (the print's <congMember> families, words after a chamber title, a House-styled
# "Hon." name), never by splitting a list.
NEW_LINES = ['Hon. Eleanor Holmes Norton, a Delegate in Congress from the District of Columbia',
             'Response to request arising during the hearing by: Hon. Richard Roe.......... 13,14 Hon. Eleanor Smith',
             'Responses to additional questions from: Senators Roe and Lautenberg.....81,',
             'Herrera Beutler, Hon. Jaime, Commissioner, Office of Things.......... Responses to additional questions '
             'from: Senator Lautenberg']
NEW_MEMBERS = ['Roe, Richard', 'Smith, Eleanor', 'Lautenberg, Frank R.']
NEW_BEFORE = [occurrence('mods:witness[1]', 'Eleanor Holmes Norton', DELEGATE),
              occurrence('mods:witness[4]', 'Jaime Herrera Beutler', 'Commissioner', 'Office of Things')]


def asked(locator, name, order, kind='record_material', **more):
    return dict(occurrence(locator, name, **more), witness_type=kind, display_order=order)


NEW_AFTER = [dict(NEW_BEFORE[0], witness_type=None, display_order=1),
             asked('mods:witness[2]', 'Richard Roe', 2), asked('mods:witness[2]/part[2]', 'Eleanor Smith', 3),
             asked('mods:witness[3]', 'Roe', 4), asked('mods:witness[3]/part[2]', 'Lautenberg', 5),
             dict(NEW_BEFORE[1], witness_type=None, display_order=6), asked('mods:witness[4]/part[2]', 'Lautenberg', 7)]


def test_askers_on_asking_lines_pass_and_a_witness_beside_them_keeps_its_row(tmp_path):
    """Each Member a request heading, a list of Senators or a witness's line names as an asker is a supported asker;
    the witness whose entry carries the heading (a person who is not one of the line's Members) stays a witness, and
    a Member Day line with no heading asks nothing."""
    write(tmp_path, before=NEW_BEFORE, after=NEW_AFTER, lines=NEW_LINES, members=NEW_MEMBERS)
    code, out = run(tmp_path)
    assert code == 0 and out['status'] == 'passed'
    assert [i['locator'] for i in out['asker']] == [
        'mods:witness[2]', 'mods:witness[2]/part[2]', 'mods:witness[3]', 'mods:witness[3]/part[2]',
        'mods:witness[4]/part[2]']


def test_the_review_lines_published_as_one_witness_fail(tmp_path):
    """Review round 2: a request heading naming two Members published as one witness named for the heading, a list of
    Senators published as a witness named "Senators Roe", and a heading in capitals published as a witness."""
    lines = [NEW_LINES[1], 'Senators Roe, Smith, and Lautenberg', 'QUESTIONS FROM HON. RICHARD ROE, HON. ELEANOR SMITH']
    rows = [asked('mods:witness[1]', 'Response to request arising during the hearing by: Hon. Richard Roe', 1, None),
            asked('mods:witness[2]', 'Senators Roe', 2, None, position='Smith'),
            asked('mods:witness[3]', 'QUESTIONS FROM HON. RICHARD ROE', 3, None)]
    write(tmp_path, before=rows, after=rows, lines=lines, members=NEW_MEMBERS)
    code, out = run(tmp_path)
    assert code == 1 and out['failed'] == {'question_asker_as_witness': 3, 'member_unnamed': 3}
    assert [(i['locator'], i['words']) for i in out['member_unnamed']] == [
        ('mods:witness[1]', ['eleanor', 'smith']), ('mods:witness[2]', ['lautenberg', 'smith']),
        ('mods:witness[3]', ['eleanor', 'smith'])]


@pytest.mark.parametrize('kind, flag, locator, planted', [
    # Review round 2's missed plant K3: a new asker written surname first.
    ('reversed-asker', 'reorder_unsupported', 'mods:witness[2]', 'Roe Richard'),
    # H1: two askers of one line exchange their names (display order no longer follows the print).
    ('askers-swapped', 'order_unsupported', 'mods:witness[2]/part[2]', 'Richard Roe'),
    # W1, W2: a real witness printed with "Hon." on a line that asks nothing, typed as an asker.
    ('witness-as-asker', 'type_unsupported', 'mods:witness[1]', 'record_material'),
    # L1, L3: a line's askers put back as one witness named for the heading.
    ('heading-reverted', 'question_asker_as_witness', 'mods:witness[2]',
     'Response to request arising during the hearing by: Hon. Richard Roe'),
    # G1, G3, G5: an asker named by surname alone given a first name the line does not print.
    ('given-added', 'name_not_in_line', 'mods:witness[3]', 'Bill Roe'),
])
def test_each_planted_asker_value_is_flagged_without_an_accept(tmp_path, kind, flag, locator, planted):
    lines = [*NEW_LINES[:3], 'Herrera Beutler, Hon. Jaime, Commissioner, Office of Things']
    write(tmp_path, before=NEW_BEFORE, after=NEW_AFTER[:6], lines=lines, members=NEW_MEMBERS)
    code, out = run(tmp_path)
    assert code == 0, out['failed']
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted'][0]['flagged'] and out['planted'][0]['planted'] == planted
    assert locator in [i['locator'] for i in out[flag]]


def test_a_witness_typed_as_an_asker_on_an_asking_line_fails(tmp_path):
    """F1 (Hilton Kelley): the person whose entry carries a question heading is no asker; typed record material, it
    fails on content (record material on an asking line must be nameless, a Member's, or on a line of names)."""
    after = [*NEW_AFTER[:5], dict(NEW_AFTER[5], witness_type='record_material'), NEW_AFTER[6]]
    write(tmp_path, before=NEW_BEFORE, after=after, lines=NEW_LINES, members=NEW_MEMBERS)
    code, out = run(tmp_path)
    assert code == 1 and out['failed'] == {'type_unsupported': 1}
    assert [i['locator'] for i in out['type_unsupported']] == ['mods:witness[4]']


# Round 4 (owner decisions 2026-11-10 on the third review): answerers beside askers, Members counted a second time from
# the members table, Members merged into one row, a position the line does not print, and display order across lines.
ROUND4_LINES = ['Hon. Jane Doe, a Representative in Congress from the State of Ohio',
                'Response to request arising during the hearing by: Hon. Richard Roe....... 13 Hon. Joe Doe',
                'Questions from Senator Frank Lautenberg to Jaime Herrera Beutler and Dr. Moe',
                'Kerr, Mark, Director, Office of Things', 'Moe, Dr. Anne, Professor, College of Things',
                'Poe, Edgar, Director, Office of Ravens']
ROUND4_BEFORE = [asked('mods:witness[1]', 'Jane Doe', 1, None, position='a Representative in Congress from the State of Ohio'),
                 asked('mods:witness[4]', 'Mark Kerr', 7, None, position='Director', organization='Office of Things'),
                 asked('mods:witness[5]', 'Anne Moe', 8, None, position='Professor', organization='College of Things'),
                 asked('mods:witness[6]', 'Edgar Poe', 9, None, position='Director', organization='Office of Ravens')]
ROUND4_AFTER = [ROUND4_BEFORE[0], asked('mods:witness[2]', 'Richard Roe', 2), asked('mods:witness[2]/part[2]', 'Joe Doe', 3),
                asked('mods:witness[3]', 'Frank Lautenberg', 4),
                # Herrera Beutler answered only in writing (no line of hers asks nothing): a statement for the record.
                asked('mods:witness[3]/part[2]', 'Jaime Herrera Beutler', 5, 'statement_for_record'),
                asked('mods:witness[3]/part[3]', 'Moe', 6, None), *ROUND4_BEFORE[1:]]
# Joe Doe, Jane Doe and Frank Lautenberg serve in the 118th by the members table; the print's <congMember> list
# names Roe.
ROUND4_TABLE = ['Richard Roe', 'Joe Doe', 'Frank Lautenberg', 'Jane Doe']


def round4(tmp_path, after=ROUND4_AFTER, table=ROUND4_TABLE, **more):
    write(tmp_path, before=ROUND4_BEFORE, after=after, lines=ROUND4_LINES, members=['Roe, Richard'], table=table, **more)


def test_answerers_beside_askers_and_members_the_list_omits_pass(tmp_path):
    """An answerer on an asking line, a person who is not one of its Members, is listed beside the askers ("Dr. Moe"
    by the civil title, Herrera Beutler by two printed words); Joe Doe, whom the print's list omits, is an asker by the
    members table."""
    round4(tmp_path)
    code, out = run(tmp_path)
    assert code == 0, out['failed']
    assert [i['locator'] for i in out['answerer']] == ['mods:witness[3]/part[2]', 'mods:witness[3]/part[3]']
    assert [i['locator'] for i in out['asker']] == ['mods:witness[2]', 'mods:witness[2]/part[2]', 'mods:witness[3]']


@pytest.mark.parametrize('row, flag', [
    # The reviewer's "roster-gap-reverted": a Member the print's list omits, left a witness.
    (asked('mods:witness[2]/part[2]', 'Joe Doe', 3, None), 'question_asker_as_witness'),
    # ... or left as a member's statement, as the published generation typed some askers.
    (asked('mods:witness[2]/part[2]', 'Joe Doe', 3, 'member_statement'), 'question_asker_as_witness'),
    # The reviewer's "merged": two Members in one row.
    (asked('mods:witness[2]/part[2]', 'Richard Roe and Joe Doe', 3), 'members_merged'),
])
def test_members_the_list_omits_and_merged_members_are_seen(tmp_path, row, flag):
    """Only the members table counts Joe Doe (the print's list names Roe alone, and "Hon." is any official's): with a
    table that names no one serving, the flag is not raised."""
    after = [*ROUND4_AFTER[:2], row, *ROUND4_AFTER[3:]]
    round4(tmp_path, after=after)
    code, out = run(tmp_path)
    assert code == 1 and [i['locator'] for i in out[flag]] == [row['source_locator']]
    (tmp_path / 'raw').rename(tmp_path / 'raw-old')
    round4(tmp_path, after=after, table=())
    code, out = run(tmp_path)
    assert not out[flag]


def test_a_position_the_line_does_not_print_and_order_across_lines_fail(tmp_path):
    """The reviewer's "wrong-chamber" and "rotate-across-lines", written by hand."""
    after = [dict(ROUND4_AFTER[0], position='a Senator in Congress from the State of Ohio'), *ROUND4_AFTER[1:7],
             dict(ROUND4_AFTER[7], display_order=9), dict(ROUND4_AFTER[8], display_order=8)]
    round4(tmp_path, after=after)
    code, out = run(tmp_path)
    assert code == 1 and out['failed'] == {'position_not_in_line': 1, 'order_across_lines': 1}
    assert [i['locator'] for i in out['position_not_in_line']] == ['mods:witness[1]']
    assert [i['locator'] for i in out['order_across_lines']] == ['mods:witness[6]']


def test_the_plants_run_together_each_on_its_own_print(tmp_path):
    """Plants for each blind spot the third review found, batched in one run, each on its own print, each flagged."""
    kinds = ['members-merged', 'wrong-chamber', 'rotate-across-lines', 'roster-gap-reverted', 'roster-gap-dropped']
    prints = [(f'{n:02x}' * 32, ROUND4_LINES, ['Roe, Richard'], ROUND4_BEFORE, ROUND4_AFTER) for n in range(1, len(kinds))]
    round4(tmp_path, prints=prints)
    code, out = run(tmp_path)
    assert code == 0, out['failed']
    code, out = run(tmp_path, '--plant', *kinds)
    assert code == 1 and [p['kind'] for p in out['planted']] == kinds
    assert len({p['body'] for p in out['planted']}) == len(kinds) and all(p['flagged'] for p in out['planted'])
    assert {p['kind']: p['locator'] for p in out['planted']} == {
        'members-merged': 'mods:witness[2]', 'wrong-chamber': 'mods:witness[1]', 'rotate-across-lines': 'mods:witness[5]',
        'roster-gap-reverted': 'mods:witness[3]', 'roster-gap-dropped': 'mods:witness[2]'}
    code, out = run(tmp_path, '--plant', 'split-untrimmed')
    assert out['planted'] == [dict(kind='split-untrimmed', body=None, locator=None, name=None, planted=None, flagged=None)]


# Round 5 (the fourth review): record material on an asking line whether or not its type changed, an added answerer's
# type, a document's text cut short, a position taken from another row, the reading change's own lost words, and a
# Member's submission.
ROUND5_LINES = ['Kulick, John D., Chair, Standards Board',
                'Questions submitted by Senator Klobuchar for John D. Kulick, Ph.D',
                'Report, Arsenic and Old Laws, NRDC..........267-285 Responses to additional questions from: Senator Crapo',
                'Accompanied By:.............. Svinicki, Hon. Kristine L., Commissioner Responses to additional questions '
                'from Senator Boxer',
                'Courtney, Hon. Joe, a Representative in Congress from the State of Connecticut: Hartford Courant article: '
                'Coffeehouse opens',
                # Transcript prose naming a person and a Member: no entry, no one missing from it.
                'years ago, Richard Roe said 199 staffers had clearances. In 2018, when Senator Klobuchar checked, there '
                'were 35',
                'Questions from Senator Klobuchar to Dr. Rue', 'Rue, Dr. Penny, Vice President for Campus Life']
ROUND5_MEMBERS = ['Klobuchar, Amy', 'Crapo, Mike', 'Boxer, Barbara']
KULICK = asked('mods:witness[1]', 'John D. Kulick', 1, None, position='Chair', organization='Standards Board')
RUE = asked('mods:witness[8]', 'Penny Rue', 13, None, position='Vice President for Campus Life')
ROUND5_BEFORE = [KULICK, asked('mods:witness[2]', None, 2, 'record_material'),
                 asked('mods:witness[3]', 'Arsenic and Old Laws Report', 4, None),
                 asked('mods:witness[4]', 'Accompanied By:', 6, None, position='Svinicki',
                       organization='Hon. Kristine L., Commissioner Responses to additional questions from Senator Boxer'),
                 asked('mods:witness[5]', 'Joe Courtney', 8, None,
                       position='a Representative in Congress from the State of Connecticut: Hartford Courant article: '
                                'Coffeehouse opens'),
                 asked('mods:witness[6]', 'years ago', 9, None,
                       position='Richard Roe said 199 staffers had clearances. In 2018'), RUE]
ROUND5_AFTER = [KULICK, asked('mods:witness[2]', 'John D. Kulick', 3, None),
                asked('mods:witness[2]/part[2]', 'Klobuchar', 2),
                asked('mods:witness[3]', None, 4, organization='Report, Arsenic and Old Laws, NRDC'),
                asked('mods:witness[3]/part[2]', 'Crapo', 5),
                asked('mods:witness[4]', 'Kristine L. Svinicki', 6, None, position='Commissioner'),
                asked('mods:witness[4]/part[2]', 'Boxer', 7),
                dict(ROUND5_BEFORE[4], witness_type='member_statement'),
                asked('mods:witness[6]', None, 9), asked('mods:witness[7]', 'Klobuchar', 10),
                asked('mods:witness[7]/part[2]', 'Rue', 11, None), RUE]


def round5(tmp_path, after=ROUND5_AFTER, **more):
    write(tmp_path, before=ROUND5_BEFORE, after=after, lines=ROUND5_LINES, members=ROUND5_MEMBERS,
          people=('Kristine Svinicki', 'John Kulick'), **more)


def test_the_reading_changes_own_losses_pass_by_content_and_a_typed_answerer_is_judged(tmp_path):
    """The document's text, "Accompanied By:" and a prose fragment shed, a Member's article typed a member's statement,
    the answerer Rue listed, and the answerer Kulick, who testified (line 1), typed a witness where the published row
    was nameless record material (round 6: an answerer who testified is a witness): all pass."""
    round5(tmp_path)
    code, out = run(tmp_path)
    assert code == 0, out['failed']
    assert [i['locator'] for i in out['answerer']] == ['mods:witness[7]/part[2]']
    after = [ROUND5_AFTER[0], dict(ROUND5_AFTER[1], witness_type='record_material'), *ROUND5_AFTER[2:]]
    (tmp_path / 'raw').rename(tmp_path / 'raw-old')
    round5(tmp_path, after=after)
    code, out = run(tmp_path)
    # The fourth review's missed plant P2a: the same answerer typed record material, the published row's own type.
    assert [(i['locator'], i['after']['witness_type']) for i in out['type_unsupported']] == [
        ('mods:witness[2]', 'record_material')]


def test_the_round5_plants_run_together_each_flagged(tmp_path):
    kinds = ['answerer-mistyped', 'document-cut', 'position-from-other-row']
    prints = [(f'{n:02x}' * 32, ROUND5_LINES, ROUND5_MEMBERS, ROUND5_BEFORE, ROUND5_AFTER) for n in range(1, len(kinds))]
    round5(tmp_path, prints=prints)
    code, out = run(tmp_path, '--plant', *kinds)
    assert [p['kind'] for p in out['planted']] == kinds and all(p['flagged'] for p in out['planted'])
    assert {p['kind']: (p['locator'], p['planted']) for p in out['planted']} == {
        'answerer-mistyped': ('mods:witness[7]/part[2]', 'statement_for_record'),
        'document-cut': ('mods:witness[3]', 'Report, Arsenic and Old Laws'),
        'position-from-other-row': ('mods:witness[4]/part[2]', 'Commissioner')}


# Round 6 (owner decisions 2026-11-10): an answerer is a witness when they testified, a statement for the record when
# they answered only in writing; a Senator's prepared statement is a member's statement.
ROUND6_LINES = ['Avalos, Hon. Edward M., Under Secretary, Marketing and Regulatory Programs',
                'Submitted questions: Avalos, Hon. Edward M', 'Submitted questions: Ramaswamy, Ph.D., Sonny',
                'Thomas, Hon. Craig, a U.S. Senator from the State of Wyoming, prepared statement']
ROUND6_BEFORE = [asked('mods:witness[1]', 'Edward M. Avalos', 1, None, position='Under Secretary',
                       organization='Marketing and Regulatory Programs'),
                 asked('mods:witness[2]', 'Edward M Avalos', 2), asked('mods:witness[3]', 'Sonny Ramaswamy', 3, None),
                 asked('mods:witness[4]', 'Craig Thomas', 4, None, position='a U.S. Senator from the State of Wyoming')]
ROUND6_AFTER = [ROUND6_BEFORE[0], dict(ROUND6_BEFORE[1], witness_type=None),
                dict(ROUND6_BEFORE[2], witness_type='statement_for_record'),
                dict(ROUND6_BEFORE[3], witness_type='member_statement')]


@pytest.mark.parametrize('before, after, flagged', [
    (ROUND6_BEFORE, ROUND6_AFTER, []),
    # A Senator's statement typed a statement for the record before is a member's statement now.
    ([*ROUND6_BEFORE[:3], dict(ROUND6_BEFORE[3], witness_type='statement_for_record')], ROUND6_AFTER, []),
    # Avalos testified (line 1): a statement for the record is wrong for him.
    (ROUND6_BEFORE, [ROUND6_AFTER[0], dict(ROUND6_AFTER[1], witness_type='statement_for_record'), *ROUND6_AFTER[2:]],
     ['mods:witness[2]']),
    # Ramaswamy did not: a witness typed from record material is wrong for him.
    ([*ROUND6_BEFORE[:2], dict(ROUND6_BEFORE[2], witness_type='record_material'), ROUND6_BEFORE[3]],
     [*ROUND6_AFTER[:2], dict(ROUND6_AFTER[2], witness_type=None), ROUND6_AFTER[3]], ['mods:witness[3]']),
])
def test_an_answerers_type_follows_whether_they_testified(tmp_path, before, after, flagged):
    write(tmp_path, before=before, after=after, lines=ROUND6_LINES, table=['Craig Thomas'])
    code, out = run(tmp_path)
    assert [i['locator'] for i in out['type_unsupported']] == flagged
    assert code == (1 if flagged else 0), out['failed']


# Round 7 (the fifth review): a position cut one word late, an added answerer who never testified typed a witness, an
# official listed as accompanying a witness (at the table), and a line split into three people and a speaker's turn.
ROUND7_LINES = ['Cross, Gerald, M.D., Acting Under Secretary; accompanied by Caitlin Thompson, Ph.D., Coordinator',
                'Response to questions submitted by Senator Klobuchar to Caitlin Thompson, Ph.D',
                'Ostendorff, Hon. William C., Commissioner Responses to additional questions from Senator Klobuchar',
                'Roe, Mr. Richard, Director, Office of Things....... Prepared statement of............ Smith, Ms. Eleanor, '
                'Director, Office of Stuff Mr. Yoder. We will call the panel now. Thank you all.']
ROUND7_MEMBERS = ['Klobuchar, Amy']
ROUND7_BEFORE = [asked('mods:witness[1]', 'Gerald Cross', 1, None, position='Acting Under Secretary',
                       organization='accompanied by Caitlin Thompson, Ph.D., Coordinator'),
                 asked('mods:witness[3]', 'William C. Ostendorff', 4, None,
                       position='Commissioner Responses to additional questions from Senator Klobuchar'),
                 asked('mods:witness[4]', 'Richard Roe', 6, None, position='Director',
                       organization='Office of Things....... Prepared statement of, Smith, Ms. Eleanor, Director, Office of '
                                    'Stuff Mr. Yoder. We will call the panel now. Thank you all.')]
ROUND7_AFTER = [ROUND7_BEFORE[0], asked('mods:witness[2]', 'Klobuchar', 2),
                asked('mods:witness[2]/part[2]', 'Caitlin Thompson', 3, None),
                dict(ROUND7_BEFORE[1], position='Commissioner'), asked('mods:witness[3]/part[2]', 'Klobuchar', 5),
                asked('mods:witness[4]', 'Richard Roe', 6, None, position='Director', organization='Office of Things'),
                asked('mods:witness[4]/part[2]', 'Eleanor Smith', 7, None, position='Director', organization='Office of Stuff')]


def round7(tmp_path, after=ROUND7_AFTER, **more):
    write(tmp_path, before=ROUND7_BEFORE, after=after, lines=ROUND7_LINES, members=ROUND7_MEMBERS,
          people=('Gerald Cross', 'Caitlin Thompson', 'William Ostendorff'), **more)


def test_an_accompanying_official_answers_as_a_witness_and_a_line_splits_into_its_people(tmp_path):
    round7(tmp_path)
    code, out = run(tmp_path)
    assert code == 0, out['failed']
    assert [i['locator'] for i in out['answerer']] == ['mods:witness[2]/part[2]']
    assert [i['locator'] for i in out['split']] == ['mods:witness[4]/part[2]']


@pytest.mark.parametrize('row, index, flag', [
    # The fifth review's R5-2: a position cut one word late.
    (dict(ROUND7_AFTER[3], position='Commissioner Responses'), 3, 'position_not_in_line'),
    # Thompson sat at the table: answering in writing is wrong for her.
    (dict(ROUND7_AFTER[2], witness_type='statement_for_record'), 2, 'type_unsupported'),
])
def test_a_position_with_a_heading_word_and_a_mistyped_answerer_fail(tmp_path, row, index, flag):
    after = [*ROUND7_AFTER[:index], row, *ROUND7_AFTER[index + 1:]]
    round7(tmp_path, after=after)
    code, out = run(tmp_path)
    assert code == 1 and [i['locator'] for i in out[flag]] == [row['source_locator']]


def test_an_added_answerer_who_never_testified_typed_a_witness_fails(tmp_path):
    """The fifth review's R5-5 (Greene): Herrera Beutler answered only in writing; typed a witness she fails."""
    after = [*ROUND4_AFTER[:4], dict(ROUND4_AFTER[4], witness_type=None), *ROUND4_AFTER[5:]]
    round4(tmp_path, after=after)
    code, out = run(tmp_path)
    assert code == 1 and [i['locator'] for i in out['type_unsupported']] == ['mods:witness[3]/part[2]']


def test_the_round7_plants_are_flagged(tmp_path):
    prints = [('01' * 32, ROUND4_LINES, ['Roe, Richard'], ROUND4_BEFORE, ROUND4_AFTER)]
    round7(tmp_path, prints=prints, table=ROUND4_TABLE)
    code, out = run(tmp_path, '--plant', 'position-heading-word', 'answerer-untestified-witness')
    assert [(p['kind'], p['flagged']) for p in out['planted']] == [
        ('position-heading-word', True), ('answerer-untestified-witness', True)]


# Round 8: a Member's opening statement keeps the words, from its line or an opening statements heading over it; a
# heading or a sitting's date run into a Member's entry is shed; a Member's opening statement is untyped.
OHIO = 'a Representative in Congress from the State of Ohio'
ROUND8_LINES = [f'OPENING STATEMENTS Roe, Hon. Richard, {OHIO}',
                f'Doe, Hon. Jane, {OHIO}',
                'Tuesday, May 24, 2023--Subcommittee on Livestock Smith, Hon. Eleanor, a Representative in Congress from '
                'Ohio, opening statement',
                'Weidman, Richard F., Executive Director for Policy, Vietnam Veterans of America',
                f'Herrera Beutler, Hon. Jaime, {WASHINGTON}, prepared statement',
                'Doe, Hon. John a Representative in Congress from Ohio, opening statement',
                'U.S. Department of the Treasury, Hon. Robert Rubin, Secretary']
ROUND8_MEMBERS = ['Roe, Richard', 'Doe, Jane', 'Smith, Eleanor', 'Herrera Beutler, Jaime', 'Doe, John']
ROUND8_BEFORE = [asked('mods:witness[1]', 'Richard Roe', 1, None, position=OHIO),
                 asked('mods:witness[2]', 'Jane Doe', 2, None, position=OHIO),
                 asked('mods:witness[3]', 'May 24 Tuesday', 3, None, position='2023--Subcommittee on Livestock Smith',
                       organization='Hon. Eleanor, a Representative in Congress from Ohio, opening statement'),
                 asked('mods:witness[4]', 'Richard F. Weidman', 4, None, position='Executive Director for Policy',
                       organization='Vietnam Veterans of America'),
                 asked('mods:witness[5]', 'Jaime Herrera Beutler', 5, 'member_statement', position=WASHINGTON),
                 asked('mods:witness[6]', 'John Doe', 6, 'member_statement'),
                 asked('mods:witness[7]', 'Robert Rubin', 7, None, position='Secretary',
                       organization='U.S. Department of the Treasury')]
ROUND8_AFTER = [dict(ROUND8_BEFORE[0], organization='opening statement'),
                dict(ROUND8_BEFORE[1], organization='opening statement'),
                asked('mods:witness[3]', 'Eleanor Smith', 3, None, position='a Representative in Congress from Ohio',
                      organization='opening statement'),
                ROUND8_BEFORE[3], ROUND8_BEFORE[4],
                asked('mods:witness[6]', 'John Doe', 6, None, position='a Representative in Congress from Ohio',
                      organization='opening statement'),
                ROUND8_BEFORE[6]]
ROUND8_TABLE = ['Richard Roe', 'Jane Doe', 'Eleanor Smith', 'Jaime Herrera Beutler', 'John Doe']
ROUND8_PEOPLE = ('Richard Roe', 'Jane Doe', 'John Doe', 'Richard Weidman', 'Robert Rubin')


def round8(tmp_path, after=ROUND8_AFTER, **more):
    write(tmp_path, before=ROUND8_BEFORE, after=after, lines=ROUND8_LINES, members=ROUND8_MEMBERS, table=ROUND8_TABLE,
          people=ROUND8_PEOPLE, **more)


def test_members_opening_statements_pass_from_their_line_or_the_heading_over_it(tmp_path):
    round8(tmp_path)
    code, out = run(tmp_path)
    assert code == 0, out['failed']


@pytest.mark.parametrize('index, row, flag', [
    # The heading's words dropped from a Member under it.
    (1, dict(ROUND8_AFTER[1], organization=None), 'opening_statement_dropped'),
    # A witness who is no Member given an opening statement.
    (3, dict(ROUND8_AFTER[3], organization='Vietnam Veterans of America, opening statement'), 'words_gained'),
    # A date heading shed with the Member's given name.
    (2, dict(ROUND8_AFTER[2], name='Smith'), 'words_lost'),
    # A Member's prepared statement untyped: only an opening statement is left to the model step.
    (4, dict(ROUND8_AFTER[4], witness_type=None), 'type_unsupported'),
    # An organization printed before its official shed as if it were a heading.
    (6, dict(ROUND8_AFTER[6], organization=None), 'words_lost'),
])
def test_a_dropped_opening_statement_or_a_heading_shed_wrongly_fails(tmp_path, index, row, flag):
    round8(tmp_path, after=[*ROUND8_AFTER[:index], row, *ROUND8_AFTER[index + 1:]])
    code, out = run(tmp_path)
    assert code == 1 and [i['locator'] for i in out[flag]] == [row['source_locator']]


def test_the_round8_plants_are_flagged(tmp_path):
    kinds = ['opening-dropped', 'opening-on-witness', 'heading-took-given', 'member-statement-untyped',
             'heading-strip-organization']
    prints = [(f'{n:02d}' * 32, ROUND8_LINES, ROUND8_MEMBERS, ROUND8_BEFORE, ROUND8_AFTER) for n in range(11, 15)]
    round8(tmp_path, prints=prints)
    code, out = run(tmp_path, '--plant', *kinds)
    assert [(p['kind'], p['flagged']) for p in out['planted']] == [(kind, True) for kind in kinds]


def test_an_office_shed_from_a_name_and_a_member_only_the_table_names_pass(tmp_path):
    """m16: a given name run into the Member's style ("Roe, Hon. Richard a Representative ...") sheds the office into
    the position, which moves no person; a name surname first whose given name other publishers do not state is a
    Member's by the members table ("Vito Fossella"); an opening statements heading in capitals is no part of the
    Member's name, so the heading carries (Jeffords, then Carper; CHRG-107shrg78075)."""
    lines = [f'Roe, Hon. Richard {OHIO}', 'Fossella, Hon. Vito a Representative in Congress from the State of New York',
             'OPENING STATEMENTS Jeffords, Hon. James M., U.S. Senator from the State of Vermont',
             'Carper, Hon. Thomas R., U.S. Senator from the State of Delaware']
    new_york = 'a Representative in Congress from the State of New York'
    before = [asked('mods:witness[1]', f'Richard {OHIO} Roe', 1, None),
              asked('mods:witness[2]', f'Vito {new_york} Fossella', 2, None),
              asked('mods:witness[3]', 'James M. Jeffords', 3, None, position='U.S. Senator from the State of Vermont'),
              asked('mods:witness[4]', 'Thomas R. Carper', 4, None, position='U.S. Senator from the State of Delaware')]
    after = [asked('mods:witness[1]', 'Richard Roe', 1, None, position=OHIO),
             asked('mods:witness[2]', 'Vito Fossella', 2, None, position=new_york),
             dict(before[2], organization='opening statement'), dict(before[3], organization='opening statement')]
    write(tmp_path, before=before, after=after, lines=lines,
          table=['Richard Roe', 'Vito Fossella', 'James Jeffords', 'Thomas Carper'])
    code, out = run(tmp_path)
    assert code == 0, out['failed']


# Round 9 (the sixth review): an office shed with the middle initial, the record's committee lists, a lower-case
# surname entry read as prose, and a note's sentence or a contents heading run in before an entry.
VIRGINIA = 'a Representative in Congress from the State of Virginia'
TEXAS = 'a Representative in Congress from the State of Texas'
ROUND9_LINES = [f'Moran, Hon. James P. {VIRGINIA}',
                f'Armey, Hon. Richard K. {TEXAS}, and Majority Leader, U.S. House of Representatives',
                'de Rugy, Veronique, Senior Research Fellow, Mercatus Center',
                'record. Scott Cleland, President, Precursor LLC',
                'Letters: Daschle, Hon. Tom, U.S. Senator from the State of South Dakota']
ROUND9_BEFORE = [asked('mods:witness[1]', f'James P. {VIRGINIA} Moran', 1, None),
                 asked('mods:witness[2]', f'Richard K. {TEXAS} Armey', 2, None, position='and Majority Leader',
                       organization='U.S. House of Representatives'),
                 asked('mods:witness[3]', 'Veronique de Rugy', 3, None, position='Senior Research Fellow',
                       organization='Mercatus Center'),
                 asked('mods:witness[4]', 'record. Scott Cleland', 4, None, position='President', organization='Precursor LLC'),
                 asked('mods:witness[5]', 'Letters: Daschle', 5, 'member_statement', position='Hon. Tom',
                       organization='U.S. Senator from the State of South Dakota')]
ROUND9_AFTER = [asked('mods:witness[1]', 'James P. Moran', 1, None, position=VIRGINIA),
                asked('mods:witness[2]', 'Richard K. Armey', 2, None, position=TEXAS,
                      organization='and Majority Leader, U.S. House of Representatives'),
                ROUND9_BEFORE[2],
                asked('mods:witness[4]', 'Scott Cleland', 4, None, position='President', organization='Precursor LLC'),
                asked('mods:witness[5]', 'Tom Daschle', 5, 'member_statement',
                      position='U.S. Senator from the State of South Dakota')]
ROUND9_PEOPLE = ('James Moran', 'Richard Armey', 'Veronique de Rugy', 'Scott Cleland', 'Tom Daschle')


def round9(tmp_path, after=ROUND9_AFTER, **more):
    write(tmp_path, before=ROUND9_BEFORE, after=after, lines=ROUND9_LINES, people=ROUND9_PEOPLE,
          table=['James Moran', 'Richard Armey', 'Tom Daschle'], **more)


def test_offices_shed_entries_a_note_ran_into_and_a_lower_case_surname_pass(tmp_path):
    # A speech addressing an office ("Would you, Mr. Secretary, recommend ...") is still prose: its row may name no one.
    speech = 'miles per gallon does; it backs out all the oil. Would you, Mr. Secretary, recommend to the President that'
    before = [*ROUND9_BEFORE, asked('mods:witness[6]', 'miles per gallon does; it backs out all the oil. Would you', 6,
                                    None, position='Mr. Secretary')]
    after = [*ROUND9_AFTER, asked('mods:witness[6]', None, 6, 'record_material')]
    write(tmp_path, before=before, after=after, lines=[*ROUND9_LINES, speech], people=ROUND9_PEOPLE,
          table=['James Moran', 'Richard Armey', 'Tom Daschle'])
    code, out = run(tmp_path)
    assert code == 0, out['failed']


def test_the_round9_reading_passes(tmp_path):
    round9(tmp_path)
    code, out = run(tmp_path)
    assert code == 0, out['failed']


@pytest.mark.parametrize('index, row, flag', [
    # The sixth review's plants: an office shed with the middle initial.
    (0, dict(ROUND9_AFTER[0], name='James Moran', position=f'P. {VIRGINIA}'), 'person_moved'),
    (1, dict(ROUND9_AFTER[1], name='Richard Armey', position=f'K. {TEXAS}'), 'person_moved'),
    # An entry whose surname opens in lower case read as prose.
    (2, dict(ROUND9_AFTER[2], name=None, position=None, organization=None, witness_type='record_material'), 'words_lost'),
])
def test_an_initial_moved_with_an_office_and_an_entry_read_as_prose_fail(tmp_path, index, row, flag):
    round9(tmp_path, after=[*ROUND9_AFTER[:index], row, *ROUND9_AFTER[index + 1:]])
    code, out = run(tmp_path)
    assert code == 1 and [i['locator'] for i in out[flag]] == [row['source_locator']]


def committee_prints(tmp_path, prints):
    """Prints of (digest, committees, members, held): each states `committees` (in its extension, the first again in a
    constituent item) and `members` as COMMMEMBER entries beside a WITNESS one; the after generation holds `held`
    (committees, committee_members)."""
    member = '<congMember bioGuideId="{}" role="{}"><name type="authority-lnf">{}</name></congMember>'
    row = asked('mods:witness[1]', 'Richard Roe', 1, None, position='Director')
    sides = dict(before=[], after=[])
    for digest, committees, members, held in prints:
        body = ('<mods xmlns="http://www.loc.gov/mods/v3"><extension><congress>118</congress>'
                + ''.join(f'<congCommittee authorityId="{c.upper()}"/>' for c in committees)
                + ''.join(member.format(b, 'COMMMEMBER', f'Doe{i}, Jane') for i, b in enumerate(members))
                + member.format('W000001', 'WITNESS', 'Roe, Richard') + '<witness>Roe, Richard, Director</witness>'
                + '</extension><relatedItem><extension>' + f'<congCommittee authorityId="{committees[0]}"/>'
                + '</extension></relatedItem></mods>').encode()
        (tmp_path / 'raw' / digest[:2]).mkdir(parents=True, exist_ok=True)
        (tmp_path / 'raw' / digest[:2] / f'{digest}.gz').write_bytes(gzip.compress(body))
        for side, facts in (('before', (None, None)), ('after', held)):
            sides[side].append(dict(source='mods', record_sha=bytes.fromhex(digest), package_id=f'CHRG-{digest[:2]}',
                                    appearances=[row], committees=facts[0], committee_members=facts[1]))
    for side, rows in sides.items():
        pq.write_table(pa.Table.from_pylist(rows), tmp_path / f'{side}.parquet')
    pq.write_table(pa.Table.from_pylist([dict(bioguide_id='X', name='Nobody Here', terms=[])]), tmp_path / 'members.parquet')
    pq.write_table(pa.Table.from_pylist([dict(source='congress_gov', name='Richard Roe')] * 2), tmp_path / 'people.parquet')


@pytest.mark.parametrize('held, flags', [
    ((['hsag00', 'hsag03'], ['B000001', 'C000002']), []),
    # Another record's committee; a committee member twice; the members out of the document's order.
    ((['hsif00', 'hsag03'], ['B000001', 'C000002']), ['committees_differ']),
    ((['hsag00', 'hsag03'], ['B000001', 'C000002', 'B000001']), ['committee_members_differ']),
    ((['hsag00', 'hsag03'], ['C000002', 'B000001']), ['committee_members_differ']),
])
def test_a_records_committee_lists_are_the_documents_own_in_order(tmp_path, held, flags):
    committee_prints(tmp_path, [(DIGEST, ['hsag00', 'hsag03'], ['B000001', 'C000002'], held)])
    code, out = run(tmp_path)
    assert [flag for flag in ('committees_differ', 'committee_members_differ') if out[flag]] == flags
    assert code == (1 if flags else 0)


def test_the_round9_plants_are_flagged(tmp_path):
    kinds = ['office-took-initial', 'office-took-initial', 'surname-as-prose']
    prints = [(f'{n:02d}' * 32, ROUND9_LINES, (), ROUND9_BEFORE, ROUND9_AFTER) for n in range(11, 13)]
    round9(tmp_path, prints=prints)
    code, out = run(tmp_path, '--plant', *kinds)
    assert [(p['kind'], p['flagged']) for p in out['planted']] == [(kind, True) for kind in kinds]
    assert len({p['body'] for p in out['planted']}) == len(kinds)


def test_the_committee_plants_are_flagged(tmp_path):
    lists = [(['hsag00'], ['B000001', 'C000002']), (['hsif00', 'hsif02'], ['D000003'])]
    committee_prints(tmp_path, [(f'{n:02d}' * 32, *lists[n % 2], lists[n % 2]) for n in range(11, 14)])
    kinds = ['committee-from-other-record', 'member-duplicated']
    code, out = run(tmp_path)
    assert code == 0, out['failed']
    code, out = run(tmp_path, '--plant', *kinds)
    assert [(p['kind'], p['flagged']) for p in out['planted']] == [(kind, True) for kind in kinds]


# The seventh review: a note's run-in sentence may be shed only up to its last full stop, and a name printed in order
# keeps the capitalised words printed just before its family name.
NOTE_LINES = ['are available at: docs.house.gov. Brenda Leong, Senior Counsel, Future of Privacy Forum',
              'record. Scott Cleland, President, Precursor LLC']
NOTE_BEFORE = [asked('mods:witness[1]', None, 1, None),
               asked('mods:witness[2]', 'record. Scott Cleland', 2, None, position='President', organization='Precursor LLC')]
NOTE_AFTER = [asked('mods:witness[1]', 'Brenda Leong', 1, None, position='Senior Counsel',
                    organization='Future of Privacy Forum'),
              asked('mods:witness[2]', 'Scott Cleland', 2, None, position='President', organization='Precursor LLC')]


def notes(tmp_path, after=NOTE_AFTER, **more):
    write(tmp_path, before=NOTE_BEFORE, after=after, lines=NOTE_LINES, people=('Brenda Leong', 'Scott Cleland'), **more)


@pytest.mark.parametrize('index, name, flags', [
    (None, None, []),
    # The reviewer's plants: the note shed with the given name after it.
    (0, 'Leong', ['name_cut']),
    (1, 'Cleland', ['name_cut', 'words_lost']),
])
def test_a_note_is_shed_up_to_its_last_full_stop_and_no_further(tmp_path, index, name, flags):
    after = NOTE_AFTER if index is None else [*NOTE_AFTER[:index], dict(NOTE_AFTER[index], name=name),
                                              *NOTE_AFTER[index + 1:]]
    notes(tmp_path, after=after)
    code, out = run(tmp_path)
    assert [flag for flag in ('name_cut', 'words_lost') if out[flag]] == flags
    assert code == (1 if flags else 0)


def test_the_note_plant_is_flagged(tmp_path):
    notes(tmp_path, prints=[('11' * 32, NOTE_LINES, (), NOTE_BEFORE, NOTE_AFTER)])
    code, out = run(tmp_path, '--plant', 'note-took-given', 'note-took-given')
    assert [(p['kind'], p['flagged']) for p in out['planted']] == [('note-took-given', True)] * 2


# Wave 3 (ct-6mvl, ct-eppo, ct-vj08, ct-uz8q, ct-17op): organization-in-position (both directions), written-answer
# label shapes, 'the Honorable', no-space honorifics, lower-case surname particles, honorific/org abbreviations in prose,
# and dedicated rank/credentials fields.
WAVE3_LINES = [
    'Page Barreto, Hon. Hector V., U.S. Small Business Administration',
    'Hon. Eleanor Holmes Norton, a Delegate in Congress from the District of Columbia',
    'Statement of the Honorable Richard Roe, Mayor',
    'The Hon.Eleanor Smith, a Representative in Congress from the State of Texas, statement',
    'van Welie, Gordon, President and CEO, ISO New England Inc.',
    'de Rugy, Veronique, Senior Fellow; accompanied by Gov. Jane Doe and Acme Corp. staff',
    r'Answers to submitted questions \*\ Richard Roe, Executive Director, National Association of Boards',
    'Answers to Submitted Questions, Mr. Jeff Hopkins',
    'Response to question submitted for the record by Jeanine Derby, Forest Supervisor.............   252',
    'Nakasone, Lieutenant General Paul M., USA, Commander, U.S. Cyber Command',
]
WAVE3_BEFORE = [
    asked('mods:witness[1]', 'Hector V. Barreto', 1, None, position='U.S. Small Business Administration'),
    asked('mods:witness[2]', 'Eleanor Holmes Norton', 2, None, position=DELEGATE),
    asked('mods:witness[3]', 'the Honorable Richard Roe', 3, None, position='Mayor'),
    asked('mods:witness[4]', 'The Hon.Eleanor Smith', 4, None,
          position='a Representative in Congress from the State of Texas', organization='statement'),
    asked('mods:witness[5]', 'van Welie', 5, None, position='Gordon', organization='President and CEO, ISO New England Inc.'),
    asked('mods:witness[6]', 'Veronique de Rugy', 6, None, position='Senior Fellow',
          organization='accompanied by Gov. Jane Doe and Acme Corp. staff'),
    asked('mods:witness[10]', 'Paul M. Nakasone', 7, None, position='Commander', organization='U.S. Cyber Command'),
]
WAVE3_AFTER = [
    asked('mods:witness[1]', 'Hector V. Barreto', 1, None, position=None, organization='U.S. Small Business Administration'),
    WAVE3_BEFORE[1],
    asked('mods:witness[3]', 'Richard Roe', 3, None, position='Mayor'),
    asked('mods:witness[4]', 'Eleanor Smith', 4, 'member_statement',
          position='a Representative in Congress from the State of Texas', organization='statement'),
    asked('mods:witness[5]', 'Gordon van Welie', 5, None, position='President and CEO', organization='ISO New England Inc.'),
    WAVE3_BEFORE[5],
    asked('mods:witness[7]', 'Richard Roe', 7, None, position='Executive Director',
          organization='National Association of Boards'),
    asked('mods:witness[8]', 'Jeff Hopkins', 8, 'statement_for_record'),
    asked('mods:witness[9]', 'Jeanine Derby', 9, 'statement_for_record', position='Forest Supervisor'),
    dict(asked('mods:witness[10]', 'Paul M. Nakasone', 10, None, position='Commander', organization='U.S. Cyber Command'),
         rank='Lieutenant General', credentials='USA'),
]


def test_wave3_reread_passes_and_all_nine_wave3_plants_are_flagged(tmp_path):
    kinds = [
        'org-in-position',
        'role-in-organization',
        'the-honorable-kept',
        'no-space-honorific-kept',
        'particle-given-dropped',
        'abbreviation-as-prose',
        'eppo-asterisk-dropped',
        'eppo-comma-dropped',
        'eppo-singular-dropped',
    ]
    prints = [
        (f'{n:02d}' * 32, WAVE3_LINES, ['Smith, Eleanor'], WAVE3_BEFORE, WAVE3_AFTER)
        for n in range(21, 21 + len(kinds))
    ]
    write(
        tmp_path,
        before=WAVE3_BEFORE,
        after=WAVE3_AFTER,
        lines=WAVE3_LINES,
        members=['Smith, Eleanor'],
        table=['Eleanor Smith'],
        people=('Hector Barreto', 'Gordon van Welie', 'Veronique de Rugy', 'Jeanine Derby', 'Paul Nakasone'),
        prints=prints,
    )
    code, out = run(tmp_path)
    assert code == 0, out['failed']

    code, out = run(tmp_path, '--plant', *kinds)
    assert code == 1
    assert [(p['kind'], p['flagged']) for p in out['planted']] == [(k, True) for k in kinds]
    assert len({p['body'] for p in out['planted']}) == len(kinds)


def test_wave3_corpus_calibrations_slash_dates_particles_and_residuals(tmp_path):
    lines = [
        'Colonel Pamela A. Melroy, United States Air Force (Ret.)/NASA Astronaut, retired',
        'PEER, Presidents of Local Unions, June 29, 2006',
        'de Bernardo, Mark, partner, Jackson Lewis, LLP',
        'von Droste, Bernd, Director, World Heritage Center',
        'Heinen, M.P.P., LuAnn, Vice President, National Business Group on Health',
        'Coston, Ph.D., D.C., Vice President for Agriculture, North Dakota State University',
        'Ben Hoffman, MD, FAAP, CPST-I, Chair, American Academy of Pediatrics',
        'Chandler &amp; Associates, LLC, and Chandler Company, Richard Roe',
    ]
    before = [
        asked('mods:witness[1]', 'Pamela A. Melroy', 1, None, position='United States Air Force/NASA Astronaut', organization='retired'),
        asked('mods:witness[2]', 'Presidents of Local Unions', 2, 'record_material', position='June 29', organization='2006'),
        asked('mods:witness[3]', 'de Bernardo', 3, None, position='Mark', organization='partner, Jackson Lewis, LLP'),
        asked('mods:witness[4]', 'von Droste', 4, None, position='Bernd', organization='Director, World Heritage Center'),
        asked('mods:witness[5]', 'M.P.P. Heinen', 5, None, position='LuAnn', organization='Vice President, National Business Group on Health'),
        asked('mods:witness[6]', 'Ph.D. Coston', 6, None, position='Vice President for Agriculture', organization='North Dakota State University'),
        asked('mods:witness[7]', 'Ben Hoffman', 7, None, position='CPST-I', organization='Chair, American Academy of Pediatrics'),
        asked('mods:witness[8]', 'Chandler & Associates', 8, None, position='and Chandler Company', organization='Richard Roe'),
    ]
    after = [
        dict(asked('mods:witness[1]', 'Pamela A. Melroy', 1, None, position='NASA Astronaut', organization='retired'),
             rank='Colonel', credentials='United States Air Force (Ret.)'),
        asked('mods:witness[2]', None, 2, 'record_material', organization='PEER, Presidents of Local Unions, June 29, 2006'),
        asked('mods:witness[3]', 'Mark de Bernardo', 3, None, position='partner', organization='Jackson Lewis, LLP'),
        asked('mods:witness[4]', 'Bernd von Droste', 4, None, position='Director', organization='World Heritage Center'),
        dict(asked('mods:witness[5]', 'LuAnn Heinen', 5, None, position='Vice President', organization='National Business Group on Health'),
             credentials='M.P.P.'),
        dict(asked('mods:witness[6]', 'D.C. Coston', 6, None, position='Vice President for Agriculture', organization='North Dakota State University'),
             credentials='Ph.D.'),
        dict(asked('mods:witness[7]', 'Ben Hoffman', 7, None, position='Chair', organization='American Academy of Pediatrics'),
             credentials='MD, FAAP, CPST-I'),
        asked('mods:witness[8]', 'Chandler & Associates', 8, None, position='LLC', organization='and Chandler Company, Richard Roe'),
    ]
    write(
        tmp_path,
        before=before,
        after=after,
        lines=lines,
        people=('Pamela Melroy', 'June Smith', 'Mark Smith', 'Ben Hoffman'),
    )
    code, out = run(tmp_path)
    assert code == 0, out['failed']
    assert [r['locator'] for r in out['residual']] == ['mods:witness[8]']
