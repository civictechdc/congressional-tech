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


def _release(tmp_path):
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw = tmp_path / 'raw'
    lines = []
    for requested, final, content in [*CASES, REPEAT]:
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
    build_release(captures=captures, readings=pages['readings'], filename_readings=names['readings'],
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}, catalog_version=names['catalog_version'],
        engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    details = pq.read_table(tmp_path / 'release/detail.parquet').to_pylist()
    by_body = {d['saved_body']: d for d in details}
    rows = [by_body[hashlib.sha256(content).digest()] for _, _, content in CASES]
    conflicts = pq.read_table(tmp_path / 'model/evidence/filename_conflicts.parquet').to_pylist()
    queries = {q['name']: q['data'] for q in json.loads((tmp_path / 'model/result.json').read_text())['queries']}
    return rows, conflicts, queries


def test_both_names_fill_what_the_shown_name_lacks_and_keep_disagreements(tmp_path):
    (ramos, lhamon, grassley, all_fields), conflicts, queries = _release(tmp_path)
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
