"""Witness identity slice 1 (ct-46f3) and Congress.gov retained items (ct-960v) end-to-end tests."""
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import appearance_records as ar_lake, filenames, meeting_records as mr_lake, readings
from congress_api.lake.capture_staging import stage_captures
from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets

from archive_job_fixture import spicy_input


def _stage_raw(tmp_path, engine, capture_specs):
    raw = tmp_path / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    receipt_groups = {}
    for spec in capture_specs:
        data = spec['data']
        fmt = spec.get('format', 'html')
        compress = spec.get('compress', fmt in ('html', 'xml', 'json', 'vtt', 'm3u8'))
        stored = gzip.compress(data, mtime=0) if compress else data
        digest = spec.get('sha256') or hashlib.sha256(data).hexdigest()
        suffix = '.gz' if compress else spec.get('suffix', '')
        key = f'bodies/sha256/{digest[:2]}/{digest}{suffix}'
        path = raw / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stored)
        url = spec['url']
        rk = spec.get('receipt_key', 'receipts/documents/2026-10-20/base.jsonl.gz')
        receipt_groups.setdefault(rk, []).append(dict(
            writer=dict(job='fixture', commit='a' * 40),
            run_id=spec.get('run_id', 'fixture'),
            mode='fetch',
            family=spec.get('family', 'documents'),
            outcome=spec.get('outcome', 'stored'),
            requested_url=spec.get('requested_url', url),
            url=url,
            response_headers=spec.get('headers', {}),
            http_status=200,
            complete=True,
            retrieved_at=spec.get('retrieved_at', '2026-10-20T12:00:00Z'),
            captures=[dict(
                sha256=digest,
                bytes=len(data),
                media_type=spec.get('media_type', {'json': 'application/json', 'xml': 'application/xml', 'pdf': 'application/pdf'}.get(fmt, 'text/html')),
                fidelity='exact-bytes',
                sniffed_format=fmt,
                sniff_version=readings.current_version('sniff'),
                intact=True if fmt == 'pdf' else None,
                stored_suffix=suffix,
                stored_bytes=len(stored),
                stored_md5=hashlib.md5(stored).hexdigest(),
                context_url=spec.get('context_url'),
            )],
        ))
    staged_specs = []
    for idx, (rk, rows) in enumerate(sorted(receipt_groups.items())):
        receipt = raw / rk
        receipt.parent.mkdir(parents=True, exist_ok=True)
        encoded = gzip.compress((''.join(json.dumps(r) + '\n' for r in rows)).encode(), mtime=0)
        receipt.write_bytes(encoded)
        qual = tmp_path / f'receipt-pin-{idx}.json'
        qual.write_text(json.dumps(dict(
            path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture',
        )))
        staged_specs.append(dict(key=rk, path=str(receipt), qualification=str(qual)))
    captures = stage_captures(staged_specs, engine=engine, work=tmp_path / 'capture-stage') / 'captures.parquet'
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(
        inventory, engine,
        inputs=[dict(name='captures', kind='parquet', path=str(captures))],
        steps=[],
        outputs=[parquet_output(
            inventory, 'bodies',
            """SELECT DISTINCT sha256 AS body_sha,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
            stored_bytes FROM captures WHERE sha256 IS NOT NULL""",
            ['body_sha'],
        )],
    )
    page_formats = ['html'] + sorted({spec.get('format', 'html') for spec in capture_specs} & {'xml', 'json'})
    staged_pages = [readings.stage(
        captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw,
        engine=engine, work=tmp_path / f'reading-stage-{parser}', decided_at='2026-10-27T12:00:00Z', parser=parser,
    )['readings'] for parser in page_formats]
    page_readings = staged_pages[0]
    if len(staged_pages) > 1:
        page_readings = tmp_path / 'page-readings.parquet'
        pq.write_table(pa.concat_tables([pq.read_table(p) for p in staged_pages]), page_readings)
    names = filenames.stage(
        captures=captures, recovery_files=(), engine=engine, work=tmp_path / 'filename-stage', decided_at='2026-10-27T12:00:00Z',
    )
    return dict(
        captures=captures,
        readings=page_readings,
        filename_readings=names['readings'],
        parser_versions={
            **{p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']},
            'meeting_records': mr_lake.current_versions(),
            'appearance_records': ar_lake.current_versions(),
        },
        catalog_version=names['catalog_version'],
    )


def _pdf_bytes(tag: str) -> bytes:
    return f'%PDF-1.4\n% {tag}\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'.encode()


def _cg_json(event_id: int, stamp: str, tag: str) -> bytes:
    return json.dumps({
        'committeeMeeting': {
            'eventId': str(event_id),
            'chamber': 'House',
            'congress': 118,
            'updateDate': stamp,
            'title': f'Hearing {event_id} ({tag})',
        }
    }).encode()


def _spicy_fixture():
    return spicy_input(
        spicy_committees=[dict(
            system_code='hsif00', name='Energy and Commerce', chamber='house', committee_type='standing',
            parent_system_code=None, website_url='https://energycommerce.house.gov', is_current=True, history=[],
        )],
        spicy_members=[dict(
            bioguide_id='A000370', name_first='Alma', name_last='Adams', name_nickname=None,
            lis_id=None, opensecrets_id=None, govtrack_id=None, icpsr_id=None, wikidata_id=None, fec_ids=[],
        )],
        spicy_congress_bills=[dict(
            bill_id='118-hr-100', title='Clean Grid Act', short_title='Clean Grid Act',
            sponsor_bioguide_id='A000370', introduced_date='2023-01-10', latest_action_date='2023-02-01',
            latest_action_text='Referred to committee', stage='introduced', policy_area='Energy',
            subjects=['Energy'], update_date='2023-02-01T00:00:00Z', update_date_including_text='2023-02-01T00:00:00Z',
            public_law_number=None, cosponsor_count=1, related_bills=[],
        )],
        spicy_nominations=[dict(
            congress=118, number=50, part_number='00', description='Jane Nominee, to be Administrator',
            organization='Department of Energy', received_date='2023-03-01', latest_action_date='2023-03-15',
            latest_action_text='Received in the Senate', update_date='2023-03-15T00:00:00Z', hearings_json='[]',
            committees_json='[{"systemCode":"hsif00","activities":[]}]',
        )],
    )


def test_witness_carry_tiers_ambiguous_typo_prints_and_one_hop_map(tmp_path):
    """Covers all 8 ct-46f3 carry/mint scenarios plus 1-hop base_witness_key_map re-resolution."""
    from viewer_publication.archive_model import build_release
    from viewer_publication.release_gate import prior_links

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])

    cg_500_v1 = _cg_json(500, '2026-10-20T00:00:00Z', 'v1')
    cg_500_v2 = _cg_json(500, '2026-10-25T00:00:00Z', 'v2')
    cg_501_v1 = _cg_json(501, '2026-10-20T00:00:00Z', 'v1')
    cg_501_v2 = _cg_json(501, '2026-10-25T00:00:00Z', 'v2')
    cg_502_v1 = _cg_json(502, '2026-10-20T00:00:00Z', 'v1')
    cg_502_v2 = _cg_json(502, '2026-10-25T00:00:00Z', 'v2')
    cg_503_v1 = _cg_json(503, '2026-10-20T00:00:00Z', 'v1')
    cg_503_v2 = _cg_json(503, '2026-10-25T00:00:00Z', 'v2')
    cg_504_v1 = _cg_json(504, '2026-10-20T00:00:00Z', 'v1')
    cg_504_v2 = _cg_json(504, '2026-10-25T00:00:00Z', 'v2')
    mods_p1 = b'<mods><titleInfo><title>Print 1</title></titleInfo></mods>'
    mods_p2 = b'<mods><titleInfo><title>Print 2</title></titleInfo></mods>'
    sen_html = b'<html><head><title>Senate Hearing</title></head><body><p>' + b'Senate witness panel text. ' * 40 + b'</p></body></html>'
    doc_pdf = _pdf_bytes('witness-statement')

    sha = lambda b: hashlib.sha256(b).hexdigest()

    base_captures = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/500?format=json', data=cg_500_v1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/501?format=json', data=cg_501_v1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/502?format=json', data=cg_502_v1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/503?format=json', data=cg_503_v1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/504?format=json', data=cg_504_v1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z'),
        dict(url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg50001/mods.xml', data=mods_p1, format='xml', family='govinfo/mods'),
        dict(url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg50002/mods.xml', data=mods_p2, format='xml', family='govinfo/mods'),
        dict(url='https://www.banking.senate.gov/hearings/twin-hearing', data=sen_html, format='html', family='senate/pages'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/500/HHRG-118-IF00-Wstate-VanceJ-20240501.pdf', data=doc_pdf, format='pdf', suffix='.pdf'),
    ]
    staged_base = _stage_raw(tmp_path / 'stage-base', engine, base_captures)

    def mtg(eid, chamber='house', date_str='2024-05-01', title='Oversight Hearing', status='Scheduled', updated='2026-10-20T00:00:00Z', jackets=()):
        return dict(
            event_id=str(eid), chamber=chamber, congress=118, session=2, updated=updated, title=title,
            meeting_date=date_str, meeting_type='HHRG', status=status, sittings=[],
            committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber=chamber, role='host')],
            subject_keys=[], transcript_jackets=list(jackets), videos=[], document_urls=[], document_references=[],
            collection_states=dict(sittings='present', committees='present', subject_keys='empty', transcript_jackets='present' if jackets else 'empty', videos='empty', document_urls='empty'),
            access='open', access_basis='default', not_held=status in ('Postponed', 'Canceled'),
            title_key=title.lower(), reschedule_candidate=status in ('Postponed', 'Rescheduled'),
        )

    base_meetings = [
        dict(record_sha=sha(cg_500_v1), source='congress_gov', meetings=[mtg(500, title='Clean Grid Reliability Architecture', jackets=['50001', '50002'])]),
        dict(record_sha=sha(cg_501_v1), source='congress_gov', meetings=[mtg(501)]),
        dict(record_sha=sha(cg_502_v1), source='congress_gov', meetings=[mtg(502)]),
        dict(record_sha=sha(cg_503_v1), source='congress_gov', meetings=[mtg(503)]),
        dict(record_sha=sha(cg_504_v1), source='congress_gov', meetings=[mtg(504)]),
        # Postponed Senate meeting 600 in base; twin 601 added in candidate so senate_page moves 600 -> 601
        dict(record_sha='60' * 32, source='congress_gov', meetings=[mtg(600, chamber='senate', date_str='2024-06-01', title='Twin Hearing', status='Scheduled')]),
    ]
    base_appearances = [
        # 500: unchanged witness (1) + two prints of one meeting below (6)
        dict(record_sha=sha(cg_500_v1), source='congress_gov', event_id=500, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='elena rodriguez', name='Dr. Elena Rodriguez', given='Elena', family='Rodriguez', position='Director', organization='Grid Institute', panel_order=1, display_order=1),
        ]),
        # Two MODS prints on meeting 500 with identical witness text (case 6) + parser-change target on p1 (case 4)
        dict(record_sha=sha(mods_p1), source='mods', package_id='CHRG-118hhrg50001', held_dates=['2024-05-01'], title='Clean Grid Reliability Architecture', collection_state='present', appearances=[
            dict(source_locator='mods:witness[1]', name_key='marcus chen', name='Marcus Chen, Chief Engineer, Grid Corp', given='Marcus', family='Chen', position=None, organization=None, display_order=1),
            dict(source_locator='mods:witness[2]', name_key='elena rodriguez', name='Elena Rodriguez, Director, Grid Institute', given='Elena', family='Rodriguez', position=None, organization=None, display_order=2),
        ]),
        dict(record_sha=sha(mods_p2), source='mods', package_id='CHRG-118hhrg50002', held_dates=['2024-05-01'], title='Clean Grid Reliability Architecture', collection_state='present', appearances=[
            dict(source_locator='mods:witness[1]', name_key='marcus chen', name='Marcus Chen, Chief Engineer, Grid Corp', given='Marcus', family='Chen', position=None, organization=None, display_order=1),
            dict(source_locator='mods:witness[2]', name_key='elena rodriguez', name='Elena Rodriguez, Director, Grid Institute', given='Elena', family='Rodriguez', position=None, organization=None, display_order=2),
        ]),
        # 501: reorder across panels (case 2)
        dict(record_sha=sha(cg_501_v1), source='congress_gov', event_id=501, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='sarah kim', name='Sarah Kim', given='Sarah', family='Kim', position='Partner', organization='Civic Law', panel_order=1, display_order=1),
            dict(source_locator='congress_gov:witness[2]', name_key='david patel', name='David Patel', given='David', family='Patel', position='Fellow', organization='Policy Lab', panel_order=2, display_order=2),
        ]),
        # 502: typo fix at same source_locator (case 3)
        dict(record_sha=sha(cg_502_v1), source='congress_gov', event_id=502, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='jonthan vance', name='Dr. Jonthan Vance', given='Jonthan', family='Vance', position='Vice President', organization='Acme Energy', panel_order=1, display_order=1,
                 document_links=['https://docs.house.gov/meetings/IF/IF00/20240501/500/HHRG-118-IF00-Wstate-VanceJ-20240501.pdf']),
        ]),
        # 503: two genuinely equal entries in one record (case 7)
        dict(record_sha=sha(cg_503_v1), source='congress_gov', event_id=503, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='john smith', name='John Smith', given='John', family='Smith', position='Citizen', organization='Public', panel_order=1, display_order=1),
            dict(source_locator='congress_gov:witness[2]', name_key='john smith', name='John Smith', given='John', family='Smith', position='Citizen', organization='Public', panel_order=1, display_order=2),
        ]),
        # 504: single entry in base that becomes two identical entries in candidate -> ambiguous carry! (case 8)
        dict(record_sha=sha(cg_504_v1), source='congress_gov', event_id=504, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='alex morgan', name='Alex Morgan', given='Alex', family='Morgan', position='Analyst', organization='Metro Group', panel_order=1, display_order=1),
        ]),
        # Senate page on meeting 600 in base, moves to meeting 601 in candidate on same record_sha + locator (case 5)
        dict(record_sha=sha(sen_html), source='senate_page', event_id=600, context_url='https://www.banking.senate.gov/hearings/twin-hearing', collection_state='present', appearances=[
            dict(source_locator='senate_page:witness[1]', name_key='hannah abbott', name='Hannah Abbott', given='Hannah', family='Abbott', position='Chair', organization='Board', display_order=1),
        ]),
    ]

    base_out = tmp_path / 'base-release'
    build_release(
        **staged_base, engine=engine, output=base_out, scratch=tmp_path / 'base-scratch',
        meeting_records=base_meetings, appearance_records=base_appearances, spicy_regs=_spicy_fixture(), include_entities=True,
    )
    base_w = { (r['occasion'], r['source'], r['package_id'], r['source_locator']): r
               for r in pq.read_table(base_out / 'witnesses.parquet').to_pylist() }

    # Print 1 & Print 2 on meeting 500 must mint distinct keys even with identical witness text (case 6)
    k_p1 = base_w[('meeting:500', 'mods', 'CHRG-118hhrg50001', 'mods:witness[1]')]['witness_key']
    k_p2 = base_w[('meeting:500', 'mods', 'CHRG-118hhrg50002', 'mods:witness[1]')]['witness_key']
    assert k_p1 != k_p2

    # Two equal entries on 503 must have distinct keys (case 7)
    k_eq1 = base_w[('meeting:503', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key']
    k_eq2 = base_w[('meeting:503', 'congress_gov', None, 'congress_gov:witness[2]')]['witness_key']
    assert k_eq1 != k_eq2

    # Inject a 1-hop legacy map row pointing to Vance's base key (case 9)
    k_vance_base = base_w[('meeting:502', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key']
    bmap_table = pq.read_table(base_out / 'witness_key_map.parquet')
    extra_map = pa.Table.from_pylist([dict(
        old_key='0123456789abcdef', witness_key=k_vance_base, status='unambiguous',
        basis='locator', candidate_keys=[], occasion='meeting:502', source='congress_gov',
    )], schema=bmap_table.schema)
    pq.write_table(pa.concat_tables([bmap_table, extra_map]), base_out / 'witness_key_map.parquet')
    # Re-seal base manifest with updated witness_key_map
    from viewer_publication.archive_format import release_identity
    bm = json.loads((base_out / 'manifest.json').read_text())
    mdata = (base_out / 'witness_key_map.parquet').read_bytes()
    for f in bm['files']:
        if f['name'] == 'witness_key_map.parquet':
            f.update(sha256=hashlib.sha256(mdata).hexdigest(), md5=hashlib.md5(mdata).hexdigest(), size=len(mdata), rows=len(bmap_table) + 1)
    bm['release_id'] = release_identity(bm['schema_version'], bm['files'])
    (base_out / 'manifest.json').write_text(json.dumps(bm, separators=(',', ':')) + '\n')

    prior_path, retired_path = prior_links(base_out, [], tmp_path / 'ledger')

    # Candidate captures: add v2 Congress.gov fetches in a new receipt
    cand_captures = base_captures + [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/500?format=json', data=cg_500_v2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/new.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/501?format=json', data=cg_501_v2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/new.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/502?format=json', data=cg_502_v2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/new.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/503?format=json', data=cg_503_v2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/new.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/504?format=json', data=cg_504_v2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/new.jsonl.gz'),
    ]
    staged_cand = _stage_raw(tmp_path / 'stage-cand', engine, cand_captures)

    cand_meetings = base_meetings + [
        dict(record_sha=sha(cg_500_v2), source='congress_gov', meetings=[mtg(500, title='Clean Grid Reliability Architecture', updated='2026-10-25T00:00:00Z', jackets=['50001', '50002'])]),
        dict(record_sha=sha(cg_501_v2), source='congress_gov', meetings=[mtg(501, updated='2026-10-25T00:00:00Z')]),
        dict(record_sha=sha(cg_502_v2), source='congress_gov', meetings=[mtg(502, updated='2026-10-25T00:00:00Z')]),
        dict(record_sha=sha(cg_503_v2), source='congress_gov', meetings=[mtg(503, updated='2026-10-25T00:00:00Z')]),
        dict(record_sha=sha(cg_504_v2), source='congress_gov', meetings=[mtg(504, updated='2026-10-25T00:00:00Z')]),
        dict(record_sha='61' * 32, source='congress_gov', meetings=[
            mtg(600, chamber='senate', date_str='2024-06-01', title='Twin Hearing', status='Postponed', updated='2026-10-25T00:00:00Z'),
            mtg(601, chamber='senate', date_str='2024-06-15', title='Twin Hearing', status='Scheduled', updated='2026-10-25T00:00:00Z'),
        ]),
    ]
    cand_appearances = [
        # keep v1 observations in lake + add v2 observations
        base_appearances[0],
        dict(record_sha=sha(cg_500_v2), source='congress_gov', event_id=500, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='elena rodriguez', name='Dr. Elena Rodriguez', given='Elena', family='Rodriguez', position='Director', organization='Grid Institute', panel_order=1, display_order=1),
        ]),
        # Case 4: MODS parser split name/title/org on same (source, record_sha, source_locator)
        dict(record_sha=sha(mods_p1), source='mods', package_id='CHRG-118hhrg50001', held_dates=['2024-05-01'], title='Clean Grid Reliability Architecture', collection_state='present', appearances=[
            dict(source_locator='mods:witness[1]', name_key='marcus chen', name='Marcus Chen', given='Marcus', family='Chen', position='Chief Engineer', organization='Grid Corp', display_order=1),
            dict(source_locator='mods:witness[2]', name_key='elena rodriguez', name='Elena Rodriguez', given='Elena', family='Rodriguez', position='Director', organization='Grid Institute', display_order=2),
        ]),
        base_appearances[2],
        # Case 2: 501 reordered (David Patel now witness[1], Sarah Kim witness[2])
        base_appearances[3],
        dict(record_sha=sha(cg_501_v2), source='congress_gov', event_id=501, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='david patel', name='David Patel', given='David', family='Patel', position='Fellow', organization='Policy Lab', panel_order=1, display_order=1),
            dict(source_locator='congress_gov:witness[2]', name_key='sarah kim', name='Sarah Kim', given='Sarah', family='Kim', position='Partner', organization='Civic Law', panel_order=2, display_order=2),
        ]),
        # Case 3: 502 typo fix ('Dr. Jonthan Vance' -> 'Dr. Jonathan Vance')
        base_appearances[4],
        dict(record_sha=sha(cg_502_v2), source='congress_gov', event_id=502, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='jonathan vance', name='Dr. Jonathan Vance', given='Jonathan', family='Vance', position='Vice President', organization='Acme Energy', panel_order=1, display_order=1,
                 document_links=['https://docs.house.gov/meetings/IF/IF00/20240501/500/HHRG-118-IF00-Wstate-VanceJ-20240501.pdf']),
        ]),
        # Case 7: 503 two equal entries re-fetched with new record_sha
        base_appearances[5],
        dict(record_sha=sha(cg_503_v2), source='congress_gov', event_id=503, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='john smith', name='John Smith', given='John', family='Smith', position='Citizen', organization='Public', panel_order=1, display_order=1),
            dict(source_locator='congress_gov:witness[2]', name_key='john smith', name='John Smith', given='John', family='Smith', position='Citizen', organization='Public', panel_order=1, display_order=2),
        ]),
        # Case 8: 504 ambiguous carry (1 prior Alex Morgan, 2 identical Alex Morgans in v2!)
        base_appearances[6],
        dict(record_sha=sha(cg_504_v2), source='congress_gov', event_id=504, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='alex morgan', name='Alex Morgan', given='Alex', family='Morgan', position='Analyst', organization='Metro Group', panel_order=1, display_order=1),
            dict(source_locator='congress_gov:witness[2]', name_key='alex morgan', name='Alex Morgan', given='Alex', family='Morgan', position='Analyst', organization='Metro Group', panel_order=2, display_order=2),
        ]),
        # Case 5: Senate page moved from postponed 600 to held twin 601 (same record_sha + locator)
        dict(base_appearances[7], event_id=601),
    ]

    cand_out = tmp_path / 'cand-release'
    build_release(
        **staged_cand, engine=engine, output=cand_out, scratch=tmp_path / 'cand-scratch',
        meeting_records=cand_meetings, appearance_records=cand_appearances, spicy_regs=_spicy_fixture(),
        include_entities=True, prior_links=prior_path, base_retired=retired_path,
    )

    cand_rows = pq.read_table(cand_out / 'witnesses.parquet').to_pylist()
    cand_w = { (r['occasion'], r['source'], r['package_id'], r['source_locator']): r for r in cand_rows }
    cmap = { r['old_key']: r for r in pq.read_table(cand_out / 'witness_key_map.parquet').to_pylist() }

    # 1. Unchanged re-fetch carried key, 0 map row
    k_elena = base_w[('meeting:500', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key']
    assert cand_w[('meeting:500', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key'] == k_elena
    assert k_elena not in cmap

    # 2. Reorder carried each witness's key by text, 0 map row
    k_sarah = base_w[('meeting:501', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key']
    k_david = base_w[('meeting:501', 'congress_gov', None, 'congress_gov:witness[2]')]['witness_key']
    assert cand_w[('meeting:501', 'congress_gov', None, 'congress_gov:witness[2]')]['witness_key'] == k_sarah
    assert cand_w[('meeting:501', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key'] == k_david
    assert k_sarah not in cmap and k_david not in cmap

    # 3. Typo fix minted new key, wrote unambiguous locator map row, did NOT duplicate as no_longer_listed, and 1-hop map re-resolved!
    w_502 = [r for r in cand_rows if r['occasion'] == 'meeting:502']
    assert len(w_502) == 1
    k_vance_new = w_502[0]['witness_key']
    assert k_vance_new != k_vance_base
    assert cmap[k_vance_base]['status'] == 'unambiguous'
    assert cmap[k_vance_base]['basis'] == 'locator'
    assert cmap[k_vance_base]['witness_key'] == k_vance_new
    assert cmap['0123456789abcdef']['witness_key'] == k_vance_new

    # 4. Parser change on MODS carried key by Tier 1 (source, record_sha, locator)
    assert cand_w[('meeting:500', 'mods', 'CHRG-118hhrg50001', 'mods:witness[1]')]['witness_key'] == k_p1
    assert cand_w[('meeting:500', 'mods', 'CHRG-118hhrg50002', 'mods:witness[1]')]['witness_key'] == k_p2

    # 5. Senate page moved from meeting:600 to meeting:601 carried key by Tier 1!
    k_hannah = base_w[('meeting:600', 'senate_page', None, 'senate_page:witness[1]')]['witness_key']
    assert cand_w[('meeting:601', 'senate_page', None, 'senate_page:witness[1]')]['witness_key'] == k_hannah
    assert k_hannah not in cmap

    # 7. Equal entries on 503 carried by rank!
    assert cand_w[('meeting:503', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key'] == k_eq1
    assert cand_w[('meeting:503', 'congress_gov', None, 'congress_gov:witness[2]')]['witness_key'] == k_eq2

    # 8. Ambiguous carry on 504 carried to NEITHER row and wrote ambiguous map row!
    k_alex_base = base_w[('meeting:504', 'congress_gov', None, 'congress_gov:witness[1]')]['witness_key']
    w_504_keys = sorted(r['witness_key'] for r in cand_rows if r['occasion'] == 'meeting:504')
    assert len(w_504_keys) == 2 and k_alex_base not in w_504_keys
    assert cmap[k_alex_base]['status'] == 'ambiguous'
    assert sorted(cmap[k_alex_base]['candidate_keys']) == w_504_keys


def test_lost_witness_key_refuses_export_before_manifest(tmp_path):
    """A live witness key neither published nor mapped refuses build_release before manifest.json exists."""
    from viewer_publication.archive_model import build_release
    from viewer_publication.release_gate import prior_links

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    cg_700 = _cg_json(700, '2026-10-20T00:00:00Z', 'v1')
    doc_pdf = _pdf_bytes('doc-700')
    staged = _stage_raw(tmp_path / 'stage', engine, [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/700?format=json', data=cg_700, format='json', family='congress/meetings'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/700/doc.pdf', data=doc_pdf, format='pdf', suffix='.pdf'),
    ])
    sha700 = hashlib.sha256(cg_700).hexdigest()
    meetings = [dict(record_sha=sha700, source='congress_gov', meetings=[dict(
        event_id='700', chamber='house', congress=118, session=2, updated='2026-10-20T00:00:00Z',
        title='Hearing 700', meeting_date='2024-05-01', meeting_type='HHRG', status='Scheduled',
        sittings=[], committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
        subject_keys=[], transcript_jackets=[], videos=[], document_urls=[], document_references=[],
        collection_states=dict(sittings='present', committees='present', subject_keys='empty', transcript_jackets='empty', videos='empty', document_urls='empty'),
        access='open', access_basis='default', not_held=False, title_key='hearing 700', reschedule_candidate=False,
    )])]
    appearances_base = [dict(record_sha=sha700, source='congress_gov', event_id=700, collection_state='present', appearances=[
        dict(source_locator='congress_gov:witness[1]', name_key='phantom witness', name='Phantom Witness', given='Phantom', family='Witness', position='Chair', organization='Org', display_order=1),
    ])]
    base_out = tmp_path / 'base'
    build_release(
        **staged, engine=engine, output=base_out, scratch=tmp_path / 'base-scratch',
        meeting_records=meetings, appearance_records=appearances_base, spicy_regs=_spicy_fixture(), include_entities=True,
    )
    prior_path, retired_path = prior_links(base_out, [], tmp_path / 'ledger')

    # Candidate omits Phantom Witness from lake completely (simulating an unmapped lost key)
    cand_out = tmp_path / 'cand'
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build_release(
            **staged, engine=engine, output=cand_out, scratch=tmp_path / 'cand-scratch',
            meeting_records=meetings, appearance_records=[dict(record_sha=sha700, source='congress_gov', event_id=700, collection_state='empty', appearances=[])],
            spicy_regs=_spicy_fixture(), include_entities=True, prior_links=prior_path, base_retired=retired_path,
        )
    assert not (cand_out / 'manifest.json').exists()


def test_historical_25_senate_keys_map_cleanly(tmp_path):
    """The 25 lost Senate keys from e4538f00/e145d24c resolve to 20 unambiguous + 5 unresolved map rows."""
    from viewer_publication.archive_model import ROOT, build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    registry = json.loads((ROOT / 'model/registries/historical-witness-keys.json').read_text())
    assert len(registry) == 25

    sen_captures = [dict(
        url='https://docs.house.gov/meetings/IF/IF00/20240501/500/hist-doc.pdf',
        data=_pdf_bytes('hist-doc'), format='pdf', suffix='.pdf',
    )]
    appearances = []
    meetings = []
    by_sha = {}
    for row in registry:
        if row['status'] == 'unambiguous':
            eid = int(row['target_occasion'].split(':')[1])
            by_sha.setdefault((row['record_sha'], eid), []).append(dict(
                source_locator=row['source_locator'],
                name_key=f"witness {row['old_key']}",
                name=f"Witness {row['old_key']}",
                given='Witness',
                family=row['old_key'],
                position='Official',
                organization='Agency',
                display_order=len(by_sha.get((row['record_sha'], eid), [])) + 1,
            ))
        else:
            by_sha.setdefault((row['record_sha'], None), [])

    event_ids = sorted({eid for (_, eid) in by_sha if eid is not None})
    for eid in event_ids:
        cg_bytes = _cg_json(eid, '2026-10-20T00:00:00Z', 'hist')
        sen_captures.append(dict(
            url=f'https://api.congress.gov/v3/committee-meeting/118/senate/{eid}?format=json',
            data=cg_bytes, format='json', family='congress/meetings',
        ))
        meetings.append(dict(record_sha=hashlib.sha256(cg_bytes).hexdigest(), source='congress_gov', meetings=[dict(
            event_id=str(eid), chamber='senate', congress=118, session=2, updated='2026-10-20T00:00:00Z',
            title=f'Senate Hearing {eid}', meeting_date='2024-05-01', meeting_type='SHRG', status='Scheduled',
            sittings=[], committees=[dict(system_code='hsif00', name='Committee', chamber='senate', role='host')],
            subject_keys=[], transcript_jackets=[], videos=[], document_urls=[], document_references=[],
            collection_states=dict(sittings='present', committees='present', subject_keys='empty', transcript_jackets='empty', videos='empty', document_urls='empty'),
            access='open', access_basis='default', not_held=False, title_key=f'senate hearing {eid}', reschedule_candidate=False,
        )]))
        appearances.append(dict(
            record_sha=hashlib.sha256(cg_bytes).hexdigest(), source='congress_gov', event_id=eid,
            collection_state='absent', appearances=[],
        ))
    for idx, ((rsha, eid), apps) in enumerate(by_sha.items()):
        appearances.append(dict(
            record_sha=rsha, source='senate_page', event_id=eid,
            context_url=f'https://www.banking.senate.gov/hearings/h-{idx}',
            collection_state='present' if apps else 'empty',
            appearances=apps,
        ))

    staged = _stage_raw(tmp_path / 'stage-hist', engine, sen_captures)
    out = tmp_path / 'out-hist'
    build_release(
        **staged, engine=engine, output=out, scratch=tmp_path / 'scratch-hist',
        meeting_records=meetings, appearance_records=appearances, spicy_regs=_spicy_fixture(), include_entities=True,
    )
    wmap = {r['old_key']: r for r in pq.read_table(out / 'witness_key_map.parquet').to_pylist()}
    wkeys = {r['witness_key'] for r in pq.read_table(out / 'witnesses.parquet').to_pylist()}
    assert set(wmap) == {r['old_key'] for r in registry}
    unamb = [r for r in wmap.values() if r['status'] == 'unambiguous']
    unres = [r for r in wmap.values() if r['status'] == 'unresolved']
    assert len(unamb) == 20 and len(unres) == 5
    assert all(r['witness_key'] in wkeys and r['basis'] == 'occurrence' for r in unamb)
    assert all(r['witness_key'] is None and r['basis'] is None for r in unres)


def test_congress_gov_retained_items_across_witnesses_documents_subjects_and_gate(tmp_path):
    """ct-960v: dropped Congress.gov witnesses, documents, bills, and nominations stay marked no_longer_listed,
    survive a 3rd read with stable unlisted_since, obey precedence/coverage, ignore House XML drops, and pass Gate 1."""
    from viewer_publication.archive_model import build_release
    from viewer_publication.release_comparison import compare
    from viewer_publication.release_gate import meeting_updates, prior_links

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])

    # Event 800: partial witness drop + doc drop + subject drop (read 1 -> read 2 -> read 3)
    # Event 801: full witness wipe (collection_state='empty' on read 2) on a Rescheduled meeting with a twin 802
    # Event 803: Congress.gov drops Bob, MODS print still lists Bob -> MODS 'listed' leads!
    # Event 804: House XML drops Carol -> NOT retained as no_longer_listed!
    cg_800_r1 = _cg_json(800, '2026-10-20T00:00:00Z', 'r1')
    cg_800_r2 = _cg_json(800, '2026-10-25T00:00:00Z', 'r2')
    cg_800_r3 = _cg_json(800, '2026-10-28T00:00:00Z', 'r3')
    cg_801_r1 = _cg_json(801, '2026-10-20T00:00:00Z', 'r1')
    cg_801_r2 = _cg_json(801, '2026-10-25T00:00:00Z', 'r2')
    cg_802_r1 = _cg_json(802, '2026-10-25T00:00:00Z', 'r1')
    cg_803_r1 = _cg_json(803, '2026-10-20T00:00:00Z', 'r1')
    cg_803_r2 = _cg_json(803, '2026-10-25T00:00:00Z', 'r2')
    mods_803 = b'<mods><titleInfo><title>Hearing 803 Print</title></titleInfo></mods>'
    hxml_804_r1 = b'<committee-meeting><event-id>804</event-id><r>1</r></committee-meeting>'
    hxml_804_r2 = b'<committee-meeting><event-id>804</event-id><r>2</r></committee-meeting>'
    doc_keep = _pdf_bytes('keep-doc')
    doc_drop = _pdf_bytes('drop-doc')

    sha = lambda b: hashlib.sha256(b).hexdigest()
    url_keep = 'https://docs.house.gov/meetings/IF/IF00/20240501/800/keep.pdf'
    url_drop = 'https://www.banking.senate.gov/imo/media/doc/dropped-report.pdf'

    r1_captures = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/800?format=json', data=cg_800_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/801?format=json', data=cg_801_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/803?format=json', data=cg_803_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        dict(url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg80301/mods.xml', data=mods_803, format='xml', family='govinfo/mods', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/804/HMTG-118-IF00-20240501-804.xml', data=hxml_804_r1, format='xml', family='house/meeting-xml', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        dict(url=url_keep, data=doc_keep, format='pdf', suffix='.pdf', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
        # Neutral archive URL without event_id in path so meeting_keys comes ONLY from meeting_document_urls!
        dict(url=url_drop, data=doc_drop, format='pdf', suffix='.pdf', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/documents/2026-10-20/r1.jsonl.gz'),
    ]

    def mrow(eid, *, updated='2026-10-20T00:00:00Z', status='Scheduled', date_str='2024-05-01', title=None, subjects=(), doc_urls=(), doc_refs=(), jackets=()):
        t = title or f'Hearing {eid}'
        return dict(
            event_id=str(eid), chamber='house', congress=118, session=2, updated=updated, title=t,
            meeting_date=date_str, meeting_type='HHRG', status=status, sittings=[],
            committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
            subject_keys=list(subjects), transcript_jackets=list(jackets), videos=[],
            document_urls=list(doc_urls), document_references=list(doc_refs),
            collection_states=dict(
                sittings='present', committees='present',
                subject_keys='present' if subjects else 'empty',
                transcript_jackets='present' if jackets else 'empty',
                videos='empty',
                document_urls='present' if doc_urls else 'empty',
            ),
            access='open', access_basis='default', not_held=status in ('Postponed', 'Canceled'),
            title_key=t.lower(), reschedule_candidate=status in ('Postponed', 'Rescheduled'),
        )

    ref_keep = dict(collection='meeting_documents', ordinal=1, url=url_keep, role='Support Document', format='PDF', description=None, name='Keep Doc')
    ref_drop = dict(collection='meeting_documents', ordinal=2, url=url_drop, role='Support Document', format='PDF', description=None, name='Dropped Doc')

    m_r1 = [
        dict(record_sha=sha(cg_800_r1), source='congress_gov', meetings=[
            mrow(800, subjects=['118-hr-100', '118-pn-50'], doc_urls=[url_keep, url_drop], doc_refs=[ref_keep, ref_drop]),
        ]),
        dict(record_sha=sha(cg_801_r1), source='congress_gov', meetings=[mrow(801, title='Grid Reliability Review', status='Scheduled', date_str='2024-05-01')]),
        dict(record_sha=sha(cg_803_r1), source='congress_gov', meetings=[mrow(803, jackets=['80301'])]),
        dict(record_sha=sha(hxml_804_r1), source='house_xml', meetings=[mrow(804, updated='2024-05-01T10:00:00Z')]),
    ]
    a_r1 = [
        dict(record_sha=sha(cg_800_r1), source='congress_gov', event_id=800, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='alice baker', name='Alice Baker', given='Alice', family='Baker', position='Director', organization='Solar Org', panel_order=1, display_order=1),
            dict(source_locator='congress_gov:witness[2]', name_key='robert carter', name='Robert Carter', given='Robert', family='Carter', position='Counsel', organization='Wind Association', panel_order=1, display_order=2),
        ]),
        dict(record_sha=sha(cg_801_r1), source='congress_gov', event_id=801, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='diana prince', name='Diana Prince', given='Diana', family='Prince', position='CEO', organization='Grid Co', panel_order=1, display_order=1),
        ]),
        dict(record_sha=sha(cg_803_r1), source='congress_gov', event_id=803, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='frank miller', name='Frank Miller', given='Frank', family='Miller', position='Chair', organization='Board', panel_order=1, display_order=1),
        ]),
        dict(record_sha=sha(mods_803), source='mods', package_id='CHRG-118hhrg80301', held_dates=['2024-05-01'], title='Hearing 803', collection_state='present', appearances=[
            dict(source_locator='mods:witness[1]', name_key='frank miller', name='Frank Miller', given='Frank', family='Miller', position='Chair', organization='Board', display_order=1),
        ]),
        dict(record_sha=sha(hxml_804_r1), source='house_xml', event_id=804, collection_state='present', appearances=[
            dict(source_locator='house_xml:witness[1]', name_key='carol danvers', name='Carol Danvers', given='Carol', family='Danvers', position='Pilot', organization='Aero', display_order=1),
            dict(source_locator='house_xml:witness[2]', name_key='steve rogers', name='Steve Rogers', given='Steve', family='Rogers', position='Captain', organization='Civic', display_order=2),
        ]),
    ]

    staged_r1 = _stage_raw(tmp_path / 'stage-r1', engine, r1_captures)
    rel1 = tmp_path / 'rel-1'
    build_release(
        **staged_r1, engine=engine, output=rel1, scratch=tmp_path / 'scratch-1',
        meeting_records=m_r1, appearance_records=a_r1, spicy_regs=_spicy_fixture(), include_entities=True,
    )
    w_r1 = { (r['occasion'], r['source'], r['name']): r for r in pq.read_table(rel1 / 'witnesses.parquet').to_pylist() }
    assert all(r['listing_status'] == 'listed' and r['last_listed_on'] is None and r['unlisted_since'] is None for r in w_r1.values())
    k_carter = w_r1[('meeting:800', 'congress_gov', 'Robert Carter')]['witness_key']
    k_diana = w_r1[('meeting:801', 'congress_gov', 'Diana Prince')]['witness_key']

    # Read 2: Congress.gov drops Robert Carter, url_drop, and 118-pn-50 on 800; wipes 801 ('empty') and marks 801 Rescheduled with twin 802; drops Frank Miller on 803; House XML drops Steve Rogers on 804
    r2_captures = r1_captures + [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/800?format=json', data=cg_800_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/r2.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/801?format=json', data=cg_801_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/r2.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/802?format=json', data=cg_802_r1, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/r2.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/803?format=json', data=cg_803_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/r2.jsonl.gz'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/804/HMTG-118-IF00-20240501-804.xml', data=hxml_804_r2, format='xml', family='house/meeting-xml', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/documents/2026-10-25/r2.jsonl.gz'),
    ]
    m_r2 = m_r1 + [
        dict(record_sha=sha(cg_800_r2), source='congress_gov', meetings=[
            mrow(800, updated='2026-10-25T00:00:00Z', subjects=['118-hr-100'], doc_urls=[url_keep], doc_refs=[ref_keep]),
        ]),
        dict(record_sha=sha(cg_801_r2), source='congress_gov', meetings=[
            mrow(801, updated='2026-10-25T00:00:00Z', title='Grid Reliability Review', status='Rescheduled', date_str='2024-05-01'),
        ]),
        dict(record_sha=sha(cg_802_r1), source='congress_gov', meetings=[
            mrow(802, updated='2026-10-25T00:00:00Z', title='Grid Reliability Review', status='Scheduled', date_str='2024-05-20'),
        ]),
        dict(record_sha=sha(cg_803_r2), source='congress_gov', meetings=[mrow(803, updated='2026-10-25T00:00:00Z', jackets=['80301'])]),
        dict(record_sha=sha(hxml_804_r2), source='house_xml', meetings=[mrow(804, updated='2024-05-05T10:00:00Z')]),
    ]
    a_r2 = a_r1 + [
        dict(record_sha=sha(cg_800_r2), source='congress_gov', event_id=800, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='alice baker', name='Alice Baker', given='Alice', family='Baker', position='Director', organization='Solar Org', panel_order=1, display_order=1),
        ]),
        dict(record_sha=sha(cg_801_r2), source='congress_gov', event_id=801, collection_state='empty', appearances=[]),
        dict(record_sha=sha(cg_802_r1), source='congress_gov', event_id=802, collection_state='empty', appearances=[]),
        dict(record_sha=sha(cg_803_r2), source='congress_gov', event_id=803, collection_state='empty', appearances=[]),
        dict(record_sha=sha(hxml_804_r2), source='house_xml', event_id=804, collection_state='present', appearances=[
            dict(source_locator='house_xml:witness[1]', name_key='carol danvers', name='Carol Danvers', given='Carol', family='Danvers', position='Pilot', organization='Aero', display_order=1),
        ]),
    ]

    # Note: for House XML drop test on 804, Steve Rogers' key from rel1 would refuse if unmapped unless we test 804 on a fresh build or keep Rogers out of rel1.
    # Let's verify 804 on a fresh build (no base release) first so we isolate House XML non-retention from live-key refusal!
    staged_r2 = _stage_raw(tmp_path / 'stage-r2', engine, r2_captures)
    rel2_fresh = tmp_path / 'rel-2-fresh'
    build_release(
        **staged_r2, engine=engine, output=rel2_fresh, scratch=tmp_path / 'scratch-2-fresh',
        meeting_records=m_r2, appearance_records=a_r2, spicy_regs=_spicy_fixture(), include_entities=True,
    )
    w_804 = [r for r in pq.read_table(rel2_fresh / 'witnesses.parquet').to_pylist() if r['occasion'] == 'meeting:804']
    assert [r['name'] for r in w_804] == ['Carol Danvers']  # House XML drop is NOT retained as no_longer_listed!

    # Now build base -> read 2 -> read 3 for Congress.gov meetings (800, 801, 802, 803)
    staged_cg_r1 = _stage_raw(tmp_path / 'stage-cg-r1', engine, [c for c in r1_captures if '804' not in c['url']])
    staged_cg_r2 = _stage_raw(tmp_path / 'stage-cg-r2', engine, [c for c in r2_captures if '804' not in c['url']])
    m_cg_r1 = [r for r in m_r1 if r['source'] != 'house_xml']
    a_cg_r1 = [r for r in a_r1 if r['source'] != 'house_xml']
    rel_cg_1 = tmp_path / 'rel-cg-1'
    build_release(
        **staged_cg_r1, engine=engine, output=rel_cg_1, scratch=tmp_path / 'scratch-cg-1',
        meeting_records=m_cg_r1, appearance_records=a_cg_r1, spicy_regs=_spicy_fixture(), include_entities=True,
    )
    w_cg1 = { (r['occasion'], r['source'], r['name']): r for r in pq.read_table(rel_cg_1 / 'witnesses.parquet').to_pylist() }
    k_carter = w_cg1[('meeting:800', 'congress_gov', 'Robert Carter')]['witness_key']
    k_diana = w_cg1[('meeting:801', 'congress_gov', 'Diana Prince')]['witness_key']

    p12, r12 = prior_links(rel_cg_1, [], tmp_path / 'ledger-12')
    m_cg_r2 = [r for r in m_r2 if r['source'] != 'house_xml']
    a_cg_r2 = [r for r in a_r2 if r['source'] != 'house_xml']
    rel_cg_2 = tmp_path / 'rel-cg-2'
    build_release(
        **staged_cg_r2, engine=engine, output=rel_cg_2, scratch=tmp_path / 'scratch-cg-2',
        meeting_records=m_cg_r2, appearance_records=a_cg_r2, spicy_regs=_spicy_fixture(),
        include_entities=True, prior_links=p12, base_retired=r12,
    )

    w_cg2 = { (r['occasion'], r['source'], r['name']): r for r in pq.read_table(rel_cg_2 / 'witnesses.parquet').to_pylist() }
    alice = w_cg2[('meeting:800', 'congress_gov', 'Alice Baker')]
    carter = w_cg2[('meeting:800', 'congress_gov', 'Robert Carter')]
    diana = w_cg2[('meeting:801', 'congress_gov', 'Diana Prince')]
    frank_cg = w_cg2[('meeting:803', 'congress_gov', 'Frank Miller')]
    frank_mods = w_cg2[('meeting:803', 'mods', 'Frank Miller')]

    assert alice['listing_status'] == 'listed' and alice['last_listed_on'] is None and alice['unlisted_since'] is None
    assert carter['witness_key'] == k_carter
    assert carter['record_sha'] == bytes.fromhex(sha(cg_800_r1))
    assert carter['listing_status'] == 'no_longer_listed'
    assert carter['last_listed_on'] == date(2026, 10, 20)
    assert carter['unlisted_since'] == date(2026, 10, 25)
    assert carter['unlisted_by_record_sha'] == sha(cg_800_r2)

    # Full wipe on 801: Diana retained as no_longer_listed, AND 801 still moves to 802 (own_evidence ignores no_longer_listed!)
    assert diana['witness_key'] == k_diana and diana['listing_status'] == 'no_longer_listed'
    m_cg2 = { r['event_id']: r for r in pq.read_table(rel_cg_2 / 'meetings.parquet').to_pylist() }
    assert m_cg2[801]['rescheduled_to'] == 802

    # Precedence on 803: MODS 'listed' supersedes Congress.gov 'no_longer_listed'
    assert frank_mods['superseded_by'] is None
    assert frank_cg['superseded_by'] == frank_mods['witness_key']

    # Meeting 800 retained document_references + meeting_keys on dropped PDF + subject_keys + unlisted_subjects
    drefs = { r['url']: r for r in m_cg2[800]['document_references'] }
    assert drefs[url_keep]['listing_status'] == 'listed' and drefs[url_keep]['unlisted_since'] is None
    assert drefs[url_drop]['listing_status'] == 'no_longer_listed'
    assert drefs[url_drop]['last_listed_on'] == date(2026, 10, 20)
    assert drefs[url_drop]['unlisted_since'] == date(2026, 10, 25)
    assert drefs[url_drop]['unlisted_by_record_sha'] == sha(cg_800_r2)

    docs_800 = [r for r in pq.read_table(rel_cg_2 / 'list.parquet').to_pylist() if '800' in (r['meeting_keys'] or [])]
    assert len(docs_800) == 2  # dropped-report.pdf kept its meeting_keys=['800']!

    assert set(m_cg2[800]['subject_keys']) == {'118-hr-100', '118-pn-50'}
    assert m_cg2[800]['unlisted_subjects'] == [dict(
        subject_key='118-pn-50',
        last_listed_on=date(2026, 10, 20),
        unlisted_since=date(2026, 10, 25),
        unlisted_by_record_sha=sha(cg_800_r2),
    )]

    # Gate 1 comparison + unattended automatic_causes + verdict between rel_cg_1 and rel_cg_2 passes with 0 lost keys!
    from viewer_publication.release_gate import automatic_causes, verdict
    report = compare(rel_cg_1, rel_cg_2)
    assert [g for g in report['failing'] if g['file'] != 'url_state.parquet'] == []
    auto_groups, auto_reasons = automatic_causes(
        report, rel_cg_1, rel_cg_2, engine=engine,
        captures=dict(kind='parquet', path=str(staged_cg_r2['captures'])),
        live_receipt_keys=['receipts/documents/2026-10-20/r1.jsonl.gz'],
        candidate_receipt_keys=['receipts/documents/2026-10-20/r1.jsonl.gz', 'receipts/documents/2026-10-25/r2.jsonl.gz'],
        read_receipt=lambda k: (tmp_path / 'stage-cg-r2' / 'raw' / k).read_bytes(),
        work=tmp_path / 'auto-12',
    )
    assert auto_reasons == []
    assert verdict(report, dict(
        base_release_id=report['base_release'], candidate_release_id=report['candidate_release'], groups=auto_groups,
    ))[0] == []
    updates = meeting_updates(report, rel_cg_1, rel_cg_2)
    assert all(u['keys_lost'] == [] for u in updates)

    # Read 3 on 2026-10-28 (plus an unchanged poll of cg_800_r2 on 2026-10-27):
    # unlisted_since and unlisted_by_record_sha stay pinned to read 2's FIRST fetch date (2026-10-25)!
    r3_captures = [c for c in r2_captures if '804' not in c['url']] + [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/800?format=json', data=cg_800_r2, outcome='unchanged', format='json', family='congress/meetings', retrieved_at='2026-10-27T12:00:00Z', receipt_key='receipts/documents/2026-10-27/r2-unchanged.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/800?format=json', data=cg_800_r3, format='json', family='congress/meetings', retrieved_at='2026-10-28T12:00:00Z', receipt_key='receipts/documents/2026-10-28/r3.jsonl.gz'),
    ]
    staged_r3 = _stage_raw(tmp_path / 'stage-r3', engine, r3_captures)
    m_cg_r3 = m_cg_r2 + [
        dict(record_sha=sha(cg_800_r3), source='congress_gov', meetings=[
            mrow(800, updated='2026-10-28T00:00:00Z', subjects=['118-hr-100'], doc_urls=[url_keep], doc_refs=[ref_keep]),
        ]),
    ]
    a_cg_r3 = a_cg_r2 + [
        dict(record_sha=sha(cg_800_r3), source='congress_gov', event_id=800, collection_state='present', appearances=[
            dict(source_locator='congress_gov:witness[1]', name_key='alice baker', name='Alice Baker', given='Alice', family='Baker', position='Director', organization='Solar Org', panel_order=1, display_order=1),
        ]),
    ]
    p23, r23 = prior_links(rel_cg_2, [], tmp_path / 'ledger-23')
    rel_cg_3 = tmp_path / 'rel-cg-3'
    build_release(
        **staged_r3, engine=engine, output=rel_cg_3, scratch=tmp_path / 'scratch-cg-3',
        meeting_records=m_cg_r3, appearance_records=a_cg_r3, spicy_regs=_spicy_fixture(),
        include_entities=True, prior_links=p23, base_retired=r23,
    )
    w_cg3 = { (r['occasion'], r['source'], r['name']): r for r in pq.read_table(rel_cg_3 / 'witnesses.parquet').to_pylist() }
    carter_3 = w_cg3[('meeting:800', 'congress_gov', 'Robert Carter')]
    assert carter_3['witness_key'] == k_carter
    assert carter_3['last_listed_on'] == date(2026, 10, 20)
    assert carter_3['unlisted_since'] == date(2026, 10, 25)
    assert carter_3['unlisted_by_record_sha'] == sha(cg_800_r2)
    m_cg3 = { r['event_id']: r for r in pq.read_table(rel_cg_3 / 'meetings.parquet').to_pylist() }
    drefs_3 = { r['url']: r for r in m_cg3[800]['document_references'] }
    assert drefs_3[url_drop]['unlisted_since'] == date(2026, 10, 25)
    assert m_cg3[800]['unlisted_subjects'][0]['unlisted_since'] == date(2026, 10, 25)
    report_23 = compare(rel_cg_2, rel_cg_3)
    assert [g for g in report_23['failing'] if g['file'] != 'url_state.parquet'] == []
    auto_groups_23, auto_reasons_23 = automatic_causes(
        report_23, rel_cg_2, rel_cg_3, engine=engine,
        captures=dict(kind='parquet', path=str(staged_r3['captures'])),
        live_receipt_keys=['receipts/documents/2026-10-20/r1.jsonl.gz', 'receipts/documents/2026-10-25/r2.jsonl.gz'],
        candidate_receipt_keys=['receipts/documents/2026-10-20/r1.jsonl.gz', 'receipts/documents/2026-10-25/r2.jsonl.gz', 'receipts/documents/2026-10-27/r2-unchanged.jsonl.gz', 'receipts/documents/2026-10-28/r3.jsonl.gz'],
        read_receipt=lambda k: (tmp_path / 'stage-r3' / 'raw' / k).read_bytes(),
        work=tmp_path / 'auto-23',
    )
    assert auto_reasons_23 == []
    assert verdict(report_23, dict(
        base_release_id=report_23['base_release'], candidate_release_id=report_23['candidate_release'], groups=auto_groups_23,
    ))[0] == []


def test_mods_occasion_move_duplicate_collapse_and_congress_gov_absent_wipes(tmp_path):
    """Regressions for Round 1 blind review:
    - BLOCKER 1: MODS witness moving package:CHRG-... -> meeting:<id> on a record_sha bump maps unambiguous
      (never inconsistent_witness_key_map), and a 2->1 duplicate collapse maps unresolved with empty candidate_keys.
    - BLOCKER 2 & WARNING 2: Real Congress.gov JSON reads omitting meetingDocuments/relatedItems/witnesses
      (collection_state='absent') retain dropped docs, bills, nominations, wiped witness rosters, and partial
      duplicate TBA slots as no_longer_listed.
    """
    import sys
    from viewer_publication.archive_format import release_identity
    from viewer_publication.archive_model import ROOT, build_release
    from viewer_publication.release_gate import prior_links

    sys.path.insert(0, str(ROOT / 'scripts/measure'))
    import congress_gov_retained_raw_check as retained_check

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()

    mods_v1 = b'<mods><titleInfo><title> Clara Print v1 </title></titleInfo></mods>'
    mods_v2 = b'<mods><titleInfo><title> Clara Print v2 </title></titleInfo></mods>'
    hxml_911_v1 = b'<committee-meeting meeting-id="911"><r>1</r></committee-meeting>'
    hxml_911_v2 = b'<committee-meeting meeting-id="911"><r>2</r></committee-meeting>'
    doc_wiped_pdf = _pdf_bytes('wiped-by-absent-key')
    url_wiped = 'https://www.banking.senate.gov/imo/media/doc/wiped-absent.pdf'

    cg_910 = json.dumps({
        'committeeMeeting': {
            'eventId': '910',
            'chamber': 'House',
            'congress': 118,
            'updateDate': '2026-10-25T00:00:00Z',
            'title': 'Clara Print Hearing',
            'date': '2024-05-01T14:00:00Z',
            'meetingStatus': 'Scheduled',
            'committees': [{'systemCode': 'hsif00', 'name': 'Energy and Commerce'}],
            'hearingTranscript': [{'jacketNumber': '91001'}],
        }
    }).encode()

    cg_920_r1 = json.dumps({
        'committeeMeeting': {
            'eventId': '920',
            'chamber': 'House',
            'congress': 118,
            'updateDate': '2026-10-20T00:00:00Z',
            'title': 'Full Collection Wipe & Partial TBA Drop',
            'date': '2024-05-02T14:00:00Z',
            'meetingStatus': 'Scheduled',
            'committees': [{'systemCode': 'hsif00', 'name': 'Energy and Commerce'}],
            'meetingDocuments': [
                {'url': url_wiped, 'name': 'Wiped Support Doc', 'format': 'PDF', 'documentType': 'Support Document'},
            ],
            'relatedItems': {
                'bills': [{'congress': 118, 'type': 'HR', 'number': 100}],
                'nominations': [{'congress': 118, 'number': '50', 'part': '00'}],
            },
            'witnesses': [
                {'name': 'TBA', 'organization': 'Panel One', 'position': 'Witness'},
                {'name': 'TBA', 'organization': 'Panel One', 'position': 'Witness'},
            ],
        }
    }).encode()
    # Read 2 omits meetingDocuments and relatedItems completely ('absent') and drops 1 of the 2 TBA witnesses!
    cg_920_r2 = json.dumps({
        'committeeMeeting': {
            'eventId': '920',
            'chamber': 'House',
            'congress': 118,
            'updateDate': '2026-10-25T00:00:00Z',
            'title': 'Full Collection Wipe & Partial TBA Drop',
            'date': '2024-05-02T14:00:00Z',
            'meetingStatus': 'Scheduled',
            'committees': [{'systemCode': 'hsif00', 'name': 'Energy and Commerce'}],
            'witnesses': [
                {'name': 'TBA', 'organization': 'Panel One', 'position': 'Witness'},
            ],
        }
    }).encode()

    cg_921_r1 = json.dumps({
        'committeeMeeting': {
            'eventId': '921',
            'chamber': 'House',
            'congress': 118,
            'updateDate': '2026-10-20T00:00:00Z',
            'title': 'Omitted Witnesses Key Wipe',
            'date': '2024-05-03T14:00:00Z',
            'meetingStatus': 'Scheduled',
            'committees': [{'systemCode': 'hsif00', 'name': 'Energy and Commerce'}],
            'witnesses': [
                {'name': 'Diana Wiped', 'position': 'CEO', 'organization': 'Grid Co'},
            ],
        }
    }).encode()
    # Read 2 omits 'witnesses' completely (collection_state == 'absent')!
    cg_921_r2 = json.dumps({
        'committeeMeeting': {
            'eventId': '921',
            'chamber': 'House',
            'congress': 118,
            'updateDate': '2026-10-25T00:00:00Z',
            'title': 'Omitted Witnesses Key Wipe',
            'date': '2024-05-03T14:00:00Z',
            'meetingStatus': 'Postponed',
            'committees': [{'systemCode': 'hsif00', 'name': 'Energy and Commerce'}],
        }
    }).encode()

    def cg_obs(raw_bytes):
        obs = ar_lake.extract_congress_gov_observation(raw_bytes)
        return dict(
            record_sha=sha(raw_bytes),
            source='congress_gov',
            event_id=obs['event_id'],
            collection_state=obs['collection_state'],
            appearances=obs['appearances'],
        )

    assert cg_obs(cg_921_r2)['collection_state'] == 'absent'
    m920_r2 = mr_lake.extract_congress_gov_meetings(cg_920_r2)[0]
    assert m920_r2['collection_states']['document_urls'] == 'absent'
    assert m920_r2['collection_states']['subject_keys'] == 'absent'

    base_caps = [
        dict(url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg91001/mods.xml', data=mods_v1, format='xml', family='govinfo/mods', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-20/r1.jsonl.gz'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/911/HMTG-118-IF00-20240501-911.xml', data=hxml_911_v1, format='xml', family='house/meeting-xml', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-20/r1.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/920?format=json', data=cg_920_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-20/r1.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/921?format=json', data=cg_921_r1, format='json', family='congress/meetings', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-20/r1.jsonl.gz'),
        dict(url=url_wiped, data=doc_wiped_pdf, format='pdf', suffix='.pdf', retrieved_at='2026-10-20T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-20/r1.jsonl.gz'),
    ]
    staged_b = _stage_raw(tmp_path / 'st-b', engine, base_caps)
    base_m = [
        dict(record_sha=sha(hxml_911_v1), source='house_xml', meetings=[dict(
            event_id='911', chamber='house', congress=118, session=2, updated='2026-10-20T00:00:00Z',
            title='Duplicate Collapse Hearing', meeting_date='2024-05-01', meeting_type='HHRG', status='Scheduled',
            sittings=[], committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
            subject_keys=[], transcript_jackets=[], videos=[], document_urls=[], document_references=[],
            collection_states=dict(sittings='present', committees='present', subject_keys='empty', transcript_jackets='empty', videos='empty', document_urls='empty'),
            access='open', access_basis='default', not_held=False, title_key='duplicate collapse hearing', reschedule_candidate=False,
        )]),
        dict(record_sha=sha(cg_920_r1), source='congress_gov', meetings=mr_lake.extract_congress_gov_meetings(cg_920_r1)),
        dict(record_sha=sha(cg_921_r1), source='congress_gov', meetings=mr_lake.extract_congress_gov_meetings(cg_921_r1)),
    ]
    base_a = [
        dict(record_sha=sha(mods_v1), source='mods', package_id='CHRG-118hhrg91001', held_dates=['2024-05-01'], title='Clara Print Hearing', collection_state='present', appearances=[
            dict(source_locator='mods:witness[1]', name_key='clara barton', name='Clara Barton', given='Clara', family='Barton', position='President', organization='Relief Corps', display_order=1),
        ]),
        dict(record_sha=sha(hxml_911_v1), source='house_xml', event_id=911, collection_state='present', appearances=[
            dict(source_locator='house_xml:witness[1]', name_key='john doe', name='John Doe', given='John', family='Doe', position='Analyst', organization='Policy Lab', display_order=1),
            dict(source_locator='house_xml:witness[2]', name_key='john doe', name='John Doe', given='John', family='Doe', position='Analyst', organization='Policy Lab', display_order=2),
        ]),
        cg_obs(cg_920_r1),
        cg_obs(cg_921_r1),
    ]
    rel_b = tmp_path / 'rel-b'
    build_release(
        **staged_b, engine=engine, output=rel_b, scratch=tmp_path / 'sc-b',
        meeting_records=base_m, appearance_records=base_a, spicy_regs=_spicy_fixture(), include_entities=True,
    )
    bw = {(r['occasion'], r['source'], r['source_locator']): r for r in pq.read_table(rel_b / 'witnesses.parquet').to_pylist()}
    k_clara_old = bw[('package:CHRG-118hhrg91001', 'mods', 'mods:witness[1]')]['witness_key']
    k_doe_1 = bw[('meeting:911', 'house_xml', 'house_xml:witness[1]')]['witness_key']
    k_doe_2 = bw[('meeting:911', 'house_xml', 'house_xml:witness[2]')]['witness_key']
    k_diana_921 = bw[('meeting:921', 'congress_gov', 'congress_gov:witness[1]')]['witness_key']

    # Inject 1-hop legacy map rows for Clara and Doe_2 to exercise bm_unamb_hopped on both unambiguous and unresolved
    bmap_t = pq.read_table(rel_b / 'witness_key_map.parquet')
    hop_rows = pa.Table.from_pylist([
        dict(old_key='aaaa000011112222', witness_key=k_clara_old, status='unambiguous', basis='occurrence', candidate_keys=[], occasion='package:CHRG-118hhrg91001', source='mods'),
        dict(old_key='bbbb000011112222', witness_key=k_doe_2, status='unambiguous', basis='content', candidate_keys=[], occasion='meeting:911', source='house_xml'),
    ], schema=bmap_t.schema)
    pq.write_table(pa.concat_tables([bmap_t, hop_rows]), rel_b / 'witness_key_map.parquet')
    bm = json.loads((rel_b / 'manifest.json').read_text())
    mdata = (rel_b / 'witness_key_map.parquet').read_bytes()
    for f in bm['files']:
        if f['name'] == 'witness_key_map.parquet':
            f.update(sha256=hashlib.sha256(mdata).hexdigest(), md5=hashlib.md5(mdata).hexdigest(), size=len(mdata), rows=len(bmap_t) + 2)
    bm['release_id'] = release_identity(bm['schema_version'], bm['files'])
    (rel_b / 'manifest.json').write_text(json.dumps(bm, separators=(',', ':')) + '\n')

    prior_p, retired_p = prior_links(rel_b, [], tmp_path / 'ledger-b')

    cand_caps = [
        c for c in base_caps if c['data'] != mods_v1
    ] + [
        dict(url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg91001/mods.xml', data=mods_v2, format='xml', family='govinfo/mods', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-25/r2.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/910?format=json', data=cg_910, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-25/r2.jsonl.gz'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/911/HMTG-118-IF00-20240501-911.xml', data=hxml_911_v2, format='xml', family='house/meeting-xml', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-25/r2.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/920?format=json', data=cg_920_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-25/r2.jsonl.gz'),
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/921?format=json', data=cg_921_r2, format='json', family='congress/meetings', retrieved_at='2026-10-25T12:00:00Z', receipt_key='receipts/congress/meetings/2026-10-25/r2.jsonl.gz'),
    ]
    staged_c = _stage_raw(tmp_path / 'st-c', engine, cand_caps)
    cand_m = base_m + [
        dict(record_sha=sha(cg_910), source='congress_gov', meetings=mr_lake.extract_congress_gov_meetings(cg_910)),
        dict(record_sha=sha(hxml_911_v2), source='house_xml', meetings=[dict(
            event_id='911', chamber='house', congress=118, session=2, updated='2026-10-25T00:00:00Z',
            title='Duplicate Collapse Hearing', meeting_date='2024-05-01', meeting_type='HHRG', status='Scheduled',
            sittings=[], committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
            subject_keys=[], transcript_jackets=[], videos=[], document_urls=[], document_references=[],
            collection_states=dict(sittings='present', committees='present', subject_keys='empty', transcript_jackets='empty', videos='empty', document_urls='empty'),
            access='open', access_basis='default', not_held=False, title_key='duplicate collapse hearing', reschedule_candidate=False,
        )]),
        dict(record_sha=sha(cg_920_r2), source='congress_gov', meetings=mr_lake.extract_congress_gov_meetings(cg_920_r2)),
        dict(record_sha=sha(cg_921_r2), source='congress_gov', meetings=mr_lake.extract_congress_gov_meetings(cg_921_r2)),
    ]
    cand_a = [
        dict(record_sha=sha(mods_v2), source='mods', package_id='CHRG-118hhrg91001', held_dates=['2024-05-01'], title='Clara Print Hearing', collection_state='present', appearances=[
            dict(source_locator='mods:witness[1]', name_key='clara barton', name='Clara Barton', given='Clara', family='Barton', position='President', organization='Relief Corps', display_order=1),
        ]),
        dict(record_sha=sha(cg_910), source='congress_gov', event_id=910, collection_state='absent', appearances=[]),
        dict(record_sha=sha(hxml_911_v2), source='house_xml', event_id=911, collection_state='present', appearances=[
            dict(source_locator='house_xml:witness[1]', name_key='john doe', name='John Doe', given='John', family='Doe', position='Analyst', organization='Policy Lab', display_order=1),
        ]),
        cg_obs(cg_920_r1),
        cg_obs(cg_920_r2),
        cg_obs(cg_921_r1),
        cg_obs(cg_921_r2),
    ]

    rel_c = tmp_path / 'rel-c'
    build_release(
        **staged_c, engine=engine, output=rel_c, scratch=tmp_path / 'sc-c',
        meeting_records=cand_m, appearance_records=cand_a, spicy_regs=_spicy_fixture(),
        include_entities=True, prior_links=prior_p, base_retired=retired_p,
    )

    cw_rows = pq.read_table(rel_c / 'witnesses.parquet').to_pylist()
    cmap = {r['old_key']: r for r in pq.read_table(rel_c / 'witness_key_map.parquet').to_pylist()}
    cmeetings = {r['event_id']: r for r in pq.read_table(rel_c / 'meetings.parquet').to_pylist()}

    # BLOCKER 1 assertions
    clara_new = [r for r in cw_rows if r['occasion'] == 'meeting:910' and r['source'] == 'mods']
    assert len(clara_new) == 1
    assert cmap[k_clara_old]['status'] == 'unambiguous'
    assert cmap[k_clara_old]['basis'] == 'content'
    assert cmap[k_clara_old]['witness_key'] == clara_new[0]['witness_key']
    assert cmap['aaaa000011112222']['status'] == 'unambiguous'
    assert cmap['aaaa000011112222']['witness_key'] == clara_new[0]['witness_key']

    assert cmap[k_doe_1]['status'] == 'unresolved' and cmap[k_doe_1]['basis'] is None and cmap[k_doe_1]['candidate_keys'] == []
    assert cmap[k_doe_2]['status'] == 'unresolved' and cmap[k_doe_2]['basis'] is None and cmap[k_doe_2]['candidate_keys'] == []
    assert cmap['bbbb000011112222']['status'] == 'unresolved' and cmap['bbbb000011112222']['basis'] is None

    # BLOCKER 2 & WARNING 2 assertions on 920 and 921
    m920 = cmeetings[920]
    assert [r['url'] for r in m920['document_references']] == [url_wiped]
    assert m920['document_references'][0]['listing_status'] == 'no_longer_listed'
    assert m920['document_references'][0]['unlisted_by_record_sha'] == sha(cg_920_r2)
    docs_920 = [r for r in pq.read_table(rel_c / 'list.parquet').to_pylist() if '920' in (r['meeting_keys'] or [])]
    assert len(docs_920) == 1
    assert set(m920['subject_keys']) == {'118-hr-100', '118-pn-50'}
    assert {u['subject_key'] for u in m920['unlisted_subjects']} == {'118-hr-100', '118-pn-50'}

    w920 = sorted([r for r in cw_rows if r['occasion'] == 'meeting:920'], key=lambda r: r['listing_status'])
    assert [r['listing_status'] for r in w920] == ['listed', 'no_longer_listed']

    w921 = [r for r in cw_rows if r['occasion'] == 'meeting:921']
    assert len(w921) == 1
    assert w921[0]['witness_key'] == k_diana_921
    assert w921[0]['listing_status'] == 'no_longer_listed'
    assert w921[0]['unlisted_by_record_sha'] == sha(cg_921_r2)

    raw_reads, h_docs, h_subjs = retained_check.load_raw_reads(tmp_path / 'st-c' / 'raw', staged_c['captures'])
    eval_res = retained_check.evaluate(cw_rows, list(cmeetings.values()), raw_reads, h_docs, h_subjs)
    assert eval_res['flag_count'] == 0, eval_res['flags']

