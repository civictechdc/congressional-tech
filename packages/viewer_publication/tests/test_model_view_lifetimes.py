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

    # Single-reader grouping steps must be lazy views
    g_steps = {step['name']: step for step in grouping_steps()}
    for name in ['fingerprint_candidates', 'edition_bodies', 'rendition_members', 'valid_rendition_members']:
        assert g_steps[name].get('materialize') is False, f"{name} should be a view"


def test_source_annotation_addresses_regex_on_distinct_urls():
    sql = (Path(__file__).parents[3] / 'model/sql/source-annotations-addresses.sql').read_text()
    assert 'distinct_urls' in sql or 'SELECT DISTINCT url' in sql, (
        "source-annotations-addresses.sql must evaluate regexes on distinct URLs"
    )


def test_page_facts_excludes_links_and_recomputes_for_export():
    sql = (Path(__file__).parents[3] / 'model/sql/page-facts.sql').read_text()
    assert 'EXCLUDE(links)' in sql, "page-facts.sql must exclude links column"

    link_sql = (Path(__file__).parents[3] / 'model/sql/link-inputs.sql').read_text()
    assert 'FROM readings r' in link_sql, "link-inputs.sql must read links directly from readings"
