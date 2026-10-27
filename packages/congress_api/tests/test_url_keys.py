"""One native URL join rule serves the model and the scheduler."""
import json
import os
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[3]


def execute(tmp_path, cases, variants=()):
    rules = json.loads((ROOT/'model/registries/url-rules.json').read_text())
    inputs = [json_input(tmp_path,'url_inputs',
                [dict(input_id=c['id'],url=c['url']) for c in cases],input_id='Utf8',url='Utf8'),
        json_input(tmp_path,'url_rules',rules,id='Utf8',kind='Utf8',host_pattern='Utf8',
                   pattern='Utf8',replacement='Utf8',decoder='Utf8'),
        json_input(tmp_path,'url_variants',variants,canonical_url='Utf8',variant_url='Utf8')]
    return run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='url_normalized',materialize=True,
                    sql=(ROOT/'model/sql/url-normalized.sql').read_text()),
               dict(name='url_keys',sql=(ROOT/'model/sql/url-keys.sql').read_text())],outputs=[],
        queries=[dict(name='keys',sql='SELECT * FROM url_keys ORDER BY input_id')])['keys']


def test_native_url_keys_preserve_exact_urls_and_normalize_only_join_keys(tmp_path):
    cases=json.loads((ROOT/'model/fixtures/url-key-cases.json').read_text())
    result=execute(tmp_path,cases)
    assert result==[dict(input_id=c['id'],url=c['url'],url_key=c['key'],error=c.get('error'))
                   for c in sorted(cases,key=lambda c:c['id'])]


def test_normalized_variant_is_substituted_once(tmp_path):
    case=dict(id='one',url='http://www.example.gov/alias/')
    result=execute(tmp_path,[case],[dict(variant_url='https://example.gov/alias',
                                      canonical_url='https://example.gov/Canonical')])
    assert result==[dict(input_id='one',url=case['url'],url_key='example.gov/Canonical',error=None)]


@pytest.mark.parametrize('variants,error', [
    ([('a','b'),('a','c')],'variant_conflict'),
    ([('a','b'),('b','c')],'variant_chain'),
    ([('a','b'),('b','a')],'variant_chain')])
def test_invalid_variant_graph_refuses_usable_join_keys(tmp_path,variants,error):
    records=[dict(variant_url='https://example.gov/'+a,canonical_url='https://example.gov/'+b)
             for a,b in variants]
    result=execute(tmp_path,[dict(id='one',url='https://example.gov/a')],records)
    assert result==[dict(input_id='one',url='https://example.gov/a',url_key=None,error=error)]
