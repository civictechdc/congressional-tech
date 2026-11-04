"""A group holds exactly one distinct non-NULL value: `min(x)=max(x)`, never `count(DISTINCT x)=1`.

The engine keeps a distinct set per group (about 14 KB each), so the count form costs
gigabytes over hundreds of thousands of groups (source_reference_targets: 480K). min/max keep
two values per group and select the same groups for every key type the model uses.
"""
import os
import random
import re
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[3]
NESTED = r'(?:\((?:[^()]|\([^()]*\))*\))'
DISTINCT_EQUALS_ONE = re.compile(r'count\(\s*DISTINCT\b(?:[^()]|' + NESTED + r')*\)\s*=\s*1\b', re.IGNORECASE)
CASTS = dict(int='v', text='v', sha="arrow_cast(decode(v,'hex'),'FixedSizeBinary(32)')", binary="decode(v,'hex')")
FORMS = dict(
    oracle='count(DISTINCT x)=1',
    committed='min(x)=max(x)',
    plant_null_groups='min(x) IS NOT DISTINCT FROM max(x)',
    plant_duplicates='count(x)=1',
)


def seeded_rows(kind, seed=20261104):
    rng = random.Random(seed)
    pool = [None] + [format(n, '064x') if kind in ('sha', 'binary') else (n if kind == 'int' else 'k' + str(n))
                     for n in range(6)]
    rows = []
    for group in range(600):
        rows += [dict(g=group, v=rng.choice(pool)) for _ in range(rng.randint(1, 5))]
    return rows


@pytest.fixture(scope='module')
def selected(tmp_path_factory):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    found = {}
    for kind, cast in CASTS.items():
        directory = tmp_path_factory.mktemp(kind)
        rows = seeded_rows(kind)
        inputs = [json_input(directory, 'raw', rows, g='Int64', v='Int64' if kind == 'int' else 'Utf8')]
        steps = [dict(name='keyed', sql=f'SELECT g,{cast} AS x FROM raw', materialize=True)]
        result = run_job(directory, engine, inputs=inputs, steps=steps, outputs=[], queries=[
            dict(name=form, sql=f'SELECT g FROM keyed GROUP BY g HAVING {having} ORDER BY g')
            for form, having in FORMS.items()])
        found[kind] = {form: [r['g'] for r in result[form]] for form in FORMS}
    return found


@pytest.mark.parametrize('kind', sorted(CASTS))
def test_min_equals_max_selects_the_groups_count_distinct_selects(selected, kind):
    chosen = selected[kind]
    assert chosen['committed'] == chosen['oracle']
    assert 0 < len(chosen['oracle']) < 600


@pytest.mark.parametrize('kind', sorted(CASTS))
@pytest.mark.parametrize('plant', [form for form in FORMS if form.startswith('plant_')])
def test_the_seeded_groups_tell_each_wrong_rewrite_from_the_oracle(selected, kind, plant):
    assert selected[kind][plant] != selected[kind]['oracle']


def model_definitions():
    yield from sorted((ROOT / 'model/sql').glob('*.sql'))
    yield ROOT / 'packages/viewer_publication/src/viewer_publication/archive_model.py'


def test_no_model_step_counts_distinct_values_to_test_for_one():
    found = [f'{path.relative_to(ROOT)}: {match.group(0)}' for path in model_definitions()
             for match in DISTINCT_EQUALS_ONE.finditer(path.read_text())]
    assert found == [], 'use min(x)=max(x): ' + '; '.join(found)


@pytest.mark.parametrize('text', [
    'HAVING count(DISTINCT n.body_sha)=1',
    'HAVING count( distinct lower(trim(a.b)) ) = 1',
    'OR count(DISTINCT higher_person_key)=1\n',
])
def test_the_lint_flags_each_spelling(text):
    assert DISTINCT_EQUALS_ONE.search(text)


@pytest.mark.parametrize('text', [
    'HAVING count(DISTINCT name_key)>1',
    'count(DISTINCT x)=10',
    'HAVING min(x)=max(x)',
])
def test_the_lint_leaves_other_counts_alone(text):
    assert not DISTINCT_EQUALS_ONE.search(text)
