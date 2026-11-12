"""End-to-end regressions for the Wave 4 horizontal raw-data audit (cat2-x47u, cat2-8ai9)."""
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from archive_job_fixture import rebuild_model_spec, spicy_input
from congress_api.lake import readings
from congress_api.retention.provenance import file_pin, json_input, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import GENERIC_TITLES_SQL, build_release, registry_inputs

ROOT = Path(__file__).parents[3]


def _store_body(raw, content: bytes):
    digest = hashlib.sha256(content).hexdigest()
    stored = gzip.compress(content, mtime=0)
    dest = raw / 'bodies/sha256' / digest[:2] / f'{digest}.gz'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(stored)
    return digest, len(content), len(stored), hashlib.md5(stored).hexdigest()


def _fetch_row(url, retrieved_at, body_tuple, *, media_type, sniffed_format, family='documents', req_url=None):
    digest, raw_len, stored_len, md5_hex = body_tuple
    return dict(
        writer=dict(job='fixture', commit='a' * 40),
        run_id='fixture',
        mode='fetch',
        family=family,
        outcome='stored',
        requested_url=req_url or url,
        url=url,
        http_status=200,
        complete=True,
        retrieved_at=retrieved_at,
        captures=[dict(
            sha256=digest,
            bytes=raw_len,
            media_type=media_type,
            fidelity='exact-bytes',
            sniffed_format=sniffed_format,
            sniff_version=readings.current_version('sniff'),
            stored_suffix='.gz',
            stored_bytes=stored_len,
            stored_md5=md5_hex,
        )],
    )


def test_cat2_x47u_mods_facts_titles_headings_link_words_and_rcp_prints(tmp_path):
    """cat2-x47u (P0-1, F3, P2-9, F4):
    1. CHRG-* prints inherit MODS held_dates (document_date), committees (committee_keys), chambers
       (including jcse00 -> ['joint'] and CHRG-[hsj]hrg fallback), mods_title, canonical witness_keys,
       and single-day CHRG-* prints linked via meeting document_references link MODS witnesses to event_id.
    2. Accepted document_date derives congress when congress IS NULL (e.g. 2017-10-04 -> 115).
    3. GPO leading '- ' prefix is stripped in source_annotation_pages and titles.
    4. Clean <h1> ('page_heading') beats generic ('hearing | Hearings | ...') and '... |'-truncated <title>,
       and Senate ColdFusion 'Hearing status...: Hearing title...' SR-only labels are stripped.
    5. BILLS-*-RCP* Rules Committee Prints classify as committee-print / print and extract their title
       from <amendment-doc> XML text_head across both XML and PDF renditions.
    """
    raw = tmp_path / 'raw'
    raw.mkdir()

    # 1a. Single-day CHRG-116hhrg35382 linked to meeting 108999 via meeting document_references (no jacket, no <eventId>).
    pdf_single = _store_body(raw, b'%PDF-1.4\n% CHRG-116hhrg35382 single-day hearing PDF\n%%EOF\n')
    mods_single = _store_body(raw, b"""<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3">
  <titleInfo><title>VA ELECTRONIC HEALTH RECORD MODERNIZATION</title></titleInfo>
  <extension>
    <accessId>CHRG-116hhrg35382</accessId>
    <heldDate>2019-03-06</heldDate>
    <congCommittee authorityId="hsvr00" chamber="H" congress="116" type="S">
      <name type="authority-standard">Committee on Veterans' Affairs</name>
    </congCommittee>
    <witness>Stone, Richard, Executive in Charge, Veterans Health Administration</witness>
  </extension>
</mods>""")
    meeting_108999_xml = _store_body(raw, b"""<?xml version="1.0" encoding="UTF-8"?>
<committee-meeting congress-num="116" session-num="1" meeting-id="HHRG108999" meeting-type="HHRG">
  <meeting-details>
    <meeting-title>VA Electronic Health Record Modernization</meeting-title>
    <meeting-date><calendar-date>2019-03-06</calendar-date></meeting-date>
    <committees><committee-name id="VR00">Committee on Veterans' Affairs</committee-name></committees>
  </meeting-details>
  <meeting-documents>
    <meeting-document type="HT">
      <description>Printed Hearing</description>
      <files><file doc-url="https://www.govinfo.gov/content/pkg/CHRG-116hhrg35382/pdf/CHRG-116hhrg35382.pdf" doc-type="PDF"/></files>
    </meeting-document>
  </meeting-documents>
</committee-meeting>""")

    # 1b. Standalone Senate CHRG-110shrg44912 (PDF only, no meeting record) + Joint CHRG-118jhrg57466 (jcse00).
    pdf_senate = _store_body(raw, b'%PDF-1.4\n% CHRG-110shrg44912 Senate print\n%%EOF\n')
    mods_senate = _store_body(raw, b"""<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3">
  <titleInfo><title>CLEAN ENERGY DEPLOYMENT</title></titleInfo>
  <extension>
    <accessId>CHRG-110shrg44912</accessId>
    <heldDate>2008-07-15</heldDate>
    <congCommittee authorityId="sseg00" chamber="S" congress="110" type="S"/>
    <witness>Granholm, Jennifer, Governor of Michigan</witness>
  </extension>
</mods>""")
    pdf_joint = _store_body(raw, b'%PDF-1.4\n% CHRG-118jhrg57466 Helsinki Commission print\n%%EOF\n')
    mods_joint = _store_body(raw, b"""<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3">
  <titleInfo><title>1000 DAYS OF RUSSIA'S WAR ON UKRAINE</title></titleInfo>
  <extension>
    <accessId>CHRG-118jhrg57466</accessId>
    <heldDate>2024-11-19</heldDate>
    <congCommittee authorityId="jcse00" chamber="J" congress="118" type="S"/>
  </extension>
</mods>""")

    # 2 & 4a. Senate Aging HTML page: undated filename, content_date 2017-10-04 -> congress 115,
    # truncated <title> '... | Senate Committee On Aging' upgraded to full <h1>.
    aging_html = _store_body(raw, (
        '<html><head><title>Still Ringing Off The Hook: An Update on... | Senate Committee On Aging</title>'
        '<meta property="article:published_time" content="2017-10-04"/></head>'
        '<body><main><h1>Still Ringing Off The Hook: An Update on Efforts to Combat Robocalls</h1>'
        '<p>October 4, 2017</p><p>' + ('Robocall enforcement hearing record. ' * 45) + '</p></main></body></html>'
    ).encode())

    # 4b. Senate Banking HTML page: generic 'hearing | Hearings | ...' <title> + ColdFusion SR-only span in <h1>.
    banking_html = _store_body(raw, (
        '<html><head><title>hearing | Hearings | United States Committee on Banking, Housing, and Urban Affairs</title></head>'
        '<body><main><h1><span>Hearing status</span>Open: <span>Hearing title</span>Innovation in U.S. Housing: Solutions and Policies</h1>'
        '<p>Date: Wednesday, March 12, 2025</p><p>' + ('Housing innovation hearing details. ' * 45) + '</p></main></body></html>'
    ).encode())

    # 3. GPO CHRG HTML rendition with literal leading '- ' in <title>.
    pdf_gpo_dash = _store_body(raw, b'%PDF-1.4\n% CHRG-117shrg50111 PDF\n%%EOF\n')
    htm_gpo_dash = _store_body(raw, (
        '<html><head><title>\n - HEARING ON PENDING NOMINATIONS</title></head>'
        '<body><pre>' + ('[Senate Hearing 117-200] Substantive GPO hearing text. ' * 45) + '</pre></body></html>'
    ).encode())

    # 5. Rules Committee Print BILLS-115HR1009-RCP115-4 (.pdf + .xml <amendment-doc> on same stem).
    rcp_pdf = _store_body(raw, b'%PDF-1.4\n% BILLS-115HR1009-RCP115-4 PDF\n%%EOF\n')
    rcp_xml = _store_body(raw, b"""<?xml version="1.0" encoding="UTF-8"?>
<amendment-doc>
  <pre-form><meta-house><holc-filename>G:\\CMTE\\RU\\15\\RCP\\RCP_HR1009.XML</holc-filename></meta-house></pre-form>
  <form>
    <distribution-code>Rules Committee Print 115-4</distribution-code>
    <congress>Text of H.R. 1009, OIRA Insight, Reform, and Accountability Act</congress>
    <session>[Showing the text of H.R. 1009 as ordered reported by the Committee on Oversight and Government Reform]</session>
  </form>
  <legis-body><section><enum>1.</enum><header>Short title</header><text> Substantive legislative text repeated for readers. </text></section></legis-body>
</amendment-doc>""")

    receipt_rows = [
        _fetch_row('https://www.govinfo.gov/content/pkg/CHRG-116hhrg35382/pdf/CHRG-116hhrg35382.pdf', '2026-10-05T12:00:00Z', pdf_single, media_type='application/pdf', sniffed_format='pdf'),
        _fetch_row('https://www.govinfo.gov/metadata/pkg/CHRG-116hhrg35382/mods.xml', '2026-10-05T12:00:01Z', mods_single, media_type='application/xml', sniffed_format='xml'),
        _fetch_row('https://docs.house.gov/meetings/VR/VR00/20190306/108999/HHRG-116-VR00-20190306-SD001.xml', '2026-10-05T12:00:02Z', meeting_108999_xml, media_type='application/xml', sniffed_format='xml'),
        _fetch_row('https://www.govinfo.gov/content/pkg/CHRG-110shrg44912/pdf/CHRG-110shrg44912.pdf', '2026-10-05T12:01:00Z', pdf_senate, media_type='application/pdf', sniffed_format='pdf'),
        _fetch_row('https://www.govinfo.gov/metadata/pkg/CHRG-110shrg44912/mods.xml', '2026-10-05T12:01:01Z', mods_senate, media_type='application/xml', sniffed_format='xml'),
        _fetch_row('https://www.govinfo.gov/content/pkg/CHRG-118jhrg57466/pdf/CHRG-118jhrg57466.pdf', '2026-10-05T12:02:00Z', pdf_joint, media_type='application/pdf', sniffed_format='pdf'),
        _fetch_row('https://www.govinfo.gov/metadata/pkg/CHRG-118jhrg57466/mods.xml', '2026-10-05T12:02:01Z', mods_joint, media_type='application/xml', sniffed_format='xml'),
        _fetch_row('https://www.aging.senate.gov/hearings/still-ringing-off-the-hook-an-update-on-efforts-to-combat-robocalls', '2026-10-04T12:00:00Z', aging_html, media_type='text/html', sniffed_format='html'),
        _fetch_row('https://www.banking.senate.gov/hearings/03/12/2025/innovation-in-us-housing', '2026-10-04T12:05:00Z', banking_html, media_type='text/html', sniffed_format='html'),
        _fetch_row('https://www.govinfo.gov/content/pkg/CHRG-117shrg50111/pdf/CHRG-117shrg50111.pdf', '2026-10-05T12:06:00Z', pdf_gpo_dash, media_type='application/pdf', sniffed_format='pdf'),
        _fetch_row('https://www.govinfo.gov/content/pkg/CHRG-117shrg50111/html/CHRG-117shrg50111.htm', '2026-10-05T12:06:01Z', htm_gpo_dash, media_type='text/html', sniffed_format='html'),
        _fetch_row('https://docs.house.gov/billsthisweek/20170227/BILLS-115HR1009-RCP115-4.pdf', '2026-10-05T12:07:00Z', rcp_pdf, media_type='application/pdf', sniffed_format='pdf'),
        _fetch_row('https://docs.house.gov/billsthisweek/20170227/BILLS-115HR1009-RCP115-4.xml', '2026-10-05T12:07:01Z', rcp_xml, media_type='application/xml', sniffed_format='xml'),
    ]
    receipt = raw / 'receipts/documents/2026-10-05/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(gzip.compress((''.join(json.dumps(r) + '\n' for r in receipt_rows)).encode(), mtime=0))
    pin = tmp_path / 'receipt-pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), **file_pin(receipt), producer='fixture creation')))

    spec = rebuild_model_spec(tmp_path, raw=raw, receipts=[('receipts/documents/2026-10-05/slice.jsonl.gz', pin)], entities=True)
    spicy = spicy_input(spicy_committees=[
        dict(system_code='hsvr00', parent_system_code=None, name="Committee on Veterans' Affairs", chamber='House', committee_type='Standing', is_current=True, website_url='https://veterans.house.gov/', history=[]),
        dict(system_code='sseg00', parent_system_code=None, name='Committee on Energy and Natural Resources', chamber='Senate', committee_type='Standing', is_current=True, website_url='https://www.energy.senate.gov/', history=[]),
        dict(system_code='jcse00', parent_system_code=None, name='Commission on Security and Cooperation in Europe', chamber='Joint', committee_type='Commission', is_current=True, website_url='https://www.csce.gov/', history=[]),
        dict(system_code='spag00', parent_system_code=None, name='Special Committee on Aging', chamber='Senate', committee_type='Special', is_current=True, website_url='https://www.aging.senate.gov/', history=[]),
        dict(system_code='ssbk00', parent_system_code=None, name='Committee on Banking, Housing, and Urban Affairs', chamber='Senate', committee_type='Standing', is_current=True, website_url='https://www.banking.senate.gov/', history=[]),
    ])
    release = tmp_path / 'release'
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        build_release(
            captures=spec['captures']['path'],
            readings=spec['readings']['path'],
            filename_readings=spec['filename_readings']['path'],
            meeting_records=spec['meeting_records']['path'],
            appearance_records=spec['appearance_records']['path'],
            parser_versions=spec['parser_versions'],
            catalog_version=spec['catalog_version'],
            spicy_regs=spicy,
            include_entities=True,
            engine=engine,
            output=release,
            scratch=tmp_path / 'model',
        )

    details = {row['filename']: row for row in pq.read_table(release / 'detail.parquet').to_pylist()}
    witnesses = pq.read_table(release / 'witnesses.parquet').to_pylist()
    wit_by_name = {w['name']: w for w in witnesses}

    # 1a. Single-day CHRG-116hhrg35382 linked to 108999 + Stone MODS witness event_id=108999!
    d_single = details['CHRG-116hhrg35382.pdf']
    assert d_single['document_date'] == date(2019, 3, 6)
    assert d_single['committee_keys'] == ['hsvr00']
    assert d_single['chambers'] == ['house']
    assert d_single['congress'] == 116
    assert d_single['title'] == 'VA ELECTRONIC HEALTH RECORD MODERNIZATION'
    assert d_single['title_source'] == 'mods_title'
    stone = next(w for name, w in wit_by_name.items() if 'Stone' in name)
    assert stone['event_id'] == 108999
    assert stone['occasion'] == 'meeting:108999'
    assert d_single['witness_keys'] == [stone['witness_key']]

    # 1b. Standalone Senate CHRG-110shrg44912 & Joint jcse00 CHRG-118jhrg57466.
    d_sen = details['CHRG-110shrg44912.pdf']
    assert d_sen['document_date'] == date(2008, 7, 15)
    assert d_sen['document_date_source'] == 'content'
    assert d_sen['committee_keys'] == ['sseg00']
    assert d_sen['chambers'] == ['senate']
    assert d_sen['congress'] == 110
    assert d_sen['title'] == 'CLEAN ENERGY DEPLOYMENT'
    assert d_sen['title_source'] == 'mods_title'
    granholm = next(w for name, w in wit_by_name.items() if 'Granholm' in name)
    assert d_sen['witness_keys'] == [granholm['witness_key']]

    d_joint = details['CHRG-118jhrg57466.pdf']
    assert d_joint['document_date'] == date(2024, 11, 19)
    assert d_joint['committee_keys'] == ['jcse00']
    assert d_joint['chambers'] == ['joint']
    assert d_joint['congress'] == 118

    # 2 & 4a. Aging page: congress=115 from 2017-10-04 + full <h1> beats truncated <title>.
    d_aging = details['still-ringing-off-the-hook-an-update-on-efforts-to-combat-robocalls']
    assert d_aging['document_date'] == date(2017, 10, 4)
    assert d_aging['congress'] == 115
    assert d_aging['title'] == 'Still Ringing Off The Hook: An Update on Efforts to Combat Robocalls'
    assert d_aging['title_source'] == 'page_heading'

    # 4b. Banking page: <h1> (stripped of ColdFusion SR-only prefix) beats generic 'hearing | Hearings | ...' <title>.
    d_bank = details['innovation-in-us-housing']
    assert d_bank['title'] == 'Open: Innovation in U.S. Housing: Solutions and Policies'
    assert d_bank['title_source'] == 'page_heading'

    # 3. GPO leading '- ' stripped!
    d_dash = details['CHRG-117shrg50111.htm']
    assert d_dash['title'] == 'HEARING ON PENDING NOMINATIONS'
    assert d_dash['title_source'] == 'page_title'

    # 5. BILLS-115HR1009-RCP115-4.pdf classified as committee-print / print and titled from XML <amendment-doc>.
    d_rcp = details['BILLS-115HR1009-RCP115-4.pdf']
    assert d_rcp['document_kind'] == ['committee-print']
    assert d_rcp['document_family'] == ['print']
    assert d_rcp['title'] == 'Rules Committee Print 115-4 Text of H.R. 1009, OIRA Insight, Reform, and Accountability Act'
    assert d_rcp['title_source'] == 'other_format_page_title'


def test_cat2_x47u_hearing_stopword_and_split_underscore_anchors_are_link_words(tmp_path):
    """P2-9: bare 'hearing' and Senate Commerce split-anchor fragments ('_16 (as modified', '_2 (as modified),')
    are rejected as link words so descriptive link text wins."""
    links = [
        (' fiscal ', 'hearing'),
        (' fiscal ', 'Fiscal Toolkit Post-hearing report'),
        (' amdt16 ', '_16 (as modified'),
        (' amdt16 ', 'Cantwell Amendment 16 (as modified)'),
        (' amdt2 ', '_2 (as modified),'),
        (' real ', 'Hearing on Rural Lands'),
    ]
    rows = [dict(source_id=s.strip(), text=t, doc_type=None, first_good_at=f'2026-10-{i + 1:02d}T12:00:00Z',
                 context='c', page_body='p', link_index=i, split_position=0) for i, (s, t) in enumerate(links)]
    sources = sorted({s.strip() for s, _ in links})
    inputs = [i for i in registry_inputs(tmp_path / 'registries') if i['name'] in ('title_rules', 'publisher_kinds')] + [
        json_input(tmp_path, 'links', rows, source_id='Utf8', text='Utf8', doc_type='Utf8', first_good_at='Utf8',
                   context='Utf8', page_body='Utf8', link_index='Int64', split_position='Int64'),
        json_input(tmp_path, 'source_files', [dict(source_id=s) for s in sources], source_id='Utf8'),
        json_input(tmp_path, 'ordered', [dict(doc_key=str(i), title=t) for i, (_, t) in enumerate(links)], doc_key='Utf8', title='Utf8'),
    ]
    steps = [dict(name='publisher_links', sql="SELECT * EXCLUDE(first_good_at),cast(first_good_at AS TIMESTAMP WITH TIME ZONE) AS first_good_at FROM links")]
    res = run_job(tmp_path / 'job', NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps, outputs=[],
                  queries=[dict(name='listing', sql='SELECT source_id,listing_title FROM (' + (ROOT / 'model/sql/source-annotations-publisher.sql').read_text() + ') a ORDER BY 1'),
                           dict(name='generic', sql=f'SELECT DISTINCT title FROM ({GENERIC_TITLES_SQL}) g ORDER BY title')])
    assert {r['source_id']: r['listing_title'] for r in res['listing']} == {
        'amdt16': 'Cantwell Amendment 16 (as modified)',
        'amdt2': None,
        'fiscal': 'Fiscal Toolkit Post-hearing report',
        'real': 'Hearing on Rural Lands',
    }
    assert [r['title'] for r in res['generic']] == ['_16 (as modified', '_2 (as modified),', 'hearing']
