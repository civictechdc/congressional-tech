"""Raw MODS bytes, CSV repairs and adapter evidence agree without invented freshness."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from congress_api.acquisition import gpo as fetch
from congress_api.adapters import gpo
from congress_api.matching.gpo_committees import merge_cached_row as fetch_merge_cached_row
from congress_api.parsers.gpo_hearings import PARSER_VERSION as fetch_PARSER_VERSION
from congress_api.parsers.gpo_hearings import committee_on_title_page as fetch_committee_on_title_page
from congress_api.parsers.gpo_hearings import parse_mods as fetch_parse_mods
from congress_api.replay.gpo import replay
from congress_api.retention import gpo as evidence
from congress_api.retention.gpo import read_csv as fetch_read_csv
from congress_api.retention.gpo import write_csv as fetch_write_csv
from test_explorer_material_adapters import context

FIXTURES = Path(__file__).parent / 'fixtures' / 'gpo_metadata'


def parsed(package='CHRG-113hhrg21122'):
    return asdict(fetch_parse_mods(package, (FIXTURES / f'{package}.xml').read_bytes(), '2026-09-01T00:00:00Z'))


def test_real_mods_serial_and_roster_survive_as_native_evidence_without_attendance():
    row = parsed()
    assert row['serial_numbers'] == 'FC09'
    assert row['preferred_citation'] == row['serial'] == ''
    assert row['document_class'] == 'HHRG'
    raw = (FIXTURES / f"{row['package_id']}.xml").read_bytes()
    native = {'package_id': row['package_id'], 'mods': evidence.observation(raw, 'https://www.govinfo.gov/mods.xml', 'application/xml')}
    output = list(gpo.records([row], context(), evidence_by_package={row['package_id']: native}))
    source = next(x for x in output if x.kind == 'source_record')
    assert source.payload['serial_numbers'] == 'FC09'
    assert evidence.body_bytes(source.payload['upstream']['mods']) == raw
    assert source.payload['upstream']['mods']['retrieved_at'] is None
    assert '<congMember' in source.payload['upstream']['mods']['body']
    assert not any(r.kind in ('appearance', 'person', 'meeting') for r in output)


def test_real_supplement_csv_adapter_preserves_all_native_renditions():
    row = parsed('CHRG-116shrg63315')
    output = list(gpo.records([row], context()))
    urls = {loc.url for r in output if r.kind == 'representation' for loc in r.locations}
    assert len(urls) == 4
    assert sum('-add1' in url for url in urls) == 2
    assert urls == set(row['html_urls'].split(';') + row['pdf_urls'].split(';'))


def test_all_native_held_dates_reach_material_and_remain_alternatives_to_headers():
    row = parsed('CHRG-116shrg42251')
    assert row['held_dates'] == '2020-06-03;2020-06-11'
    row['held_dates'] += ';2020-06-11'
    output = list(gpo.records([row], context()))
    material = next(r for r in output if r.kind == 'material')
    assert [d.date.isoformat() for d in material.proceeding_dates] == ['2020-06-03', '2020-06-11']
    assert material.field_evidence[0].selected.citations[0].selector == '/held_dates'
    assert not any(r.kind == 'data_issue' and r.category == 'conflicting' for r in output)
    row['hearing_dates'] = '2020-06-03'
    output = list(gpo.records([row], context()))
    material = next(r for r in output if r.kind == 'material')
    assert [d.date.isoformat() for d in material.proceeding_dates] == ['2020-06-03']
    alternate = material.field_evidence[0].alternatives[0]
    assert [d['date'] for d in alternate.value] == ['2020-06-03', '2020-06-11']
    assert alternate.provenance.citations[0].selector == '/held_dates'


def test_replay_preserves_later_corrections_dates_and_digest_is_exact(tmp_path):
    row = parsed()
    row.update(title='Reviewed title', committee_code='hsxx00', hearing_dates='2013-06-14',
               text_read='yes', parser_version='', committee_metadata='', serial_numbers='',
               file_metadata='', html_urls='', pdf_urls='')
    inp, out, retained, receipt = (tmp_path / name for name in ('in.csv', 'out.csv', 'evidence.jsonl.gz', 'receipt.json'))
    fetch_write_csv({row['package_id']: row}, inp)
    result = replay(inp, FIXTURES, out, retained, receipt_path=receipt)
    repaired = fetch_read_csv(out)[row['package_id']]
    for field in ('title', 'committee_code', 'hearing_dates', 'text_read', 'last_modified'):
        assert repaired[field] == row[field]
    assert repaired['serial_numbers'] == 'FC09'
    assert repaired['parser_version'] == ''
    upstream = evidence.read(retained)[row['package_id']]
    assert upstream['mods']['retrieved_at'] is None
    assert upstream['mods']['acquisition'] == 'cached-replay'
    assert upstream['mods']['sha256'] == hashlib.sha256((FIXTURES / f"{row['package_id']}.xml").read_bytes()).hexdigest()
    assert result['failures'] == []
    before = out.read_bytes(), retained.read_bytes()
    replay(out, FIXTURES, out, retained)
    assert before == (out.read_bytes(), retained.read_bytes())


def test_unchanged_rows_refresh_by_parser_version_with_a_bound_and_no_transcript_refetch(tmp_path, monkeypatch):
    package = 'CHRG-113hhrg21122'
    row = parsed(package)
    row.update(parser_version='', title='Reviewed title', hearing_dates='2013-06-14', text_read='yes', witness_count=999)
    second = dict(row, package_id='CHRG-113hhrg99999')
    path, retained = tmp_path / 'rows.csv', tmp_path / 'evidence.jsonl.gz'
    fetch_write_csv({package: row, second['package_id']: second}, path)
    calls = []
    def get(session, url):
        calls.append(url)
        return SimpleNamespace(content=(FIXTURES / f'{package}.xml').read_bytes())
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', lambda since, key: [])
    monkeypatch.setattr(fetch, 'get_with_retry', get)
    fetch.main(path, min_congress=113, nthreads=1, refresh_limit=1, evidence_path=retained)
    rows = fetch_read_csv(path)
    assert rows[package]['parser_version'] == fetch_PARSER_VERSION
    assert rows[second['package_id']]['parser_version'] == ''
    assert rows[package]['hearing_dates'] == row['hearing_dates']
    assert rows[package]['title'] == 'Reviewed title'
    assert int(rows[package]['witness_count']) == parsed(package)['witness_count']
    assert calls == [f'https://www.govinfo.gov/metadata/pkg/{package}/mods.xml']
    observation = evidence.read(retained)[package]['mods']
    assert observation['acquisition'] == 'http' and observation['retrieved_at']
    calls.clear()
    fetch.main(path, min_congress=113, nthreads=1, refresh_limit=0, evidence_path=retained)
    assert calls == []


def test_live_refresh_fills_native_scalar_blanks_but_cache_replay_preserves_them():
    current = parsed()
    current.update(event_id='123456', subcommittees='Subcommittee on Oversight')
    old = dict(current, event_id='', committee_code_gpo='', subcommittees='',
               title='Reviewed title', hearing_dates='2013-06-14', text_read='yes')
    offline = fetch_merge_cached_row(old, current)
    live = fetch_merge_cached_row(old, current, live_refresh=True)
    for field in ('event_id', 'committee_code_gpo', 'subcommittees'):
        assert offline[field] == ''
        assert live[field] == current[field]
    for field in ('title', 'hearing_dates', 'text_read'):
        assert live[field] == old[field]


def test_evidence_round_trip_preserves_non_utf8_and_rejects_corruption(tmp_path):
    import pytest
    value = evidence.observation(b'\xff', 'https://example.gov/a', 'text/html')
    assert value['body_encoding'] == 'base64'
    assert evidence.body_bytes(value) == b'\xff'
    path = tmp_path / 'evidence.jsonl.gz'
    evidence.write({'one': {'package_id': 'one', 'mods': value}}, path)
    assert evidence.body_bytes(evidence.read(path)['one']['mods']) == b'\xff'
    value['body'] = 'AA=='
    evidence.write({'one': {'package_id': 'one', 'mods': value}}, path)
    with pytest.raises(ValueError, match='digest mismatch'):
        evidence.read(path)


def test_html_day_reader_keeps_each_constituent_response(tmp_path, monkeypatch):
    urls = ['https://example.gov/main.htm', 'https://example.gov/addendum.htm']
    pages = [b'WEDNESDAY, JUNE 12, 2013', b'THURSDAY, JUNE 13, 2013']
    def get(session, url):
        data = pages[urls.index(url)]
        return SimpleNamespace(content=data, text=data.decode())
    monkeypatch.setattr(fetch, 'get_with_retry', get)
    captured = {}
    result = fetch.read_transcript(None, {'title': 'Hearing', 'congress': 113,
        'html_urls': ';'.join(urls), 'held_date': '2013-06-12'}, captured)
    assert result['hearing_dates'] == '2013-06-12;2013-06-13'
    assert [evidence.body_bytes(captured[url]) for url in urls] == pages


def test_committee_and_material_adapters_share_enriched_source_identity():
    row = parsed()
    value = {'package_id': row['package_id'], 'mods': {'body': '<source/>'}}
    kwargs = {'evidence_by_package': {row['package_id']: value}}
    committee = next(r for r in gpo.committee_records([row], context(), existing={}, **kwargs) if r.kind == 'source_record')
    material = next(r for r in gpo.records([row], context(), **kwargs) if r.kind == 'source_record')
    assert committee.id == material.id


def test_replay_retains_html_without_mods_and_preserves_acquired_observation(tmp_path):
    row = parsed()
    input_path, output_path, retained = (tmp_path / name for name in ('in.csv', 'out.csv', 'evidence.jsonl.gz'))
    fetch_write_csv({row['package_id']: row}, input_path)
    html_dir, mods_dir = tmp_path / 'html', tmp_path / 'mods'
    html_dir.mkdir(); mods_dir.mkdir()
    raw = b'<pre>THURSDAY, JUNE 13, 2013</pre>'
    (html_dir / f"{row['package_id']}.htm").write_bytes(raw)
    receipt = replay(input_path, mods_dir, output_path, retained, html_dir=html_dir)
    value = evidence.read(retained)[row['package_id']]
    assert value.get('mods') is None
    assert evidence.body_bytes(value['transcripts'][row['html_url']]) == raw
    assert receipt['retained_html'] == 1 and receipt['retained_mods'] == 0
    assert receipt['unmatched_html_files'] == []
    value['transcripts'][row['html_url']]['retrieved_at'] = '2026-09-28T00:00:00Z'
    value['transcripts'][row['html_url']]['acquisition'] = 'http'
    evidence.write({row['package_id']: value}, retained)
    (html_dir / f"{row['package_id']}.htm").write_bytes(b'older response')
    replay(input_path, mods_dir, output_path, retained, html_dir=html_dir)
    assert evidence.body_bytes(evidence.read(retained)[row['package_id']]['transcripts'][row['html_url']]) == raw


def test_invalid_mods_root_is_failure_not_empty_success():
    import pytest
    with pytest.raises(ValueError, match='not a MODS document'):
        fetch_parse_mods('CHRG-113hhrg21122', b'<html>temporary failure</html>', '')


def test_live_errata_native_title_and_type_survive_empty_title_info():
    row = parsed('CHRG-119hhrg64429')
    assert row['title'] == 'FULL COMMITTEE BUSINESS MEETING'
    assert row['record_type'] == 'errata'
    material = next(r for r in gpo.records([row], context()) if r.kind == 'material')
    assert material.title == row['title']
    assert material.details.category == 'errata'
    old = dict(row, title='', record_type='hearing')
    refreshed = fetch_merge_cached_row(old, row, live_refresh=True)
    assert refreshed['title'] == row['title']
    assert refreshed['record_type'] == 'errata'


def test_title_page_committee_continuation_across_blank_line_excludes_layout_labels():
    html = (FIXTURES / 'CHRG-119hhrg64429.htm').read_text()
    assert fetch_committee_on_title_page(html) == 'Committee on Oversight and Government Reform'
    assert fetch_committee_on_title_page('COMMITTEE ON HOUSE\n\nADMINISTRATION\nHOUSE OF REPRESENTATIVES') == 'Committee on House Administration'
    assert fetch_committee_on_title_page("COMMITTEE ON VETERANS' AFFAIRS\n\nBEFORE THE\nUNITED STATES SENATE") == "Committee on Veterans' Affairs"
    assert fetch_committee_on_title_page('COMMITTEE ON SMALL BUSINESS\n\nUNITED STATES\nHOUSE OF REPRESENTATIVES') == 'Committee on Small Business'


def test_transcript_failure_keeps_old_row_and_successful_mods_bytes(tmp_path, monkeypatch):
    import pytest
    package = 'CHRG-113hhrg21122'
    row = parsed(package)
    row.update(parser_version='', text_read='')
    path, retained = tmp_path / 'rows.csv', tmp_path / 'evidence.jsonl.gz'
    fetch_write_csv({package: row}, path)
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', lambda since, key: [])
    def get(session, url):
        if url.endswith('/mods.xml'):
            return SimpleNamespace(content=(FIXTURES / f'{package}.xml').read_bytes())
        raise RuntimeError('temporary transcript failure')
    monkeypatch.setattr(fetch, 'get_with_retry', get)
    with pytest.raises(SystemExit):
        fetch.main(path, min_congress=113, nthreads=1, refresh_limit=1, evidence_path=retained)
    assert fetch_read_csv(path)[package]['parser_version'] == ''
    assert evidence.read(retained)[package]['mods']['retrieved_at']


def test_rejected_mods_bytes_survive_without_replacing_last_valid_source(tmp_path, monkeypatch):
    import pytest
    row = parsed()
    row.update(parser_version='', text_read='yes')
    package = row['package_id']
    path, retained = tmp_path / 'rows.csv', tmp_path / 'evidence.jsonl.gz'
    fetch_write_csv({package: row}, path)
    raw = (FIXTURES / f'{package}.xml').read_bytes()
    previous = evidence.observation(raw, 'https://www.govinfo.gov/mods.xml', 'application/xml',
                                    retrieved_at='2026-09-01T00:00:00Z')
    evidence.write({package: {'package_id': package, 'mods': previous}}, retained)
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', lambda *args: [])
    rejected = b'<html>Temporary upstream error</html>'
    monkeypatch.setattr(fetch, 'get_with_retry', lambda *args: SimpleNamespace(content=rejected))
    with pytest.raises(SystemExit):
        fetch.main(path, min_congress=113, nthreads=1, refresh_limit=1, evidence_path=retained)
    value = evidence.read(retained)[package]
    assert value['mods'] == previous
    assert evidence.body_bytes(value['failed_mods']) == rejected
    assert value['failed_mods']['retrieved_at'] and value['failed_mods']['error']
    assert fetch_read_csv(path)[package]['parser_version'] == ''
    monkeypatch.setattr(fetch, 'get_with_retry', lambda *args: SimpleNamespace(content=raw))
    fetch.main(path, min_congress=113, nthreads=1, refresh_limit=0, evidence_path=retained)
    assert 'failed_mods' not in evidence.read(retained)[package]
    assert fetch_read_csv(path)[package]['parser_version'] == fetch_PARSER_VERSION


def test_failed_new_package_retries_after_other_success_advances_watermark(tmp_path, monkeypatch):
    import pytest
    path, retained = tmp_path / 'rows.csv', tmp_path / 'evidence.jsonl.gz'
    old = parsed()
    old.update(last_modified='2026-01-10T00:00:00Z', text_read='yes')
    fetch_write_csv({old['package_id']: old}, path)
    failed, successful = 'CHRG-113hhrg11111', 'CHRG-113hhrg22222'
    first, windows = True, []
    def listing(since, key):
        windows.append(since)
        return [{'packageId': failed, 'lastModified': '2026-01-11T00:00:00Z'},
                {'packageId': successful, 'lastModified': '2026-01-20T00:00:00Z'}] if first else []
    def get(session, url):
        if first and failed in url:
            raise RuntimeError('temporary MODS failure')
        return SimpleNamespace(content=(FIXTURES / 'CHRG-113hhrg21122.xml').read_bytes())
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', listing)
    monkeypatch.setattr(fetch, 'get_with_retry', get)
    monkeypatch.setattr(fetch, 'read_transcript', lambda *args: {'hearing_dates': '', 'committee_name': ''})
    with pytest.raises(SystemExit):
        fetch.main(path, min_congress=113, nthreads=1, refresh_limit=0, evidence_path=retained)
    pending = Path(str(retained) + '.pending.json')
    assert json.loads(pending.read_text()) == {failed: '2026-01-11T00:00:00Z'}
    assert failed not in fetch_read_csv(path) and successful in fetch_read_csv(path)
    first = False
    fetch.main(path, min_congress=113, nthreads=1, refresh_limit=0, evidence_path=retained)
    assert windows[-1] == '2026-01-18T00:00:00Z'
    assert failed in fetch_read_csv(path)
    assert json.loads(pending.read_text()) == {}


def test_pending_survives_csv_failure_and_csv_write_is_atomic(tmp_path, monkeypatch):
    import pytest
    row = parsed()
    path = tmp_path / 'rows.csv'
    fetch_write_csv({row['package_id']: row}, path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        fetch_write_csv({row['package_id']: row, 'invalid': dict(row, unexpected='field')}, path)
    assert path.read_bytes() == before
    monkeypatch.setattr(fetch, 'load_congress_api_key', lambda: 'unused')
    monkeypatch.setattr(fetch, 'list_collection', lambda *args: [{'packageId': row['package_id'], 'lastModified': '2026-09-02T00:00:00Z'}])
    monkeypatch.setattr(fetch, 'get_with_retry', lambda *args: SimpleNamespace(content=(FIXTURES / 'CHRG-113hhrg21122.xml').read_bytes()))
    monkeypatch.setattr(fetch, 'read_transcript', lambda *args: {'hearing_dates': '', 'committee_name': ''})
    monkeypatch.setattr(fetch, 'write_csv', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        fetch.main(path, min_congress=113, nthreads=1, refresh_limit=0)
    assert path.read_bytes() == before
    assert json.loads(Path(str(path) + '.pending.json').read_text()) == {row['package_id']: '2026-09-02T00:00:00Z'}
