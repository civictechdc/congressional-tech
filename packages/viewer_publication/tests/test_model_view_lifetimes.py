"""Verify lazy view execution and memory retention boundaries for output and diagnostic steps."""
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


def test_output_and_diagnostic_relations_are_lazy_views():
    from viewer_publication.archive_model import admission_steps, grouping_steps

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
    assert 'capture_source_contexts' in sql, "source-annotations-addresses.sql must read narrow capture_source_contexts"


def test_page_facts_excludes_links_and_recomputes_for_export():
    sql = (Path(__file__).parents[3] / 'model/sql/page-facts.sql').read_text()
    assert 'EXCLUDE(links)' in sql, "page-facts.sql must exclude links column"

    link_sql = (Path(__file__).parents[3] / 'model/sql/link-inputs.sql').read_text()
    assert 'FROM readings r' in link_sql, "link-inputs.sql must read links directly from readings"


def test_capture_source_contexts_is_narrow():
    from viewer_publication.archive_model import source_steps
    steps = {step['name']: step for step in source_steps()}
    assert 'capture_source_contexts' in steps, "capture_source_contexts must be present in source_steps"
    assert steps['capture_source_contexts']['materialize'] is True


def test_capture_sources_released_after_source_files(tmp_path):
    from archive_job_fixture import real_model_spec
    from viewer_publication.archive_model_job import execute, validate_spec
    value, _digest, _html = real_model_spec(tmp_path)
    result = execute(validate_spec(value, base=tmp_path))
    assert result['status'] == 'built'
    job = json.loads((tmp_path / 'model/job.json').read_text())
    releasers = [st['name'] for st in job['steps'] if 'capture_sources' in st.get('release_after', [])]
    assert releasers == ['source_files'], f"capture_sources must be released by source_files, got {releasers}"
