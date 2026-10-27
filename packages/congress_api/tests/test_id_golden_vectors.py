"""E3: fixed legacy ID bytes for current code and the future native SQL model."""
from hashlib import sha256
import json
from pathlib import Path
import re

import pytest

from congress_api.retention.index.bipartite import source_identity, compute_document_id
from congress_api.retention.index.schemas import compact

FIXTURE = Path(__file__).parents[3] / 'model/fixtures/id-golden-vectors.json'
VECTORS = json.loads(FIXTURE.read_text())


@pytest.mark.parametrize('case', VECTORS['source_ids'], ids=lambda case: case['name'])
def test_source_id_golden_bytes(case):
    row = case['inputs']
    identity = [row.get(key) for key in ('body_key', 'filename', 'source_url')]
    assert compact(identity) == case['compact_json']
    assert sha256(case['compact_json'].encode('utf-8')).hexdigest() == case['expected_hex']
    assert source_identity(row) == case['expected_hex']


@pytest.mark.parametrize('case', VECTORS['document_ids'], ids=lambda case: case['name'])
def test_document_id_golden_bytes(case):
    inputs = case['inputs']
    bodies = sorted(set(inputs['bodies']))
    identity = ['bodies', bodies] if bodies else ['sources', sorted(set(inputs['source_ids']))]
    assert identity[0] == case['formula']
    assert compact(identity) == case['compact_json']
    assert sha256(case['compact_json'].encode('utf-8')).hexdigest() == case['expected_hex']
    assert compute_document_id(inputs['bodies'], inputs['source_ids']) == case['expected_hex']


def test_golden_boundary_relationships():
    # DM §3 keeps the historical .gz identity even when storage is bare or PDF.
    logical = r'bodies/sha256/([a-f0-9]{2})/[a-f0-9]{64}[.]gz'
    for case in VECTORS['source_ids']:
        key = case['inputs'].get('body_key')
        if key:
            assert re.fullmatch(logical, key), case['name']
    for case in VECTORS['document_ids']:
        assert all(re.fullmatch(logical, key) for key in case['inputs']['bodies'])
    sources = {case['name']: case['expected_hex'] for case in VECTORS['source_ids']}
    documents = {case['name']: case['expected_hex'] for case in VECTORS['document_ids']}
    assert sources['missing-all'] == sources['explicit-nulls']
    assert sources['missing-body-url'] == sources['null-body-url']
    assert sources['empty-strings'] != sources['explicit-nulls']
    assert sources['unicode-nfc'] != sources['unicode-nfd']
    assert sources['query-order-one'] != sources['query-order-two']
    assert sources['ordinary'] == sources['ignored-interpretation']
    assert documents['bodies-unsorted'] == documents['bodies-duplicated'] == documents['bodies-reordered']
    assert documents['one-body'] == documents['bodies-ignore-sources']
    assert documents['sources-unsorted'] == documents['sources-duplicated'] == documents['sources-reordered']
    assert documents['one-body'] != documents['distinct-second-body']
