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


def write(tmp_path, before=BEFORE, after=AFTER, lines=LINES, members=(), table=(), prints=()):
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
              for n in ('Richard Roe', 'Eleanor Smith', 'Hon. Jaime Herrera Beutler')]
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
    ('person-moved', {'person_moved': 1}, 'mods:witness[3]', None),
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
    accept = [signed('mods:witness[2]', flag, fields(left), LINES[1]) for flag in ('words_lost', 'person_left_in_organization')]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 0 and [(i['locator'], i['flag']) for i in out['accepted']] == [
        ('mods:witness[2]', 'words_lost'), ('mods:witness[2]', 'person_left_in_organization')]
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
    assert code == 1 and out['failed'] == {'name_not_person': 1, 'words_lost': 1, 'stale_accept': 1}


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
    assert code == 1 and out['failed'] == {'words_lost': 1, 'person_left_in_organization': 1, 'stale_accept': 1}
    assert [a['flag'] for a in out['unsigned_accept']] == ['words_lost'] and not out['accepted']


# Round 2 (ct-zs48, ct-3aap review): every Member a question line names has a row; a restored heading names a
# person; a committee title is not a name; a document's title or an organization's statement left a witness fails.
ASKER_LINES = ['Questions and Answers (Post-Hearing) from: Chairman Richard Roe.......... 36,',
               'Hon. Eleanor Smith.............. 22,32 Hon. Jaime Herrera Beutler',
               'Responses to questions for the record from the following Representatives: Hon. Eleanor Smith, of Texas',
               'Senators Roe and Lautenberg........81,']
ASKER_BEFORE = [typed(occurrence('mods:witness[1]', 'Richard Roe'), 'record_material'),
                typed(occurrence('mods:witness[2]', 'Eleanor Smith', 'Hon. Jaime Herrera Beutler'), 'record_material'),
                typed(occurrence('mods:witness[4]', 'Roe'), 'record_material'),
                typed(occurrence('mods:witness[4]/part[2]', 'Lautenberg'), 'record_material')]
ASKER_AFTER = [ASKER_BEFORE[0], typed(occurrence('mods:witness[2]', 'Eleanor Smith'), 'record_material'),
               typed(occurrence('mods:witness[2]/part[2]', 'Jaime Herrera Beutler'), 'record_material'),
               typed(occurrence('mods:witness[3]', 'Eleanor Smith', 'of Texas'), 'record_material'), *ASKER_BEFORE[2:]]


def test_a_faithful_reading_of_several_askers_passes(tmp_path):
    write(tmp_path, before=ASKER_BEFORE, after=ASKER_AFTER, lines=ASKER_LINES, members=['Lautenberg, Frank R.'])
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
    write(tmp_path, before=ASKER_BEFORE, after=ASKER_AFTER, lines=ASKER_LINES, members=['Lautenberg, Frank R.'])
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted'][0]['flagged'] and out['planted'][0]['locator'] == locator
    assert [i['locator'] for i in out[flag]] == [locator]
    if missing:
        assert out[flag][0]['words'] == missing


def test_a_member_named_only_by_the_prints_own_members_list_is_counted(tmp_path):
    """The <congMember> half of member_unnamed sees a Member the line prints without a title."""
    lines = [*ASKER_LINES[:3], 'Roe and Lautenberg........81,']
    after = [*ASKER_AFTER[:4], typed(occurrence('mods:witness[4]', 'Roe'), 'record_material')]
    write(tmp_path, before=ASKER_BEFORE[:3], after=after, lines=lines, members=['Lautenberg, Frank R.'])
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
                asked('mods:witness[3]', 'Frank Lautenberg', 4), asked('mods:witness[3]/part[2]', 'Jaime Herrera Beutler', 5, None),
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
