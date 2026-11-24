"""Backfill partial-failure gate and stale budget accounting in gpo-fetch."""

from dataclasses import asdict
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.acquisition import gpo as fetch
from congress_api.matching.gpo_committees import clean_rows
from congress_api.parsers.gpo_hearings import PARSER_VERSION, parse_mods
from congress_api.retention import gpo as evidence
from congress_api.transport.zip_member import ZipMemberReadError

FIXTURES = Path(__file__).parent / 'fixtures' / 'gpo_metadata'
MODS = (FIXTURES / 'CHRG-113hhrg21122.xml').read_bytes()
METS = (FIXTURES / 'package_manifests' / 'CHRG-116hhrg43625-dip.xml').read_bytes()
MODIFIED = '2026-10-01T00:00:00Z'


def _stale_row(package_id, *, last_modified=MODIFIED, parser_version='old-parser'):
    row = asdict(parse_mods(package_id, MODS, last_modified))
    row.update(parser_version=parser_version, text_read='yes')
    clean_rows({package_id: row})
    return row


def _stub_gpo(monkeypatch, *, listing_rows=(), fail_mods=(), fail_manifest=()):
    fetched_mods = []
    fetched_manifests = []

    def listing(since, key):
        return list(listing_rows)

    def get(session, url):
        package_id = url.split('/pkg/')[1].split('/')[0]
        fetched_mods.append(package_id)
        if package_id in fail_mods:
            raise RuntimeError(f'mods error for {package_id}')
        return SimpleNamespace(content=MODS)

    def manifest(session, url, member):
        package_id = member.split('/')[0]
        fetched_manifests.append(package_id)
        if package_id in fail_manifest:
            raise ZipMemberReadError(
                'ZIP source precondition failed (HTTP 412)',
                source={'url': url, 'requests': [], 'request_failure': {'http_status': 412}},
            )
        raw = METS.replace(b'OBJID="CHRG-116hhrg43625"', f'OBJID="{package_id}"'.encode())
        return SimpleNamespace(data=raw, source={'url': url, 'member': member})

    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', listing)
    monkeypatch.setattr(fetch, 'get_with_retry', get)
    monkeypatch.setattr(fetch, 'read_zip_member', manifest)
    monkeypatch.setattr(
        fetch,
        'read_transcript',
        lambda *args: {'hearing_dates': '', 'committee_name': '', 'text_read': 'yes'},
    )
    return fetched_mods, fetched_manifests


def test_live_failure_exits_one_even_when_backfill_succeeds(tmp_path, monkeypatch):
    output, retained = tmp_path / 'hearings.csv', tmp_path / 'evidence.jsonl.gz'
    backfill_ok = 'CHRG-113hhrg10001'
    live_fail = 'CHRG-113hhrg20002'
    evidence.write_csv({backfill_ok: _stale_row(backfill_ok)}, output)
    _stub_gpo(
        monkeypatch,
        listing_rows=[{'packageId': live_fail, 'lastModified': '2026-10-15T00:00:00Z'}],
        fail_manifest={live_fail},
    )

    with pytest.raises(SystemExit) as error:
        fetch.main(output, min_congress=113, nthreads=1, refresh_limit=5, evidence_path=retained)
    assert error.value.code == 1
    assert evidence.read_csv(output)[backfill_ok]['parser_version'] == PARSER_VERSION
    assert json.loads(Path(str(retained) + '.pending.json').read_text()) == {
        live_fail: '2026-10-15T00:00:00Z',
    }


def test_backfill_only_partial_failure_with_progress_logs_warning_and_exits_zero(tmp_path, monkeypatch, caplog):
    output, retained = tmp_path / 'hearings.csv', tmp_path / 'evidence.jsonl.gz'
    ok_pkg = 'CHRG-113hhrg10001'
    fail_pkg = 'CHRG-113hhrg10002'
    evidence.write_csv({ok_pkg: _stale_row(ok_pkg), fail_pkg: _stale_row(fail_pkg)}, output)
    pending_path = Path(str(retained) + '.pending.json')
    pending_path.write_text(json.dumps({fail_pkg: MODIFIED}))
    _stub_gpo(monkeypatch, listing_rows=[], fail_manifest={fail_pkg})

    with caplog.at_level(logging.WARNING):
        fetch.main(output, min_congress=113, nthreads=1, refresh_limit=5, evidence_path=retained)

    assert any('backfill hearing(s) failed' in rec.message and rec.levelno == logging.WARNING for rec in caplog.records)
    rows = evidence.read_csv(output)
    assert rows[ok_pkg]['parser_version'] == PARSER_VERSION
    assert rows[fail_pkg]['parser_version'] == 'old-parser'
    saved = evidence.read(retained)
    assert saved[ok_pkg]['manifest']['source_zip']['member'] == f'{ok_pkg}/dip.xml'
    assert '412' in saved[fail_pkg]['failed_manifest']['error']
    assert json.loads(pending_path.read_text()) == {fail_pkg: MODIFIED}


def test_backfill_only_zero_progress_exits_one(tmp_path, monkeypatch):
    output, retained = tmp_path / 'hearings.csv', tmp_path / 'evidence.jsonl.gz'
    fail_pkg = 'CHRG-113hhrg10002'
    evidence.write_csv({fail_pkg: _stale_row(fail_pkg)}, output)
    _stub_gpo(monkeypatch, listing_rows=[], fail_manifest={fail_pkg})

    with pytest.raises(SystemExit) as error:
        fetch.main(output, min_congress=113, nthreads=1, refresh_limit=5, evidence_path=retained)
    assert error.value.code == 1
    assert json.loads(Path(str(retained) + '.pending.json').read_text()) == {fail_pkg: MODIFIED}


def test_stale_budget_respects_pending_count_while_keeping_live_deltas(tmp_path, monkeypatch):
    output, retained = tmp_path / 'hearings.csv', tmp_path / 'evidence.jsonl.gz'
    pending_a, pending_b = 'CHRG-113hhrg10001', 'CHRG-113hhrg10002'
    stale_1, stale_2, stale_3 = 'CHRG-114hhrg10003', 'CHRG-114hhrg10004', 'CHRG-113hhrg10005'
    live_new = 'CHRG-119hhrg99999'

    evidence.write_csv(
        {
            pending_a: _stale_row(pending_a),
            pending_b: _stale_row(pending_b),
            stale_1: _stale_row(stale_1),
            stale_2: _stale_row(stale_2),
            stale_3: _stale_row(stale_3),
        },
        output,
    )
    pending_path = Path(str(retained) + '.pending.json')
    pending_path.write_text(json.dumps({pending_a: MODIFIED, pending_b: MODIFIED}))
    fetched_mods, _ = _stub_gpo(
        monkeypatch,
        listing_rows=[{'packageId': live_new, 'lastModified': '2026-10-20T00:00:00Z'}],
    )

    fetch.main(output, min_congress=113, nthreads=1, refresh_limit=3, evidence_path=retained)
    # 2 pending + 1 stale = 3 (refresh_limit), plus the live listing delta.
    assert set(fetched_mods) == {pending_a, pending_b, stale_1, live_new}
    assert json.loads(pending_path.read_text()) == {}

    # When pending already meets or exceeds refresh_limit, stale_budget is 0 while live deltas still run.
    fetched_mods.clear()
    rows = evidence.read_csv(output)
    for pkg in (pending_a, pending_b, stale_2, stale_3):
        rows[pkg]['parser_version'] = 'old-parser'
    evidence.write_csv(rows, output)
    pending_path.write_text(json.dumps({pending_a: MODIFIED, pending_b: MODIFIED}))
    fetched_mods_2, _ = _stub_gpo(
        monkeypatch,
        listing_rows=[{'packageId': live_new, 'lastModified': '2026-10-21T00:00:00Z'}],
    )

    fetch.main(output, min_congress=113, nthreads=1, refresh_limit=2, evidence_path=retained)
    assert set(fetched_mods_2) == {pending_a, pending_b, live_new}
