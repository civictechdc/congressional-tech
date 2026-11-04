"""url_normalized copies the rows source_url_normalized already holds and normalizes only the rest.

The oracle is the step as it stood before ct-6v77 R8: url-normalized.sql over every url_inputs literal.
The committed pair (url_literals, url_normalized) must give the same rows, and the same url-keys.sql
result, on seeded literals that are new, shared with the source step, source-only, duplicated or NULL.
"""
import json
import os
import random
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import source_steps, url_normalized_steps

ROOT = Path(__file__).parents[3]
POLICY = (ROOT/'model/sql/url-normalized.sql').read_text()
KEYS = (ROOT/'model/sql/url-keys.sql').read_text()
COLUMNS = 'url,error,still_wrapped,base_key'

# Wrong rewrites the seeded literals must tell apart from the oracle: (committed step, text replaced, replacement).
PLANTS = {
    'reuse_joined_on_base_key': ('url_literals', 's.url=l.url', 's.base_key=l.url'),
    'union_all_renormalizes_reused': ('url_normalized', 'FROM url_literals WHERE NOT reused', 'FROM url_literals'),
    'copies_every_source_row': ('url_normalized', 'FROM url_literals WHERE reused', 'FROM source_url_normalized'),
}


def committed():
    return {step['name']: step['sql'] for step in url_normalized_steps(root=ROOT)}


def variant_steps(name, sql):
    """One copy of the committed pair, its relations renamed so every variant runs in one job."""
    rename = lambda text: text.replace('url_literals', f'{name}_literals')
    return [dict(name=f'{name}_literals', sql=rename(sql['url_literals']), materialize=True),
            dict(name=f'{name}_normalized', sql=rename(sql['url_normalized']), materialize=True)]


def seeded_literals(seed=20261104, generated=600):
    """url_inputs rows, source_url_inputs rows and url_variants from the URL key fixtures plus generated
    addresses: wrapped up to three times, tracker and search parameters, www and ports, schemeless
    host/path strings that equal another literal's base key, and invalid text."""
    rng = random.Random(seed)
    pool = [case['url'] for case in json.loads((ROOT/'model/fixtures/url-key-cases.json').read_text()) if case['url']]
    hosts = ['example.gov', 'www.example.gov', 'congress.gov', 'www.congress.gov:8443', 'finance.senate.gov',
             'judiciary.senate.gov', 'democrats-science.house.gov']
    for _ in range(generated):
        host, path = rng.choice(hosts), '/'.join(rng.choice(['a', 'b', 'download', 'x.pdf', 'C']) for _ in range(rng.randrange(1, 4)))
        query = '&'.join(rng.sample(['q=state', 'utm_source=x', 'id=3', 'download=1', 'z=1', 'a='], rng.randrange(0, 4)))
        url = f"{rng.choice(['https', 'http', 'HTTP'])}://{host}/{path}{rng.choice(['', '/'])}" + (f'?{query}' if query else '')
        for _ in range(rng.choice([0, 0, 0, 1, 1, 2, 3])):
            url = rng.choice(['https://web.archive.org/web/20250610160415id_/', 'https://webarchive.loc.gov/all/20110707213402/']) + url
        pool.append(rng.choice([url, url, url, url, f'{host}/{path}', 'not a URL ' + path]))
    variants = [(f'https://canonical.gov/c{i}', f'https://variant.gov/v{i}/') for i in range(8)]
    inputs, sources = [], []
    for url in pool + [url for pair in variants for url in pair]:
        side = rng.random()
        if side < 0.7:
            inputs.append(url)
        if side > 0.25:
            sources.append(url)
    inputs += rng.sample(inputs, len(inputs)//10) + [None]
    sources += rng.sample(sources, len(sources)//10) + [None]
    return inputs, sources, variants


def case_inputs(directory, urls, source_urls, variants):
    rules = json.loads((ROOT/'model/registries/url-rules.json').read_text())
    return [json_input(directory, 'url_inputs', [dict(input_id=f'i{n}', url=u) for n, u in enumerate(urls)], input_id='Utf8', url='Utf8'),
            json_input(directory, 'source_url_inputs', [dict(input_id=f's{n}', url=u) for n, u in enumerate(source_urls)],
                       input_id='Utf8', url='Utf8'),
            json_input(directory, 'url_rules', rules, id='Utf8', kind='Utf8', host_pattern='Utf8', pattern='Utf8',
                       replacement='Utf8', decoder='Utf8'),
            json_input(directory, 'url_variants', [dict(canonical_url=c, variant_url=v) for c, v in variants],
                       canonical_url='Utf8', variant_url='Utf8')]


@pytest.fixture(scope='module')
def url_normalized_variants(tmp_path_factory):
    """Oracle, committed pair and every plant, with keys for the oracle and committed pair, in one job per case."""
    sql = committed()
    planted = {}
    for plant, (step, old, new) in PLANTS.items():
        if old in sql[step]:
            planted[plant] = dict(sql, **{step: sql[step].replace(old, new)})
    source = next(step for step in source_steps(root=ROOT) if step['name'] == 'source_url_normalized')
    steps = [source, dict(name='oracle_normalized', sql=POLICY, materialize=True)] + variant_steps('committed', sql)
    for plant, plant_sql in planted.items():
        steps += variant_steps(plant, plant_sql)
    steps += [dict(name=f'{name}_keys', sql=KEYS.replace('url_normalized', f'{name}_normalized'), materialize=True)
              for name in ('oracle', 'committed')]
    order = f' ORDER BY {COLUMNS}'
    queries = [dict(name=name, sql=f'SELECT {COLUMNS} FROM {name}_normalized{order}') for name in ['oracle', 'committed', *planted]]
    queries += [dict(name=f'{name}_keys', sql=f'SELECT * FROM {name}_keys ORDER BY input_id') for name in ('oracle', 'committed')]
    queries += [dict(name='split', sql='SELECT reused,count(*) AS n FROM committed_literals GROUP BY reused ORDER BY reused'),
                dict(name='source', sql=f'SELECT {COLUMNS} FROM source_url_normalized{order}')]
    inputs, sources, variants = seeded_literals()
    cases = dict(seeded=(inputs, sources, variants), empty=([], [], []), no_url_inputs=([], sources, variants),
                 null_variant=(inputs, sources, variants + [(None, 'https://variant.gov/v0/')]))
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    results = {}
    for case, rows in cases.items():
        directory = tmp_path_factory.mktemp(case)
        results[case] = run_job(directory, engine, inputs=case_inputs(directory, *rows), steps=steps, outputs=[], queries=queries)
    return results


def test_empty_inputs_give_no_rows(url_normalized_variants):
    empty = url_normalized_variants['empty']
    assert empty['oracle'] == empty['committed'] == []


@pytest.mark.parametrize('case', ['seeded', 'no_url_inputs', 'null_variant'])
def test_url_normalized_equals_one_pass_over_every_literal(url_normalized_variants, case):
    result = url_normalized_variants[case]
    assert result['committed'] == result['oracle']
    assert result['committed_keys'] == result['oracle_keys']


def test_the_seed_reaches_new_shared_source_only_and_null_literals(url_normalized_variants):
    seeded = url_normalized_variants['seeded']
    split = {row['reused']: row['n'] for row in seeded['split']}
    assert split[True] > 200 and split[False] > 100
    oracle, source = {row['url'] for row in seeded['oracle']}, {row['url'] for row in seeded['source']}
    assert len(source - oracle) > 50 and None in oracle and None in source
    assert {row['error'] for row in seeded['oracle']} >= {None, 'invalid_url'}
    assert any(row['still_wrapped'] for row in seeded['oracle'])
    # A schemeless literal equal to another literal's base key, which only a join on the wrong column reuses.
    assert {row['base_key'] for row in seeded['source']} & {row['url'] for row in seeded['oracle'] if row['error']}
    assert any(row['url_key'] for row in seeded['committed_keys']) and any(row['url_key'] is None for row in seeded['committed_keys'])
    assert {row['error'] for row in url_normalized_variants['null_variant']['committed_keys']} == {'invalid_variant'}
    assert url_normalized_variants['no_url_inputs']['oracle'] and url_normalized_variants['no_url_inputs']['committed_keys'] == []


@pytest.mark.parametrize('plant', PLANTS)
def test_seeded_literals_tell_each_wrong_rewrite_from_the_oracle(url_normalized_variants, plant):
    seeded = url_normalized_variants['seeded']
    assert plant in seeded, f'{plant}: its replaced text is no longer in the committed SQL'
    assert seeded[plant] != seeded['oracle']
