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


def test_source_annotation_addresses_regex_on_distinct_urls(tmp_path):
    from congress_api.retention.provenance import json_input, run_job
    from docspec_client.client import NativeDatasets

    sql = (Path(__file__).parents[3] / 'model/sql/source-annotations-addresses.sql').read_text()
    assert 'distinct_urls' in sql or 'SELECT DISTINCT url' in sql, (
        "source-annotations-addresses.sql must evaluate regexes on distinct URLs"
    )
