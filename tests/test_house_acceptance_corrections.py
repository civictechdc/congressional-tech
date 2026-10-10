"""Frozen source regressions; passing uncertainty guards is not audit acceptance.

The fixtures contain exact retained HTML and parent-adjudicated source evidence.
No destination content, redirect outcome, or repaired URL is assumed. The ten
unsafe confirmed references stay source metadata rather than downloadable files.
"""
import gzip
import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest

from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import parse_event_page
from congress_api.parsers.document_links import http_url


FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/acceptance-corrections'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text())
PAGES = {p['sample_id']: p for p in MANIFEST['pages']}
PAIRS = MANIFEST['confirmed_pairs']
CONTROLS = MANIFEST['unresolved_controls']
DOCUMENT_CASES = [c for c in PAIRS if c['policy'].startswith('retain_document')]
EXCLUDED_CASES = [c for c in PAIRS if c['policy'] == 'exclude_document']
SOURCE_ONLY_CASES = [c for c in PAIRS if c['policy'] == 'source_reference_only']


def sha256(value):
    return hashlib.sha256(value).hexdigest()


@lru_cache(maxsize=None)
def retained_body(sample_id):
    source = PAGES[sample_id]
    compressed = (FIXTURES / source['file']).read_bytes()
    assert sha256(compressed) == source['gzip_sha256']
    body = gzip.decompress(compressed)
    assert len(body) == source['body_bytes']
    assert sha256(body) == source['body_sha256']
    return body


@lru_cache(maxsize=None)
def parsed_page(sample_id):
    return parse_event_page(retained_body(sample_id), PAGES[sample_id]['url'])


def literal_hrefs(case):
    return {r['attributes']['href'] for r in case['source_references'] if 'href' in r['attributes']}


def source_links(case, page):
    return [link for link in page['page_metadata']['links']
            if link['attributes'].get('href') in literal_hrefs(case)]


def nested_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nested_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_dicts(child)


def source_labels(case):
    return {node['label'] for proof in case['evidence']
            for node in nested_dicts(proof['original_source_evidence'])
            if isinstance(node.get('label'), str)}


def test_frozen_confirmed_scope_and_separate_unknowns():
    assert len(PAIRS) == 113
    assert len({c['sample_id'] for c in PAIRS}) == 42
    assert len({(c['sample_id'], c['exact_target']) for c in PAIRS}) == 113
    # Two false promotions are also kind contradictions; do not double count.
    assert Counter(k for c in PAIRS for k in c['confirmed_categories']) == {
        'omitted_reference': 56, 'kind_contradiction': 51, 'false_document_promotion': 8}
    assert Counter(c['policy'] for c in PAIRS) == {
        'retain_document': 46, 'retain_document_without_contradiction': 49,
        'exclude_document': 8, 'source_reference_only': 10}
    assert len(CONTROLS) == 10
    assert len({c['sample_id'] for c in CONTROLS}) == 5
    assert all(c['status'] == 'unresolved' and c['semantic_acceptance'] is False for c in CONTROLS)


@pytest.mark.parametrize('sample_id', sorted(PAGES))
def test_exact_retained_html_survives_parsing(sample_id):
    assert content_bytes(parsed_page(sample_id)['raw_html']) == retained_body(sample_id)


@pytest.mark.parametrize('case', PAIRS + CONTROLS, ids=lambda c: c['case_id'])
def test_literal_source_regions_and_parent_evidence(case):
    source = retained_body(case['sample_id']).decode('utf-8')
    assert case['source_references']
    for ref in case['source_references']:
        start, end = ref['raw_char_range']
        assert source[start:end] == ref['source_start_tag']
        assert sha256(source[start:end].encode()) == ref['raw_start_tag_sha256']
    for proof in case['evidence']:
        assert proof['original_source_evidence']
        assert proof['source_file_sha256'] and proof['record_sha256']
        statuses = {j['original_judgment']['status'] for j in proof['parent_judgments']}
        assert statuses == ({'unresolved'} if case in CONTROLS else {'confirmed'})


@pytest.mark.parametrize('case', DOCUMENT_CASES, ids=lambda c: c['case_id'])
def test_source_designated_target_is_retained_without_confirmed_kind_error(case):
    page = parsed_page(case['sample_id'])
    target = case['exact_target']
    rows = [row for row in page['documents'] if row[2] == target]
    assert len(rows) == 1, (case['confirmed_finding_ids'], case['source_roles'], target)
    # The frozen criterion accepts broad "other". This test rejects the specific
    # source contradiction rather than imposing a new document-kind vocabulary.
    assert rows[0][0] not in case['forbidden_kinds'], case['source_roles']
    occurrences = page['document_metadata'][target]['occurrences']
    retained_hrefs = {attrs.get('href') for occurrence in occurrences
                      for attrs in occurrence['attributes']}
    assert literal_hrefs(case) <= retained_hrefs


@pytest.mark.parametrize('case', EXCLUDED_CASES, ids=lambda c: c['case_id'])
def test_repository_registration_and_coverage_are_not_documents(case):
    page = parsed_page(case['sample_id'])
    assert case['exact_target'] not in {d[2] for d in page['documents']}
    links = source_links(case, page)
    assert literal_hrefs(case) <= {link['attributes']['href'] for link in links}
    role = ('registration' if case['sample_id'] == 'p0727' else
            'related_coverage' if case['sample_id'] in {'p0011', 'p0758'} else 'repository')
    assert all(link.get('related_page', {}).get('role') == role for link in links)


@pytest.mark.parametrize('case', SOURCE_ONLY_CASES, ids=lambda c: c['case_id'])
def test_unsafe_source_designation_keeps_uncertainty_without_a_fetchable_url(case):
    page = parsed_page(case['sample_id'])
    target = case['exact_target']
    urls = {d[2] for d in page['documents']}
    assert target not in urls
    links = source_links(case, page)
    assert literal_hrefs(case) <= {link['attributes']['href'] for link in links}
    assert links and all(link['text'] in source_labels(case) for link in links)
    for link in links:
        designation = link.get('related_page', {})
        assert designation.get('role') == 'source_document_reference'
        assert designation.get('uncertainty') == case['uncertainty']
        assert designation.get('literal_href') == link['attributes']['href']
        assert 'url' not in designation
    if case['uncertainty'] == 'fragment_target':
        # Removing a fragment cannot turn this advisory reference into the site.
        bare_root = target.split('#')[0]
        assert bare_root not in urls and bare_root + '/' not in urls
        assert http_url(target) == bare_root
    else:
        assert http_url(target) is None
        # No replacement host is invented for the publisher's literal edit- host.
        assert not any(urlsplit(url).path == urlsplit(target).path for url in urls)


@pytest.mark.parametrize('case', [c for c in DOCUMENT_CASES if c['sample_id'] == 'p0029'],
                         ids=lambda c: c['case_id'])
def test_redirect_href_stays_distinct_from_displayed_pdf_address(case):
    page = parsed_page(case['sample_id'])
    urls = {d[2] for d in page['documents']}
    assert case['exact_target'] in urls
    # The PDF address is the source's visible label, not a fetched redirect result.
    displayed_addresses = {label for label in source_labels(case) if label.startswith('https://')}
    assert displayed_addresses
    assert displayed_addresses.isdisjoint(urls)


@pytest.mark.parametrize('case', CONTROLS, ids=lambda c: c['case_id'])
def test_unresolved_sources_do_not_gain_an_invented_identity(case):
    """Guard against fabrication only; the manifest retains each unresolved status."""
    page = parsed_page(case['sample_id'])
    documents = {d[2]: d[0] for d in page['documents']}
    target = case['exact_target']
    policy = case['policy']
    if policy == 'no_invented_bill_text':
        # A bill landing page does not independently establish a text attachment.
        assert documents.get(target) in {None, 'other'}
        assert source_links(case, page)
    elif policy in {'no_invented_image_document', 'no_stale_span_promotion'}:
        # Empty alt / stale non-anchor hrefs do not prove an applicable document.
        assert target not in documents
    elif policy == 'no_filename_override':
        # The parent left Testimony versus Testimony.Bio unresolved. Preserve
        # both literal clues; do not make either kind a passing semantic answer.
        assert target in documents
        assert 'Testimony' in source_labels(case)
        assert target.endswith('Schiff%20Testimony.Bio.pdf')
        detail = page['document_metadata'][target]
        assert 'Testimony' in detail['labels']
        assert literal_hrefs(case) <= {attrs.get('href') for occurrence in detail['occurrences']
                                      for attrs in occurrence['attributes']}
    elif policy == 'no_scheme_repair':
        assert http_url(target) is None
        assert target not in documents
        assert 'h' + target not in documents
        assert target.replace('ttp:', 'https:', 1) not in documents
        assert source_links(case, page)
    elif policy == 'no_markup_truncation_repair':
        literal, = literal_hrefs(case)
        assert http_url(literal, PAGES[case['sample_id']]['url']) is None
        invented_prefix = urljoin(PAGES[case['sample_id']]['url'], literal.split('</a>')[0])
        assert invented_prefix not in documents
        assert source_links(case, page)
    else:
        raise AssertionError(f'Unrecognized unresolved guard: {policy}')
