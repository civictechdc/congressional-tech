import base64
from dataclasses import replace
import hashlib
import json
import os
import subprocess
import sys
import pytest
from corpus_recovery.discovery import (Response, webharvest_lookup, wayback_lookup, acquire_wayback,
    acquire_candidates, house_listing_candidate, relocated_search, govinfo_document_candidate, govinfo_bill_candidate)
from corpus_recovery.cdx import key, parse_cdx
from corpus_recovery.discovery import campaign_lookup

TARGET = 'https://example.gov/report.pdf'
K = key(TARGET)
ROW = f'{K} 20200102030405 {TARGET} application/pdf 200 ABC - - 123 0 file\n'.encode()

def lookup(pages, limit=2):
    calls = []
    def call(kind, url):
        calls.append((kind, url))
        return replace(pages[len(calls)-1], final_url=url)
    result = webharvest_lookup(TARGET, 'congress118th', call, parse_cdx=parse_cdx, url_key=key, max_pages=limit)
    return result, calls

def response(body=b'', status=200, complete=True):
    return Response(status, body, complete, 'receipt', 'text/plain')

def test_cdx_pages_and_negative():
    result, calls = lookup([response(ROW + b'\nabc\n'), response()])
    assert result['complete'] and len(calls) == 2 and 'resumeKey=abc' in calls[1][1]
    assert result['candidates'][0]['url'].endswith('20200102030405id_/' + TARGET)
    assert lookup([response()])[0]['complete']

def test_partial_denied_and_invalid_are_not_negative():
    for page in [response(status=403), response(complete=False), response(b'<html>denied</html>'), response(ROW + b'\nabc\n')]:
        assert not lookup([page], 1)[0]['complete']
    assert lookup([response(ROW + b'\nabc\n')], 1)[0]['reason'] == 'page_limit'

def test_wayback_binary_identity():
    replay = 'https://web.archive.org/web/20200102030405id_/' + TARGET
    data = b'%PDF-1.7\x00\xff'
    assert acquire_wayback(replay, TARGET, '20200102030405', lambda *_: Response(200, data, True, 'receipt', final_url=replay)).body == data
    for bad in [replay.replace('web.archive.org', 'evil.example'), replay.replace('20200102030405', '20210102030405'), replay.replace('report.pdf', 'other.pdf')]:
        with pytest.raises(ValueError):
            acquire_wayback(bad, TARGET, '20200102030405', lambda *_: response(data))

def test_scoped_deduplicated_search_and_limits():
    calls=[]
    def search(q, page, hosts):
        assert hosts == ('example.gov',)
        calls.append((q,page))
        return {'complete': True, 'evidence': 'search-receipt', 'candidates': [TARGET, 'https://example.gov/new.pdf', 'https://outside.gov/new.pdf', 'https://example.gov/new.pdf'], 'next_page': None}
    result=relocated_search(TARGET, ['report', 'report'], {'example.gov'}, search, {TARGET}, max_queries=1, max_pages=1, max_candidates=4)
    assert result['complete'] and len(calls)==1 and [c['url'] for c in result['candidates']]==['https://example.gov/new.pdf']
    result=relocated_search(TARGET, ['report', 'other'], {'example.gov'}, search, set(), max_queries=1, max_pages=1, max_candidates=1)
    assert not result['complete'] and result['reason'] == 'candidate_limit'

def test_govinfo_identifier_mismatch():
    assert govinfo_document_candidate(TARGET, 'CDOC-105hdoc123', expected_package_id='CDOC-105hdoc124', evidence='source:1') is None
    assert govinfo_document_candidate(TARGET, 'CDOC-105hdoc123', expected_package_id='CDOC-105hdoc123', evidence='source:1')['url'].endswith('/CDOC-105hdoc123.pdf')
    assert govinfo_document_candidate(TARGET, 'CDOC-105hdoc123', expected_package_id='CDOC-105hdoc123', evidence='') is None


def test_wayback_rejects_unknown_or_changed_final_url():
    replay = 'https://web.archive.org/web/20200102030405id_/' + TARGET
    for final_url in [None, replay.replace('report.pdf', 'other.pdf')]:
        with pytest.raises(ValueError):
            acquire_wayback(replay, TARGET, '20200102030405', lambda *_: Response(200, b'data', True, 'receipt', final_url=final_url))

def test_bill_package_preserves_version():
    identity = {'congress': 118, 'bill_type': 'hr', 'number': 123, 'version': 'ih'}
    candidate = govinfo_bill_candidate(TARGET, 118, 'hr', 123, 'ih', source_identity=identity, evidence='source:1')
    assert candidate['package_id'] == 'BILLS-118hr123ih'
    assert govinfo_bill_candidate(TARGET, 118, 'hr', 123, 'enr', source_identity=identity, evidence='source:1') is None


FIELDS = ['urlkey', 'timestamp', 'original', 'mimetype', 'statuscode', 'digest', 'length']

def wayback_page(rows=(), resume=None):
    data = [FIELDS, *rows]
    if resume:
        data.extend([[], [resume]])
    return json.dumps(data).encode()

def test_wayback_pagination_resume_and_replay_digest():
    body = b'%PDF-1.7\x00\xff'
    digest = base64.b32encode(hashlib.sha1(body).digest()).decode()
    row = [K, '20200102030405', TARGET, 'application/pdf', '200', digest, str(len(body))]
    pages = iter([wayback_page([row], 'abc%2F+!'), wayback_page()])
    calls = []
    def capture(kind, url):
        calls.append((kind, url))
        return Response(200, next(pages), True, f'receipt:{len(calls)}', final_url=url)
    found = wayback_lookup(TARGET, capture, max_pages=2, from_timestamp='2020', to_timestamp='2020')
    assert found['complete'] and len(found['evidence']) == 2 and 'resumeKey=' in calls[1][1]
    candidate = found['candidates'][0]
    capture_body = lambda kind, url: Response(200, body, True, 'body:1', final_url=url)
    fetched = acquire_candidates([candidate, candidate], capture_body, allowed_targets={TARGET}, allowed_candidate_urls={candidate['url']}, seen_identities=set(), max_candidates=1)
    assert len(fetched['results']) == 1 and fetched['results'][0]['response'].body == body
    with pytest.raises(ValueError, match='digest mismatch'):
        acquire_wayback(candidate['url'], TARGET, candidate['timestamp'], lambda kind, url: Response(200, b'wrong', True, 'body:2', final_url=url), digest=digest)

def test_wayback_incomplete_denied_and_wrong_identity():
    wrong = [K, '20200102030405', 'https://example.gov/other.pdf', 'application/pdf', '200', '-', '0']
    wrong_urlkey = ['gov,other)/report.pdf', '20200102030405', TARGET, 'application/pdf', '200', '-', '0']
    non_200_row = [K, '20200102030405', TARGET, 'application/pdf', '404', '-', '0']
    bad_ts_row = [K, '20201302030405', TARGET, 'application/pdf', '200', '-', '0']
    out_of_window_row = [K, '20190102030405', TARGET, 'application/pdf', '200', '-', '0']
    for row in [wrong, wrong_urlkey, non_200_row, bad_ts_row]:
        res = wayback_lookup(TARGET, lambda kind, url: Response(200, wayback_page([row]), True, 'receipt', final_url=url), max_pages=1)
        assert not res['complete'] and res['reason'] == 'invalid_index_response' and res['candidates'] == []
    res_win = wayback_lookup(TARGET, lambda kind, url: Response(200, wayback_page([out_of_window_row]), True, 'receipt', final_url=url), max_pages=1, from_timestamp='2020', to_timestamp='2020')
    assert not res_win['complete'] and res_win['reason'] == 'invalid_index_response' and res_win['candidates'] == []
    res_redirect = wayback_lookup(TARGET, lambda kind, url: Response(200, wayback_page(), True, 'receipt', final_url='https://evil.example/cdx'), max_pages=1)
    assert not res_redirect['complete'] and res_redirect['reason'] == 'incomplete_response'
    res_429 = wayback_lookup(TARGET, lambda kind, url: Response(429, b'', True, 'receipt', final_url=url), max_pages=1)
    assert not res_429['complete'] and res_429['reason'] == 'denied'
    valid_row = [K, '20200102030405', TARGET, 'application/pdf', '200', '-', '0']
    res_page_limit = wayback_lookup(TARGET, lambda kind, url: Response(200, wayback_page([valid_row], 'next-token'), True, 'receipt', final_url=url), max_pages=1)
    assert not res_page_limit['complete'] and res_page_limit['reason'] == 'page_limit' and len(res_page_limit['candidates']) == 1
    for body, status, complete in [(wayback_page([wrong]), 200, True), (b'bad', 200, True), (b'', 403, True), (b'', 200, False)]:
        result = wayback_lookup(TARGET, lambda kind, url: Response(status, body, complete, 'receipt', final_url=url), max_pages=1)
        assert not result['complete']
    result = wayback_lookup(TARGET, lambda kind, url: Response(200, wayback_page(resume='again'), True, 'receipt', final_url=url), max_pages=2)
    assert not result['complete'] and result['reason'] == 'repeated_resume_key'

def test_house_listing_and_bounded_raw_consumer():
    xml = 'https://docs.house.gov/billsthisweek/20170710/BILLS%20-115HR2810-RCP115-23.xml'
    pdf = xml[:-4] + '.pdf'
    listing = 'https://docs.house.gov/meetings/AG/index.xml'
    kwargs = dict(listing_url=listing, listing_urls=[xml, pdf], evidence='listing:1', target_version='RCP115-23', candidate_version='RCP115-23')
    assert house_listing_candidate(xml, pdf, **kwargs)['url'] == pdf
    assert house_listing_candidate(xml, pdf, **{**kwargs, 'candidate_version': 'other'}) is None
    assert house_listing_candidate(xml, pdf, **{**kwargs, 'listing_urls': [xml]}) is None
    pages = []
    def capture(kind, url):
        pages.append((kind, url))
        return Response(200, ROW, True, 'index:1', 'text/plain', final_url=url)
    result = campaign_lookup(TARGET, 'congress118th', capture, max_pages=1)
    assert result['complete'] and len(pages) == 1
    item = result['candidates'][0]
    item['digest'] = '-'
    other = {**item, 'url': item['url'].replace('20200102030405', '20200102030406'), 'timestamp': '20200102030406'}
    out = acquire_candidates([item, item, {**item, 'target_url': 'https://outside.gov/'}, other], capture, allowed_targets={TARGET}, allowed_candidate_urls={item['url'], other['url']}, seen_identities=set(), max_candidates=1)
    assert len(out['results']) == 1 and out['limited'] and len(pages) == 2
    assert acquire_candidates([item], capture, allowed_targets={TARGET}, allowed_candidate_urls={item['url']}, seen_identities={item['url']}, max_candidates=1)['results'] == []
    assert acquire_candidates([item], capture, allowed_targets={TARGET}, allowed_candidate_urls=set(), seen_identities=set(), max_candidates=1)['results'] == []

def test_cdx_resume_trailer_and_redirect_refusal():
    assert parse_cdx(ROW + b'\norg%2Carchive%29%2F+20200101%21\n')[1] == 'org%2Carchive%29%2F+20200101%21'
    result = webharvest_lookup(TARGET, 'congress118th', lambda kind, url: Response(200, ROW, True, 'receipt', final_url='https://elsewhere.invalid/'), parse_cdx=parse_cdx, url_key=key, max_pages=1)
    assert not result['complete'] and not result['candidates']

def test_search_limits_and_uncertain_results():
    def partial(query, page, hosts):
        return {'complete': False, 'evidence': 'search:partial', 'candidates': [], 'next_page': None}
    result = relocated_search(TARGET, ['name'], {'example.gov'}, partial, set(), max_queries=1, max_pages=1, max_candidates=2)
    assert not result['complete'] and result['reason'] == 'incomplete_search'
    def repeated(query, page, hosts):
        return {'complete': True, 'evidence': 'search:page', 'candidates': [], 'next_page': 'same'}
    result = relocated_search(TARGET, ['name'], {'example.gov'}, repeated, set(), max_queries=1, max_pages=4, max_candidates=2)
    assert not result['complete'] and result['reason'] == 'repeated_page'
    result = relocated_search(TARGET, ['name', 'other'], {'example.gov'}, partial, set(), max_queries=2, max_pages=2, max_candidates=2, max_stems=1)
    assert not result['complete']

def test_capture_budget_and_restart_identity_prevent_dispatch():
    candidate = {'target_url': TARGET, 'original_url': TARGET, 'source': 'wayback', 'timestamp': '20200102030405',
                 'url': 'https://web.archive.org/web/20200102030405id_/' + TARGET, 'digest': '-'}
    journal = set()
    requests = []
    def capture(kind, url):
        requests.append(url)
        journal.add(url)  # The real capture owner must persist before dispatch.
        return Response(200, b'%PDF', True, 'attempt:1', final_url=url)
    acquire_candidates([candidate], capture, allowed_targets={TARGET}, allowed_candidate_urls={candidate['url']}, seen_identities=journal, max_candidates=1)
    acquire_candidates([candidate], capture, allowed_targets={TARGET}, allowed_candidate_urls={candidate['url']}, seen_identities=journal, max_candidates=1)
    assert requests == [candidate['url']]
    def exhausted(kind, url):
        raise RuntimeError('budget exhausted')
    with pytest.raises(RuntimeError, match='budget exhausted'):
        acquire_candidates([candidate], exhausted, allowed_targets={TARGET}, allowed_candidate_urls={candidate['url']}, seen_identities=set(), max_candidates=1)

def test_restart_reuses_first_page_when_capture_reconciles_it():
    stored = {}
    network_calls = []
    fail_once = True
    def capture(kind, url):
        nonlocal fail_once
        if url in stored:
            return stored[url]
        network_calls.append(url)
        if 'resumeKey=' in url and fail_once:
            fail_once = False
            raise RuntimeError('injected interruption')
        body = b'' if 'resumeKey=' in url else ROW + b'\nnext\n'
        stored[url] = Response(200, body, True, 'attempt:' + str(len(network_calls)), 'text/plain', final_url=url)
        return stored[url]
    with pytest.raises(RuntimeError, match='interruption'):
        campaign_lookup(TARGET, 'congress118th', capture, max_pages=2)
    assert campaign_lookup(TARGET, 'congress118th', capture, max_pages=2)['complete']
    assert len(network_calls) == 3 and network_calls[0] != network_calls[1] == network_calls[2]

def test_cli_fixture_replays_binary_and_makes_no_network_calls(tmp_path):
    body = b'%PDF-1.7\x00\xff'
    replay = 'https://webharvest.gov/congress118th/20200102030405id_/' + TARGET
    row = ROW.replace(b' ABC ', b' - ')
    page = lambda data, evidence: {'status': 200, 'complete': True, 'evidence': evidence,
                                    'body_base64': base64.b64encode(data).decode()}
    fixture = {'original': TARGET, 'collection': 'congress118th', 'max_pages': 1, 'max_candidates': 1,
               'pages': [page(row, 'index:1')], 'replays': {replay: page(body, 'body:1')}}
    path = tmp_path / 'fixture.json'
    path.write_text(json.dumps(fixture))
    result = subprocess.run([sys.executable, '-m', 'corpus_recovery.discovery', str(path)],
                            check=True, capture_output=True, text=True, env=os.environ.copy())
    output = json.loads(result.stdout)
    assert base64.b64decode(output['acquired'][0]['body_base64']) == body
