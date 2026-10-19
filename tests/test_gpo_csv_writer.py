"""GPO owns field/order choices; the maintained writer owns replacement."""
import csv
from dataclasses import fields
from io import StringIO
from pathlib import Path

import pytest

from congress_api.parsers.gpo_hearings import GpoHearing
from congress_api.retention import gpo, tables


def original_csv_bytes(rows):
    """Capture the previous GPO writer's exact stdlib serialization policy."""
    handle = StringIO(newline='')
    writer = csv.DictWriter(handle, fieldnames=[field.name for field in fields(GpoHearing)])
    writer.writeheader()
    for package_id in sorted(rows):
        writer.writerow(rows[package_id])
    return handle.getvalue().encode('utf-8')


@pytest.mark.parametrize('rows', [{}, {
    'Z-last': {'package_id': 'Z-last', 'title': 'José 🏛️, "quoted"\r\nnext line',
               'congress': 119, 'witness_count': 0, 'serial': None},
    'A-first': {'title': ' commas, quotes" and\nnewlines ', 'package_id': 'A-first'},
}])
def test_gpo_delegates_without_changing_sorted_bytes(tmp_path, monkeypatch, rows):
    delegated = []
    original = tables.write_csv
    def capture(path, selected, names):
        selected = list(selected)
        delegated.append((selected, names))
        return original(path, selected, names)
    monkeypatch.setattr(tables, 'write_csv', capture)
    path = tmp_path / 'nested' / 'rows.csv'
    assert gpo.write_csv(rows, path) is None
    assert path.read_bytes() == original_csv_bytes(rows)
    assert delegated == [([rows[key] for key in sorted(rows)], [field.name for field in fields(GpoHearing)])]
    assert not path.with_suffix('.csv.tmp').exists()


def test_failed_replacement_preserves_prior_destination_and_cleans_temporary(tmp_path, monkeypatch):
    path = tmp_path / 'rows.csv'
    path.write_bytes(b'prior destination\n')
    rows = {'A': {'package_id': 'A', 'title': 'replacement'}}
    def refuse(source, destination):
        assert source == path.with_suffix('.csv.tmp')
        assert destination == path
        assert source.read_bytes() == original_csv_bytes(rows)
        raise OSError('replacement refused')
    monkeypatch.setattr(Path, 'replace', refuse)
    with pytest.raises(OSError, match='replacement refused'):
        gpo.write_csv(rows, path)
    assert path.read_bytes() == b'prior destination\n'
    assert not path.with_suffix('.csv.tmp').exists()


@pytest.mark.parametrize('rows,error', [
    ({'A': {'package_id': 'A', 'unknown': 'not a GPO field'}}, ValueError),
    ({'A': {'package_id': 'A'}, 1: {'package_id': '1'}}, TypeError),
])
def test_row_and_sort_failures_keep_destination_and_existing_cleanup(tmp_path, rows, error):
    path = tmp_path / 'rows.csv'
    path.write_bytes(b'prior destination\n')
    temporary = path.with_suffix('.csv.tmp')
    temporary.write_bytes(b'stale temporary')
    with pytest.raises(error):
        gpo.write_csv(rows, path)
    assert path.read_bytes() == b'prior destination\n'
    assert not temporary.exists()
