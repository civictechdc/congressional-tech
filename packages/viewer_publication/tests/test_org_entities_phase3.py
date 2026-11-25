"""Phase 3 organization entity Wikidata reconciliation tests (ct-39u8)."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake.model_sql import sql_dependencies
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import build_org_entities, build_release

from archive_job_fixture import spicy_input
from test_witness_identity import _cg_json, _pdf_bytes, _stage_raw

ROOT = Path(__file__).resolve().parents[3]


def _org_sha16(prefix: str, value: str) -> str:
    return hashlib.sha256((prefix + value).encode('utf-8')).hexdigest()[:16]


def _bag_sha16(tokens: list[str]) -> str:
    return hashlib.sha256(('|'.join(sorted(tokens))).encode('utf-8')).hexdigest()[:16]


def _write_resolved_appearances(path: Path, rows: list[dict]) -> Path:
    schema = pa.schema([
        ('witness_key', pa.string()),
        ('organization', pa.string()),
        ('on_behalf_of', pa.string()),
    ])
    table = pa.table(
        {
            'witness_key': [r['witness_key'] for r in rows],
            'organization': [r.get('organization') for r in rows],
            'on_behalf_of': [r.get('on_behalf_of') for r in rows],
        },
        schema=schema,
    )
    pq.write_table(table, path)
    return path


def _write_reconcile_tables(
    work: Path,
    *,
    captures_rows: list[dict],
    readings_rows: list[dict],
) -> tuple[Path, Path]:
    cap_schema = pa.schema([
        ('family', pa.string()),
        ('mode', pa.string()),
        ('outcome', pa.string()),
        ('sha256', pa.binary(32)),
        ('receipt_key', pa.string()),
        ('retrieved_at', pa.timestamp('us', tz='UTC')),
        ('requested_url', pa.string()),
    ])
    cap_table = pa.table(
        {
            'family': [r['family'] for r in captures_rows],
            'mode': [r['mode'] for r in captures_rows],
            'outcome': [r['outcome'] for r in captures_rows],
            'sha256': [r['sha256'] for r in captures_rows],
            'receipt_key': [r['receipt_key'] for r in captures_rows],
            'retrieved_at': [r['retrieved_at'] for r in captures_rows],
            'requested_url': [r['requested_url'] for r in captures_rows],
        },
        schema=cap_schema,
    )
    cap_path = work / 'captures.parquet'
    pq.write_table(cap_table, cap_path)

    read_schema = pa.schema([
        ('body_sha', pa.binary(32)),
        ('parser', pa.string()),
        ('status', pa.string()),
        ('fields', pa.list_(pa.struct([
            pa.field('field', pa.string(), nullable=False),
            pa.field('value', pa.string(), nullable=False),
        ]))),
    ])
    read_table = pa.table(
        {
            'body_sha': [r['body_sha'] for r in readings_rows],
            'parser': [r['parser'] for r in readings_rows],
            'status': [r['status'] for r in readings_rows],
            'fields': [r['fields'] for r in readings_rows],
        },
        schema=read_schema,
    )
    read_path = work / 'selected_readings.parquet'
    pq.write_table(read_table, read_path)
    return cap_path, read_path


def _wd_cand(qid: str, name: str, score: float, desc: str = 'organization', match: bool = False, types: tuple[str, ...] = ('Q43229',)) -> str:
    return json.dumps(
        dict(id=qid, name=name, description=desc, score=score, match=match, types=list(types)),
        ensure_ascii=False,
        separators=(',', ':'),
    )


def test_wikidata_sql_dependencies():
    assert sql_dependencies((ROOT / 'model/sql/wikidata-reconcile-bodies.sql').read_text()) == {
        'captures', 'selected_readings',
    }
    assert sql_dependencies((ROOT / 'model/sql/org-reconcile-requests.sql').read_text()) == {
        'captures', 'org_bag_registry_matches', 'org_bags', 'wikidata_reconcile_bodies',
    }
    assert sql_dependencies((ROOT / 'model/sql/org-wikidata-links.sql').read_text()) == {
        'org_bags', 'org_decisions_current', 'wikidata_reconcile_bodies',
    }


def test_incremental_reconcile_request_batching(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    # Create 15 distinct bags with distinct appearance counts.
    appearances = []
    idx = 0
    # 12 bags needing reconciliation + 1 registry-linked + 1 URL-receipted empty + 1 body-receipted
    org_specs = [
        ('Public Policy, Nature Conservancy', 5),
        ('Acme Renewable Energy', 4),
        ('National Wildlife Federation', 3),
        ('Environmental Protection Agency', 3),
        ('Already Empty Receipt Co', 2),
        ('Already Body Receipt Co', 2),
    ] + [(f'Test Org {i:02d}', 1) for i in range(9)]

    for name, count in org_specs:
        for _ in range(count):
            idx += 1
            appearances.append(dict(witness_key=f'{idx:016d}', organization=name, on_behalf_of=None))

    app_path = _write_resolved_appearances(tmp_path / 'appearances.parquet', appearances)

    # First run without captures/registry to learn exact bag_keys.
    probe = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'probe-out',
        scratch=tmp_path / 'probe-scratch',
    )
    bags_by_raw = {
        raw: r['bag_key']
        for r in pq.read_table(probe['outputs']['org_strings.parquet']).to_pylist()
        for raw in r['raw_texts']
    }
    b_reg = bags_by_raw['Environmental Protection Agency']
    b_empty_url = bags_by_raw['Already Empty Receipt Co']
    b_body = bags_by_raw['Already Body Receipt Co']

    sha_empty = hashlib.sha256(b'empty').digest()
    sha_body = hashlib.sha256(b'body').digest()
    from datetime import datetime, timezone
    ts = datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc)
    empty_url = (
        'https://wikidata-reconciliation.wmcloud.org/en/api?queries='
        f'%7B%22{b_empty_url}%22%3A%7B%22limit%22%3A5%2C%22query%22%3A%22already%20empty%20receipt%22%7D%7D'
    )
    cap_path, read_path = _write_reconcile_tables(
        tmp_path,
        captures_rows=[
            dict(
                family='wikidata/reconcile',
                mode='fetch',
                outcome='stored',
                sha256=sha_empty,
                receipt_key='receipts/wikidata/reconcile/2026-11-25/r1.jsonl.gz',
                retrieved_at=ts,
                requested_url=empty_url,
            ),
            dict(
                family='wikidata/reconcile',
                mode='fetch',
                outcome='stored',
                sha256=sha_body,
                receipt_key='receipts/wikidata/reconcile/2026-11-25/r2.jsonl.gz',
                retrieved_at=ts,
                requested_url='https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%7D',
            ),
        ],
        readings_rows=[
            dict(
                body_sha=sha_empty,
                parser='wikidata_reconcile',
                status='completed',
                fields=[dict(field=f'query:{b_empty_url}', value='[]')],
            ),
            dict(
                body_sha=sha_body,
                parser='wikidata_reconcile',
                status='completed',
                fields=[dict(
                    field=f'query:{b_body}',
                    value=json.dumps([json.loads(_wd_cand('Q999', 'Already Body Receipt Co', 95.0))]),
                )],
            ),
        ],
    )

    res = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'out',
        scratch=tmp_path / 'scratch',
        captures=cap_path,
        selected_readings=read_path,
        refspec=ROOT / 'model/jobs/refspec/refspec.json',
    )
    batches = pq.read_table(res['outputs']['org_reconcile_requests.parquet']).to_pylist()
    assert len(batches) == 2
    assert [b['batch_size'] for b in batches] == [10, 2]
    assert res['wikidata_stats']['reconcile_requested_bags'] == 12

    requested_bags = set()
    parsed_queries = {}
    for b in batches:
        assert b['request_url'].startswith('https://wikidata-reconciliation.wmcloud.org/en/api?queries=')
        assert '#' not in b['request_url']
        qs = parse_qs(urlparse(b['request_url']).query, strict_parsing=True)
        payload = json.loads(qs['queries'][0])
        assert list(payload.keys()) == sorted(payload.keys())
        for bk, qobj in payload.items():
            assert qobj['limit'] == 5
            requested_bags.add(bk)
            parsed_queries[bk] = qobj['query']

    assert b_reg not in requested_bags
    assert b_empty_url not in requested_bags
    assert b_body not in requested_bags
    assert parsed_queries[bags_by_raw['Public Policy, Nature Conservancy']] == 'nature conservancy'
    assert parsed_queries[bags_by_raw['Acme Renewable Energy']] == 'acme renewable energy'


def test_wikidata_acceptance_review_queue_precedence_and_different_override(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    rows = [
        # Bag A & Bag B: two bags auto-accepting Q100 -> merge when include_wikidata_links=True
        dict(witness_key='1000000000000001', organization='National Wildlife Federation', on_behalf_of=None),
        dict(witness_key='1000000000000002', organization='National Wildlife Federation', on_behalf_of=None),
        dict(witness_key='1000000000000003', organization='Natl Wildlife Federation', on_behalf_of=None),
        # Bag C: top tie >= 90 -> MUST go to org_review_queue, NOT auto-accept (5 appearances)
        *[dict(witness_key=f'200000000000000{i}', organization='Mercury Policy Project', on_behalf_of=None) for i in range(5)],
        # Bag D: score 80..89 -> MUST go to org_review_queue, NOT auto-accept (2 appearances)
        dict(witness_key='3000000000000001', organization='Clear Air Institute', on_behalf_of=None),
        dict(witness_key='3000000000000002', organization='Clear Air Institute', on_behalf_of=None),
        # Bag E: score < 80 -> below threshold
        dict(witness_key='4000000000000001', organization='Tiny Local Club', on_behalf_of=None),
        # Bag F: fr_agency + wikidata + decision -> fr_agency:<id> wins tier 1
        dict(witness_key='5000000000000001', organization='Environmental Protection Agency', on_behalf_of=None),
        # Bag G: manual decision only -> decision:<id> tier 3
        dict(witness_key='6000000000000001', organization='Decision Only Org', on_behalf_of=None),
    ]
    app_path = _write_resolved_appearances(tmp_path / 'appearances.parquet', rows)
    probe = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'probe-out',
        scratch=tmp_path / 'probe-scratch',
    )
    bags = {
        raw: r['bag_key']
        for r in pq.read_table(probe['outputs']['org_strings.parquet']).to_pylist()
        for raw in r['raw_texts']
    }
    b_a = bags['National Wildlife Federation']
    b_b = bags['Natl Wildlife Federation']
    b_c = bags['Mercury Policy Project']
    b_d = bags['Clear Air Institute']
    b_e = bags['Tiny Local Club']
    b_f = bags['Environmental Protection Agency']
    b_g = bags['Decision Only Org']

    body_sha_bytes = hashlib.sha256(b'wd-response-1').digest()
    body_sha_hex = body_sha_bytes.hex()
    from datetime import datetime, timezone
    ts = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)
    cap_path, read_path = _write_reconcile_tables(
        tmp_path,
        captures_rows=[dict(
            family='wikidata/reconcile',
            mode='fetch',
            outcome='stored',
            sha256=body_sha_bytes,
            receipt_key='receipts/wikidata/reconcile/2026-11-25/batch0.jsonl.gz',
            retrieved_at=ts,
            requested_url='https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%7D',
        )],
        readings_rows=[dict(
            body_sha=body_sha_bytes,
            parser='wikidata_reconcile',
            status='completed',
            fields=[
                dict(field=f'query:{b_a}', value='[' + ','.join([
                    _wd_cand('Q100', 'National Wildlife Federation', 96.0, 'US conservation organization', True),
                    _wd_cand('Q101', 'Wildlife Federation (Other)', 83.0, 'disambiguation'),
                ]) + ']'),
                dict(field=f'query:{b_b}', value='[' + _wd_cand('Q100', 'National Wildlife Federation', 92.0, 'US conservation organization', True) + ']'),
                dict(field=f'query:{b_c}', value='[' + ','.join([
                    _wd_cand('Q301', 'Mercury Policy Project (US)', 95.0, 'US NGO'),
                    _wd_cand('Q302', 'Mercury Policy Project (CA)', 95.0, 'Canadian NGO'),
                ]) + ']'),
                dict(field=f'query:{b_d}', value='[' + _wd_cand('Q401', 'Clean Air Institute', 85.0, 'nonprofit') + ']'),
                dict(field=f'query:{b_e}', value='[' + _wd_cand('Q501', 'Tiny Club', 72.0, 'club') + ']'),
                dict(field=f'query:{b_f}', value='[' + _wd_cand('Q460173', 'United States Environmental Protection Agency', 99.0, 'US agency', True) + ']'),
            ],
        )],
    )

    decisions_file = tmp_path / 'decisions.jsonl'
    decisions_file.write_text(''.join(json.dumps(d, separators=(',', ':')) + '\n' for d in [
        dict(id='dec_f_same', subject=f'bag:{b_f}', verdict='same', object=f'bag:{b_f}', note='keep anchor', reviewer='t', decided_at='2026-11-25T00:00:00Z', supersedes=None),
        dict(id='dec_g_same', subject=f'bag:{b_g}', verdict='same', object=f'bag:{b_g}', note='decision anchor', reviewer='t', decided_at='2026-11-25T00:00:00Z', supersedes=None),
    ]))
    refspec_manifest = ROOT / 'model/jobs/refspec/refspec.json'

    # 1. Default include_wikidata_links=False: links classified for audit, NOT published yet.
    res_off = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'out-off',
        scratch=tmp_path / 'scratch-off',
        org_decision_files=[decisions_file],
        captures=cap_path,
        selected_readings=read_path,
        refspec=refspec_manifest,
        include_wikidata_links=False,
    )
    w_off = {(r['witness_key'], r['field']): r for r in pq.read_table(res_off['outputs']['witness_organizations.parquet']).to_pylist()}
    assert w_off[('1000000000000001', 'organization')]['org_id'] != w_off[('1000000000000003', 'organization')]['org_id']
    assert res_off['wikidata_stats']['wikidata_auto_accept_rows'] == 3
    assert res_off['wikidata_stats']['wikidata_published_orgs'] == 0

    # 2. include_wikidata_links=True: unique >= 90 merges & publishes; ties & 80..89 stay in review queue ordered by appearance_count.
    res_on = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'out-on',
        scratch=tmp_path / 'scratch-on',
        org_decision_files=[decisions_file],
        captures=cap_path,
        selected_readings=read_path,
        refspec=refspec_manifest,
        include_wikidata_links=True,
    )
    orgs = {r['org_id']: r for r in pq.read_table(res_on['outputs']['organizations.parquet']).to_pylist()}
    w_on = {(r['witness_key'], r['field']): r for r in pq.read_table(res_on['outputs']['witness_organizations.parquet']).to_pylist()}
    org_ids = pq.read_table(res_on['outputs']['organization_ids.parquet']).to_pylist()
    queue = [r for r in pq.read_table(res_on['outputs']['org_review_queue.parquet']).to_pylist() if r['queue_kind'] == 'wikidata_review']

    expected_nwf = _org_sha16('org-v1', 'wikidata:Q100')
    assert w_on[('1000000000000001', 'organization')]['org_id'] == expected_nwf
    assert w_on[('1000000000000001', 'organization')]['method'] == 'wikidata_auto'
    assert w_on[('1000000000000001', 'organization')]['score'] == 96.0
    assert w_on[('1000000000000001', 'organization')]['evidence'] == body_sha_hex
    assert w_on[('1000000000000003', 'organization')]['org_id'] == expected_nwf
    assert w_on[('1000000000000003', 'organization')]['method'] == 'wikidata_auto'
    assert w_on[('1000000000000003', 'organization')]['score'] == 92.0
    assert w_on[('1000000000000003', 'organization')]['evidence'] == body_sha_hex
    assert w_on[('5000000000000001', 'organization')]['method'] == 'registry'
    assert w_on[('6000000000000001', 'organization')]['method'] == 'decision'
    assert w_on[('4000000000000001', 'organization')]['method'] == 'token_bag'
    assert orgs[expected_nwf]['anchor'] == 'wikidata:Q100'
    assert orgs[expected_nwf]['display_name'] == 'National Wildlife Federation'
    wd_id_rows = [r for r in org_ids if r['org_id'] == expected_nwf and r['scheme'] == 'wikidata']
    assert [(r['value'], r['evidence']) for r in wd_id_rows] == [('Q100', body_sha_hex)]

    # Tier precedence check: fr_agency:<id> (tier 1) > wikidata:<Q> (tier 2) > decision:<id> (tier 3) > bag:<bag_key> (tier 4)
    assert orgs[w_on[('5000000000000001', 'organization')]['org_id']]['anchor'] == 'fr_agency:145'
    assert orgs[w_on[('6000000000000001', 'organization')]['org_id']]['anchor'] == 'decision:dec_g_same'
    assert orgs[w_on[('4000000000000001', 'organization')]['org_id']]['anchor'] == f'bag:{b_e}'

    # Review queue: Q301 & Q302 (bag C top tie, app=5), Q101 (bag A runner-up, app=2), Q401 (bag D 85.0, app=2).
    # Ordered by combined_appearances DESC, bag_key_a ASC, bag_key_b ASC!
    expected_queue = sorted(
        [(b_c, 'Q301', 5), (b_c, 'Q302', 5), (b_a, 'Q101', 2), (b_d, 'Q401', 2)],
        key=lambda item: (-item[2], item[0], item[1]),
    )
    assert [(r['bag_key_a'], r['wikidata_qid'], r['combined_appearances']) for r in queue] == expected_queue
    assert not any(r['scheme'] == 'wikidata' and r['value'] in ('Q301', 'Q302', 'Q401', 'Q501', 'Q101') for r in org_ids)

    # 3. AC #5: 'different' decision on (bag, Q) blocks the link on rebuild!
    decisions_diff = tmp_path / 'decisions-diff.jsonl'
    decisions_diff.write_text(decisions_file.read_text() + json.dumps(
        dict(
            id='dec_diff_ba_q100',
            subject=f'bag:{b_a}',
            verdict='different',
            object='wikidata:Q100',
            note='False positive on bag A',
            reviewer='t',
            decided_at='2026-11-25T02:00:00Z',
            supersedes=None,
        ),
        separators=(',', ':'),
    ) + '\n')

    res_diff = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'out-diff',
        scratch=tmp_path / 'scratch-diff',
        org_decision_files=[decisions_diff],
        captures=cap_path,
        selected_readings=read_path,
        refspec=refspec_manifest,
        include_wikidata_links=True,
    )
    w_diff = {(r['witness_key'], r['field']): r for r in pq.read_table(res_diff['outputs']['witness_organizations.parquet']).to_pylist()}
    org_ids_diff = pq.read_table(res_diff['outputs']['organization_ids.parquet']).to_pylist()
    links_diff = {(r['bag_key'], r['qid']): r['link_status'] for r in pq.read_table(res_diff['outputs']['org_wikidata_links.parquet']).to_pylist()}
    assert links_diff[(b_a, 'Q100')] == 'blocked_different'
    assert links_diff[(b_b, 'Q100')] == 'auto_accept'
    assert w_diff[('1000000000000001', 'organization')]['org_id'] == _org_sha16('org-v1', f'bag:{b_a}')
    assert w_diff[('1000000000000003', 'organization')]['org_id'] == expected_nwf
    assert not any(
        r['org_id'] == _org_sha16('org-v1', f'bag:{b_a}') and r['scheme'] == 'wikidata' and r['value'] == 'Q100'
        for r in org_ids_diff
    )


def test_wikidata_coexisting_decision_precedence_decided_status_and_url_encoding(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    rows = [
        dict(witness_key='9000000000000001', organization='AT&T 100% #1 Café', on_behalf_of=None),
        dict(witness_key='9000000000000002', organization='Midscore Same Org', on_behalf_of=None),
        dict(witness_key='9000000000000003', organization='Midscore Unsure Org', on_behalf_of=None),
    ]
    app_path = _write_resolved_appearances(tmp_path / 'appearances.parquet', rows)
    probe = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'probe-out',
        scratch=tmp_path / 'probe-scratch',
    )
    bags = {
        raw: r['bag_key']
        for r in pq.read_table(probe['outputs']['org_strings.parquet']).to_pylist()
        for raw in r['raw_texts']
    }
    b_amp = bags['AT&T 100% #1 Café']
    b_same = bags['Midscore Same Org']
    b_unsure = bags['Midscore Unsure Org']

    # Choose a SHA-256 byte string sorting strictly BEFORE 'decision:' in UTF-8 ('00...' < 'decision:')
    # to prove priority ordering beats raw SHA lexicographic sorting.
    early_sha_bytes = bytes.fromhex('00' * 32)
    early_sha_hex = early_sha_bytes.hex()
    from datetime import datetime, timezone
    ts = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)
    cap_path, read_path = _write_reconcile_tables(
        tmp_path,
        captures_rows=[dict(
            family='wikidata/reconcile',
            mode='fetch',
            outcome='stored',
            sha256=early_sha_bytes,
            receipt_key='receipts/wikidata/reconcile/2026-11-25/batch0.jsonl.gz',
            retrieved_at=ts,
            requested_url='https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%7D',
        )],
        readings_rows=[dict(
            body_sha=early_sha_bytes,
            parser='wikidata_reconcile',
            status='completed',
            fields=[
                dict(field=f'query:{b_amp}', value='[' + _wd_cand('Q700', 'AT&T', 97.0, 'telecom', True) + ']'),
                dict(field=f'query:{b_same}', value='[' + _wd_cand('Q701', 'Midscore Same Org', 85.0) + ']'),
                dict(field=f'query:{b_unsure}', value='[' + _wd_cand('Q702', 'Midscore Unsure Org', 85.0) + ']'),
            ],
        )],
    )
    decisions_file = tmp_path / 'decisions.jsonl'
    decisions_file.write_text(''.join(json.dumps(d, separators=(',', ':')) + '\n' for d in [
        dict(id='dec_amp_same', subject=f'bag:{b_amp}', verdict='same', object='wikidata:Q700', note='confirmed', reviewer='t', decided_at='2026-11-25T02:00:00Z', supersedes=None),
        dict(id='dec_mid_same', subject=f'bag:{b_same}', verdict='same', object='wikidata:Q701', note='manual accept', reviewer='t', decided_at='2026-11-25T02:00:00Z', supersedes=None),
        dict(id='dec_mid_unsure', subject=f'bag:{b_unsure}', verdict='unsure', object='wikidata:Q702', note='needs review', reviewer='t', decided_at='2026-11-25T02:00:00Z', supersedes=None),
    ]))

    res = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'out',
        scratch=tmp_path / 'scratch',
        org_decision_files=[decisions_file],
        captures=cap_path,
        selected_readings=read_path,
        include_wikidata_links=True,
    )
    links = {(r['bag_key'], r['qid']): r['link_status'] for r in pq.read_table(res['outputs']['org_wikidata_links.parquet']).to_pylist()}
    assert links[(b_same, 'Q701')] == 'decided'
    assert links[(b_unsure, 'Q702')] == 'decided'

    w_rows = {(r['witness_key'], r['field']): r for r in pq.read_table(res['outputs']['witness_organizations.parquet']).to_pylist()}
    amp_row = w_rows[('9000000000000001', 'organization')]
    assert amp_row['org_id'] == _org_sha16('org-v1', 'wikidata:Q700')
    assert amp_row['method'] == 'decision'
    assert amp_row['score'] == 1.0
    assert amp_row['evidence'] == 'decision:dec_amp_same'

    org_ids = pq.read_table(res['outputs']['organization_ids.parquet']).to_pylist()
    amp_wd_ids = [r for r in org_ids if r['org_id'] == _org_sha16('org-v1', 'wikidata:Q700') and r['scheme'] == 'wikidata']
    assert [(r['value'], r['evidence']) for r in amp_wd_ids] == [('Q700', 'decision:dec_amp_same')]
    assert early_sha_hex < 'decision:dec_amp_same'

    # Also verify URL encoding round-trip with &, %, #, UTF-8 when uncaptured:
    res_urls = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'out-urls',
        scratch=tmp_path / 'scratch-urls',
        include_wikidata_links=False,
    )
    batches = pq.read_table(res_urls['outputs']['org_reconcile_requests.parquet']).to_pylist()
    assert len(batches) == 1
    assert '#' not in batches[0]['request_url']
    qs = parse_qs(urlparse(batches[0]['request_url']).query, strict_parsing=True)
    payload = json.loads(qs['queries'][0])
    assert payload[b_amp]['query'] == 'at and t 100 1 cafe'
    assert payload[b_same]['query'] == 'midscore same org'


def test_full_build_release_includes_phase3_org_tables(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    cg = _cg_json(117001, '2026-10-20T00:00:00Z', 'h117001')
    pdf = _pdf_bytes('Phase 3 test transcript')
    pkg_url = 'https://docs.house.gov/meetings/IF/IF00/20240501/117001/HHRG-118-IF00-Wstate-DoeJ-20240501.pdf'
    staged = _stage_raw(
        tmp_path / 'stage',
        engine,
        [
            dict(url='https://api.congress.gov/v3/committee-meeting/118/house/117001?format=json', data=cg, format='json', family='congress/meetings'),
            dict(url=pkg_url, data=pdf, format='pdf', suffix='.pdf'),
        ],
    )
    meeting = dict(
        event_id='117001', chamber='house', congress=118, session=2,
        updated='2026-10-20T00:00:00Z', title='Phase 3 Hearing',
        meeting_date='2024-05-01', meeting_type='HHRG', status='Scheduled',
        sittings=[], committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
        subject_keys=[], transcript_jackets=[], videos=[], document_urls=[], document_references=[],
        collection_states=dict(sittings='present', committees='present', subject_keys='empty',
                               transcript_jackets='empty', videos='empty', document_urls='empty'),
        access='open', access_basis='default', not_held=False, title_key='phase 3 hearing', reschedule_candidate=False,
    )
    appearance = dict(
        record_sha=hashlib.sha256(cg).hexdigest(),
        source='congress_gov',
        event_id=117001,
        collection_state='present',
        appearances=[dict(
            source_locator='cg:1', name_key='jane doe', name='Jane Doe', given='Jane', family='Doe',
            organization='Acme Energy Corp.', on_behalf_of=None, display_order=1,
        )],
    )
    spicy = spicy_input(
        spicy_committees=[dict(
            system_code='hsif00', name='Energy and Commerce', chamber='house',
            committee_type='standing', parent_system_code=None,
            website_url='https://energycommerce.house.gov', is_current=True, history=[],
        )],
        spicy_members=[], spicy_member_terms=[],
    )
    scratch = tmp_path / 'scratch'
    out = tmp_path / 'out'
    build_release(
        **staged,
        engine=engine,
        output=out,
        scratch=scratch,
        meeting_records=[dict(record_sha=hashlib.sha256(cg).hexdigest(), source='congress_gov', meetings=[meeting])],
        appearance_records=[appearance],
        spicy_regs=spicy,
        include_entities=True,
        include_org_entities=True,
        include_wikidata_links=False,
    )
    org_dir = scratch / 'evidence' / 'org_entities'
    assert (org_dir / 'org_reconcile_requests.parquet').is_file()
    assert (org_dir / 'org_wikidata_links.parquet').is_file()
    batches = pq.read_table(org_dir / 'org_reconcile_requests.parquet').to_pylist()
    assert len(batches) == 1
    assert batches[0]['batch_size'] == 1


def test_wikidata_query_exclusions_and_type_country_guards(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    rows = [
        dict(witness_key='7000000000000001', organization='Prepared statement of', on_behalf_of=None),
        dict(witness_key='7000000000000002', organization='P.A', on_behalf_of=None),
        dict(witness_key='7000000000000003', organization='Glass Lewis & Co', on_behalf_of=None),
        dict(witness_key='7000000000000004', organization='Bay Bank', on_behalf_of=None),
        dict(witness_key='7000000000000005', organization='Palo, IA', on_behalf_of=None),
        dict(witness_key='7000000000000006', organization='Toyota Motor Manufacturing, Indiana, Inc.', on_behalf_of=None),
        dict(witness_key='7000000000000007', organization='Untyped Example Org', on_behalf_of=None),
        dict(witness_key='7000000000000008', organization='City of Schenectady', on_behalf_of=None),
    ]
    app_path = _write_resolved_appearances(tmp_path / 'appearances.parquet', rows)
    probe = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'probe-out',
        scratch=tmp_path / 'probe-scratch',
    )
    bags = {
        raw: r['bag_key']
        for r in pq.read_table(probe['outputs']['org_strings.parquet']).to_pylist()
        for raw in r['raw_texts']
    }
    req_batches = pq.read_table(probe['outputs']['org_reconcile_requests.parquet']).to_pylist()
    requested = {}
    for b in req_batches:
        for bk, obj in json.loads(b['queries_json']).items():
            requested[bk] = obj['query']
    assert bags['Prepared statement of'] not in requested
    assert bags['P.A'] not in requested
    assert requested[bags['Glass Lewis & Co']] == 'glass lewis'

    body_sha = hashlib.sha256(b'wd-guard-1').digest()
    from datetime import datetime, timezone
    ts = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
    cap_path, read_path = _write_reconcile_tables(
        tmp_path,
        captures_rows=[dict(
            family='wikidata/reconcile',
            mode='fetch',
            outcome='stored',
            sha256=body_sha,
            receipt_key='receipts/wikidata/reconcile/2026-11-25/guard.jsonl.gz',
            retrieved_at=ts,
            requested_url='https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%7D',
        )],
        readings_rows=[dict(
            body_sha=body_sha,
            parser='wikidata_reconcile',
            status='completed',
            fields=[
                dict(field=f"query:{bags['Glass Lewis & Co']}", value='[' + _wd_cand('Q112829332', 'Arnold Lewis Glass', 91.0, '1951-', False, types=('Q5',)) + ']'),
                dict(field=f"query:{bags['Bay Bank']}", value='[' + _wd_cand('Q4855904', 'Bank Bay', 100.0, 'human settlement in Alberta, Canada', True, types=('Q3257686',)) + ']'),
                dict(field=f"query:{bags['Palo, IA']}", value='[' + _wd_cand('Q1926239', 'Palo', 100.0, 'city in Iowa', True, types=('Q1093829',)) + ']'),
                dict(field=f"query:{bags['Toyota Motor Manufacturing, Indiana, Inc.']}", value='[' + _wd_cand('Q2447176', 'Toyota Motor Manufacturing UK', 95.0, 'Toyota subsidiary in the UK', False, types=('Q21980538',)) + ']'),
                dict(field=f"query:{bags['Untyped Example Org']}", value='[' + _wd_cand('Q999002', 'Untyped Example Org', 100.0, 'something', True, types=()) + ']'),
                dict(field=f"query:{bags['City of Schenectady']}", value='[' + _wd_cand('Q489999', 'Schenectady', 100.0, 'city in New York', True, types=('Q1093829',)) + ']'),
            ],
        )],
    )
    res = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'out',
        scratch=tmp_path / 'scratch',
        captures=cap_path,
        selected_readings=read_path,
        include_wikidata_links=True,
    )
    links = {(r['bag_key'], r['qid']): r['link_status'] for r in pq.read_table(res['outputs']['org_wikidata_links.parquet']).to_pylist()}
    assert links[(bags['Glass Lewis & Co'], 'Q112829332')] == 'review'
    assert links[(bags['Bay Bank'], 'Q4855904')] == 'review'
    assert links[(bags['Palo, IA'], 'Q1926239')] == 'review'
    assert links[(bags['Toyota Motor Manufacturing, Indiana, Inc.'], 'Q2447176')] == 'review'
    assert links[(bags['Untyped Example Org'], 'Q999002')] == 'review'
    assert links[(bags['City of Schenectady'], 'Q489999')] == 'auto_accept'
