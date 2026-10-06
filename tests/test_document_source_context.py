"""Original link occurrences remain paired through retained source relationships."""
import gzip
import json
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.parsers.senate_page import source_details
from congress_api.retention.document_index import DocumentSources, read_document_sources

PAGE = 'https://www.aging.senate.gov/hearings/care'
LINK = 'https://www.aging.senate.gov/download/sca_bart_11_15_19'
REQUESTED = LINK + '?download=1'
FAILED = 'https://www.aging.senate.gov/imo/media/doc/C91B8DD0-5056-A066-60B9-F84A2AAA981E/SCA_Bart_11_15_19.pdf'
CANDIDATE = 'https://www.aging.senate.gov/imo/media/doc/SCA_Bart_11_15_19.pdf'


def state(url=LINK, *, label='SCA_Bart_11_15_19', kind='other', digest='a' * 64):
    return {'aging.senate.gov': {'pages': {PAGE: {
        'title': 'Care hearing', 'cache_replay': {'raw_sha256': digest},
        'documents': [[kind, label, url]], 'document_labels': {url: label},
        'document_metadata': {url: {'labels': [label], 'headings': ['Witnesses'], 'witness_indexes': [0]}},
        'witnesses': [{'name': 'J. Bart Rose', 'position': 'Doctor', 'organization': 'University'}],
    }}}}


def failed_receipt():
    return {'url': REQUESTED, 'final_url': FAILED, 'http_status': 404, 'usable': False,
            'redirects': [{'url': REQUESTED, 'status': 302, 'location': FAILED}],
            'format': 'html', 'result': 'http_error', 'body_complete': True}


def candidate_receipt():
    return {'url': CANDIDATE, 'final_url': CANDIDATE, 'http_status': 200, 'usable': True,
            'source_associations': [{'original_url': REQUESTED,
                                     'basis': 'candidate_without_legacy_directory'}],
            'format': 'pdf', 'result': 'captured', 'body_complete': True}


def test_original_parent_hash_heading_and_inferred_type_stay_together():
    sources = DocumentSources()
    sources.add_senate(state())
    row = sources.for_url(LINK)
    occurrence, = row['source_occurrences']
    assert occurrence['source_page_url'] == [PAGE]
    assert occurrence['source_page_sha256'] == ['a' * 64]
    assert occurrence['source_link_url'] == [LINK]
    assert occurrence['source_link_label'] == ['SCA_Bart_11_15_19']
    assert occurrence['source_link_heading'] == ['Witnesses']
    assert occurrence['source_document_type'] == ['other']
    assert occurrence['source_document_type_basis'] == ['senate_parser_fallback']
    assert occurrence['source_occurrence_scope'] == ['retained_url_aggregate']
    assert not occurrence.get('source_label_document_kind')
    assert all(isinstance(v, set) for v in sources.by_url[LINK].values())


def test_shared_url_occurrences_keep_parent_titles_and_hashes_paired():
    sources = DocumentSources()
    sources.add_senate(state(digest='a' * 64))
    second = state(digest='b' * 64)
    page = second['aging.senate.gov']['pages'].pop(PAGE)
    page['title'] = 'Different hearing'
    second['aging.senate.gov']['pages'][PAGE + '-two'] = page
    sources.add_senate(second)
    sources.add_senate(second)  # Replay deduplicates the same occurrence.
    row = sources.for_url(LINK)
    assert row['source_page_sha256'] == ['a' * 64, 'b' * 64]
    assert {(tuple(o['source_page_url']), tuple(o['source_page_sha256'])) for o in row['source_occurrences']} == {
        ((PAGE,), ('a' * 64,)), ((PAGE + '-two',), ('b' * 64,))}


def test_each_anchor_keeps_its_own_label_heading_and_witness():
    raw = '<section><h2>Witnesses</h2><div class="vcard"><span class="fn">Jane Smith</span><h3>Jane attachment</h3><a href="/shared.pdf">Testimony</a></div><div class="vcard"><span class="fn">John Jones</span><h3>John attachment</h3><a href="/shared.pdf">Article</a></div></section>'
    people = [{'name': 'Jane Smith'}, {'name': 'John Jones'}]
    files, _, _ = source_details(raw, PAGE, people)
    shared = 'https://www.aging.senate.gov/shared.pdf'
    assert [(o['labels'], o['headings'], o['witness_indexes']) for o in files[shared]['occurrences']] == [
        (['Testimony'], ['Jane attachment'], [0]), (['Article'], ['John attachment'], [1])]
    sources = DocumentSources()
    sources.add_senate({'aging.senate.gov': {'pages': {PAGE: {'documents': [['other', 'aggregate', shared]],
        'document_metadata': files, 'witnesses': people}}}})
    occurrences = sources.for_url(shared)['source_occurrences']
    assert {(tuple(o['source_link_label']), tuple(o['source_witness_name'])) for o in occurrences} == {
        (('Testimony',), ('Jane Smith',)), (('Article',), ('John Jones',))}
    assert all(o['source_occurrence_scope'] == ['anchor'] for o in occurrences)


def test_publisher_api_type_is_distinct_from_senate_parser_type():
    sources = DocumentSources()
    sources.add_meeting({'eventId': '1', 'congress': 119, 'chamber': 'Senate', '_url': 'https://api.test/meeting',
                        'meetingDocuments': [{'url': LINK, 'documentType': 'Support Document'}]})
    sources.add_senate(state(kind='witness statement'))
    observations = sources.for_url(LINK)['source_occurrences']
    assert {(tuple(o['source_document_type']), tuple(o['source_document_type_basis'])) for o in observations} == {
        (('Support Document',), ('publisher',)), (('witness statement',), ('senate_parser_inference',))}


def test_failed_publisher_redirect_keeps_origin_without_claiming_document_identity():
    sources = DocumentSources()
    sources.add_senate(state(REQUESTED))
    sources.add_redirect(failed_receipt())
    row = sources.for_url(FAILED)
    occurrence, = row['source_occurrences']
    assert occurrence['source_link_url'] == [REQUESTED]
    assert occurrence['source_page_sha256'] == ['a' * 64]
    assert occurrence['source_association_basis'] == ['publisher_redirect']
    assert occurrence['source_associated_url'] == [REQUESTED]
    assert not {'document_id', 'body_key', 'usable', 'document_kind'} & row.keys()
    assert sources.for_url(CANDIDATE) == {}


def test_recovery_candidate_preserves_basis_and_exact_associated_url():
    sources = DocumentSources()
    sources.add_senate(state(REQUESTED))
    sources.add_associations(candidate_receipt())
    row = sources.for_url(CANDIDATE)
    occurrence, = row['source_occurrences']
    assert occurrence['source_association_basis'] == ['candidate_without_legacy_directory']
    assert occurrence['source_associated_url'] == [REQUESTED]
    assert occurrence['source_link_url'] == [REQUESTED]
    assert occurrence['source_page_url'] == [PAGE]
    assert 'publisher_redirect' not in row['source_association_basis']
    assert sources.for_url(FAILED) == {}
    assert sources.for_url(CANDIDATE.replace('SCA_', 'Other_')) == {}


@pytest.mark.parametrize('original, targets, basis', [
    ('https://www.lis.gov/cgi-lis/t2GPO/https://www.gpo.gov/fdsys/pkg/BILLS-114hr456ih/pdf/BILLS-114hr456ih.pdf',
     ['https://www.gpo.gov/fdsys/pkg/BILLS-114hr456ih/pdf/BILLS-114hr456ih.pdf'], 'lis_gpo_wrapper'),
    ('https://example.gov/a.xmlhttps://example.gov/b.xml',
     ['https://example.gov/a.xml', 'https://example.gov/b.xml'], 'concatenated_file_urls'),
])
def test_repaired_links_preserve_literal_source_and_association_in_catalog(original, targets, basis):
    from congress_api.parsers.archive_links import capture_links
    sources = DocumentSources()
    receipt = {'source_receipt_key': ['receipts/source.json.gz'], 'source_receipt_line': ['1']}
    for link in capture_links({'url': original, 'parent_url': PAGE, 'text': 'Publisher label'}):
        sources.add_link(link, receipt)
    for target in targets:
        row = sources.for_url(target)
        assert row['source_link_url'] == [original]
        assert row['source_link_label'] == ['Publisher label']
        assert row['source_association_basis'] == [basis]
        assert row['source_associated_url'] == [original]
        assert row['source_page_url'] == [PAGE]
        assert row['source_receipt_key'] == receipt['source_receipt_key']
        assert 'publisher_redirect' not in row['source_association_basis']
    # Later source context follows the same established recovery relationship.
    sources.add_url(original, {'source_document_type': {'Support Document'}})
    assert all(sources.for_url(target)['source_document_type'] == ['Support Document'] for target in targets)


@pytest.mark.parametrize('label,expected', [('Amy Berman - Article', ['article']), ('Dr. Gawande - Op-Ed', ['op-ed']),
    ('Article', ['article']), ('Report on article use', None), ('SCA_testimony_article.pdf', None),
    ('Support Document', None), ('Download testimony', None), ('Article about testimony', None)])
def test_source_label_signal_is_bounded_and_does_not_retype_native_other(label, expected):
    sources = DocumentSources()
    sources.add_senate(state(label=label))
    row = sources.for_url(LINK)
    assert row.get('source_label_document_kind') == expected
    assert row['source_document_type'] == ['other']
    assert 'document_kind' not in row


def test_archive_reads_migration_candidate_receipts_and_retained_download_links(tmp_path):
    (tmp_path / 'indexes').mkdir()
    records = [
        ('senate/pages', 'old/senate.json.gz', state()),
        ('documents', 'old/documents/receipts.jsonl', candidate_receipt()),
        ('documents', 'old/documents/linked/receipts.jsonl', failed_receipt()),
    ]
    download_html = f'<h1>Download File</h1><a href="{REQUESTED}">Download File</a>'.encode()
    digest = sha256(download_html).hexdigest()
    body_key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    path = tmp_path / body_key
    path.parent.mkdir(parents=True)
    with gzip.open(path, 'wb') as f:
        f.write(download_html)
    records.append(('documents', 'old/documents/receipts.jsonl', {
        'url': LINK, 'final_url': LINK, 'http_status': 200, 'usable': False,
        'format': 'html_requires_document_discovery', 'result': 'unresolved_response',
        'sha256': digest, 'raw_path': 'old-download.html.gz'}))
    captures = []
    with gzip.open(tmp_path / 'receipts.jsonl.gz', 'wt') as f:
        for n, (family, source_file, record) in enumerate(records, 1):
            f.write(json.dumps({'record': record}) + '\n')
            captures.append(dict(family=family, source_file=source_file, receipt_key='receipts.jsonl.gz',
                                 receipt_line=n, body_key=body_key if n == 4 else None,
                                 context_url=LINK if n == 4 else None))
    pq.write_table(pa.Table.from_pylist(captures), tmp_path / 'indexes/captures.parquet')
    sources = read_document_sources(tmp_path, {FAILED, CANDIDATE})
    for url, basis in [(FAILED, 'publisher_redirect'), (CANDIDATE, 'candidate_without_legacy_directory')]:
        row = sources.for_url(url)
        assert row['source_page_url'] == [PAGE]
        occurrences = row['source_occurrences']
        assert any(o['source_link_url'] == [LINK] and basis in o['source_association_basis'] for o in occurrences)
        assert all(o.get('source_receipt_key') for o in occurrences)
    assert sources.for_url(CANDIDATE)['source_associated_url'] == sorted([LINK, REQUESTED])


def test_restored_paired_occurrences_do_not_create_a_cross_product():
    sources = DocumentSources()
    old = {'source_page_url': ['https://one.test', 'https://two.test'],
           'source_page_sha256': ['a' * 64, 'b' * 64],
           'source_occurrences': [
               {'source_page_url': ['https://one.test'], 'source_page_sha256': ['a' * 64]},
               {'source_page_url': ['https://two.test'], 'source_page_sha256': ['b' * 64]}]}
    sources.add_url(LINK, old)
    assert len(sources.for_url(LINK)['source_occurrences']) == 2
    assert all(len(o['source_page_url']) == 1 for o in sources.for_url(LINK)['source_occurrences'])


def test_inventory_native_and_inferred_types_are_separate_paired_claims():
    sources = DocumentSources()
    sources.add_inventory({'url': LINK, 'observations': [{
        'page_url': PAGE, 'kind': 'other', 'native': {'documentType': 'Support Document'}}]})
    row = sources.for_url(LINK)
    assert row['source_document_type'] == ['Support Document', 'other']
    assert {(tuple(o['source_document_type']), tuple(o['source_document_type_basis']))
            for o in row['source_occurrences']} == {
                (('Support Document',), ('publisher',)), (('other',), ('inventory_inference',))}


def test_original_html_hash_is_paired_with_html_parent_not_confirmed_api_url():
    sources = DocumentSources()
    api = 'https://api.test/committee-meeting/1'
    sources.add_meeting({'eventId': '1', 'congress': 119, 'chamber': 'Senate', '_url': api})
    raw = state()
    raw['aging.senate.gov']['pages'][PAGE]['events'] = ['1']
    sources.add_senate(raw)
    row = sources.for_url(LINK)
    occurrence, = row['source_occurrences']
    assert row['source_page_url'] == sorted([PAGE, api])
    assert occurrence['source_original_page_url'] == [PAGE]
    assert occurrence['source_page_sha256'] == ['a' * 64]


def test_duplicate_archive_receipts_keep_one_original_occurrence_and_representative_locator():
    sources = DocumentSources()
    sources.add_senate(state(), {'source_receipt_key': {'original.jsonl.gz'}, 'source_receipt_line': {'4'}})
    sources.add_senate(state(), {'source_receipt_key': {'copied.jsonl.gz'}, 'source_receipt_line': {'500'}})
    occurrence, = sources.for_url(LINK)['source_occurrences']
    assert occurrence['source_receipt_key'] == ['original.jsonl.gz']
    assert occurrence['source_receipt_line'] == ['4']


def test_candidate_redirect_keeps_unverified_basis_and_original_parent_receipt():
    sources = DocumentSources()
    sources.add_senate(state(REQUESTED), {'source_receipt_key': {'parent.jsonl.gz'}, 'source_receipt_line': {'7'}})
    sources.add_associations(candidate_receipt(), {'source_receipt_key': {'recovery.jsonl.gz'}, 'source_receipt_line': {'40'}})
    final = 'https://cdn.test/recovered.pdf'
    sources.add_redirect({'url': CANDIDATE, 'final_url': final, 'http_status': 200},
                         {'source_receipt_key': {'download.jsonl.gz'}, 'source_receipt_line': {'90'}})
    row = sources.for_url(final)
    assert row['source_association_basis'] == ['candidate_without_legacy_directory', 'publisher_redirect']
    assert row['source_associated_url'] == sorted([REQUESTED, CANDIDATE])
    occurrence, = row['source_occurrences']
    assert occurrence['source_receipt_key'] == ['parent.jsonl.gz']
    assert occurrence['source_receipt_line'] == ['7']


def test_meeting_receipt_locators_do_not_accumulate_in_inherited_context():
    sources = DocumentSources()
    meeting = {'eventId': '1', 'congress': 119, 'chamber': 'Senate', '_url': 'https://api.test/meeting'}
    for line in range(30):
        sources.add_meeting(meeting, {'source_receipt_key': {'meetings.jsonl.gz'}, 'source_receipt_line': {str(line)}})
    assert not any(key.startswith('source_receipt_') for key in sources.event_context('1'))
    sources.add_link({'url': LINK, 'parent_url': meeting['_url'], 'text': 'Linked file'})
    assert not sources.for_url(LINK).get('source_receipt_key')
