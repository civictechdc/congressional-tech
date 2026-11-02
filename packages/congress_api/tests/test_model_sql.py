"""Model SQL dependencies come from the files, so hand-built jobs cannot omit one."""
import pytest

from congress_api.lake.model_sql import (ROOT, _file_references, _model_files, check_relations,
    model_steps, sql_dependencies)


def test_named_file_brings_its_model_inputs_first_and_respects_provided_relations():
    steps = model_steps(['good-fetches'], provided=['capture_evidence'])
    assert [step['name'] for step in steps] == ['good_archive_containers', 'good_fetches']
    check_relations([dict(name='capture_evidence')], steps)


def test_missing_model_relation_refuses_before_the_engine_runs():
    with pytest.raises(ValueError, match=r'good_fetches \(good-fetches\.sql\) reads good_archive_containers'):
        check_relations([dict(name='capture_evidence')], model_steps(['good-fetches'],
            provided=['capture_evidence', 'good_archive_containers']))


def test_parser_sees_every_join_form_the_model_uses():
    sql = '''/* FROM ignored_block */ -- FROM ignored_line
        WITH source_files AS (SELECT * FROM source_files)
        SELECT 'FROM ignored_literal' FROM (effective_filenames f JOIN "Page_Facts" p ON true),
        SNIFF_FACTS s LEFT ANTI JOIN body_evidence b USING(body_sha), source_files'''
    assert sql_dependencies(sql) == {'source_files', 'effective_filenames', 'page_facts',
                                     'sniff_facts', 'body_evidence'}


def test_release_lifetimes_use_the_same_parser():
    from viewer_publication import archive_model_lifetimes
    assert archive_model_lifetimes.sql_dependencies is sql_dependencies


def test_every_model_file_loads_after_everything_it_reads():
    files = _model_files(str(ROOT))
    templated = {name for name, path in files.items() if '{{' in path.read_text()}
    steps = model_steps(sorted(files.keys() - templated), provided=templated)
    assert {step['name'] for step in steps} == files.keys() - templated
    defined = set(templated)
    for step in steps:
        reads, _ = _file_references(str(ROOT), step['name'])
        assert reads - {step['name']} <= defined, step['name']
        defined.add(step['name'])
    check_relations([dict(name=name) for name in templated], steps)


def test_inline_sql_the_parser_cannot_read_is_left_to_the_engine():
    check_relations([], [dict(name='lists', sql='SELECT * EXCEPT(record_items) FROM good_fetches')])
