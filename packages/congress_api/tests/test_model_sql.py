"""Model SQL dependencies come from the files, so hand-built jobs cannot omit one."""
import pytest

from congress_api.lake.model_sql import _model_files, ROOT, check_relations, model_steps, references


def test_named_file_brings_its_model_inputs_first_and_respects_provided_relations():
    steps = model_steps(['good-fetches'], provided=['capture_evidence'])
    assert [step['name'] for step in steps] == ['good_archive_containers', 'good_fetches']
    check_relations([dict(name='capture_evidence')], steps)


def test_missing_model_relation_refuses_before_the_engine_runs():
    with pytest.raises(ValueError, match='good_fetches reads good_archive_containers'):
        check_relations([dict(name='capture_evidence')], model_steps(['good-fetches'],
            provided=['capture_evidence', 'good_archive_containers']))


def test_comments_literals_and_ctes_are_not_references():
    sql = """-- FROM good_fetches
        WITH good_fetches AS (SELECT 'FROM page_facts' AS x) SELECT * FROM good_fetches"""
    assert references(sql) == set()


def test_every_model_file_resolves_without_a_cycle():
    names = sorted(_model_files(str(ROOT)))
    assert {step['name'] for step in model_steps(names)} == set(names)
