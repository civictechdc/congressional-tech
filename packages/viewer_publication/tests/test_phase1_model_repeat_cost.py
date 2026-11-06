"""No model reader re-runs work over a large relation, judged from its native plan.

The pinned DataFusion plans every CTE and view reference as its own subtree and ignores
AS MATERIALIZED (AGENTS.md: a CTE runs once per reference), so a CTE read twice inside a
CTE that is itself read twice runs four times. Each run is one `TableScan` in the reader's
optimized logical plan, so counting scans counts the work, nesting and views included.

The job is the one the build submits (every step, export and query), planned over zero-row
inputs with the producers' schemas: nothing corpus-sized runs, and the lint sees plan shape,
not memory or time. A reader's score is the sum, over relations its plan scans more than
once, of (scans - 1) x rows, the extra row-scans the materialization audit ranked by
(.cache/archive-release/investigations/model-step-materialization-audit-20261104.md, M40).
Rows are not in an empty plan: they come from fixtures/model-relation-rows.json, measured
from one nightly-shaped build (scripts/measure/model_relation_rows.py regenerates it). A
step missing from it is estimated at its largest input's rows.
"""
import collections
import json
import os
import re
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec, spicy_input
from congress_api.lake import appearance_records, committee_records, meeting_records, video_records
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import build_prepared_release, prepare_model_inputs
from viewer_publication.archive_model_lifetimes import sql_dependencies

#: Extra row-scans at which a reader must materialize what it repeats, as a step of its own.
THRESHOLD = 10_000_000
MEASURED = json.loads((Path(__file__).parent/'fixtures/model-relation-rows.json').read_text())

# Readers over the line today, with their scores on the measured rows and the audit section that
# names the repeated CTE or view. Each is a ct-6v77 follow-up; fix one and delete its entry. A reader
# that is not listed may not cross the line.
REPEAT_COST_TRACKED = {
    'entity_profile_completeness': 49_033_171,  # query; captures x10, readings x9 (M17, M28)
    'model_invariants': 48_118_770,             # query; the merged 7-way join x5 (M13)
    'merged_recovery_fields': 43_005_605,       # query; the merged 7-way join x5 (M13)
    'bills_export': 33_468_701,                 # spicy_congress_bills x30, ordered x27 (M17)
    'component_meeting_links': 32_189_482,      # effective_filenames x4, source_annotations x6 (M17)
    'retired_links_export': 31_775_718,         # the links view: ordered x29, prior_links x21 (M16)
    'profile_completeness': 23_295_486,         # query; readings through the current selected_readings (M28)
    'model_url_keys': 18_289_579,               # url_normalized x11 through mappings (M17)
    'relationship_invariants': 32_996_170,      # includes exact legislative leaf rows; pre-repair plan has the same score
    'source_url_keys': 13_842_862,              # source_url_normalized x11 through mappings (M17)
    'pinned_readings': 14_177_632,              # current compatible reading selection (M28)
    'link_inputs': 14_177_632,                  # current compatible reading selection (M28)
    'publisher_links': 11_093_345,              # resolved_links x2, model_url_keys x4 (M17)
}
# Reconciled against df3a9c91 and the caption-resource candidate with native zero-row
# plans in mcp-research-20261106/hearings/repeat-cost-baseline/comparison.json.
# Only caption_resources added work in that reconciliation. The later legislative
# leaf counts and meetings regex baseline are bound by before/after tiny job replays
# in parallel-sessions/ct-m104/repeat-audit-{before-v2,after-v1}/report.json.
# Both plans have identical tracked costs and no new offender. These are estimated
# row-scan scores, never measured time or RSS.
# Readers whose plan runs the same regex join more than once, with that join's runs: a nested-loop
# regex join costs CPU per rule and row, which the row score cannot see (audit M15). Tracked under
# ct-6v77 likewise.
REGEX_REPEAT_TRACKED = {
    'url_normalized': 2,                  # components, read by pairs and base_keys (M15)
    'source_url_normalized': 2,           # the same
    'appearance_url_normalized': 2,       # the same
    'url_state_sanitized_normalized': 2,  # the same
    'source_annotation_publisher': 2,     # kinds (M40)
    'source_annotation_pages': 2,         # link_word_texts (M40)
    'recordings_entity': 6,               # raw_meeting_videos (M40)
    'meetings_export': 3,                 # current transcript/status plan; identical before the window repair
}

# New offenders the lint must catch, and one it must let through.
PLANTED = {
    'planted_cte_read_three_times': """WITH targets AS (
        SELECT page_body,target_url FROM resolved_links WHERE target_url IS NOT NULL)
        SELECT page_body FROM targets UNION ALL SELECT target_url FROM targets
        UNION ALL SELECT page_body||target_url FROM targets""",
    'planted_regex_join_read_twice': """WITH matched AS (
        SELECT u.url,r.id FROM url_inputs u JOIN url_rules r ON regexp_like(u.url,r.pattern))
        SELECT url FROM matched UNION ALL SELECT id FROM matched""",
    'planted_small_cte_read_three_times': """WITH current AS (
        SELECT witness_key,superseded_by FROM witness_precedence WHERE superseded_by IS NOT NULL)
        SELECT witness_key FROM current UNION ALL SELECT superseded_by FROM current
        UNION ALL SELECT witness_key||superseded_by FROM current""",
}

SCAN = re.compile(r'^\s*TableScan: (\S+)', re.M)
JOIN = re.compile(r'^\s*\w+ Join: (.*)$', re.M)
REGEX = re.compile(r'regexp_|\s!?~\*?\s|SIMILAR TO', re.I)


class _Submitted(Exception):
    pass


class _Capture:
    """Records the job the build submits instead of running it."""
    def __init__(self, engine, path):
        self.engine, self.path = engine, path

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def run_job(self, path):
        shutil.copy(path, self.path)
        raise _Submitted


def submitted_job(root, engine):
    """The release job over empty inputs with every producer schema: entities and Explorer tables included."""
    value, _digest, _html = real_model_spec(root)
    empty = {}
    for name in ('captures', 'readings', 'filename_readings'):
        empty[name] = root/f'empty-{name}.parquet'
        pq.write_table(pq.read_schema(value[name]['path']).empty_table(), empty[name])
    for name, lake in dict(meeting_records=meeting_records, appearance_records=appearance_records,
                           video_records=video_records, committee_records=committee_records).items():
        empty[name] = root/f'empty-{name}.parquet'
        pq.write_table(lake.table([]), empty[name])
    decisions = root/'recording-decisions.jsonl'; decisions.write_text('')
    versions = dict(value['parser_versions'], meeting_records=meeting_records.current_versions(),
                    appearance_records=appearance_records.current_versions(),
                    video_records={'youtube_cache': 'pv', 'youtube_api': 'pa'}, committee_records={'house_xml': 'pc'})
    prepared = prepare_model_inputs(**empty, parser_versions=versions, catalog_version=value['catalog_version'],
        engine=engine, scratch=root/'prepared', spicy_regs=spicy_input(), include_entities=True,
        recording_decision_files=[dict(key='provenance/recording_decisions/empty.jsonl', path=str(decisions))])
    with pytest.raises(_Submitted):
        build_prepared_release(prepared, engine=_Capture(engine, root/'submitted-job.json'), output=root/'release')
    return json.loads((root/'submitted-job.json').read_text())


def readers(job):
    """Everything that executes: materialized and components steps, exports and queries. Views run inside them."""
    for step in job['steps']:
        if 'components' in step:
            yield step['name'], step['components']['sql']
        elif step.get('materialize'):
            yield step['name'], step['sql']
    for item in job['outputs'] + job['queries']:
        yield item['name'], item['sql']


@pytest.fixture(scope='module')
def planned(tmp_path_factory):
    root = tmp_path_factory.mktemp('repeat-cost')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        job = submitted_job(root, engine)
        steps = [{k: v for k, v in step.items() if k != 'release_after'} for step in job['steps']]
        steps += [dict(name=name, sql=sql, materialize=True) for name, sql in PLANTED.items()]
        job = dict(job, steps=steps)
        named = list(readers(job))
        path = root/'explain-job.json'
        path.write_text(json.dumps(dict(inputs=job['inputs'], steps=steps, outputs=[], scratch=str(root/'native'),
            queries=[dict(name=f'reader_{i}', sql='EXPLAIN '+sql) for i, (_name, sql) in enumerate(named)])))
        result = engine.run_job(path)
    plans = {name: next(row['plan'] for row in query['data'] if row['plan_type'] == 'logical_plan')
             for (name, _sql), query in zip(named, result['queries'])}
    assert len(plans) == len(named), 'reader names must be unique'
    return job, plans


def rows(job, name, seen=()):
    if name in MEASURED['rows']:
        return MEASURED['rows'][name]
    step = next((s for s in job['steps'] if s['name'] == name), None)
    if step is None or name in seen:
        raise KeyError(f'{name}: no measured rows; regenerate fixtures/model-relation-rows.json')
    sql = step['components']['sql'] if 'components' in step else step['sql']
    return max((rows(job, dependency, seen + (name,)) for dependency in sql_dependencies(sql)), default=0)


def scans(plan):
    return collections.Counter(SCAN.findall(plan))


def score(job, plan):
    """Extra row-scans, and (scans, rows) per relation scanned more than once."""
    repeated = {name: (count, rows(job, name)) for name, count in scans(plan).items() if count > 1}
    return sum((count - 1) * size for count, size in repeated.values()), repeated


def repeated_regex_joins(plan):
    return {condition: count for condition, count in collections.Counter(JOIN.findall(plan)).items()
            if count > 1 and REGEX.search(condition)}


def offenders(job, plans):
    by_score = {name: score(job, plan) for name, plan in plans.items()}
    return ({name: value for name, value in by_score.items() if value[0] >= THRESHOLD},
            {name: joins for name, plan in plans.items() if (joins := repeated_regex_joins(plan))})


def model_plans(plans):
    return {name: plan for name, plan in plans.items() if name not in PLANTED}


def test_views_are_planned_inside_their_readers(planned):
    job, plans = planned
    views = {s['name'] for s in job['steps'] if not s.get('materialize') and 'components' not in s}
    assert views, 'the submitted job has no views, so this check would pass vacuously'
    # A view named in a TableScan would hide its own scans from the count.
    assert not {name for plan in plans.values() for name in scans(plan)} & views


def test_no_untracked_reader_reruns_work_over_a_large_relation(planned):
    job, plans = planned
    flagged, _regex = offenders(job, model_plans(plans))
    assert {name: value for name, value in flagged.items() if name not in REPEAT_COST_TRACKED} == {}


def test_tracked_repeat_costs_match_their_recorded_scores(planned):
    job, plans = planned
    current = {name: score(job, plans[name])[0] for name in REPEAT_COST_TRACKED}
    assert current == REPEAT_COST_TRACKED, 'a fixed reader leaves the list; a changed one records its new score'
    assert all(value >= THRESHOLD for value in current.values())


def test_regex_joins_run_once_outside_the_tracked_readers(planned):
    job, plans = planned
    _flagged, regex = offenders(job, model_plans(plans))
    assert {name: max(joins.values()) for name, joins in regex.items()} == REGEX_REPEAT_TRACKED, regex


def test_document_witness_keys_no_longer_reruns_its_matches(planned):
    # Before 2d76d689 single_meeting_components and hhrg_slugs ran inside it 8 and 4 times: its plan
    # scanned these 44 times, 103M extra row-scans on the measured rows.
    job, plans = planned
    plan = plans['document_witness_keys']
    assert score(job, plan)[0] < THRESHOLD and not repeated_regex_joins(plan)
    assert not set(scans(plan)) & {'effective_filenames', 'source_annotations', 'document_metadata',
                                   'document_members', 'source_files'}


def test_lint_flags_a_planted_step_that_reads_a_cte_three_times_over_a_large_relation(planned):
    job, plans = planned
    flagged, _regex = offenders(job, plans)
    resolved_links = MEASURED['rows']['resolved_links']
    assert flagged['planted_cte_read_three_times'] == (2 * resolved_links, {'resolved_links': (3, resolved_links)})


def test_lint_flags_a_planted_regex_join_read_twice_over_small_relations(planned):
    job, plans = planned
    flagged, regex = offenders(job, plans)
    assert 'planted_regex_join_read_twice' not in flagged
    assert list(regex['planted_regex_join_read_twice'].values()) == [2]


def test_lint_passes_the_same_three_reads_over_a_small_relation(planned):
    job, plans = planned
    flagged, regex = offenders(job, plans)
    assert score(job, plans['planted_small_cte_read_three_times'])[1] == {
        'witness_precedence': (3, MEASURED['rows']['witness_precedence'])}
    assert 'planted_small_cte_read_three_times' not in flagged and 'planted_small_cte_read_three_times' not in regex
