"""Committee pages supplement central records with retained, matched evidence."""
from copy import deepcopy
from datetime import date
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.acquisition import house
from congress_api.acquisition.house_fallback import CommitteeFallback, committee_websites, merge_documents, needs_fallback
from congress_api.models.content import RawContent, content_bytes
from congress_api.models.house import HouseParsedRecord
from congress_api.parsers.committee_pages import calendar_links, discovery_links, match_event, parse_event_page
from congress_api.parsers.document_links import document_links
from congress_api.parsers.house import parsed
from congress_api.retention.tables import read_state, write_state

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory'
HOME = 'https://energycommerce.house.gov/'
PAGE = HOME + 'events/health-subcommittee-examining-policies-to-enhance-seniors-access-to-breakthrough-medical-technologies'
ROYSE = 'https://d1dth6e84htgma.cloudfront.net/09_18_2025_HE_Hearing_Witness_Testimony_Royse_1_25e99f5986.pdf'
BODY = (FIXTURES / 'house-energycommerce-event.html').read_bytes()
CALENDAR = (FIXTURES / 'house-energycommerce-calendar.json').read_bytes()
MEETING = dict(eventId='118632', congress=119, chamber='House', date='2025-09-18T13:45:00Z',
    title='Examining Policies to Enhance Seniors’ Access to Breakthrough Medical Technologies', type='Hearing',
    committees=[dict(systemCode='hsif14')], updateDate='2025-09-18T00:00:00Z', meetingStatus='Scheduled')
DIRECTORY = [dict(congress=119, committee=dict(systemCode='hsif00', chamber='House'),
                  detail=dict(systemCode='hsif00', committeeWebsiteUrl=HOME))]


def empty():
    return parsed(None, None, '', 'unfetched')


def retained(pages=None):
    return {'energycommerce.house.gov': dict(pages={url: parse_event_page(body, url)
        for url, body in (pages or {PAGE: BODY}).items()}, coverage={'status': 'discovered_queue_exhausted'})}


def client(pages=None):
    pages = {HOME: b'<html><h1>Committee</h1></html>', HOME + 'api/events': CALENDAR, PAGE: BODY, **(pages or {})}
    calls = []
    def request(url, receipts, **kwargs):
        calls.append((url, kwargs))
        body = pages.get(url)
        if isinstance(body, Exception):
            raise body
        status = 200 if body is not None else 404
        receipt = dict(url=url, status_code=status, outcome='retrieved' if status == 200 else 'not_found', completed_at='2026-10-07T06:00:00Z')
        if body is not None:
            receipt['content'] = RawContent.from_bytes(body, 'application/json' if kwargs else 'text/html').source_dict()
        receipts.append(receipt)
        return SimpleNamespace(status_code=status, content=body or b'', url=url)
    return request, calls


def test_real_embedded_event_yields_royse_and_nine_other_documents():
    links = document_links(BODY, PAGE)
    assert len(links) == 10
    royse, = [link for link in links if link.url == ROYSE]
    assert royse.source_selector == '__NEXT_DATA__/props/pageProps/event/agenda/0/info'
    assert 'Testimony' in royse.text
    assert match_event(BODY, PAGE, MEETING)['method'] == 'same_committee_date_title'


def test_shared_parser_ignores_unrelated_json_and_survives_bad_json():
    page = b'''<a href="/keep.pdf">Keep</a><script id="__NEXT_DATA__">oops</script>
      <script type="application/ld+json">{"@graph":null}</script>
      <script>{"link":"https://bad.test/unrelated.pdf"}</script>'''
    assert [link.url for link in document_links(page, HOME)] == [HOME + 'keep.pdf']
    data = {'props': {'pageProps': {'recommended': {'info': '<a href="/unrelated.pdf">No</a>'}}}}
    assert document_links(('<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>').encode(), HOME) == []


@pytest.mark.parametrize('change', [dict(date='2025-09-19'), dict(title='A completely different subject and purpose')])
def test_event_match_refuses_wrong_date_or_title(change):
    assert match_event(BODY, PAGE, {**MEETING, **change}) is None


def test_event_index_link_is_not_evidence_all_its_documents_belong_to_one_meeting():
    body = b'<h1>Events</h1><a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=118632">Hearing</a><a href="/other.pdf">Other</a>'
    assert match_event(body, PAGE, MEETING) is None
    mixed = BODY.replace(b'</body>', b'<a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=999">Other hearing</a></body>')
    assert match_event(mixed, PAGE, MEETING) is None


def test_official_directory_is_congress_scoped_and_uses_parent_code():
    request, calls = client()
    fallback = CommitteeFallback(DIRECTORY, retained())
    assert fallback.find(MEETING)['status'] == 'matched'
    assert fallback.find({**MEETING, 'congress': 118})['status'] == 'no_official_website'
    assert not committee_websites([{**DIRECTORY[0], 'detail': {'committeeWebsiteUrl': 'https://unofficial.example/'}}])
    assert not committee_websites([{**DIRECTORY[0], 'committee': {'systemCode': 'hsif00', 'chamber': 'Senate'}}])


def test_retained_fallback_does_not_fetch_and_keeps_exact_source():
    fallback = CommitteeFallback(DIRECTORY, retained())
    report = fallback.find(MEETING)
    assert report['status'] == 'matched'
    assert report['pages'][0]['url'] == PAGE
    check = report['checks'][report['pages'][0]['check_index']]
    assert content_bytes(check['content']) == BODY
    assert check['mode'] == 'retained'
    assert fallback.find(MEETING) == report


def test_ambiguous_pages_and_uncollected_sites_do_not_become_absence():
    report = CommitteeFallback(DIRECTORY, retained({PAGE: BODY, PAGE + '-alternate': BODY})).find(MEETING)
    assert report['status'] == 'ambiguous' and not report['pages']
    report = CommitteeFallback(DIRECTORY, {}).find(MEETING)
    assert report['status'] == 'not_found_in_retained_pages'
    assert report['coverage']['energycommerce.house.gov']['status'] == 'not_collected'


def test_other_committee_page_cannot_supply_fallback_evidence():
    report = CommitteeFallback(DIRECTORY, retained({'https://other.house.gov/events/wrong': BODY})).find(MEETING)
    assert not report['pages']


def test_merge_retains_xml_and_separate_publisher_context_without_summary_duplicates():
    request, _ = client()
    report = CommitteeFallback(DIRECTORY, retained()).find(MEETING)
    saved = parsed((FIXTURES / 'house-multiple-files.xml').read_bytes(), None, '', 'absent')
    primary = deepcopy(saved['evidence']['document_groups'])
    merge_documents(saved, report)
    assert saved['evidence']['document_groups'][:len(primary)] == primary
    assert HouseParsedRecord.model_validate(saved).source_dict() == saved
    once = deepcopy(saved)
    merge_documents(saved, report)
    assert saved == once
    group, = [g for g in saved['evidence']['document_groups'] if g.get('source_url') == PAGE and g['files'][0]['url'] == ROYSE]
    assert 'owning_witness_selector' not in group  # No invented witness ownership.
    assert group['metadata']['link']['source_selector'].endswith('/agenda/0/info')
    from congress_api.retention.document_index import DocumentSources
    index = DocumentSources()
    index.add_house({'118632': saved})
    sources = index.for_url(ROYSE)
    assert sources['source_page_url'] == [PAGE]
    assert sources['source_page_sha256'] == [group['source_sha256']]
    from test_house_source_fidelity import adapt
    assert ROYSE in {loc.url for row in adapt(saved) if row.kind == 'representation' for loc in row.locations}


def test_fetch_primary_complete_skips_fallback_and_missing_xml_uses_it(monkeypatch):
    full = empty()
    full.update(status='xml', documents=[['statement', 'Testimony', 'https://docs.house.gov/test.pdf', []]])
    monkeypatch.setattr(house, '_fetch', lambda *args: deepcopy(full))
    request, calls = client()
    fallback = CommitteeFallback(DIRECTORY, retained())
    assert house.fetch(MEETING, {}, fallback=fallback)['documents'] == full['documents']
    assert not calls
    monkeypatch.setattr(house, '_fetch', lambda *args: empty())
    saved = house.fetch(MEETING, {}, fallback=fallback)
    assert saved['status'] == 'page' and saved['repository_status'] == 'absent'
    assert saved['last_check']['outcome'] == 'present'
    assert ROYSE in {d[2] for d in saved['documents']}


def test_failed_url_forces_fallback_but_alternate_is_not_identity_repair(monkeypatch):
    broken = 'https://docs.house.gov/broken.pdf'
    full = empty()
    full.update(status='xml', documents=[['statement', 'Testimony', broken, []]])
    monkeypatch.setattr(house, '_fetch', lambda *args: deepcopy(full))
    request, calls = client()
    saved = house.fetch(MEETING, {}, fallback=CommitteeFallback(DIRECTORY, retained()), failed_urls={broken})
    assert saved['committee_fallback']['reason'] == 'known_failed_document'
    assert broken in {d[2] for d in saved['documents']} and ROYSE in {d[2] for d in saved['documents']}


def test_refresh_error_preserves_prior_fallback_evidence(monkeypatch):
    request, _ = client()
    previous = empty()
    merge_documents(previous, CommitteeFallback(DIRECTORY, retained()).find(MEETING))
    previous['status'] = 'page'
    previous['page_status'] = 'committee_fallback'
    previous['retrieved_at'] = '2026-10-06T00:00:00Z'
    original = deepcopy(previous)
    monkeypatch.setattr(house, '_fetch', lambda *args: empty())
    failing, _ = client({HOME + 'api/events': RuntimeError('outage'), PAGE: RuntimeError('outage')})
    saved = house.fetch(MEETING, previous, fallback=CommitteeFallback(DIRECTORY, {}))
    assert saved['committee_fallback_check']['status'] == 'not_found_in_retained_pages'
    assert saved['committee_fallback'] == original['committee_fallback']
    assert saved['documents'] == original['documents']
    assert previous == original


def test_primary_error_with_matched_fallback_is_explicit_and_without_it_raises(monkeypatch):
    def broken(*args):
        raise ValueError('Invalid XML')
    monkeypatch.setattr(house, '_fetch', broken)
    request, _ = client()
    saved = house.fetch(MEETING, {}, fallback=CommitteeFallback(DIRECTORY, retained()))
    assert saved['last_check']['outcome'] == 'error'
    assert saved['repository_status'] == 'error'
    assert ROYSE in {d[2] for d in saved['documents']}
    check = {}
    with pytest.raises(ValueError, match='Invalid XML'):
        house.fetch(MEETING, {}, fallback=CommitteeFallback([], retained()), check=check)
    assert check['committee_fallback']['status'] == 'no_official_website'


def test_offline_keeps_saved_pages_and_never_requests(tmp_path, monkeypatch):
    meetings = tmp_path / 'meetings.jsonl.gz'
    meetings.write_bytes(gzip.compress((json.dumps(MEETING) + '\n').encode()))
    request, _ = client()
    saved = empty()
    merge_documents(saved, CommitteeFallback(DIRECTORY, retained()).find(MEETING))
    saved.update(checked='2026-10-07', version=MEETING['updateDate'])
    write_state(tmp_path / 'house.json.gz', {'118632': saved})
    (tmp_path / 'missing.csv').write_text('package_id,event_id\n')
    def forbidden(*args, **kwargs):
        pytest.fail('Offline collector attempted HTTP')
    monkeypatch.setattr(house, 'request', forbidden)
    house.main(meetings, tmp_path / 'missing.csv', tmp_path, tmp_path, offline=True, as_of=date(2026, 10, 7))
    assert read_state(tmp_path / 'house.json.gz')['118632'] == saved
    assert ROYSE in (tmp_path / 'house_documents_found.csv').read_text()


def test_fallback_bodies_use_existing_bundle_separation_and_exact_restore():
    from test_raw_bundle_extraction import extract
    from congress_api.retention.bundles import restore
    request, _ = client()
    saved = empty()
    merge_documents(saved, CommitteeFallback(DIRECTORY, retained()).find(MEETING))
    record, captures, bodies = extract(saved)
    assert restore(record, captures, bodies.__getitem__) == saved
    match, = [capture for capture in captures if capture.get('context_url') == PAGE]
    assert match['fidelity'] == 'exact-bytes'
    assert BODY in bodies.values()


def test_main_uses_retained_directory_and_forces_known_failures_through_normal_outputs(tmp_path, monkeypatch):
    broken = 'https://docs.house.gov/broken.pdf'
    meeting = {**MEETING, 'witnesses': [{'name': 'Witness'}],
               'meetingDocuments': [{'url': broken, 'documentType': 'Hearing Transcript', 'name': 'Hearing Transcript'}]}
    assert not house.lacking(meeting, [])
    meetings = tmp_path / 'meetings.jsonl.gz'
    meetings.write_bytes(gzip.compress((json.dumps(meeting) + '\n').encode()))
    directory = tmp_path / 'congress_committees.jsonl.gz'
    directory.write_bytes(gzip.compress((json.dumps(DIRECTORY[0]) + '\n').encode()))
    gpo = tmp_path / 'gpo.csv'
    gpo.write_text('package_id,event_id\n')
    full = empty()
    full.update(status='xml', documents=[['statement', 'Testimony', broken, []]])
    monkeypatch.setattr(house, '_fetch', lambda *args: deepcopy(full))
    request, calls = client()
    monkeypatch.setattr(house, 'request', lambda url, zyte, checks, **kwargs: request(url, checks, **kwargs))
    write_state(tmp_path / 'house-sites.json.gz', retained())
    house.main(meetings, gpo, tmp_path, tmp_path, failed_urls=[broken], as_of=date(2026, 10, 7))
    saved = read_state(tmp_path / 'house.json.gz')['118632']
    assert saved['committee_fallback']['reason'] == 'known_failed_document'
    assert ROYSE in (tmp_path / 'house_documents_found.csv').read_text()
    assert not calls  # XML fallback reads the retained shared collection.


def test_duplicate_xml_url_keeps_both_observations_but_one_compact_row():
    request, _ = client()
    report = CommitteeFallback(DIRECTORY, retained()).find(MEETING)
    saved = empty()
    saved['documents'] = [['statement', 'Primary label', ROYSE, []]]
    saved['evidence']['document_groups'] = [dict(source='meeting_xml', selector='/primary', files=[dict(url=ROYSE)])]
    merge_documents(saved, report)
    assert sum(d[2] == ROYSE for d in saved['documents']) == 1
    assert len([g for g in saved['evidence']['document_groups'] if g['files'][0]['url'] == ROYSE]) == 2


def test_calendar_rejects_unrecognized_shapes_and_unsafe_slugs():
    with pytest.raises(ValueError, match='Unrecognized'):
        calendar_links(b'{"error":"upstream"}', HOME)
    data = {'events_connection': {'nodes': [dict(slug='../foreign'), dict(slug='safe', title='Hearing')]}}
    assert calendar_links(json.dumps(data).encode(), HOME) == [(HOME + 'events/safe', 'Hearing')]


def test_new_retained_page_supplements_recent_xml_check_without_another_request(tmp_path, monkeypatch):
    meetings = tmp_path / 'meetings.jsonl.gz'
    meetings.write_bytes(gzip.compress((json.dumps(MEETING) + '\n').encode()))
    directory = tmp_path / 'congress_committees.jsonl.gz'
    directory.write_bytes(gzip.compress((json.dumps(DIRECTORY[0]) + '\n').encode()))
    (tmp_path / 'gpo.csv').write_text('package_id,event_id\n')
    saved = empty(); saved.update(checked='2026-10-07', version=MEETING['updateDate'])
    write_state(tmp_path / 'house.json.gz', {'118632': saved})
    write_state(tmp_path / 'house-sites.json.gz', retained())
    monkeypatch.setattr(house, 'request', lambda *a, **k: pytest.fail('Unexpected HTTP'))
    house.main(meetings, tmp_path / 'gpo.csv', tmp_path, tmp_path, as_of=date(2026, 10, 7))
    saved = read_state(tmp_path / 'house.json.gz')['118632']
    assert saved['checked'] == '2026-10-07'
    assert ROYSE in {d[2] for d in saved['documents']}
    assert not saved.get('retrieved_at')  # No fabricated fresh fetch time.


def test_matched_empty_event_does_not_claim_document_recovery():
    body = b'<h1>Examining Policies to Enhance Seniors Access to Breakthrough Medical Technologies</h1><p>Date: September 18, 2025</p>'
    report = CommitteeFallback(DIRECTORY, retained({PAGE: body})).find(MEETING)
    assert report['status'] == 'matched_without_documents'
