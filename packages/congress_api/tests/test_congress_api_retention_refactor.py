"""Atomic retention failures preserve published files and remove partial files."""

import gzip
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.models.gpo import GpoEvidenceObservation
from congress_api.retention import gpo, rejected_pages, tables, transcripts


def _write(kind, path):
    if kind == 'gpo':
        gpo.write({'P': {'package_id': 'P', 'title': 'José', 'future': None}}, path)
    elif kind == 'observation':
        value = GpoEvidenceObservation.model_validate(gpo.observation(b'\xff', 'https://example.gov', 'text/html'))
        gpo.write_observation(value, path)
    elif kind == 'csv':
        tables.write_csv(path, [{'name': 'José'}], ['name'])
    elif kind == 'state':
        tables.write_state(path, {'title': 'José', 'future': None})
    elif kind == 'rejected':
        rejected_pages.retain_rejected_page(path, {'future': None}, url='https://example.gov', offset=0)
    else:
        transcripts.retain_response(SimpleNamespace(text=None, sdk_http_response=None), path.parent,
                                    model='test', start=0, end=1, attempt=1)


@pytest.mark.parametrize('kind', ['gpo', 'observation', 'csv', 'state', 'rejected', 'transcript'])
def test_replace_failure_preserves_destination_and_cleans_temporary(kind, tmp_path, monkeypatch):
    path = tmp_path / 'saved.json.gz'
    before = b'[]' if kind == 'rejected' else b'previous snapshot'
    destination = path.with_suffix('.gz.rejected.json') if kind == 'rejected' else path
    destination.write_bytes(before)
    replacements = []

    def fail(source, target):
        replacements.append((source, target))
        assert source.exists()
        raise OSError('replace failed')

    monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        _write(kind, path)
    assert destination.read_bytes() == before
    assert len(replacements) == 1
    assert not replacements[0][0].exists()
    if kind == 'transcript':
        assert not replacements[0][1].exists()


@pytest.mark.parametrize('kind', ['gpo', 'csv'])
def test_failure_after_first_row_removes_partial_file(kind, tmp_path):
    path = tmp_path / 'saved.gz'
    path.write_bytes(b'previous snapshot')
    with pytest.raises((TypeError, ValueError)):
        if kind == 'gpo':
            gpo.write({'A': {'valid': True}, 'B': {'invalid': object()}}, path)
        else:
            tables.write_csv(path, [{'name': 'valid'}, {'unexpected': 'invalid'}], ['name'])
    assert path.read_bytes() == b'previous snapshot'
    assert not path.with_suffix(path.suffix + '.tmp').exists()


def test_state_gpo_and_csv_keep_distinct_serialized_bytes(tmp_path):
    state = {'title': 'José', 'future': None}
    path = tmp_path / 'state.gz'
    tables.write_state(path, state)
    assert path.read_bytes() == gzip.compress(b'{"future":null,"title":"Jos\xc3\xa9"}', mtime=0)

    path = tmp_path / 'gpo.gz'
    gpo.write({'B': state, 'A': {'future': None}}, path)
    expected = io.BytesIO()
    with gzip.GzipFile(fileobj=expected, mode='wb', mtime=0, filename='') as stream:
        stream.write(b'{"future":null}\n{"future":null,"title":"Jos\xc3\xa9"}\n')
    assert path.read_bytes() == expected.getvalue()

    path = tmp_path / 'rows.csv'
    tables.write_csv(path, [{'title': 'José', 'future': None}, {'title': 'second', 'future': ''}], ['future', 'title'])
    assert path.read_bytes() == b'future,title\r\n,Jos\xc3\xa9\r\n,second\r\n'


def test_state_with_tmp_extension_keeps_destination_on_success_and_failure(tmp_path, monkeypatch):
    path = tmp_path / 'state.tmp'
    tables.write_state(path, {'before': True})
    before = path.read_bytes()
    assert tables.read_state(path) == {'before': True}
    temporary = path.with_suffix('.tmp.tmp')
    assert not temporary.exists()

    def fail(source, target):
        assert source == temporary and target == path
        raise OSError('replace failed')

    monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        tables.write_state(path, {'after': True})
    assert path.read_bytes() == before
    assert not temporary.exists()
