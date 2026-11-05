"""A redirect's two names are both read (owner, 2026-11-02).

The final URL's name is shown (captures.url is the final URL since b9ac6cc5), but the requested,
linked URL's name often carries what the final name lacks: 320 documents lost a filename date and
525 lost a kind in the r1b candidate (causes/attribution/documents.json). Raw shapes from the Senate
`/download/<slug>` redirects to `/imo/media/doc/<Name>.pdf`.
"""
import gzip
import hashlib
import json
import os
from datetime import date
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import filenames, readings
from congress_api.lake.capture_staging import stage_captures
from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets

FINANCE = 'https://www.finance.senate.gov/'
JUDICIARY = 'https://www.judiciary.senate.gov/'
CASES = [  # requested (linked) URL, final URL, body
    (FINANCE + 'download/03172021-ramos-testimony&download=1',
     FINANCE + 'imo/media/doc/AdelinaRamos_WrittenTestimony%20March%2017.pdf', b'%PDF-1.7\nRamos\n%%EOF\n'),
    (JUDICIARY + 'download/lhamon-testimony', JUDICIARY + 'imo/media/doc/Lhamon1.pdf', b'%PDF-1.7\nLhamon\n%%EOF\n'),
    (FINANCE + 'download/07302020-grassley-statement&download=1',
     FINANCE + 'imo/media/doc/07302020%20Grassley%20Testimony.pdf', b'%PDF-1.7\nGrassley\n%%EOF\n'),
    (FINANCE + 'download/HHRG-119-IF00-Wstate-X000001-20260203.pdf',
     FINANCE + 'imo/media/doc/Opaque.pdf', b'%PDF-1.7\nAll fields\n%%EOF\n'),
]
# A second linked name for the same final-URL source: every disagreement must reach triage.
REPEAT = (FINANCE + 'download/07302020-grassley-report&download=1', *CASES[2][1:])
REVIEW_FINAL = FINANCE + 'imo/media/doc/ReviewOpaque.pdf'
REVIEW_A = FINANCE + 'download/a.pdf'
REVIEW_B = FINANCE + 'download/b.pdf'
REVIEW_BODY = b'%PDF-1.7\nReview\n%%EOF\n'
REVIEW_CASES = [(REVIEW_A, REVIEW_FINAL, REVIEW_BODY), (REVIEW_B, REVIEW_FINAL, REVIEW_BODY)]


def _review_readings(shown_status):
    """Complementary completed linked readings; an error shown row also has untrustworthy values."""
    def transform(rows):
        assert len(rows) == 3
        by_url = {row['source_url']: row for row in rows}
        shown = by_url[REVIEW_FINAL]
        failed = shown_status == 'error'
        shown.update(status=shown_status, error_type='invalid-filename' if failed else None, valid=False,
            filename_date=date(2000, 1, 1) if failed else None, congress=1 if failed else None,
            document_kind=['invalid-shown'] if failed else [], document_family=['invalid-shown'] if failed else [],
            committee_code=['BAD'] if failed else [])
        for url in (REVIEW_A, REVIEW_B):
            by_url[url].update(status='completed', error_type=None, valid=True, filename_date=None,
                congress=None, document_kind=[], document_family=[], committee_code=[])
        by_url[REVIEW_A].update(filename_date=date(2021, 1, 2), document_kind=['testimony'])
        by_url[REVIEW_B].update(document_kind=['statement'], document_family=['statement'],
            congress=118, committee_code=['IF00'])
    return transform


def _release(tmp_path, capture_cases=None, transform_names=None):
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    result_cases = CASES if capture_cases is None else list({
        content: (requested, final, content) for requested, final, content in capture_cases
    }.values())
    capture_cases = [*CASES, REPEAT] if capture_cases is None else capture_cases
    raw = tmp_path / 'raw'
    lines = []
    for requested, final, content in capture_cases:
        digest = hashlib.sha256(content).hexdigest()
        path = raw / f'bodies/sha256/{digest[:2]}/{digest}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        lines.append(dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents',
            outcome='stored', requested_url=requested, url=final, response_headers={}, http_status=200, complete=True,
            retrieved_at='2026-10-27T12:00:00Z', captures=[dict(sha256=digest, bytes=len(content), media_type='application/pdf',
                fidelity='exact-bytes', sniffed_format='pdf', sniff_version=readings.current_version('sniff'), intact=True,
                stored_suffix='', stored_bytes=len(content), stored_md5=hashlib.md5(content).hexdigest())]))
    receipt = raw / 'receipts/documents/2026-10-27/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(''.join(json.dumps(r) + '\n' for r in lines).encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / 'pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
    captures = stage_captures([dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(pin))],
        engine=engine, work=tmp_path / 'stage') / 'captures.parquet'
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(inventory, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[], outputs=[parquet_output(inventory, 'bodies',
        """SELECT DISTINCT sha256 AS body_sha,'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS relative_path,stored_bytes
        FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
    pages = readings.stage(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw, engine=engine,
        work=tmp_path / 'read', decided_at='2026-10-27T12:00:00Z', parser='html')
    names = filenames.stage(captures=captures, recovery_files=(), engine=engine, work=tmp_path / 'names', decided_at='2026-10-27T12:00:00Z')
    if transform_names is not None:
        table = pq.read_table(names['readings'])
        reading_rows = table.to_pylist()
        transform_names(reading_rows)
        pq.write_table(pa.Table.from_pylist(reading_rows, schema=table.schema), names['readings'])
    build_release(captures=captures, readings=pages['readings'], filename_readings=names['readings'],
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}, catalog_version=names['catalog_version'],
        engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    details = pq.read_table(tmp_path / 'release/detail.parquet').to_pylist()
    by_body = {d['saved_body']: d for d in details}
    rows = [by_body[hashlib.sha256(content).digest()] for _, _, content in result_cases]
    conflicts = pq.read_table(tmp_path / 'model/evidence/filename_conflicts.parquet').to_pylist()
    queries = {q['name']: q['data'] for q in json.loads((tmp_path / 'model/result.json').read_text())['queries']}
    annotations = pq.read_table(tmp_path / 'model/evidence/source_filename_readings.parquet').to_pylist()
    return rows, conflicts, queries, annotations


def test_both_names_fill_what_the_shown_name_lacks_and_keep_disagreements(tmp_path):
    (ramos, lhamon, grassley, all_fields), conflicts, queries, _ = _release(tmp_path)
    # The shown name stays the final URL's.
    assert [r['filename'] for r in (ramos, lhamon, grassley, all_fields)] == [
        'AdelinaRamos_WrittenTestimony March 17.pdf', 'Lhamon1.pdf', '07302020 Grassley Testimony.pdf', 'Opaque.pdf']
    # A date only the linked name carries comes back (one of the 320).
    assert str(ramos['document_date']) == '2021-03-17' and ramos['document_date_source'] == 'filename'
    # A kind only the linked name carries comes back (one of the 525).
    assert lhamon['document_kind'] == ['testimony']
    # All five owner-named fields fill from the linked reading and reach their typed exports.
    assert all_fields['document_kind'] == ['witness-statement']
    assert all_fields['document_family'] == ['statement']
    assert all_fields['congress'] == 119 and all_fields['committee_keys'] == ['hsif00']
    assert str(all_fields['document_date']) == '2026-02-03' and all_fields['document_date_source'] == 'filename'
    # Both names give a kind and they differ: the shown name's stays, each other is a triage row.
    assert grassley['document_kind'] == ['testimony']
    assert [(c['field'], c['shown_value'], c['other_value'], c['other_name'], c['other_url']) for c in conflicts] == [
        ('document_family', 'statement', 'report', '07302020-grassley-report&download=1', REPEAT[0]),
        ('document_kind', 'testimony', 'report', '07302020-grassley-report&download=1', REPEAT[0]),
        ('document_kind', 'testimony', 'statement', '07302020-grassley-statement&download=1', CASES[2][0])]
    assert {(c['shown_name'], c['shown_url']) for c in conflicts} == {('07302020 Grassley Testimony.pdf', CASES[2][1])}
    counts = queries['filename_both_names'][0]
    assert counts['sources_with_two_names'] == 4
    assert (counts['filename_date_filled'], counts['document_kind_filled'], counts['document_kind_conflicting']) == (2, 2, 2)
    assert (counts['document_family_filled'], counts['congress_filled'], counts['committee_code_filled']) == (2, 1, 1)
    assert counts['document_family_conflicting'] == 1


def _assert_review_values(row):
    assert row['filename'] == 'ReviewOpaque.pdf'
    assert str(row['document_date']) == '2021-01-02' and row['document_date_source'] == 'filename'
    assert row['document_kind'] == ['testimony'] and row['document_family'] == ['statement']
    assert row['congress'] == 118 and row['committee_keys'] == ['hsif00']


def test_per_field_fills_use_each_supplying_name_and_triage_linked_disagreements(tmp_path):
    """Review fixture: opaque final name, complementary linked fields, and a kind conflict."""
    (row,), conflicts, _, (annotation,) = _release(
        tmp_path, capture_cases=REVIEW_CASES, transform_names=_review_readings('completed'))
    _assert_review_values(row)
    # A supplies date/kind; B supplies family/congress/committee. Each choice keeps its own source.
    assert (annotation['filename_date_name'], annotation['filename_date_url']) == ('a.pdf', REVIEW_A)
    assert (annotation['document_kind_name'], annotation['document_kind_url']) == ('a.pdf', REVIEW_A)
    for field in ('document_family', 'congress', 'committee_code'):
        assert (annotation[field + '_name'], annotation[field + '_url']) == ('b.pdf', REVIEW_B)
    # The effective choice is A's testimony, so B's statement is the sourced alternate in triage.
    assert [(c['field'], c['shown_value'], c['shown_name'], c['shown_url'],
             c['other_value'], c['other_name'], c['other_url']) for c in conflicts] == [
        ('document_kind', 'testimony', 'a.pdf', REVIEW_A, 'statement', 'b.pdf', REVIEW_B)]


def test_failed_shown_reading_does_not_block_completed_linked_typed_values(tmp_path):
    (row,), _, queries, (annotation,) = _release(
        tmp_path, capture_cases=REVIEW_CASES, transform_names=_review_readings('error'))
    _assert_review_values(row)
    assert annotation['status'] == annotation['shown_status'] == 'error'
    assert annotation['error_type'] == annotation['shown_error_type'] == 'invalid-filename'
    for field in ('filename_date', 'document_kind', 'document_family', 'congress', 'committee_code'):
        assert annotation[field + '_status'] == 'completed'
    counts = queries['filename_both_names'][0]
    assert [counts[field + suffix] for field, suffix in [
        ('filename_date', '_filled'), ('document_kind', '_filled'), ('document_family', '_filled'),
        ('congress', '_filled'), ('committee_code', '_filled')]] == [1, 1, 1, 1, 1]


def test_opaque_download_dates_do_not_set_observed_bounds(tmp_path):
    foreign = 'https://www.foreign.senate.gov/'
    aliases = [
        ('02271901', '02 27 19 Assessing The Role Of The United States In The World2.pdf', date(1901, 2, 27)),
        ('03261901', '03 26 19 US Policy Toward North Korea After the Second Summit1.pdf', date(1901, 3, 26)),
        ('06191901', '06 19 19 Nomination of Kelly Craft, of Kentucky, to be United States Ambassador to the United Nations.pdf',
         date(1901, 6, 19)),
    ]
    cases = [(foreign + 'download/transcript-' + alias, foreign + 'imo/media/doc/' + quote(name),
              f'%PDF-1.7\n{alias}\n%%EOF\n'.encode()) for alias, name, _ in aliases]
    # The Government Publishing Office dates the printing of S. Rept. 56-2496 to March 2, 1901.
    # https://www.govinfo.gov/app/details/SERIALSET-04067_00_00-174-2496-0000/
    # Give the fixture a plain displayed filename to exercise the date with a null Congress.
    historical = foreign + 'imo/media/doc/Deficiency%20appropriation%20bill%20March%202,%201901.pdf'
    typo = 'https://www.help.senate.gov/imo/media/doc/FDA%20PAHPA%20testimony%20May%204%202303%20HELP1.pdf'
    # An opaque supplier sorts first by URL. A supported, named supplier should still win.
    judiciary = (
        JUDICIARY + 'download/results-of-executive-business-meeting-may-9-2019',
        JUDICIARY + 'imo/media/doc/050919%20Results%20of%20Executive%20Business%20Meeting.pdf',
        b'%PDF-1.7\nResults\n%%EOF\n',
    )
    competing_alias = (foreign + 'download/transcript-00000000', *judiciary[1:])

    def add_opaque_reading(rows):
        row = next(row for row in rows if row['source_url'] == competing_alias[0])
        row.update(filename_date=date(1900, 1, 1), valid=False)

    rows, conflicts, _, annotations = _release(tmp_path, capture_cases=[
        *cases, (historical, historical, b'%PDF-1.7\nHistorical\n%%EOF\n'),
        (typo, typo, b'%PDF-1.7\nTypo\n%%EOF\n'), CASES[0], judiciary, competing_alias,
    ], transform_names=add_opaque_reading)
    by_name = {row['filename']: row for row in annotations}
    for row, (alias, name, literal) in zip(rows, aliases):
        assert (row['document_date'], row['document_date_source'], row['document_date_status']) == (None, None, None)
        source = by_name[name]
        assert source['date_token'] == name[:8]
        assert source['shown_filename_date'] is None
        assert source['filename_date'] == literal
        assert source['filename_date_url'] == foreign + 'download/transcript-' + alias
        assert source['filled_date'] is True and source['filename_date_eligible'] is False
    actual, future, named, alternate = rows[3:]
    assert (actual['document_date'], actual['document_date_status'], actual['congress']) == (date(1901, 3, 2), 'accepted', None)
    assert (future['document_date'], future['document_date_status'], future['document_date_source']) == (
        date(2303, 5, 4), 'suspect', 'filename')
    assert (named['document_date'], named['document_date_status']) == (date(2021, 3, 17), 'accepted')
    assert (alternate['document_date'], alternate['document_date_status']) == (date(2019, 5, 9), 'accepted')
    alternate_source = by_name[alternate['filename']]
    assert alternate_source['filename_date_url'] == judiciary[0]
    assert alternate_source['filename_date_valid'] is False and alternate_source['filename_date_eligible'] is True
    assert any(c['field'] == 'filename_date' and c['other_url'] == competing_alias[0] for c in conflicts)

    release = json.loads((tmp_path / 'release/manifest.json').read_text())
    coverage = next(item['coverage'] for item in release['files'] if item['name'] == 'detail.parquet')
    assert coverage['document_dates'] == {'accepted': 3, 'suspect': 1, 'undated': 3}
    assert (coverage['date_start'], coverage['date_end']) == ('1901-03-02', '2021-03-17')
