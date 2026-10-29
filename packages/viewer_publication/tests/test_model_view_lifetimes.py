"""Verify memory retention boundaries, lifetime releases, and narrow projections."""
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


def test_diagnostic_relations_materialized_to_release_upstream():
    from viewer_publication.archive_reviews import _steps as review_steps
    from viewer_publication.archive_provenance import _steps as provenance_steps
    from viewer_publication.archive_model import ROOT

    r_steps = {s['name']: s for s in review_steps(['document-link-key-conflicts'], ROOT)}
    assert r_steps['document_link_key_conflicts'].get('materialize') is True, (
        "document_link_key_conflicts must be materialized so initial_document_link_keys can release"
    )

    p_steps = {s['name']: s for s in provenance_steps(['recovery-diagnostics', 'recovery-attachment-diagnostics'], ROOT)}
    assert p_steps['recovery_diagnostics'].get('materialize') is True, (
        "recovery_diagnostics must be materialized so recovery_candidates can release"
    )
    assert p_steps['recovery_attachment_diagnostics'].get('materialize') is True, (
        "recovery_attachment_diagnostics must be materialized so model_recovery_rows can release"
    )


def test_source_annotation_addresses_single_union_no_hash_join():
    sql = (Path(__file__).parents[3] / 'model/sql/source-annotations-addresses.sql').read_text()
    assert 'JOIN' not in sql, (
        "source-annotations-addresses.sql must avoid CTE self-joins to prevent duplicate 5.8 GB inlined aggregates"
    )
    assert sql.count('UNION SELECT') == 2, (
        "source-annotations-addresses.sql must use a single 3-way UNION"
    )
    assert 'capture_source_contexts' in sql, (
        "source-annotations-addresses.sql must read narrow capture_source_contexts"
    )


def test_page_facts_excludes_links_and_recomputes_for_export():
    sql = (Path(__file__).parents[3] / 'model/sql/page-facts.sql').read_text()
    assert 'EXCLUDE(links)' in sql, "page-facts.sql must exclude links column"

    link_sql = (Path(__file__).parents[3] / 'model/sql/link-inputs.sql').read_text()
    assert 'FROM readings r' in link_sql, "link-inputs.sql must read links directly from readings"


def test_capture_source_contexts_is_strictly_narrow():
    from viewer_publication.archive_model import source_steps
    steps = {step['name']: step for step in source_steps()}
    assert 'capture_source_contexts' in steps, "capture_source_contexts must be present in source_steps"
    assert steps['capture_source_contexts']['materialize'] is True

    sql = (Path(__file__).parents[3] / 'model/sql/capture-source-contexts.sql').read_text()
    for omitted in ['receipt_key', 'requested_url', 'filename', 'source_url', 'fidelity', 'media_type']:
        assert omitted not in sql, f"capture-source-contexts.sql must not project heavy column {omitted}"
    for required in ['source_id', 'context_url', 'member_path', 'outcome', 'body_sha']:
        assert required in sql, f"capture-source-contexts.sql must project required column {required}"


def test_dead_tables_released_early(tmp_path):
    from archive_job_fixture import real_model_spec
    from viewer_publication.archive_model_job import execute, validate_spec
    value, _digest, _html = real_model_spec(tmp_path)
    result = execute(validate_spec(value, base=tmp_path))
    assert result['status'] == 'built'
    job = json.loads((tmp_path / 'model/job.json').read_text())

    # Check release_after for dead tables
    releases = {}
    for st in job['steps']:
        for rel in st.get('release_after', []):
            releases[rel] = st['name']

    assert releases.get('capture_sources') == 'source_files', "capture_sources must be released by source_files"
    assert releases.get('initial_document_link_keys') == 'duplicate_component_edges', (
        "initial_document_link_keys must be released by duplicate_component_edges"
    )
    assert releases.get('recovery_candidates') == 'recovery_diagnostics', (
        "recovery_candidates must be released by recovery_diagnostics"
    )
    assert releases.get('model_recovery_rows') == 'recovery_attachment_diagnostics', (
        "model_recovery_rows must be released by recovery_attachment_diagnostics"
    )
