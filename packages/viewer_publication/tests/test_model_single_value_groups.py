"""A group holds exactly one distinct non-NULL value: `min(x)=max(x)`, never `count(DISTINCT x)=1`.

The engine keeps a distinct set per group (about 14 KB each), so the count form costs
gigabytes over hundreds of thousands of groups (source_reference_targets: 480K). min/max keep
two values per group and select the same groups for every key type the model uses.

An equivalent body-admissions.sql rewrite used to repin the readings bundle and
reopen 25 settled failures. The diagnostics now flag the edit for review while
the declared version keeps those decisions eligible.
"""
import json
import os
import random
import re
from pathlib import Path

import pytest

from congress_api.lake.compatible_versions import accepted_versions_input, selected_readings_steps
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
PUBLISHED = json.loads((ROOT / 'model/jobs/publish-model.json').read_text())['parser_versions']
LEAVES = {parser: PUBLISHED[parser] for parser in ('sniff', 'html', 'xml', 'json')}
# Pin the bundle formed by the model's selected leaves and current producer. The fixture
# below uses decisions at that version. Reconcile prior real decisions separately.
READINGS_BUNDLE = '7b006df14ea065d7bab8c15a319c9201c57d4547c174d722651a33107dbd73ed'
ADMISSIONS = ROOT / 'model/sql/body-admissions.sql'
# Two of build-1's 25 bodies whose only settlement was a readings decision at READINGS_BUNDLE:
# one with no sniff reading, one sniffed as xml with no xml reading.
UNSNIFFED, UNPAGED = ('044f1c5412079a563cabdb6b9882e0a459870cd275af4b41cc6c0a48f3eed11d',
                      'c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e')


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


def parser_fingerprint_files(monkeypatch):
    """SQL files included in producer versions or the bundle's advisory fingerprint."""
    from congress_api.lake import filenames, reading_version_diagnostics as diagnostics, versions, video_records
    hashed, digest = set(), versions.version_digest

    def capture(*, packages, files, values=None):
        hashed.update(Path(path).resolve() for path in files.values())
        return digest(packages=packages, files=files, values=values)
    # filenames reaches version_digest through versions.producer_version.
    for module in (diagnostics, versions, video_records):
        monkeypatch.setattr(module, 'version_digest', capture)
    diagnostics.snapshot()
    filenames.current_version()
    video_records.current_versions()
    monkeypatch.undo()
    return hashed


def plant_rewritten_admissions(monkeypatch, tmp_path):
    """Hash the branch's min=max rewrite of body-admissions.sql in place of the committed bytes."""
    from congress_api.lake import reading_version_diagnostics as diagnostics
    text = ADMISSIONS.read_text()
    assert text.count('count(DISTINCT c.media_type)=1') == 1
    planted = tmp_path / 'body-admissions.sql'
    planted.write_text(text.replace('count(DISTINCT c.media_type)=1', 'min(c.media_type)=max(c.media_type)'))
    digest = diagnostics.version_digest

    def swapped(*, packages, files, values=None):
        files = {name: planted if Path(path).resolve() == ADMISSIONS else path for name, path in files.items()}
        return digest(packages=packages, files=files, values=values)
    monkeypatch.setattr(diagnostics, 'version_digest', swapped)


def test_no_model_step_counts_distinct_values_to_test_for_one(monkeypatch):
    hashed = parser_fingerprint_files(monkeypatch)
    found = [f'{path.relative_to(ROOT)}: {match.group(0)}' for path in model_definitions()
             if path.resolve() not in hashed for match in DISTINCT_EQUALS_ONE.finditer(path.read_text())]
    assert found == [], 'use min(x)=max(x): ' + '; '.join(found)


def test_the_lint_exempts_only_fingerprinted_step_files(monkeypatch):
    exempt = parser_fingerprint_files(monkeypatch) & {path.resolve() for path in model_definitions()}
    assert ADMISSIONS in exempt
    assert DISTINCT_EQUALS_ONE.search(ADMISSIONS.read_text())
    assert not {path.name for path in exempt} & {
        'appearance-observations.sql', 'document-witness-raw-matches.sql', 'meeting-records-resolved.sql',
        'retired-links.sql', 'source-reference-targets.sql', 'witness-precedence.sql', 'archive_model.py'}


def test_the_published_leaves_make_the_pinned_readings_bundle():
    from viewer_publication.archive_model_profile import readings_bundle_version
    assert readings_bundle_version(LEAVES) == READINGS_BUNDLE


def test_the_planted_rewrite_warns_without_moving_the_readings_bundle(monkeypatch, tmp_path):
    from congress_api.lake import reading_version_diagnostics as diagnostics
    from viewer_publication.archive_model_profile import readings_bundle_version
    before = diagnostics.snapshot()
    plant_rewritten_admissions(monkeypatch, tmp_path)
    assert dict(diagnostics.drift_messages(before, diagnostics.snapshot())) == {'readings': (
        f'readings reading version evidence changed (workspace_sha256); using {READINGS_BUNDLE}. '
        'Record equivalence or a deliberate bump.'
    )}
    assert readings_bundle_version(LEAVES) == READINGS_BUNDLE


@pytest.mark.parametrize('arm,expected', [('current', {}), ('advisory', {}), ('bumped', {'missing_sniff': 1, 'missing_pages': 1})])
def test_readings_decisions_at_the_pinned_bundle_settle_their_bodies(monkeypatch, tmp_path, arm, expected):
    from viewer_publication.archive_model_profile import (completeness_checks, completeness_steps,
                                                          readings_bundle_version)
    if arm == 'advisory':
        plant_rewritten_admissions(monkeypatch, tmp_path)
    if arm == 'bumped':
        from congress_api.lake.reading_versions import READING_VERSIONS
        monkeypatch.setitem(READING_VERSIONS, 'readings', 'deliberately-bumped')
    pins = {**LEAVES, 'readings': readings_bundle_version(LEAVES)}
    bodies = (UNSNIFFED, UNPAGED)
    inputs = [
        json_input(tmp_path, 'capture_rows', [dict(receipt_key='r', receipt_line=1, capture_index=i, body_hex=body)
                                              for i, body in enumerate(bodies)],
                   receipt_key='Utf8', receipt_line='Int32', capture_index='Int32', body_hex='Utf8', bytes='Int64'),
        json_input(tmp_path, 'reading_rows', [dict(body_hex=UNPAGED, parser='sniff', parser_version=LEAVES['sniff'],
                                                   status='completed')],
                   body_hex='Utf8', parser='Utf8', parser_version='Utf8', status='Utf8'),
        json_input(tmp_path, 'sniff_rows', [dict(body_hex=UNPAGED, format='xml')], body_hex='Utf8', format='Utf8'),
        json_input(tmp_path, 'admission_rows', [], body_hex='Utf8', format='Utf8', basis='Utf8'),
        json_input(tmp_path, 'filename_readings', [dict(filename='a.pdf', source_url='', catalog_version='catalog-1',
                                                        status='completed')],
                   filename='Utf8', source_url='Utf8', catalog_version='Utf8', status='Utf8'),
        json_input(tmp_path, 'unreadable_rows', [dict(body_sha256=body, parser='readings', parser_version=READINGS_BUNDLE)
                                                 for body in bodies],
                   body_sha256='Utf8', parser='Utf8', parser_version='Utf8'),
        json_input(tmp_path, 'parser_versions', [dict(parser=p, version=v) for p, v in LEAVES.items()],
                   parser='Utf8', version='Utf8'),
        accepted_versions_input(tmp_path, [], pins=pins)]
    steps = [
        dict(name='captures', sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM capture_rows"),
        dict(name='readings', sql="SELECT *,decode(body_hex,'hex') AS body_sha FROM reading_rows"),
        *selected_readings_steps([]),
        dict(name='sniff_facts', sql="SELECT decode(body_hex,'hex') AS body_sha,format FROM sniff_rows"),
        dict(name='body_admissions', sql="SELECT decode(body_hex,'hex') AS body_sha,format,basis FROM admission_rows"),
        dict(name='source_files', sql="SELECT 'a.pdf' AS filename,cast(NULL AS VARCHAR) AS source_url"),
        dict(name='active_unreadable', sql='SELECT body_sha256,cast(NULL AS VARCHAR) AS record_sha,parser,parser_version '
                                           'FROM unreadable_rows')]
    report = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs,
                     steps=steps + completeness_steps(), outputs=[],
                     queries=completeness_checks(catalog_version='catalog-1'))['profile_completeness'][0]
    assert {name: value for name, value in report.items() if value} == expected


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
