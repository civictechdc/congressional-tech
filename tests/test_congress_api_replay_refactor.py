"""Replay admission is decided before interpreting protected cache inputs."""

from dataclasses import asdict
from pathlib import Path

import pytest

from congress_api.parsers.gpo_hearings import parse_mods
from congress_api.replay.gpo import replay
from congress_api.retention import gpo as evidence


@pytest.mark.parametrize('acquired', [False, True])
def test_gpo_malformed_cache_only_fails_when_admitted(tmp_path, acquired):
    package = 'CHRG-113hhrg21122'
    raw = (Path(__file__).parent / 'fixtures' / 'gpo_metadata' / f'{package}.xml').read_bytes()
    row = asdict(parse_mods(package, raw, '2026-09-01T00:00:00Z'))
    source, output, retained = (tmp_path / name for name in ('in.csv', 'out.csv', 'evidence.jsonl.gz'))
    evidence.write_csv({package: row}, source)
    original_csv = source.read_bytes()
    observation = evidence.observation(raw, 'https://www.govinfo.gov/mods.xml', 'application/xml',
        retrieved_at='2026-09-01T00:00:00Z' if acquired else None)
    evidence.write({package: {'package_id': package, 'mods': observation}}, retained)
    original_evidence = retained.read_bytes()
    cache = tmp_path / 'mods'
    cache.mkdir()
    (cache / f'{package}.xml').write_bytes(b'<html>temporary failure</html>')

    report = replay(source, cache, output, retained)

    assert output.read_bytes() == original_csv
    assert source.read_bytes() == original_csv
    assert retained.read_bytes() == original_evidence
    if acquired:
        assert report['failures'] == []
        assert report['packages'] == [{'package_id': package, 'status': 'kept-acquired-evidence'}]
    else:
        assert report['packages'] == []
        assert len(report['failures']) == 1
        assert report['failures'][0]['package_id'] == package
        assert 'not a MODS document' in report['failures'][0]['error']


def test_gpo_protected_field_violation_is_failure_not_write(tmp_path, monkeypatch):
    package = 'CHRG-113hhrg21122'
    raw = (Path(__file__).parent / 'fixtures' / 'gpo_metadata' / f'{package}.xml').read_bytes()
    row = asdict(parse_mods(package, raw, '2026-09-01T00:00:00Z'))
    source, output, retained = (tmp_path / name for name in ('in.csv', 'out.csv', 'evidence.jsonl.gz'))
    evidence.write_csv({package: row}, source)
    original = source.read_bytes()
    cache = tmp_path / 'mods'
    cache.mkdir()
    (cache / f'{package}.xml').write_bytes(raw)
    monkeypatch.setattr('congress_api.replay.gpo.merge_cached_row',
                        lambda old, parsed: dict(old, title='CHANGED BY BUG'))

    report = replay(source, cache, output, retained)

    assert output.read_bytes() == original
    assert len(report['failures']) == 1
    assert report['failures'][0]['package_id'] == package
    assert 'Protected fields changed' in report['failures'][0]['error']
    assert report['packages'] == []
