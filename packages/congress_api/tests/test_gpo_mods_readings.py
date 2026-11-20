"""Unit and staging tests for the derived GovInfo MODS citation reader (ct-n131)."""
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from congress_api.lake import readings
from congress_api.lake.capture_staging import stage_captures
from congress_api.parsers.gpo_mods import reading_row
from docspec_client.client import NativeDatasets

FIXTURES = Path(__file__).parent / 'fixtures/gpo_metadata'


def test_gpo_mods_reading_row_extracts_package_and_granule_citations():
    single = reading_row((FIXTURES / 'CHRG-116shrg42251.xml').read_bytes())
    assert single['status'] == 'completed'
    assert dict((f['field'], f['value']) for f in single['fields']) == {
        'package_id': 'CHRG-116shrg42251',
        'preferred_citation': 'S. Hrg. 116-439',
    }

    multipart = reading_row((FIXTURES / 'CHRG-115hhrg24725.xml').read_bytes())
    assert multipart['status'] == 'completed'
    assert dict((f['field'], f['value']) for f in multipart['fields']) == {
        'package_id': 'CHRG-115hhrg24725',
        'preferred_citation': 'Serial No. 115-3',
        'granule:CHRG-115hhrg24725-pt1': 'Serial No. 115-3, Part 1',
        'granule:CHRG-115hhrg24725-pt2': 'Serial No. 115-3, Part 2',
    }

    refused = reading_row(b'<bill><title>Not a MODS document</title></bill>')
    assert refused['status'] == 'error'
    assert refused['error_type'] == 'unsupported_gpo_mods'


def test_gpo_mods_stage_scopes_only_govinfo_mods_captures(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw = tmp_path / 'raw'
    mods_bytes = (FIXTURES / 'CHRG-116shrg42251.xml').read_bytes()
    other_xml = b'<?xml version="1.0"?><committee-meeting><title>Unrelated</title></committee-meeting>'

    def put_body(data: bytes):
        sha = hashlib.sha256(data).hexdigest()
        gz = gzip.compress(data, mtime=0)
        dest = raw / f'bodies/sha256/{sha[:2]}/{sha}.gz'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(gz)
        return sha, len(data), len(gz), hashlib.md5(gz).hexdigest()

    mods_sha, mods_len, mods_gz_len, mods_md5 = put_body(mods_bytes)
    xml_sha, xml_len, xml_gz_len, xml_md5 = put_body(other_xml)

    def make_receipt(family_key: str, url: str, sha: str, size: int, gz_size: int, md5: str):
        rpath = raw / family_key
        rpath.parent.mkdir(parents=True, exist_ok=True)
        line = dict(
            url=url,
            requested_url=url,
            retrieved_at='2026-11-20T00:00:00Z',
            http_status=200,
            complete=True,
            captures=[dict(
                outcome='stored',
                sha256=sha,
                bytes=size,
                media_type='application/xml',
                sniffed_format='xml',
                sniff_version=readings.current_version('sniff'),
                intact=True,
                stored_suffix='.gz',
                stored_bytes=gz_size,
                stored_md5=md5,
            )],
        )
        encoded = gzip.compress((json.dumps(line) + '\n').encode(), mtime=0)
        rpath.write_bytes(encoded)
        pin = tmp_path / (Path(family_key).name + '.pin.json')
        pin.write_text(json.dumps(dict(
            path=str(rpath),
            size=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
            producer='test',
        )))
        return dict(key=family_key, path=str(rpath), qualification=str(pin))

    receipts = [
        make_receipt('receipts/govinfo/mods/2026-11-20/mods.jsonl.gz',
                     'https://www.govinfo.gov/metadata/pkg/CHRG-116shrg42251/mods.xml',
                     mods_sha, mods_len, mods_gz_len, mods_md5),
        make_receipt('receipts/house/meeting-xml/2026-11-20/meeting.jsonl.gz',
                     'https://docs.house.gov/meetings/AG/AG00/20260101/119001/HHRG-119-AG00-20260101-119001.xml',
                     xml_sha, xml_len, xml_gz_len, xml_md5),
    ]
    captures = stage_captures(receipts, engine=engine, work=tmp_path / 'captures') / 'captures.parquet'
    staged = readings.stage(
        captures=captures,
        body_inventory=None,
        captured_copies=True,
        local_root=raw,
        engine=engine,
        work=tmp_path / 'stage-mods',
        decided_at='2026-11-20T00:00:00Z',
        parser='gpo_mods',
        parser_workers=1,
    )
    rows = pq.read_table(staged['readings']).to_pylist()
    assert len(rows) == 1
    assert rows[0]['body_sha'].hex() == mods_sha
    assert rows[0]['parser'] == 'gpo_mods'
    assert rows[0]['status'] == 'completed'
    assert dict((f['field'], f['value']) for f in rows[0]['fields']) == {
        'package_id': 'CHRG-116shrg42251',
        'preferred_citation': 'S. Hrg. 116-439',
    }
