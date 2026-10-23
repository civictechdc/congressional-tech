"""Bill labels within witness testimony sections retain their document meaning."""
from hashlib import sha256
import gzip
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.parsers.senate import parsed
from congress_api.retention.document_index import DocumentSources, fill_document_kind, read_document_sources

PAGE = 'https://www.indian.senate.gov/hearings/legislative-hearing-receive-testimony-following-bills-s-817-s-818-s-1436-s-1761-s-1822-s/'
LINK = 'https://www.indian.senate.gov/sites/default/files/upload/files/10.7.15%20Michael%20Smith%20H.R.%20387.pdf'
RAW = (Path(__file__).parent/'fixtures/meeting_inventory/senate-indian-testimony.html').read_text()


def test_real_bill_links_in_testimony_paragraphs_keep_label_and_witness():
    page = parsed(RAW, PAGE)
    assert len(page['witnesses']) == 2
    document = next(d for d in page['documents'] if d[2] == LINK)
    assert document == ('witness statement', 'H.R.387', LINK)
    occurrence, = page['document_metadata'][LINK]['occurrences']
    assert occurrence['headings'] == ['Testimony on the Following Bills:']
    assert occurrence['witness_indexes'] == [0]
    context = DocumentSources()
    context.add_senate({'indian.senate.gov': {'pages': {PAGE: page}}})
    row = context.for_url(LINK)
    fill_document_kind(row)
    assert row['document_kind'] == ['witness-statement']
    assert row['source_link_label'] == ['H.R.387']
    assert row['source_witness_name'] == ['Michael Smith']
    assert row['source_document_type_basis'] == ['publisher_section_heading']
    assert {d[0] for d in page['documents']} == {'witness statement'}


@pytest.mark.parametrize('tag,label', [('h2','Testimony'), ('h3','Witness Testimony'),
    ('strong','Testimony on the Following Bills:'), ('b','Testimony on the Following Bills :')])
def test_scoped_testimony_labels(tag, label):
    wrapper = 'p' if tag in ('strong', 'b') else 'section'
    raw = f'<{wrapper}><{tag}>{label}</{tag}> <a href="/download/opaque.pdf">H.R.387</a></{wrapper}>'
    assert parsed(raw, PAGE)['documents'][0][0] == 'witness statement'


@pytest.mark.parametrize('raw', [
    '<p><strong>Testimony on the Following Bills:</strong><a href="/download/first.pdf">H.R.387</a></p><p><a href="/download/opaque.pdf">Attachment</a></p>',
    '<p>Read about <strong>Testimony</strong><a href="/download/opaque.pdf">Attachment</a></p>',
    '<section><h2>Hearing to receive testimony on bills</h2><a href="/download/opaque.pdf">Bill</a></section>',
    '<section><h2>Testimony</h2></section><section><a href="/download/opaque.pdf">Bill</a></section>',
    '<p><strong>Testimony:</strong><a href="/download/first.pdf">H.R.387</a><strong>Related Bills:</strong><a href="/download/opaque.pdf">Bill</a></p>',
    '<div class="paragraph--witness"><h2>Testimony</h2></div><div class="paragraph--witness"><a href="/download/opaque.pdf">Bill</a></div>',
])
def test_testimony_labels_do_not_leak_to_other_material(raw):
    doc = next(d for d in parsed(raw, PAGE)['documents'] if d[2].endswith('/opaque.pdf'))
    assert doc[0] == 'other'


@pytest.mark.parametrize('available,status', [(True,200),(False,200),(True,403)])
def test_independent_retained_html_capture_supplies_missing_context(tmp_path, available, status):
    digest = sha256(RAW.encode()).hexdigest()
    key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    if available:
        path = tmp_path/key
        path.parent.mkdir(parents=True)
        path.write_bytes(gzip.compress(RAW.encode()))
    final = LINK.replace('/sites/default/files/', '/wp-content/uploads/')
    # The legacy state has no HTML digest. The separate capture is another
    # real observation, not an invented replacement for the old state.
    legacy = {'title':'Legislative hearing', 'witnesses':[], 'documents':[['other','H.R.387',LINK]]}
    records = [({'indian.senate.gov':{'pages':{PAGE:legacy}}}, 'senate/pages', 'old/senate.json.gz', None, None),
               ({'url':PAGE,'status_code':status,'raw_sha256':digest}, 'senate/pages', 'old/pages/receipts.jsonl', key, PAGE),
               ({'url':LINK,'final_url':final,'http_status':200}, 'documents', 'old/documents/receipts.jsonl', None, None)]
    captures = []
    with gzip.open(tmp_path/'receipts.jsonl.gz','wt') as f:
        for i,(record,family,source_file,body,url) in enumerate(records,1):
            f.write(json.dumps({'record':record})+'\n')
            captures.append(dict(family=family,source_file=source_file,receipt_key='receipts.jsonl.gz',
                                 receipt_line=i,body_key=body,context_url=url,http_status=status if body else None))
    (tmp_path/'indexes').mkdir()
    pq.write_table(pa.Table.from_pylist(captures), tmp_path/'indexes/captures.parquet')
    context = read_document_sources(tmp_path, {final})
    row = context.for_url(final)
    fill_document_kind(row)
    if available and status == 200:
        assert row['document_kind'] == ['witness-statement']
        assert row['source_witness_name'] == ['Michael Smith']
        observed = [o for o in row['source_occurrences'] if o.get('source_page_sha256') == [digest]]
        assert len(observed) == 1
        assert observed[0]['source_receipt_line'] == ['2']
        assert observed[0]['source_link_label'] == ['H.R.387']
        assert observed[0]['source_link_heading'] == ['Testimony on the Following Bills:']
        assert observed[0]['source_association_basis'] == ['publisher_redirect']
    else:
        assert row['document_kind'] is None
