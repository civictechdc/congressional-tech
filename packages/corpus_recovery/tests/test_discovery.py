import pytest
from corpus_recovery.discovery import Response, webharvest_lookup, acquire_wayback, relocated_search, govinfo_document_candidate
from webharvest_cdx import key, parse_cdx

TARGET = 'https://example.gov/report.pdf'
K = key(TARGET)
ROW = f'{K} 20200102030405 {TARGET} application/pdf 200 ABC - - 123 0 file\n'.encode()

def lookup(pages, limit=2):
    calls = []
    def call(kind, url):
        calls.append((kind, url))
        return pages[len(calls)-1]
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
    assert acquire_wayback(replay, TARGET, '20200102030405', lambda *_: response(data)).body == data
    for bad in [replay.replace('web.archive.org', 'evil.example'), replay.replace('20200102030405', '20210102030405'), replay.replace('report.pdf', 'other.pdf')]:
        with pytest.raises(ValueError):
            acquire_wayback(bad, TARGET, '20200102030405', lambda *_: response(data))

def test_scoped_deduplicated_search_and_limits():
    calls=[]
    def search(q, page):
        calls.append((q,page))
        return {'complete': True, 'evidence': 'search-receipt', 'candidates': [TARGET, 'https://example.gov/new.pdf', 'https://outside.gov/new.pdf', 'https://example.gov/new.pdf'], 'next_page': None}
    result=relocated_search(TARGET, ['report', 'report'], {'example.gov'}, search, {TARGET}, max_queries=1, max_pages=1, max_candidates=2)
    assert result['complete'] and len(calls)==1 and [c['url'] for c in result['candidates']]==['https://example.gov/new.pdf']
    result=relocated_search(TARGET, ['report', 'other'], {'example.gov'}, search, set(), max_queries=1, max_pages=1, max_candidates=1)
    assert not result['complete'] and result['reason'] == 'candidate_limit'

def test_govinfo_identifier_mismatch():
    assert govinfo_document_candidate(TARGET, 'CDOC-105hdoc123', expected_package_id='CDOC-105hdoc124') is None
    assert govinfo_document_candidate(TARGET, 'CDOC-105hdoc123', expected_package_id='CDOC-105hdoc123')['url'].endswith('/CDOC-105hdoc123.pdf')
