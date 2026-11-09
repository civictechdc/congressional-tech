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


def write(tmp_path, before=BEFORE, after=AFTER):
    body = ('<mods xmlns="http://www.loc.gov/mods/v3"><extension>'
            + ''.join(f'<witness>{line}</witness>' for line in LINES) + '</extension></mods>').encode()
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


@pytest.mark.parametrize('kind, flag, locator, planted', [
    ('person-moved', 'person_moved', 'mods:witness[3]', None),
    ('reversed-name', 'reorder_unsupported', 'mods:witness[4]', 'Beutler Jaime Herrera'),
])
def test_each_planted_wrong_value_is_flagged(tmp_path, kind, flag, locator, planted):
    write(tmp_path)
    code, out = run(tmp_path, '--plant', kind)
    assert code == 1 and out['planted']['flagged'] and out['planted']['planted'] == planted
    assert out['failed'] == {flag: 1}
    assert [i['locator'] for i in out[flag]] == [locator]


def test_a_person_left_in_the_organization_a_lost_word_and_a_dropped_row_are_flagged(tmp_path):
    after = [AFTER[0], occurrence('mods:witness[2]', None, None, 'Vietnam Veterans of America, Richard F. Weidman'), AFTER[3]]
    write(tmp_path, after=after)
    code, out = run(tmp_path)
    assert code == 1
    assert [i['locator'] for i in out['person_left_in_organization']] == ['mods:witness[2]']
    assert out['words_lost'][0]['words'] == ['director', 'executive', 'for', 'policy']
    assert [i['locator'] for i in out['removed']] == ['mods:witness[3]']


def test_a_reviewed_flag_is_accepted_and_an_accept_the_run_no_longer_flags_fails(tmp_path):
    after = [AFTER[0], occurrence('mods:witness[2]', None, None, 'Vietnam Veterans of America, Richard F. Weidman'), *AFTER[2:]]
    write(tmp_path, after=after)
    accept = [dict(body=DIGEST, locator='mods:witness[2]', flag=flag, reason='read')
              for flag in ('words_lost', 'person_left_in_organization')]
    (tmp_path / 'accept.json').write_text(json.dumps(accept))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 0 and [(i['locator'], i['flag']) for i in out['accepted']] == [
        ('mods:witness[2]', 'words_lost'), ('mods:witness[2]', 'person_left_in_organization')]
    stale = accept + [dict(body=DIGEST, locator='mods:witness[1]', flag='person_moved', reason='read')]
    (tmp_path / 'accept.json').write_text(json.dumps(stale))
    code, out = run(tmp_path, '--accept', str(tmp_path / 'accept.json'))
    assert code == 1 and out['failed'] == {'stale_accept': 1}
