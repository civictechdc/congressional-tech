"""Only an explicit publication cover supplies a content-derived hearing kind."""
from pathlib import Path

import pytest

from congress_api.parsers.document_cover import document_cover, senate_hearing_citation
from congress_api.retention.document_evidence import enrich_document_covers
from congress_api.retention.document_index import fill_document_kind, refresh_source_metadata

PDF = (Path(__file__).parent / 'fixtures/meeting_inventory/senate-burma-hearing-cover.pdf').read_bytes()
COVER = '''U.S. GOVERNMENT PUBLISHING OFFICE
S. H RG. 117–16
U.S. RESPONSE TO THE COUP IN BURMA
HEARING
BEFORE THE
SUBCOMMITTEE ON EAST ASIA, THE PACIFIC, AND INTERNATIONAL CYBERSECURITY POLICY
OF THE
COMMITTEE ON FOREIGN RELATIONS
UNITED STATES SENATE
ONE HUNDRED SEVENTEENTH CONGRESS
FIRST SESSION'''


def test_actual_pdf_cover_yields_publication_identity():
    # First page of retained PDF 739cae101d58cb29a624a919816767f89d866fa7166ea7d8b9bb9f1f8dade6c8.
    assert document_cover(PDF) == {
        'content_document_kind': ['published-hearing'], 'content_citation': ['S. Hrg. 117-16']}


@pytest.mark.parametrize('text', [
    COVER.replace('S. H RG. 117–16', 'Reference: S. Hrg. 117–16'),
    COVER.replace('HEARING\nBEFORE THE', 'Prepared statement for the hearing before the'),
    COVER.replace('HEARING', 'REPORT'),
    COVER.replace('UNITED STATES SENATE', 'An unrelated institution'),
    COVER.replace('U.S. GOVERNMENT PUBLISHING OFFICE', 'Private publisher'),
    'Statement for the hearing on S. Hrg. 117–16', '',
])
def test_topic_words_and_references_do_not_establish_a_hearing_publication(text):
    assert senate_hearing_citation(text) is None


def test_spacing_and_former_printing_office_name():
    assert senate_hearing_citation(COVER) == 'S. Hrg. 117-16'
    assert senate_hearing_citation(COVER.replace('PUBLISHING', 'PRINTING').replace('S. H RG.', 'S. HRG.')) == 'S. Hrg. 117-16'


@pytest.mark.parametrize('body', [b'', b'<html>HEARING</html>', b'%PDF-1.4\ninvalid'])
def test_unreadable_or_non_pdf_contents_abstain(body):
    assert document_cover(body) == {}


def test_cover_in_a_later_appendix_does_not_classify_the_containing_pdf():
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_page(PdfReader(BytesIO(PDF)).pages[0])
    output = BytesIO()
    writer.write(output)
    assert document_cover(output.getvalue()) == {}


def test_cover_evidence_follows_identical_bytes_and_keeps_filename_kind():
    rows = [dict(filename='03 25 21 US Response to the Coup in Burma.pdf',
                 body_key='body', media_type=['application/pdf']),
            dict(filename='opaque', body_key='body', media_type=['application/pdf']),
            dict(filename='CHRG-117shrg44721.pdf', body_key='body', document_kind=['published-hearing'])]
    reads = []
    def read(key):
        reads.append(key)
        return PDF
    enrich_document_covers(rows, read_body=read)
    assert reads == ['body']
    for row in rows:
        fill_document_kind(row)
        assert row['document_kind'] == ['published-hearing']
        assert row['content_citation'] == ['S. Hrg. 117-16']
    assert rows[0]['document_kind_source'] == ['content']
    assert rows[2]['document_kind_source'] == ['filename']


def test_classified_or_failed_rows_do_not_trigger_pdf_extraction():
    rows = [dict(body_key='one', filename='x.pdf', document_kind=['witness-statement']),
            dict(body_key='two', filename='x.pdf', response_usable=['false']),
            dict(body_key='three', filename='x.pdf', record_role=['capture-state']),
            dict(body_key='four', filename='x.xml')]
    enrich_document_covers(rows, read_body=lambda _: pytest.fail('Must not parse this body'))
    assert all(not row.get('content_document_kind') for row in rows)


def test_source_refresh_persists_cover_metadata_and_preserves_identity(tmp_path):
    import gzip
    from hashlib import sha256
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.document_index import SOURCE_SCHEMA, STRINGS, write_document_indexes

    digest = sha256(PDF).hexdigest()
    key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    path = tmp_path / key
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(PDF))
    (tmp_path / 'indexes').mkdir()
    index = tmp_path / 'indexes/document-filenames.parquet'
    schema = pa.schema([*SOURCE_SCHEMA, ('document_kind', STRINGS)])
    write_document_indexes(index, [dict(filename='Burma.pdf', source_url='https://www.foreign.senate.gov/opaque',
                                      body_key=key, media_type=['application/pdf'], http_status=['200'])], schema)
    before, = pq.read_table(index).to_pylist()
    refresh_source_metadata(tmp_path)
    after, = pq.read_table(index).to_pylist()
    assert after['source_id'] == before['source_id']
    assert after['document_id'] == before['document_id']
    assert after['document_kind'] == ['published-hearing']
    assert after['document_kind_source'] == ['content']
    assert after['content_citation'] == ['S. Hrg. 117-16']
