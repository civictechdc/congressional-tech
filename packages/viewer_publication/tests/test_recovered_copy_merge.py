"""A recovered copy byte-identical to a published document is another address of it (owner, 2026-11-02).

The r1b run listed 4,060 recovery-only rows whose recovered body was already a published
document's body, 44 of them with neither filename nor title (democrats-edworkforce
`download/?id=GUID` links recovered by the docs.house.gov witness statement). The merge must
keep every signal: the dead link stays an address with its own listing page and link text,
its recovery record and keys move to the copy, and a document field the copy lacks is filled
from the recovered link while a differing one stays on that link's annotation.
"""
import gzip
import hashlib
import json
import os

import pyarrow.parquet as pq

from congress_api.lake import filenames, readings
from congress_api.lake.capture_staging import stage_captures
from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets

DOCS = 'https://docs.house.gov/meetings/ED/ED13/20251210/118730/'
COPY_A = DOCS + 'HHRG-119-ED13-Wstate-DiDonatoG-20251210.pdf'
COPY_B = DOCS + 'HHRG-119-ED13-Wstate-CheneyS-20251210.pdf'
DEM = 'https://democrats-edworkforce.house.gov/'
DEAD_A = DEM + 'download/?id=B6029D49-F86F-497E-B2E7-94CB6D9D0E6C'
DEAD_B1 = DEM + 'download/?id=3E01B60E-DB14-4D82-AF8D-35AE87A6F00F'
DEAD_B2 = DEM + 'download/?id=E5E09AD6-3AD2-4777-A5D6-9A0B01E81097'
DEAD_EXCERPT = DEM + 'uploadedfiles/didonato_hearing_excerpt.pdf'
COMMITTEE_PAGE = DEM + 'hearings/building-a-talent-marketplace'
DOCS_PAGE = 'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=118730'
WORDS = 'The subcommittee heard testimony on learning and employment records and talent marketplaces. ' * 30


def _page(title, links):
    items = ''.join(f'<li><a href="{href}">{text}</a></li>' for href, text in links)
    return f'<html><head><title>{title}</title></head><body><main><p>{WORDS}</p><ul>{items}</ul></main></body></html>'.encode()


def _release(tmp_path):
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw = tmp_path / 'raw'
    pdf_a = b'%PDF-1.7\nTestimony of Greg DiDonato before the Subcommittee\n%%EOF\n'
    pdf_b = b'%PDF-1.7\nTestimony of Scott Cheney before the Subcommittee\n%%EOF\n'
    committee = _page('Building a Talent Marketplace | Democrats', [(DEAD_A, 'Testimony of Greg DiDonato'),
        (DEAD_B1, 'Testimony of Scott Cheney'), (DEAD_B2, 'Cheney written testimony'), (DEAD_EXCERPT, 'DiDonato hearing excerpt')])
    docs = _page('Committee Repository', [(COPY_A, 'Mr. Greg DiDonato, EBSCOed (Testimony)')])

    def entry(content, fmt):
        compress = fmt == 'html'
        stored = gzip.compress(content, mtime=0) if compress else content
        digest = hashlib.sha256(content).hexdigest()
        suffix = '.gz' if compress else ''
        path = raw / f'bodies/sha256/{digest[:2]}/{digest}{suffix}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stored)
        return dict(sha256=digest, bytes=len(content), media_type='text/html' if compress else 'application/pdf', fidelity='exact-bytes',
            sniffed_format=fmt, sniff_version=readings.current_version('sniff'), intact=True if fmt == 'pdf' else None,
            stored_suffix=suffix, stored_bytes=len(stored), stored_md5=hashlib.md5(stored).hexdigest())

    def fetch(url, content=None, fmt='html', status=200):
        return dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents',
            outcome='stored' if content else 'failed', requested_url=url, url=url, response_headers={}, http_status=status,
            complete=True, retrieved_at='2026-10-12T14:25:11Z', captures=[entry(content, fmt)] if content else [])

    def recovered(original, content, category, copy_url):
        return dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='retained_import', family='documents',
            outcome='saved', requested_url=copy_url, url=copy_url, response_headers={}, http_status=200, complete=True,
            retrieved_at='2026-10-15T13:43:02Z', source_associations=[dict(original_url=original, basis='user_accepted_url_variant')],
            recovery_evidence=dict(original_url=original, imported_at='2026-10-15T14:00:50Z', match_basis='user_accepted_url_variant',
                acquisition=dict(prior_access_category=category, recovered_url=copy_url, source='user_accepted_recovery')),
            captures=[entry(content, 'pdf')])

    lines = [fetch(COMMITTEE_PAGE, committee), fetch(DOCS_PAGE, docs), fetch(COPY_A, pdf_a, 'pdf'), fetch(COPY_B, pdf_b, 'pdf'),
        *(fetch(url, status=410) for url in (DEAD_A, DEAD_B1, DEAD_B2, DEAD_EXCERPT)),
        recovered(DEAD_A, pdf_a, 'recovered_document', COPY_A),
        # Two dead links whose recovered copy is the same published body (the Cheney case).
        recovered(DEAD_B1, pdf_b, 'recovered_document', COPY_B), recovered(DEAD_B2, pdf_b, 'recovered_document', COPY_B),
        # Same bytes, but the link asked for an excerpt of the hearing record: not a copy, its own document.
        recovered(DEAD_EXCERPT, pdf_a, 'requested_content_in_official_hearing', COPY_A)]
    receipt = raw / 'receipts/documents/2026-10-15/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(''.join(json.dumps(r) + '\n' for r in lines).encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / 'pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
    decisions = tmp_path / 'recoveries.jsonl'
    decisions.write_text(''.join(json.dumps(dict(id=f'decision-{i}', body_sha256=hashlib.sha256(content).hexdigest(), original_url=original,
        recovered_filename=None, recovered_url=copy_url, kind=kind, identity_note=None, decided_at='2026-10-27T15:46:39Z', supersedes=None,
        recovery_record_version=2)) + '\n' for i, (original, content, kind, copy_url) in enumerate([
            (DEAD_A, pdf_a, 'recovered_document', COPY_A), (DEAD_B1, pdf_b, 'recovered_document', COPY_B),
            (DEAD_B2, pdf_b, 'recovered_document', COPY_B), (DEAD_EXCERPT, pdf_a, 'requested_content_in_official_hearing', COPY_A)])))
    recovery_files = [dict(key='provenance/recoveries/fixture.jsonl', path=str(decisions))]
    captures = stage_captures([dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(pin))],
        engine=engine, work=tmp_path / 'stage') / 'captures.parquet'
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(inventory, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[], outputs=[parquet_output(inventory, 'bodies',
        """SELECT DISTINCT sha256 AS body_sha,'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,stored_bytes
        FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
    pages = readings.stage(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw, engine=engine,
        work=tmp_path / 'read', decided_at='2026-10-27T12:00:00Z', parser='html')
    names = filenames.stage(captures=captures, recovery_files=recovery_files, engine=engine, work=tmp_path / 'names', decided_at='2026-10-27T12:00:00Z')
    build_release(captures=captures, readings=pages['readings'], filename_readings=names['readings'], recovery_files=recovery_files,
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}, catalog_version=names['catalog_version'],
        engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    release = tmp_path / 'release'
    read = lambda name: pq.read_table(release / f'{name}.parquet').to_pylist()
    return {name: read(name) for name in ('detail', 'links', 'urls', 'sources', 'recoveries')}, \
        json.loads((tmp_path / 'model/result.json').read_text()), (pdf_a, pdf_b)


def _url_key(url):
    return hashlib.sha256(('url:' + url).encode()).digest()[:8]


def test_a_recovered_copy_is_another_address_of_the_published_document(tmp_path):
    files, result, (pdf_a, pdf_b) = _release(tmp_path)
    details = files['detail']
    row = lambda body: next(i for i, d in enumerate(details) if d['saved_body'] == hashlib.sha256(body).digest() and d['saved_kind'] == 'original')
    a, b = row(pdf_a), row(pdf_b)
    links = {r['link_key']: r['list_row'] for r in files['links']}
    recoveries = lambda list_row: sorted((r['kind'], r['recovered_url']) for r in files['recoveries'] if r['list_row'] == list_row)
    sources = lambda list_row: {r['url']: r for r in files['sources'] if r['list_row'] == list_row}

    # An exact copy attaches: no recovery-only row; its key, lookup and recovery record resolve to the copy.
    assert links[_url_key(DEAD_A)] == a
    assert recoveries(a) == [('recovered_document', COPY_A)]
    # The dead link stays an address with its own listing page and link text (the committee page's
    # title), while the copy keeps the docs.house.gov title.
    assert sources(a)[DEAD_A]['listed_on'] == COMMITTEE_PAGE and sources(a)[DEAD_A]['link_text'] == 'Testimony of Greg DiDonato'
    assert sources(a)[DEAD_A]['is_saved'] is False and sources(a)[COPY_A]['is_saved'] is True
    assert details[a]['title'] == 'Mr. Greg DiDonato, EBSCOed (Testimony)'
    assert details[a]['filename'] == 'HHRG-119-ED13-Wstate-DiDonatoG-20251210.pdf'

    # Two dead links recovering one body both attach; the copy had no title, so a link's text fills it.
    assert links[_url_key(DEAD_B1)] == b and links[_url_key(DEAD_B2)] == b
    assert recoveries(b) == [('recovered_document', COPY_B)] * 2
    assert {DEAD_B1, DEAD_B2} <= set(sources(b))

    # A recovery of another kind with the same bytes stays its own document.
    excerpt = links[_url_key(DEAD_EXCERPT)]
    assert details[excerpt]['saved_kind'] == 'recovery' and excerpt != a
    assert [d['saved_kind'] for d in details].count('recovery') == 1

    queries = {q['name']: q['data'] for q in result['queries']}
    assert queries['model_invariants'][0]['unaccounted_merged_signal'] == 0
    merged = queries['merged_recovery_fields'][0]
    assert (merged['merged_links'], merged['merged_documents']) == (3, 2)
    # One Cheney link's text fills the copy's missing title; the other link's text and the
    # committee page's DiDonato title differ from the shown title and stay on their links.
    assert (merged['title_filled'], merged['title_conflicting']) == (1, 2)
    assert details[b]['title'] == 'Cheney written testimony'


def test_the_merge_audit_names_each_signal_a_merged_link_would_lose(tmp_path):
    """The audit reads the published relations: a link the document does not list as an address,
    key, lookup or recovery, or whose committee key and title the document shows nowhere, is lost."""
    from congress_api.retention.provenance import json_input, list_of, struct
    from viewer_publication.archive_model import LOST_FLAGS, MERGED_RECOVERY_SQL
    strings = list_of('Utf8')
    facts = list_of(struct(field='Utf8', value='Utf8'))
    ann = dict(title=None, reading_title=None, listing_title=None, congress=None, filename_date=None, content_date=None, package_id=None,
               document_kind=[], document_family=[], committee_keys=[], chambers=[], meeting_keys=[], measure_keys=[], bioguide_ids=[], facts=[])
    kept, lost = DEAD_B1, DEAD_A
    inputs = [
        json_input(tmp_path, 'recovered_copy_members', [dict(source_id='kept', component='c'), dict(source_id='lost', component='c')],
                   source_id='Utf8', component='Utf8'),
        json_input(tmp_path, 'document_members', [dict(source_id='kept', component='c', source_url=kept, filename=''),
                   dict(source_id='lost', component='c', source_url=lost, filename=''), dict(source_id='copy', component='c', source_url=COPY_A, filename='a.pdf')],
                   source_id='Utf8', component='Utf8', source_url='Utf8', filename='Utf8'),
        json_input(tmp_path, 'source_annotations', [dict(ann, source_id='kept', title='Shown title'),
                   dict(ann, source_id='lost', title='Committee title', committee_keys=['HSED13']), dict(ann, source_id='copy')],
                   source_id='Utf8', title='Utf8', reading_title='Utf8', listing_title='Utf8', congress='Int32', filename_date='Date32',
                   content_date='Date32', package_id='Utf8', document_kind=strings, document_family=strings, committee_keys=strings,
                   chambers=strings, meeting_keys=strings, measure_keys=strings, bioguide_ids=strings, facts=facts),
        json_input(tmp_path, 'document_identities', [dict(component='c', document_id='doc')], component='Utf8', document_id='Utf8'),
        json_input(tmp_path, 'ordered', [dict(doc_key='doc', list_row=0, filename='a.pdf', title='Shown title', congress=None, document_date=None,
                   package_id=None, document_kind=[], document_family=[], committee_keys=[], chambers=[], meeting_keys=[], measure_keys=[],
                   bioguide_ids=[], facts=[])], doc_key='Utf8', list_row='Int32', filename='Utf8', title='Utf8', congress='Int16',
                   document_date='Date32', package_id='Utf8', document_kind=strings, document_family=strings, committee_keys=strings,
                   chambers=strings, meeting_keys=strings, measure_keys=strings, bioguide_ids=strings, facts=facts),
        json_input(tmp_path, 'saved_files', [dict(component='c', source_id='copy', filename='a.pdf', saved_rank=1)],
                   component='Utf8', source_id='Utf8', filename='Utf8', saved_rank='Int64'),
        json_input(tmp_path, 'source_rows', [dict(list_row=0, url=COPY_A), dict(list_row=0, url=kept)], list_row='Int32', url='Utf8'),
        json_input(tmp_path, 'lookup_sources', [dict(list_row=0, url=kept)], list_row='Int32', url='Utf8'),
        json_input(tmp_path, 'current_recoveries', [dict(original_url=u, body_sha='b' * 64) for u in (kept, lost)], original_url='Utf8', body_sha='Utf8'),
        json_input(tmp_path, 'recovery_rows', [dict(list_row=0, original_url=kept, body_hex='b' * 64)], list_row='Int32', original_url='Utf8', body_hex='Utf8')]
    steps = [dict(name='links', sql=f"SELECT decode(substr(encode(sha256('url:{kept}'),'hex'),1,16),'hex') AS link_key,cast(0 AS INT) AS list_row"),
             dict(name='recovery_rows_typed', sql="SELECT list_row,original_url,decode(body_hex,'hex') AS body FROM recovery_rows")]
    sql = MERGED_RECOVERY_SQL.replace('recovery_rows r ON', 'recovery_rows_typed r ON')
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='a', sql=f"SELECT source_id,{','.join('lost_' + f for f in LOST_FLAGS)} FROM ({sql}) g ORDER BY source_id")])
    rows = {row.pop('source_id'): {k for k, v in row.items() if v} for row in result['a']}
    assert rows == {'kept': set(), 'lost': {'lost_address', 'lost_link', 'lost_lookup', 'lost_recovery', 'lost_committees'}}
