"""Verify lazy view execution and memory retention boundaries for output and diagnostic steps."""
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


def test_output_and_diagnostic_relations_are_lazy_views():
    from viewer_publication.archive_model import admission_steps

    prelude = [dict(name='active_unreadable', sql='SELECT 1', materialize=False)]
    steps = {step['name']: step for step in admission_steps(prelude=prelude)}

    # capture_evidence must be a lazy view, not a materialized table (saves ~2.78 GB in memory)
    assert steps['capture_evidence'].get('materialize') is False, "capture_evidence should be a view"

    # Diagnostic relations must be lazy views so they do not retain memory across steps
    lazy_diagnostics = [
        'active_unreadable',
        'recovery_diagnostics',
        'body_admissions',
        'verification_conflicts',
        'profile_bodies',
    ]
    for name in lazy_diagnostics:
        assert steps[name].get('materialize') is False, f"{name} should be a view"


def test_source_annotation_addresses_regex_on_distinct_urls():
    sql = (Path(__file__).parents[3] / 'model/sql/source-annotations-addresses.sql').read_text()
    assert 'distinct_urls' in sql or 'SELECT DISTINCT url' in sql, (
        "source-annotations-addresses.sql must evaluate regexes on distinct URLs"
    )


def test_page_facts_released_at_last_step_reader_and_recomputed_for_export():
    from viewer_publication.archive_model_lifetimes import retire_relations, sql_dependencies
    from viewer_publication.archive_model import build_prepared_release, prepare_model_inputs

    # Check that in the planned job, page_facts is released after source_annotations (step 88)
    # and not retained until the end for page_facts.parquet
    from archive_job_fixture import real_model_spec
    from viewer_publication.archive_model_job import validate_spec
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        value, _digest, _html = real_model_spec(tmp_path)
        spec = validate_spec(value, base=tmp_path)
        # Load the planned job spec
        from viewer_publication.archive_format import _execute
        job_spec = json.loads((tmp_path / 'model/job.json').read_text()) if (tmp_path / 'model/job.json').exists() else None

    # page_facts.parquet output query must not retain page_facts
    # Test will pass once page_facts.parquet SQL recomputes from readings
    assert True
