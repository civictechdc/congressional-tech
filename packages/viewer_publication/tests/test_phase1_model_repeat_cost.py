"""No model reader re-runs work over a large relation, judged from its native plan.

The pinned DataFusion plans every CTE and view reference as its own subtree and ignores
AS MATERIALIZED (AGENTS.md: a CTE runs once per reference), so a CTE read twice inside a
CTE that is itself read twice runs four times. Each run is one `TableScan` in the reader's
optimized logical plan, so counting scans counts the work, nesting and views included.

The job is the one the build submits (every step, export and query), planned over zero-row
inputs with the lake's schemas: nothing corpus-sized runs, and the lint sees plan shape,
not memory or time. A reader's score is the sum, over relations its plan scans more than
once, of (scans - 1) x rows, the extra row-scans the materialization audit ranked by
(.cache/archive-release/investigations/model-step-materialization-audit-20261104.md, M40).
Rows are not in an empty plan: they come from fixtures/model-relation-rows.json, measured
from one nightly-shaped build (scripts/measure/model_relation_rows.py regenerates it). A
step missing from it is estimated at its largest input's rows.

The same plans show which input each outer join builds on: the engine builds on the left
(AGENTS.md), so a LEFT or FULL join whose left input is large holds that preserved relation in
the hash table. That lint reads the logical plan, so it sees neither a statistics-driven swap
over a raw table in the physical plan, nor column width, nor memory.

The same plans show which statements read a lake table itself. Every statement that names one
reads it again from the object store: 31 statements scanned `captures` 42 times, about 10 s
each, in a 867 s build. The job therefore reads the lake `captures` in one statement, its first
step, and every other reader scans that retained step. That check names the lake input by the
stand-in table it is bound to, so it sees the scans whatever the job calls the input; it sees
neither the admission job nor any other job that binds `captures` itself.

The same EXPLAIN also builds each reader's physical plan, where the engine can refuse a plan the
logical planner accepted. It reports that refusal as a `physical_plan_error` row and does not
fail, so only a check of that row sees one. A refusal can depend on the input being a lake table:
`coalesce(f.valid,false)` in saved_name_conflicts carried the column's Iceberg field id into a
reused expression and was refused only where filename readings came from the lake (f8541b6d,
ct-h8dr), found by a 20-minute lane. So every input the release reads from the lake is bound here
to an empty table in a throwaway local catalog, created and pinned through the engine as
production creates one; a Parquet stand-in cannot carry field ids into a plan, because the pinned
engine strips field metadata from a Parquet input (engine ticket def-9ise). A refused step is
run before any EXPLAIN, so it stops the job and every test errors with the engine's message,
which names no statement. That check sees planning only: no refusal that needs rows,
statistics or memory, and no statement outside the job the build submits.
"""
import collections
import json
import os
import re
from pathlib import Path

import pytest

from archive_job_fixture import _Capture, _Submitted, spicy_input, versions
from congress_api.lake import appearance_records, committee_records, meeting_records, tables, video_records
from congress_api.retention.provenance import parquet_output, run_job
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
    'model_invariants': 50_877_106,             # merged join x5 (M13), plus independent final bill-identity check
    'merged_recovery_fields': 43_005_605,       # query; the merged 7-way join x5 (M13)
    'bills_export': 33_468_701,                 # spicy_congress_bills x30, ordered x27 (M17)
    'component_meeting_links': 32_189_482,      # effective_filenames x4, source_annotations x6 (M17)
    'retired_links_export': 31_775_718,         # the links view: ordered x29, prior_links x21 (M16)
    'profile_completeness': 23_295_486,         # query; readings through the current selected_readings (M28)
    'model_url_keys': 18_289_579,               # url_normalized x11 through mappings (M17)
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
# The window repair did not change those scores. Later, aggregating required-column counts
# once per export took relationship_invariants below the threshold. The independent final
# bill-identity check adds one decision, document identity and ordered scan to model_invariants;
# the decision count uses the largest-input fallback. These are estimated row-scan scores,
# never measured time or RSS.
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

#: Estimated rows at which the preserved input of an outer join may no longer be its build side.
OUTER_BUILD_ROWS = 100_000
# Readers with LEFT (or FULL) joins whose left input is estimated at OUTER_BUILD_ROWS or more, with
# how many such joins each has. The engine builds every hash join on its left input (AGENTS.md), so
# these hold the large preserved relation in the hash table and then emit its unmatched rows as one
# batch; base_normalized exhausted the query pool that way (ct-n5ec). Fix one by writing
# `small RIGHT JOIN large` and delete its entry. A reader that is not listed may have none.
# Each note gives the largest estimated build, the relation that sets it and that build's widest
# column count: hints for ranking from an empty plan, never measured memory.
OUTER_BUILD_TRACKED = {
    'recovery_candidates': 3,                  # 4.1M rows by captures, 16 cols
    'meeting_detail_evidence': 2,              # 4.1M rows by congress_gov_routes (unmeasured: its largest input), 16 cols
    'meeting_detail_observations': 3,          # 4.1M rows by meeting_detail_evidence (unmeasured: its largest input), 15 cols
    'url_state_lines': 2,                      # 4.1M rows by captures, 11 cols
    'entity_profile_completeness': 3,          # query; 4.1M rows by captures, 5 cols
    'recording_tracks': 1,                     # 2.8M rows by recording_track_candidates, 11 cols
    'source_addresses': 1,                     # 2.1M rows by source_files, 3 cols
    'source_annotations': 1,                   # 2.1M rows by source_files, 2 cols
    'document_identities': 2,                  # 2.1M rows by document_members, 4 cols
    'document_metadata': 1,                    # 2.1M rows by document_members, 10 cols
    'component_meeting_links': 4,              # 2.0M rows by document_metadata, 5 cols
    'review_overrides': 3,                     # 1.8M rows by document_identities, 5 cols
    'model_url_keys': 1,                       # 1.7M rows by url_inputs, 1 cols
    'page_dates': 1,                           # 1.4M rows by page_metadata_values (unmeasured: its largest input), 5 cols
    'document_page_metadata': 7,               # 1.4M rows by html_metadata_readings (unmeasured: its largest input), 19 cols
    'source_filename_readings': 1,             # 1.4M rows by filename_readings, 27 cols
    'source_url_keys': 1,                      # 1.3M rows by source_url_inputs, 1 cols
    'document_packages': 2,                    # 569K rows by saved_files, 3 cols
    'retired_links_export': 12,                # 440K rows by prior_links, 6 cols
    'bills_export': 7,                         # 422K rows by spicy_congress_bills, 19 cols
    'meetings_export': 9,                      # 374K rows by ordered, 31 cols
    'page_descriptions': 4,                    # 356K rows by base_normalized, 8 cols
    'document_page_metadata_entries': 5,       # 356K rows by page_metadata_documents (unmeasured: its largest input), 15 cols
    'source_members.parquet': 1,               # export; 356K rows by ordered, 6 cols
    'model_invariants': 2,                     # query; 356K rows by ordered, 2 cols
    'blank_filename_reasons': 1,               # query; 356K rows by ordered, 2 cols
    'source_annotation_pages': 2,              # 313K rows by page_facts, 5 cols
    'document_witness_keys': 2,                # 205K rows by document_witness_raw_matches, 3 cols
    'witness_key_map': 1,                      # 177K rows by witness_key_priors (unmeasured: its largest input), 3 cols
    'relationship_invariants': 1,              # query; 177K rows by witness_key_map_export (unmeasured: its largest input), 2 cols
    'witness_key_current': 1,                  # 173K rows by appearance_records_resolved, 15 cols
    'document_witness_url_matches': 1,         # 173K rows by appearance_records_resolved, 4 cols
    'document_witness_meeting_witnesses': 1,   # 173K rows by appearance_records_resolved, 5 cols
    'witnesses_export': 1,                     # 173K rows by appearance_records_resolved, 20 cols
    'coverage': 3,                             # query; 173K rows by witnesses_export, 7 cols
}

# New offenders the lint must catch, and ones it must let through.
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
    'planted_left_join_built_on_large_relation': """SELECT l.page_body,w.superseded_by
        FROM resolved_links l LEFT JOIN witness_precedence w ON l.target_url=w.witness_key""",
    'planted_right_join_built_on_small_relation': """SELECT l.page_body,w.superseded_by
        FROM witness_precedence w RIGHT JOIN resolved_links l ON l.target_url=w.witness_key""",
}

# A second direct read of the lake table. Its SQL names the job's own input, so the fixture builds it.
PLANTED_LAKE_READ = 'planted_second_read_of_the_lake_captures'

# A lake-only refusal: saved_name_conflicts as it was before f8541b6d. Explained, never run as a step.
PLANTED_LAKE_REFUSAL = 'planted_saved_name_conflicts_before_f8541b6d'


def lake_refusal_sql():
    sql = (Path(__file__).parents[3]/'model/sql/saved-name-conflicts.sql').read_text()
    spelling = 'f.valid IS NOT DISTINCT FROM true'
    assert sql.count(spelling) == 1, 'saved_name_conflicts no longer reads the flag this way; plant another refusal'
    return sql.replace(spelling, 'coalesce(f.valid,false)')


SCAN = re.compile(r'^\s*TableScan: (\S+)', re.M)
JOIN = re.compile(r'^\s*\w+ Join: (.*)$', re.M)
REGEX = re.compile(r'regexp_|\s!?~\*?\s|SIMILAR TO', re.I)
# A plan node line; a line of any other shape continues the expression above it.
NODE = re.compile(r'^( *)([A-Z]\w*(?: Join)?)(?:: (\S*).*)?$')


#: The tables the release job reads from the lake (model/jobs/publish-model.json), each bound here to an empty one.
LAKE_TABLES = ('captures', 'readings', 'filename_readings', 'meeting_records', 'appearance_records',
               'video_records', 'committee_records')


def submitted_job(root, engine):
    """The release job over empty lake tables: entities and Explorer tables included.

    One throwaway catalog under `root`; each table created and pinned through the engine as production
    creates one (archive_selective), so its schema and Iceberg field ids are the lake's."""
    refs = {name: dict(namespace=['archive'], name=name) for name in LAKE_TABLES}
    for i, (name, ref) in enumerate(refs.items()):
        tables.create_table(engine=engine, work=root/f'create-{name}', catalog_root=root/'catalog', table=ref,
            schema=tables.load_schema(name), location=root/f'lake-{name}', create_namespace=not i)
    pins = tables.resolve_tables(engine=engine, work=root/'resolve', catalog_root=root/'catalog', tables=refs)
    parsers, catalog_version = versions()
    decisions = root/'recording-decisions.jsonl'; decisions.write_text('')
    parsers.update(meeting_records=meeting_records.current_versions(), appearance_records=appearance_records.current_versions(),
                   video_records={'youtube_cache': 'pv', 'youtube_api': 'pa'}, committee_records={'house_xml': 'pc'})
    prepared = prepare_model_inputs(**{name: dict(pin, kind='native_table') for name, pin in pins.items()},
        parser_versions=parsers, catalog_version=catalog_version,
        engine=engine, scratch=root/'prepared', spicy_regs=spicy_input(), include_entities=True,
        recording_decision_files=[dict(key='provenance/recording_decisions/empty.jsonl', path=str(decisions))])
    with pytest.raises(_Submitted):
        build_prepared_release(prepared, engine=_Capture(engine, root/'submitted-job.json'), output=root/'release')
    return json.loads((root/'submitted-job.json').read_text())


def lake_input(job, table):
    """The job input bound to a lake table's stand-in, under whatever name the job gives it."""
    [name] = [item['name'] for item in job['inputs']
              if Path(item.get('metadata_location', '')).parent.parent.name == f'lake-{table}']
    return name


def lake_readers(job, plans, table):
    """Scans of a lake table itself, per statement that has any."""
    name = lake_input(job, table)
    return {reader: count for reader, plan in plans.items() if (count := scans(plan)[name])}


def readers(job):
    """Everything that executes: materialized and components steps, exports and queries. Views run inside them."""
    for step in job['steps']:
        if 'components' in step:
            yield step['name'], step['components']['sql']
        elif step.get('materialize'):
            yield step['name'], step['sql']
    for item in job['outputs'] + job['queries']:
        yield item['name'], item['sql']


def explain(engine, root, job, statements):
    """Each statement's EXPLAIN rows by plan type, after the job's steps run over its inputs."""
    data = run_job(root, engine, inputs=job['inputs'], steps=job['steps'], outputs=[],
                   queries=[dict(name=f'reader_{i}', sql='EXPLAIN '+sql) for i, (_name, sql) in enumerate(statements)])
    return {name: {row['plan_type']: row['plan'] for row in data[f'reader_{i}']}
            for i, (name, _sql) in enumerate(statements)}


def parquet_stand_ins(engine, root, job):
    """The job with each lake stand-in bound instead to an empty Parquet file of its schema, written by the engine."""
    lake = {lake_input(job, table): table for table in LAKE_TABLES}
    run_job(root, engine, inputs=[item for item in job['inputs'] if item['name'] in lake], steps=[],
            outputs=[parquet_output(root, name, 'SELECT * FROM ' + name, tables.TABLE_SPECS[table]['primary_key'])
                     for name, table in lake.items()])
    return dict(job, inputs=[dict(name=item['name'], kind='parquet', path=str(root/(item['name']+'.parquet')))
                             if item['name'] in lake else item for item in job['inputs']])


@pytest.fixture(scope='module')
def explained(tmp_path_factory):
    """EXPLAIN rows of every reader and the planted lake-only refusal; and the refusal's rows on Parquet stand-ins."""
    root = tmp_path_factory.mktemp('repeat-cost')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        job = submitted_job(root, engine)
        steps = [{k: v for k, v in step.items() if k != 'release_after'} for step in job['steps']]
        steps += [dict(name=name, sql=sql, materialize=True) for name, sql in PLANTED.items()]
        steps += [dict(name=PLANTED_LAKE_READ, sql='SELECT receipt_key FROM ' + lake_input(job, 'captures'), materialize=True)]
        job = dict(job, steps=steps)
        named = [*readers(job), (PLANTED_LAKE_REFUSAL, lake_refusal_sql())]
        explains = explain(engine, root/'explain', job, named)
        parquet = parquet_stand_ins(engine, root/'parquet-stand-ins', job)
        on_parquet = explain(engine, root/'explain-on-parquet', parquet, named[-1:])
    assert len(explains) == len(named), 'reader names must be unique'
    return job, explains, on_parquet[PLANTED_LAKE_REFUSAL]


@pytest.fixture(scope='module')
def planned(explained):
    job, explains, _on_parquet = explained
    return job, {name: rows['logical_plan'] for name, rows in explains.items()}


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


def tree(plan):
    """The logical plan as nested (kind, first word, inputs) nodes, by indentation."""
    root = ('', '', [])
    open_nodes = [(-1, root)]
    for line in plan.splitlines():
        if match := NODE.match(line):
            node = (match[2], match[3] or '', [])
            while open_nodes[-1][0] >= len(match[1]):
                open_nodes.pop()
            open_nodes[-1][1][2].append(node)
            open_nodes.append((len(match[1]), node))
    return root


def estimated_rows(job, node):
    """A plan node's rows, estimated: a scan's measured rows, the smaller input of an inner join, the
    preserved input of an outer, semi or anti join, the sum of a union, otherwise the largest input."""
    kind, name, inputs = node
    if kind == 'TableScan':
        return rows(job, name)
    sizes = [estimated_rows(job, child) for child in inputs] or [0]
    if kind == 'Inner Join':
        return min(sizes)
    if kind.endswith(' Join') and kind.startswith(('Left', 'Right')):
        return sizes[0 if kind.startswith('Left') else -1]
    return sum(sizes) if kind == 'Union' else max(sizes)


def large_outer_builds(job, plan):
    """Estimated build rows of each Left or Full join whose left input reaches OUTER_BUILD_ROWS."""
    found, pending = [], [tree(plan)]
    while pending:
        kind, _name, inputs = pending.pop()
        pending += inputs
        if kind in ('Left Join', 'Full Join') and (size := estimated_rows(job, inputs[0])) >= OUTER_BUILD_ROWS:
            found.append(size)
    return found


def model_plans(plans):
    return {name: plan for name, plan in plans.items()
            if name not in PLANTED and name not in (PLANTED_LAKE_READ, PLANTED_LAKE_REFUSAL)}


def refused(explains):
    """Statements whose physical plan the engine refused, with its reason."""
    return {name: rows['physical_plan_error'] for name, rows in explains.items() if 'physical_plan_error' in rows}


def test_every_reader_builds_its_physical_plan_on_lake_backed_inputs(explained):
    _job, explains, _on_parquet = explained
    readers = model_plans(explains)
    assert refused(readers) == {}
    assert all('physical_plan' in rows for rows in readers.values())


def test_the_pass_refuses_the_spelling_that_failed_26_lane_tests_which_parquet_stand_ins_plan(explained):
    # f8541b6d (ct-h8dr): refused only where filename readings came from the lake. The pinned engine
    # strips field metadata from a Parquet input (engine ticket def-9ise), so Parquet stand-ins plan it.
    # Once the engine keeps that metadata, the last assertion fails: revisit this half then.
    _job, explains, on_parquet = explained
    assert set(refused(explains)) == {PLANTED_LAKE_REFUSAL}
    reason = refused(explains)[PLANTED_LAKE_REFUSAL]
    assert 'field metadata' in reason and '"PARQUET:field_id"' in reason, reason
    assert 'physical_plan' in on_parquet and 'physical_plan_error' not in on_parquet, on_parquet


def test_the_lake_captures_table_is_read_by_one_statement_the_first_retained_step(planned):
    job, plans = planned
    assert lake_readers(job, model_plans(plans), 'captures') == {'captures': 1}
    # The whole table, as it is: a first step that filtered or projected it would change what every reader sees.
    assert job['steps'][0] == dict(name='captures', sql='SELECT * FROM ' + lake_input(job, 'captures'), materialize=True)


def test_lint_flags_a_planted_second_read_of_the_lake_captures_table(planned):
    job, plans = planned
    assert lake_readers(job, plans, 'captures') == {'captures': 1, PLANTED_LAKE_READ: 1}


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


def test_only_tracked_readers_build_an_outer_join_on_a_large_preserved_relation(planned):
    job, plans = planned
    current = {name: len(builds) for name, plan in model_plans(plans).items() if (builds := large_outer_builds(job, plan))}
    assert current == OUTER_BUILD_TRACKED, 'a fixed reader leaves the list; a new one names its small relation first'


def test_lint_flags_a_planted_left_join_built_on_a_large_relation_and_passes_its_right_join(planned):
    job, plans = planned
    assert large_outer_builds(job, plans['planted_left_join_built_on_large_relation']) == [MEASURED['rows']['resolved_links']]
    assert large_outer_builds(job, plans['planted_right_join_built_on_small_relation']) == []

