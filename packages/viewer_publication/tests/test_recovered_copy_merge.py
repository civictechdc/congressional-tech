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
import shutil

import pyarrow.parquet as pq
import pytest

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
OVERSIGHT = 'https://oversightdemocrats.house.gov/imo/media/doc/'
BOWMAN_DEAD = OVERSIGHT + 'documents/Bowman%20Testimony.pdf'
BOWMAN_2012 = OVERSIGHT + 'Bowman%20Testimony.pdf'
BOWMAN_2018 = DEM + 'imo/media/doc/Bowman%20Testimony.pdf'
DEAD_C = DEM + 'download/?id=0C3A54D1-52B1-4E0B-9E0D-6B7C1B2F4A10'
COPY_C = DOCS + 'HHRG-119-ED13-Wstate-RussellD-20251210.pdf'
EARLIER, LATER = '2026-10-15T05:44:38Z', '2026-10-15T14:00:50Z'
WORDS = 'The subcommittee heard testimony on learning and employment records and talent marketplaces. ' * 30


def _page(title, links):
    items = ''.join(f'<li><a href="{href}">{text}</a></li>' for href, text in links)
    return f'<html><head><title>{title}</title></head><body><main><p>{WORDS}</p><ul>{items}</ul></main></body></html>'.encode()


def _entry(raw, content, fmt):
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


def _fetch(raw, url, content=None, fmt='html', status=200):
    return dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents',
        outcome='stored' if content else 'failed', requested_url=url, url=url, response_headers={}, http_status=status,
        complete=True, retrieved_at='2026-10-12T14:25:11Z', captures=[_entry(raw, content, fmt)] if content else [])


def _recovered(raw, original, content, category, copy_url, imported_at='2026-10-15T14:00:50Z', fmt='pdf'):
    return dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='retained_import', family='documents',
        outcome='saved', requested_url=copy_url, url=copy_url, response_headers={}, http_status=200, complete=True,
        retrieved_at='2026-10-15T13:43:02Z', source_associations=[dict(original_url=original, basis='user_accepted_url_variant')],
        recovery_evidence=dict(original_url=original, imported_at=imported_at, match_basis='user_accepted_url_variant',
            acquisition=dict(prior_access_category=category, recovered_url=copy_url, source='user_accepted_recovery')),
        captures=[_entry(raw, content, fmt)])


def _root(tmp_path, name, roles):
    """The model definitions with a recovered-file-roles registry of (original_url, content, role) entries."""
    from viewer_publication.archive_model_profile import ROOT, _definition_hashes
    root = tmp_path / name
    for relative in _definition_hashes(ROOT):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, root / relative)
    (root / 'model/registries/recovered-file-roles.json').write_text(json.dumps([dict(original_url=original,
        body_sha=hashlib.sha256(content).hexdigest(), role=role, evidence='fixture') for original, content, role in roles], indent=2))
    return root


def _stage(tmp_path, lines, decided):
    """Model inputs from receipt lines and (original, content, kind, copy_url) recovery decisions."""
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw = tmp_path / 'raw'
    receipt = raw / 'receipts/documents/2026-10-15/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(''.join(json.dumps(r) + '\n' for r in lines).encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / 'pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
    decisions = tmp_path / 'recoveries.jsonl'
    decisions.write_text(''.join(json.dumps(dict(id=f'decision-{i}', body_sha256=hashlib.sha256(content).hexdigest(), original_url=original,
        recovered_filename=None, recovered_url=copy_url, kind=kind, identity_note=None, decided_at='2026-10-27T15:46:39Z', supersedes=None,
        recovery_record_version=2)) + '\n' for i, (original, content, kind, copy_url) in enumerate(decided)))
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
    return dict(captures=captures, readings=pages['readings'], filename_readings=names['readings'], recovery_files=recovery_files,
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}, catalog_version=names['catalog_version'])


def _release_from(tmp_path, staged, root=None, name='release', scratch='model'):
    """Build one release from staged inputs, with the model definitions under `root` when given."""
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    build_release(**staged, engine=engine, output=tmp_path / name, scratch=tmp_path / scratch, **({'root': root} if root else {}))
    read = lambda table: pq.read_table(tmp_path / name / f'{table}.parquet').to_pylist()
    return {table: read(table) for table in ('detail', 'links', 'urls', 'sources', 'recoveries')}, \
        json.loads((tmp_path / scratch / 'result.json').read_text())


def _build(tmp_path, lines, decided):
    """A release from receipt lines and (original, content, kind, copy_url) recovery decisions."""
    return _release_from(tmp_path, _stage(tmp_path, lines, decided))


def _release(tmp_path):
    raw = tmp_path / 'raw'
    pdf_a = b'%PDF-1.7\nTestimony of Greg DiDonato before the Subcommittee\n%%EOF\n'
    pdf_b = b'%PDF-1.7\nTestimony of Scott Cheney before the Subcommittee\n%%EOF\n'
    committee = _page('Building a Talent Marketplace | Democrats', [(DEAD_A, 'Testimony of Greg DiDonato'),
        (DEAD_B1, 'Testimony of Scott Cheney'), (DEAD_B2, 'Cheney written testimony'), (DEAD_EXCERPT, 'DiDonato hearing excerpt')])
    docs = _page('Committee Repository', [(COPY_A, 'Mr. Greg DiDonato, EBSCOed (Testimony)')])
    decided = [(DEAD_A, pdf_a, 'recovered_document', COPY_A), (DEAD_B1, pdf_b, 'recovered_document', COPY_B),
        (DEAD_B2, pdf_b, 'recovered_document', COPY_B), (DEAD_EXCERPT, pdf_a, 'requested_content_in_official_hearing', COPY_A)]
    lines = [_fetch(raw, COMMITTEE_PAGE, committee), _fetch(raw, DOCS_PAGE, docs), _fetch(raw, COPY_A, pdf_a, 'pdf'), _fetch(raw, COPY_B, pdf_b, 'pdf'),
        *(_fetch(raw, url, status=410) for url in (DEAD_A, DEAD_B1, DEAD_B2, DEAD_EXCERPT)),
        # Two dead links whose recovered copy is the same published body (the Cheney case).
        *(_recovered(raw, original, content, kind, copy_url) for original, content, kind, copy_url in decided)]
    files, result = _build(tmp_path, lines, decided)
    return files, result, (pdf_a, pdf_b)


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


def test_a_link_is_an_address_only_of_the_file_its_own_row_shows(tmp_path):
    """ct-u9y4. One dead address was accepted with two recovered files that are different documents:
    Terry Bowman's 2012 Oversight testimony, from the same site, and his 2018 Education and
    Workforce testimony, the same file name on another committee's site. Once the 2018 file was
    fetched live the dead Oversight link became an address of it, and the link's key (published as
    cae8e4ea34ec603a) answered the 2018 file where it had answered the 2012 one. A link moves into
    a live document only through the file its own row shows, the first in the recovery order."""
    raw = tmp_path / 'raw'
    t2012 = b'%PDF-1.7\nTestimony of Terry Bowman before the Committee on Oversight, February 8, 2012\n%%EOF\n'
    t2018 = b'%PDF-1.7\nTestimony of Terry Bowman, Health, Employment, Labor and Pensions, April 26, 2018\n%%EOF\n'
    statement = b'%PDF-1.7\nTestimony of Deb Russell before the Subcommittee\n%%EOF\n'
    draft = b'%PDF-1.7\nAn earlier draft kept under the same link\n%%EOF\n'
    lines = [_fetch(raw, BOWMAN_2018, t2018, 'pdf'), _fetch(raw, COPY_C, statement, 'pdf'),
        *(_fetch(raw, url, status=410) for url in (BOWMAN_DEAD, DEAD_C)),
        _recovered(raw, BOWMAN_DEAD, t2012, 'recovered_document', BOWMAN_2012, LATER),
        _recovered(raw, BOWMAN_DEAD, t2018, 'recovered_document', BOWMAN_2018, EARLIER),
        # The same shape where the shown file is the live one: the link is that document's address,
        # whatever else was accepted for it.
        _recovered(raw, DEAD_C, statement, 'recovered_document', COPY_C, LATER),
        _recovered(raw, DEAD_C, draft, 'recovered_document', DEAD_C, EARLIER)]
    # Both rows hold two different files; a review must name them before the build publishes (ct-u9y4 item 4).
    reviewed = [(BOWMAN_DEAD, t2012), (BOWMAN_DEAD, t2018), (DEAD_C, statement), (DEAD_C, draft)]
    files, result = _release_from(tmp_path, _stage(tmp_path, lines, [(BOWMAN_DEAD, t2012, 'recovered_document', BOWMAN_2012)]),
        _root(tmp_path, 'root', [(original, content, 'undecided') for original, content in reviewed]))
    details = files['detail']
    sha = lambda content: hashlib.sha256(content).digest()
    links = {r['link_key']: r['list_row'] for r in files['links']}
    shown = lambda list_row: (details[list_row]['saved_kind'], details[list_row]['saved_body'])
    served = lambda list_row: {r['body'] for r in files['recoveries'] if r['list_row'] == list_row}
    addresses = lambda list_row: {r['url'] for r in files['sources'] if r['list_row'] == list_row}

    # Two rows, and each key answers its own file: the link's the 2012 testimony, the body key the 2018 one.
    link, live = links[_url_key(BOWMAN_DEAD)], links[sha(t2018)[:8]]
    assert link != live
    assert shown(link) == ('recovery', sha(t2012)) and shown(live) == ('original', sha(t2018))
    # The dead address is no address of the live file; it still resolves, to its own row (a
    # recovery-only row lists no source addresses, data model 7.8).
    assert addresses(live) == {BOWMAN_2018} and addresses(link) == set()
    lookup = hashlib.sha256(('lookup:' + BOWMAN_DEAD.removeprefix('https://')).encode()).digest()[:8]
    assert [r['list_row'] for r in files['urls'] if r['lookup_key'] == lookup] == [link]
    # Nothing published is dropped: the link's row still serves both files accepted for it.
    assert served(link) == {sha(t2012), sha(t2018)} and served(live) == set()

    # A link whose shown file is the live document stays merged, with both of its recoveries.
    merged = links[_url_key(DEAD_C)]
    assert merged == links[sha(statement)[:8]] and shown(merged) == ('original', sha(statement))
    assert {DEAD_C, COPY_C} <= addresses(merged) and served(merged) == {sha(statement), sha(draft)}
    assert [d['saved_kind'] for d in details].count('recovery') == 1
    queries = {q['name']: q['data'] for q in result['queries']}
    assert queries['model_invariants'][0]['unaccounted_merged_signal'] == 0
    # Both rows hold two different recovered files whose text the model has not read (PDFs): reported per build.
    assert queries['recovery_documents_with_several_files'] == [dict(agreement='text_unread', documents=2)]


def test_a_link_moves_through_its_shown_copy_or_one_with_the_same_text(tmp_path):
    """The recovered-copy links step alone (ct-u9y4, ct-jcnd item 3). Per dead link: the copies in the
    shared recovery order, excluding container ZIPs (archive_bodies and good_archive_containers) just as
    saved_recoveries_step() does, which of them is a published body, and their text fingerprints."""
    from congress_api.retention.provenance import json_input
    from viewer_publication.archive_provenance import recovered_copy_steps, saved_recoveries_step
    body = lambda name: hashlib.sha256(name.encode()).hexdigest()
    cases = {  # link: its recoveries as (body, kind, imported_at, published, fingerprint), then the bodies that move it
        'one-copy': ([('a', 'recovered_document', LATER, True, None)], ['a']),
        # Bowman: the shown copy is not published; the published one is a different file (PDFs carry no fingerprint).
        'two-documents': ([('x', 'recovered_document', LATER, False, None), ('y', 'recovered_document', EARLIER, True, None)], []),
        'shown-copy-published': ([('p', 'recovered_document', LATER, True, None), ('q', 'recovered_document', EARLIER, False, None)], ['p']),
        # Two captures of one page: other bytes, the same text.
        'same-text': ([('s1', 'recovered_document', LATER, False, 'f1'), ('s2', 'recovered_document', EARLIER, True, 'f1')], ['s2']),
        'other-text': ([('t1', 'recovered_document', LATER, False, 'f2'), ('t2', 'recovered_document', EARLIER, True, 'f3')], []),
        # A newer excerpt is not a copy and does not outrank the one recovered copy.
        'excerpt-beside-copy': ([('e1', 'requested_content_in_official_hearing', LATER, False, None), ('e2', 'recovered_document', EARLIER, True, None)], ['e2']),
        # ct-jcnd item 3: a newer container ZIP (in archive_bodies or good_archive_containers) is a source
        # container, not a shown recovery, so the link still moves through its older non-ZIP published copy.
        'zip-body-beside-copy': ([('z1', 'recovered_document', LATER, False, None), ('z2', 'recovered_document', EARLIER, True, None)], ['z2']),
        'zip-container-beside-copy': ([('zc1', 'recovered_document', LATER, False, None), ('zc2', 'recovered_document', EARLIER, True, None)], ['zc2']),
        'recording': ([('r1', 'full_recording_recovered', LATER, True, None)], ['r1']),
    }
    recoveries = [dict(id=f'{link}-{i}', kind=kind, original_url=DEM + link, body_sha=body(name), bytes=10, imported_at=at,
        receipt_key='receipts/documents/2026-10-15/slice.jsonl.gz', receipt_line=n, capture_index=0)
        for n, (link, i, (name, kind, at, _published, _print)) in enumerate((link, i, row) for link, (rows, _) in cases.items() for i, row in enumerate(rows))]
    zc1_line = next(r['receipt_line'] for r in recoveries if r['body_sha'] == body('zc1'))
    attachments = [dict(r, component=r['original_url'][len(DEM):], recovered_url=DOCS + r['id'], identity_note=None, role=None) for r in recoveries]
    files = [dict(source_id='link:' + link, body_sha=None, source_url=DEM + link, filename=link, is_real_file=False) for link in cases] + \
        [dict(source_id='file:' + name, body_sha=body(name), source_url=DOCS + name, filename=name, is_real_file=True)
         for rows, _ in cases.values() for name, _kind, _at, published, _print in rows if published]
    inputs = [
        json_input(tmp_path, 'model_recovery_rows', recoveries, id='Utf8', kind='Utf8', original_url='Utf8', body_sha='Utf8', bytes='Int64',
            imported_at='Utf8', receipt_key='Utf8', receipt_line='Int32', capture_index='Int32'),
        json_input(tmp_path, 'final_recovery_attachments', attachments, component='Utf8', id='Utf8', kind='Utf8', original_url='Utf8',
            body_sha='Utf8', bytes='Int64', imported_at='Utf8', receipt_key='Utf8', receipt_line='Int32', capture_index='Int32',
            recovered_url='Utf8', identity_note='Utf8', role='Utf8'),
        json_input(tmp_path, 'effective_filenames', [dict(input_id='recovery:' + r['id'], filename=r['original_url'][len(DEM):]) for r in recoveries],
            input_id='Utf8', filename='Utf8'),
        json_input(tmp_path, 'source_files', files, source_id='Utf8', body_sha='Utf8', source_url='Utf8', filename='Utf8', is_real_file='Boolean'),
        json_input(tmp_path, 'body_evidence', [dict(body_sha=r['body_sha'], original_size=10) for r in recoveries], body_sha='Utf8', original_size='Int64'),
        json_input(tmp_path, 'body_fingerprints', [dict(body_sha=body(name), fingerprint=mark) for rows, _ in cases.values()
            for name, _kind, _at, _published, mark in rows if mark], body_sha='Utf8', fingerprint='Utf8')]
    steps = [
        dict(name='archive_bodies', sql=f"SELECT arrow_cast(decode('{body('z1')}','hex'),'Binary') AS sha256"),
        dict(name='good_archive_containers', sql=f"SELECT 'receipts/documents/2026-10-15/slice.jsonl.gz' AS receipt_key,{zc1_line} AS receipt_line"),
        *recovered_copy_steps(),
        saved_recoveries_step(),
    ]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='moved', sql='SELECT source_id,body_sha FROM recovered_copy_links ORDER BY 1,2'),
                 dict(name='shown', sql='SELECT component,body_sha FROM saved_recoveries WHERE saved_rank=1 ORDER BY 1')])
    assert [(r['source_id'], r['body_sha']) for r in result['moved']] == \
        sorted(('link:' + link, body(name)) for link, (_rows, moves) in cases.items() for name in moves)
    shown = {r['component']: r['body_sha'] for r in result['shown']}
    assert shown['zip-body-beside-copy'] == body('z2')
    assert shown['zip-container-beside-copy'] == body('zc2')


@pytest.mark.parametrize('adjudicated', [False, True])
def test_the_merge_audit_names_each_signal_a_merged_link_would_lose(tmp_path, adjudicated):
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
        json_input(tmp_path, 'document_bill_decisions', [dict(component='c',id='decision',
            rejected_package_ids=['BILLS-118hr4775ih'],excluded_measure_keys=['118-hr-4775'])] if adjudicated else [],
            component='Utf8',id='Utf8',rejected_package_ids=strings,excluded_measure_keys=strings),
        json_input(tmp_path, 'recovered_copy_members', [dict(source_id='kept', component='c'), dict(source_id='lost', component='c')],
                   source_id='Utf8', component='Utf8'),
        json_input(tmp_path, 'document_members', [dict(source_id='kept', component='c', source_url=kept, filename=''),
                   dict(source_id='lost', component='c', source_url=lost, filename=''), dict(source_id='copy', component='c', source_url=COPY_A, filename='a.pdf')],
                   source_id='Utf8', component='Utf8', source_url='Utf8', filename='Utf8'),
        json_input(tmp_path, 'source_annotations', [dict(ann, source_id='kept', title='Shown title', package_id='BILLS-118hr4775ih', measure_keys=['118-hr-4775']),
                   dict(ann, source_id='lost', title='Committee title', committee_keys=['HSED13'],
                        package_id='BILLS-118hr9999ih', measure_keys=['118-hr-9999']), dict(ann, source_id='copy')],
                   source_id='Utf8', title='Utf8', reading_title='Utf8', listing_title='Utf8', congress='Int32', filename_date='Date32',
                   content_date='Date32', package_id='Utf8', document_kind=strings, document_family=strings, committee_keys=strings,
                   chambers=strings, meeting_keys=strings, measure_keys=strings, bioguide_ids=strings, facts=facts),
        json_input(tmp_path, 'document_identities', [dict(component='c', document_id='doc')], component='Utf8', document_id='Utf8'),
        json_input(tmp_path, 'ordered', [dict(doc_key='doc', list_row=0, filename='a.pdf', title='Shown title', congress=None, document_date=None,
                   package_id=None if adjudicated else 'BILLS-118hr4775ih', document_kind=[], document_family=[], committee_keys=[], chambers=[], meeting_keys=[],
                   measure_keys=['118-hr-4755'] if adjudicated else ['118-hr-4775'], bioguide_ids=[], facts=[])], doc_key='Utf8', list_row='Int32', filename='Utf8', title='Utf8', congress='Int16',
                   document_date='Date32', package_id='Utf8', document_kind=strings, document_family=strings, committee_keys=strings,
                   chambers=strings, meeting_keys=strings, measure_keys=strings, bioguide_ids=strings, facts=facts),
        json_input(tmp_path, 'saved_files', [dict(component='c', source_id='copy', filename='a.pdf', saved_rank=1)],
                   component='Utf8', source_id='Utf8', filename='Utf8', saved_rank='Int64'),
        json_input(tmp_path, 'source_rows', [dict(list_row=0, url=COPY_A), dict(list_row=0, url=kept)], list_row='Int32', url='Utf8'),
        json_input(tmp_path, 'lookup_sources', [dict(list_row=0, url=kept)], list_row='Int32', url='Utf8'),
        json_input(tmp_path, 'current_recoveries', [dict(original_url=u, body_sha='b' * 64) for u in (kept, lost)], original_url='Utf8', body_sha='Utf8'),
        json_input(tmp_path, 'recovery_rows', [dict(list_row=0, original_url=kept, body_hex='b' * 64)], list_row='Int32', original_url='Utf8', body_hex='Utf8'),
        json_input(tmp_path, 'recovered_file_roles', [], original_url='Utf8', body_sha='Utf8', role='Utf8')]
    steps = [dict(name='links', sql=f"SELECT decode(substr(encode(sha256('url:{kept}'),'hex'),1,16),'hex') AS link_key,cast(0 AS INT) AS list_row"),
             dict(name='recovery_rows_typed', sql="SELECT list_row,original_url,decode(body_hex,'hex') AS body FROM recovery_rows")]
    sql = MERGED_RECOVERY_SQL.replace('recovery_rows r ON', 'recovery_rows_typed r ON')
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='a', sql=f"SELECT source_id,{','.join('lost_' + f for f in LOST_FLAGS)} FROM ({sql}) g ORDER BY source_id")])
    rows = {row.pop('source_id'): {k for k, v in row.items() if v} for row in result['a']}
    assert rows == {'kept': set(), 'lost': {'lost_address', 'lost_link', 'lost_lookup', 'lost_recovery',
        'lost_committees', 'lost_measures'} | ({'lost_package'} if adjudicated else set())}


VETS = 'https://veterans.house.gov/hearing-transcript/between-peril-and-promise'
VETS_HEARINGS = 'https://veterans.house.gov/hearings'
VETS_PRINT = 'https://www.govinfo.gov/content/pkg/CHRG-113hhrg85864/pdf/CHRG-113hhrg85864.pdf'
REPORT = 'http://thomas.loc.gov/cgi-bin/cpquery/R?cp105:FLD010:@1(hr467):'
REPORT_PT1 = 'https://www.govinfo.gov/content/pkg/CRPT-105hrpt467/pdf/CRPT-105hrpt467-pt1.pdf'
SAME = DEM + 'imo/media/doc/Russell%20Testimony.pdf'
DAV = 'https://veterans.house.gov/submission-for-the-record/disabled-american-veterans-1'
DAV_PRINT = 'https://www.govinfo.gov/content/pkg/CHRG-113hhrg82238/html/CHRG-113hhrg82238.htm'


def _several_files(tmp_path):
    """ct-u9y4 shapes from release 77673bfb8fcf: a dead veterans hearing page accepted with a capture of the
    page itself (site frame) and the transcript PDF it carried, the page shown; a dead THOMAS report link
    accepted with parts 1 and 2 of the report, both recorded at the part 1 address; a dead link accepted
    with two copies of one testimony whose text the model does not read (PDFs)."""
    raw = tmp_path / 'raw'
    page = _page('Between Peril and Promise | House Committee on Veterans Affairs', [(VETS_PRINT, 'Hearing Transcript')])
    # A submission page beside the official hearing record offered as containing it (20 such rows; the record's
    # own title is the hearing's).
    dav_page = _page('Disabled American Veterans | House Committee on Veterans Affairs', [(DAV_PRINT, 'Hearing record')])
    dav_print = _page("- WHY ARE VETERANS WAITING YEARS ON APPEAL?: A REVIEW OF THE POST- DECISION PROCESS", [])
    transcript = b'%PDF-1.7\nBETWEEN PERIL AND PROMISE: hearing before the Committee on Veterans Affairs\n%%EOF\n'
    part1 = b'%PDF-1.7\nHouse Report 105-467 Part 1\n%%EOF\n'
    part2 = b'%PDF-1.7\nHouse Report 105-467 Part 2\n%%EOF\n'
    copy_a = b'%PDF-1.7\nTestimony of Deb Russell\n%%EOF\n'
    copy_b = b'%PDF-1.7\nTestimony of Deb Russell \n%%EOF\n'
    hearings = _page('Hearings | House Committee on Veterans Affairs', [(VETS, 'Between Peril and Promise')])
    lines = [_fetch(raw, VETS_HEARINGS, hearings), *(_fetch(raw, url, status=404) for url in (VETS, REPORT, SAME, DAV)),
        _recovered(raw, DAV, dav_page, 'recovered_document', DAV, EARLIER, fmt='html'),
        _recovered(raw, DAV, dav_print, 'requested_content_in_official_hearing', DAV_PRINT, LATER, fmt='html'),
        _recovered(raw, VETS, page, 'recovered_document', VETS, LATER, fmt='html'),
        _recovered(raw, VETS, transcript, 'recovered_document', VETS_PRINT, EARLIER),
        _recovered(raw, REPORT, part1, 'recovered_document', REPORT_PT1, LATER),
        _recovered(raw, REPORT, part2, 'recovered_document', REPORT_PT1, EARLIER),
        _recovered(raw, SAME, copy_a, 'recovered_document', SAME, LATER),
        _recovered(raw, SAME, copy_b, 'recovered_document', SAME, EARLIER)]
    staged = _stage(tmp_path, lines, [])
    files = dict(page=page, transcript=transcript, part1=part1, part2=part2, copy_a=copy_a, copy_b=copy_b, dav_page=dav_page, dav_print=dav_print)
    accepted = [(VETS, page), (VETS, transcript), (REPORT, part1), (REPORT, part2), (SAME, copy_a), (SAME, copy_b), (DAV, dav_page), (DAV, dav_print)]
    decided = [(VETS, page, 'source_page'), (REPORT, part2, 'edition'), (SAME, copy_a, 'same_document'), (SAME, copy_b, 'same_document'),
        (DAV, dav_page, 'source_page')]
    return staged, files, accepted, decided


def test_a_page_capture_is_the_source_of_its_file_and_an_edition_is_its_own_document(tmp_path):
    """ct-u9y4 (owner, 2026-11-11). "One document, file shown": a dead committee page accepted with a capture of
    the page itself and the file it carried is one document showing the file; the page is listed as where it
    came from (an unsaved sources row with its listing page), not as a recovered copy, as a GovInfo details page
    is folded into its hearing (ct-m878). "Split into separate documents": each other edition of the file a dead
    link shows is its own document, keyed by its body; the link keeps its key and the file it shows, and the
    link's address finds both. "Keep the page's old title" (owner, same day): a document that showed the page keeps
    the page's title on the file, not the hearing record's own title and not none. Built twice from one capture set:
    as published (every file reviewed undecided, which changes nothing) and with the decisions, against the first as
    the live release."""
    from viewer_publication.release_comparison import compare
    staged, files, accepted, decided = _several_files(tmp_path)
    before, _ = _release_from(tmp_path, staged, _root(tmp_path, 'before-root', [(o, c, 'undecided') for o, c in accepted]), 'before', 'before-model')
    title_before = lambda url: next(before['detail'][r['list_row']]['title'] for r in before['links'] if r['link_key'] == _url_key(url))
    after, result = _release_from(tmp_path, staged, _root(tmp_path, 'after-root', decided), 'after', 'after-model')
    sha = lambda name: hashlib.sha256(files[name]).digest()
    details, links = after['detail'], {r['link_key']: r['list_row'] for r in after['links']}
    served = lambda row: sorted(r['body'] for r in after['recoveries'] if r['list_row'] == row)
    lookup = lambda url: sorted(r['list_row'] for r in after['urls']
        if r['lookup_key'] == hashlib.sha256(('lookup:' + url.split('://', 1)[1]).encode()).digest()[:8])

    # The veterans page: the link's row shows the transcript; the page capture is no recovered file of it,
    # and the dead address is its unsaved source, with the page that listed it.
    vets = links[_url_key(VETS)]
    assert (details[vets]['saved_kind'], details[vets]['saved_body']) == ('recovery', sha('transcript'))
    assert served(vets) == [sha('transcript')]
    assert [(s['url'], s['is_saved'], s['listed_on'], s['link_text']) for s in after['sources'] if s['list_row'] == vets] == [
        (VETS, False, VETS_HEARINGS, 'Between Peril and Promise')]
    assert lookup(VETS) == [vets]
    # It showed the page, so the page's title stays: the transcript PDF has none of its own.
    assert details[vets]['title'] == title_before(VETS) == 'Between Peril and Promise | House Committee on Veterans Affairs'
    assert details[vets]['title_source'] == 'page_title'

    # The submission: the link's row shows the hearing record now, under the page's title, not the hearing's.
    dav = links[_url_key(DAV)]
    assert (details[dav]['saved_body'], served(dav)) == (sha('dav_print'), [sha('dav_print')])
    assert details[dav]['title'] == title_before(DAV) == 'Disabled American Veterans | House Committee on Veterans Affairs'
    assert details[dav]['title_source'] == 'page_title'

    # The report: the link keeps part 1; part 2 is its own document under its body key, and the dead
    # address finds both.
    report, part2 = links[_url_key(REPORT)], links[sha('part2')[:8]]
    assert report != part2 and details[part2]['link_key'] == sha('part2')[:8]
    assert (details[report]['saved_body'], served(report)) == (sha('part1'), [sha('part1')])
    assert (details[part2]['saved_kind'], details[part2]['saved_body'], served(part2)) == ('recovery', sha('part2'), [sha('part2')])
    assert lookup(REPORT) == sorted([report, part2])

    # Reviewed as one document: two copies of one testimony stay on one row.
    same = links[_url_key(SAME)]
    assert served(same) == sorted([sha('copy_a'), sha('copy_b')])
    # Beside them only the live hearings page that listed the veterans page.
    assert [d['saved_kind'] for i, d in enumerate(details) if i not in {vets, report, part2, same, dav}] == ['original']

    queries = {q['name']: q['data'] for q in result['queries']}
    assert queries['recovered_file_invariants'] == [dict(several_files_unreviewed=0, links_without_a_file=0)]
    assert queries['recovery_documents_with_several_files'] == [dict(agreement='text_unread', documents=1)]
    assert queries['recovered_file_roles_unused'] == [dict(entries=0)]
    assert queries['model_invariants'][0]['unaccounted_merged_signal'] == 0

    # The publish gate's link rule: no key vanishes; only the pages' link and lookup keys answer another
    # file (the page capture before, the file now), which a cause record names as a correction.
    rule = compare(tmp_path / 'before', tmp_path / 'after')['link_rule']
    assert (rule['missing'], rule['dangling'], rule['address_changed']) == (0, 0, 0)
    assert sorted((a['key'], a['live_body'], a['candidate_body']) for a in rule['changed_answers']) == sorted([
        (_url_key(VETS).hex(), sha('page').hex(), sha('transcript').hex()), (_url_key(DAV).hex(), sha('dav_page').hex(), sha('dav_print').hex())])
    assert rule['lookup_changed'] == 2


@pytest.mark.parametrize('dropped, added, invariant', [
    # The two testimony copies unreviewed: a document holding several files whose text the model cannot read refuses.
    ([(SAME, 'copy_a', 'same_document'), (SAME, 'copy_b', 'same_document')], [], 'several_files_unreviewed'),
    # Every file of the report link an edition: the link would hold no file of its own, and its key no document.
    ([], [(REPORT, 'part1', 'edition')], 'links_without_a_file')])
def test_a_document_with_several_unreviewed_files_refuses_the_build(tmp_path, dropped, added, invariant):
    """ct-u9y4 item 4: recovery_documents_with_several_files was a report, and 25 documents whose files' text
    differs shipped in 77673bfb8fcf without a refusal. Several recovered files on one document need a reviewed
    role unless their text is equal; and no review may take every file from a link."""
    from viewer_publication.archive_model import build_release
    staged, files, _accepted, decided = _several_files(tmp_path)
    named = [(o, files[n], r) for o, n, r in dropped + added]
    roles = [d for d in decided if d not in named] + [(o, files[n], r) for o, n, r in added]
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build_release(**staged, engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model', root=_root(tmp_path, 'root', roles))
    queries = {q['name']: q['data'] for q in json.loads((tmp_path / 'model/result.json').read_text())['queries']}
    assert queries['recovered_file_invariants'][0][invariant] == 1


def test_the_reviewed_roles_registry_refuses_an_unknown_role_or_a_repeated_file():
    """recovered-file-roles.json: one reviewed role per (dead link, recovered body), each with evidence."""
    from viewer_publication.archive_model import REVIEWED_REGISTRIES
    check = REVIEWED_REGISTRIES['recovered_file_roles']
    good = dict(original_url=VETS, body_sha='a' * 64, role='source_page', evidence='read')
    check([good, dict(good, body_sha='b' * 64, role='edition'), dict(good, original_url=REPORT)])
    for bad in [[good, dict(good, role='edition')], [dict(good, role='hidden')], [dict(good, evidence='')],
                [dict(good, body_sha='A' * 64)], [dict(good, original_url='')]]:
        with pytest.raises(ValueError):
            check(bad)


def test_live_edition_at_govinfo_zip_url_keeps_recovered_copy_link_and_passes_gate(tmp_path):
    """ct-jcnd item 3 / F1 (CHRG-119hhrg64154.pdf): a GovInfo ZIP member + recovered_document at the
    published PDF URL followed by a later live HTTP 200 fetch of revised PDF bytes at that URL must
    keep the recovered-copy link key and recovery row on the ZIP member's document (unaccounted_merged_signal=0)
    and pass release_comparison.compare() + automatic_causes() with zero split rows, moved keys, or changed_answers."""
    from viewer_publication.release_comparison import compare
    from viewer_publication.release_gate import automatic_causes, require_release_gates
    zip_url = 'https://www.govinfo.gov/content/pkg/CHRG-119hhrg64154.zip'
    pdf_url = 'https://www.govinfo.gov/content/pkg/CHRG-119hhrg64154/pdf/CHRG-119hhrg64154.pdf'
    zip_bytes = b'PK\x03\x04CHRG-119hhrg64154-container'
    zip_pdf = b'%PDF-1.7\nCHRG-119hhrg64154 first print from GovInfo ZIP\n%%EOF\n'
    live_pdf = b'%PDF-1.7\nCHRG-119hhrg64154 revised print fetched live HTTP 200\n%%EOF\n'
    base_key = 'receipts/documents/2026-10-16/base.jsonl.gz'
    live_key = 'receipts/documents/2026-10-31/live.jsonl.gz'

    def build_variant(sub, include_live):
        work = tmp_path / sub
        raw = work / 'raw'
        engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
        zip_entry = dict(_entry(raw, zip_bytes, 'zip'), media_type='application/zip', intact=None, expansion='expanded')
        member_entry = dict(_entry(raw, zip_pdf, 'pdf'), member_path='CHRG-119hhrg64154/pdf/CHRG-119hhrg64154.pdf')
        zip_line = dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents',
            outcome='stored', requested_url=zip_url, url=zip_url, response_headers={}, http_status=200,
            complete=True, retrieved_at='2026-10-16T10:00:00Z', captures=[zip_entry, member_entry])
        base_lines = [
            zip_line,
            _recovered(raw, pdf_url, zip_pdf, 'recovered_document', pdf_url, '2026-10-16T12:00:00Z'),
        ]
        receipt_entries = [(base_key, base_lines)]
        if include_live:
            live_line = _fetch(raw, pdf_url, live_pdf, 'pdf')
            live_line['retrieved_at'] = '2026-10-31T03:12:11Z'
            receipt_entries.append((live_key, [live_line]))
        receipt_specs = []
        raw_blobs = {}
        for idx, (rkey, rlines) in enumerate(receipt_entries):
            rpath = raw / rkey
            rpath.parent.mkdir(parents=True, exist_ok=True)
            encoded = gzip.compress(''.join(json.dumps(r) + '\n' for r in rlines).encode(), mtime=0)
            rpath.write_bytes(encoded)
            raw_blobs[rkey] = encoded
            pin = work / f'pin-{idx}.json'
            pin.write_text(json.dumps(dict(path=str(rpath), size=len(encoded),
                sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
            receipt_specs.append(dict(key=rkey, path=str(rpath), qualification=str(pin)))
        decided = [(pdf_url, zip_pdf, 'recovered_document', pdf_url)]
        decisions = work / 'recoveries.jsonl'
        decisions.write_text(''.join(json.dumps(dict(id=f'decision-{i}', body_sha256=hashlib.sha256(content).hexdigest(),
            original_url=original, recovered_filename=None, recovered_url=copy_url, kind=kind, identity_note=None,
            decided_at='2026-10-27T15:46:39Z', supersedes=None, recovery_record_version=2)) + '\n'
            for i, (original, content, kind, copy_url) in enumerate(decided)))
        recovery_files = [dict(key='provenance/recoveries/fixture.jsonl', path=str(decisions))]
        captures = stage_captures(receipt_specs, engine=engine, work=work / 'stage') / 'captures.parquet'
        inventory = work / 'inventory'
        inventory.mkdir()
        run_job(inventory, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[],
            outputs=[parquet_output(inventory, 'bodies',
                """SELECT DISTINCT sha256 AS body_sha,'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
                'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,stored_bytes
                FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
        pages = readings.stage(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw,
            engine=engine, work=work / 'read', decided_at='2026-10-27T12:00:00Z', parser='html')
        names = filenames.stage(captures=captures, recovery_files=recovery_files, engine=engine,
            work=work / 'names', decided_at='2026-10-27T12:00:00Z')
        staged = dict(captures=captures, readings=pages['readings'], filename_readings=names['readings'],
            recovery_files=recovery_files,
            parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']},
            catalog_version=names['catalog_version'])
        files, result = _release_from(work, staged, name='release', scratch='model')
        return work / 'release', files, result, captures, raw_blobs

    base_dir, base_files, _, _, _ = build_variant('base', include_live=False)
    cand_dir, cand_files, cand_result, cand_captures, cand_raw = build_variant('candidate', include_live=True)

    queries = {q['name']: q['data'] for q in cand_result['queries']}
    assert queries['model_invariants'][0]['unaccounted_merged_signal'] == 0
    assert queries['model_invariants'][0]['invalid_recovery_attachments'] == 0

    sha_zip_pdf = hashlib.sha256(zip_pdf).digest()
    sha_live_pdf = hashlib.sha256(live_pdf).digest()
    cand_details = cand_files['detail']
    zip_row = next(i for i, d in enumerate(cand_details) if d['saved_body'] == sha_zip_pdf)
    live_row = next(i for i, d in enumerate(cand_details) if d['saved_body'] == sha_live_pdf)
    assert zip_row != live_row

    cand_links = {r['link_key']: r['list_row'] for r in cand_files['links']}
    assert cand_links[sha_zip_pdf[:8]] == zip_row
    assert cand_links[_url_key(pdf_url)] == zip_row
    assert cand_links[sha_live_pdf[:8]] == live_row
    assert [r['list_row'] for r in cand_files['recoveries']] == [zip_row]

    cand_list = pq.read_table(cand_dir / 'list.parquet').to_pylist()
    assert cand_list[zip_row]['version_keys'] and cand_list[zip_row]['version_keys'] == cand_list[live_row]['version_keys']
    lookup_key = hashlib.sha256(('lookup:' + pdf_url.removeprefix('https://').removeprefix('www.')).encode()).digest()[:8]
    assert sorted(r['list_row'] for r in cand_files['urls'] if r['lookup_key'] == lookup_key) == sorted([zip_row, live_row])

    report = compare(base_dir, cand_dir)
    assert report['link_rule']['ok'] is True
    assert report['link_rule']['changed_answers'] == []
    assert report['link_rule']['address_changed'] == 0
    assert [(g['group'], g['cause']) for g in report['files']['list.parquet']['groups']] == [
        ('added rows', 'no surviving link key'),
        ('changed version_keys', 'value differs on matched key'),
    ]
    assert [(g['group'], g['cause']) for g in report['files']['links.parquet']['groups']] == [
        ('added keys', 'no evidence given'),
    ]

    gate_report = require_release_gates(
        base_dir, cand_dir, None, report_path=tmp_path / 'gate-report.json',
        automatic=lambda rep: automatic_causes(
            rep, base_dir, cand_dir,
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            captures=dict(kind='parquet', path=str(cand_captures)),
            live_receipt_keys={base_key},
            read_receipt=lambda k: cand_raw[k],
            work=tmp_path / 'auto-gate',
            candidate_receipt_keys={base_key, live_key},
        ),
    )
    assert gate_report['reasons'] == []
    auto_ids = {e['id']: e['tickets'] for e in gate_report['automatic_causes']}
    assert auto_ids['list.parquet|changed version_keys|value differs on matched key'] == ['ct-jcnd']
    assert auto_ids['detail.parquet|changed version_keys|value differs on matched key'] == ['ct-jcnd']
    assert auto_ids['sources.parquet|documents changed for a shared key|the key now answers other documents'] == ['ct-jcnd']
    assert auto_ids['urls.parquet|documents changed for a shared key|the key now answers other documents'] == ['ct-jcnd']
