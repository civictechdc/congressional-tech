"""Tests for optional docmeta_v6_1 sidecar validation, SQL aliasing, and release ingestion."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec
from congress_api.retention.provenance import file_pin, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model_job import execute, main, validate_spec
from viewer_publication.docmeta_v6_1 import SQL_FILE


ROOT = Path(__file__).resolve().parents[3]
REAL_DOCMETA_BUNDLE = ROOT / '.cache/archive-release/docmeta-v6-20261116'


def _direct_schema(*, source_col='zero_llm_source'):
    return pa.schema([
        ('link_key', pa.binary(8)),
        ('doc_key', pa.string()),
        ('saved_body', pa.binary(32)),
        ('package_id', pa.string()),
        ('disposition', pa.string()),
        ('v6_route', pa.string()),
        (source_col, pa.string()),
        ('filename', pa.string()),
        ('effective_format', pa.string()),
        ('primary_kind', pa.string()),
        ('status', pa.string()),
        ('congress', pa.int64()),
        ('chamber', pa.string()),
        ('committees', pa.list_(pa.string())),
        ('docmeta_json', pa.string()),
        ('strict_v4_valid', pa.bool_()),
    ])


def _alias_schema(*, nullable_package=False):
    return pa.schema([
        ('link_key', pa.binary(8)),
        ('doc_key', pa.string()),
        ('saved_body', pa.binary(32)),
        ('package_id', pa.null() if nullable_package else pa.string()),
        ('disposition', pa.string()),
        ('sub_disposition', pa.string()),
        ('v6_route', pa.string()),
        ('filename', pa.string()),
        ('effective_format', pa.string()),
        ('canonical_link_key', pa.binary(8)),
        ('canonical_doc_key', pa.string()),
        ('canonical_partition_bucket', pa.string()),
        ('canonical_v6_route', pa.string()),
    ])


def _write_direct_parquet(path, rows, *, source_col='zero_llm_source'):
    table = pa.Table.from_pylist(rows, schema=_direct_schema(source_col=source_col))
    pq.write_table(table, path)
    return dict(path=str(path), **file_pin(path))


def _write_alias_parquet(path, rows, *, nullable_package=False):
    clean_rows = [dict(row, package_id=None) if nullable_package else row for row in rows]
    table = pa.Table.from_pylist(clean_rows, schema=_alias_schema(nullable_package=nullable_package))
    pq.write_table(table, path)
    return dict(path=str(path), **file_pin(path))


def _seed_two_doc_spec(tmp_path):
    """Build a minimal fixture and capture its baseline document identity keys."""
    spec, _digest, _html = real_model_spec(tmp_path)
    base_spec = dict(
        spec,
        output=str(tmp_path / 'baseline-release'),
        scratch=str(tmp_path / 'baseline-model'),
    )
    execute(validate_spec(base_spec, base=tmp_path))
    details = pq.read_table(Path(base_spec['output']) / 'detail.parquet').to_pylist()
    doc_rows = pq.read_table(Path(base_spec['scratch']) / 'evidence/document_rows.parquet').to_pylist()
    assert len(details) == 1 and len(doc_rows) == 1
    doc = dict(details[0], doc_key=doc_rows[0]['document_id'])
    return spec, base_spec, doc


def test_validate_docmeta_spec_rejects_bad_shape_and_missing_required(tmp_path):
    base = tmp_path / 'spec.json'
    spec, _, _ = real_model_spec(tmp_path)
    completed = _write_direct_parquet(tmp_path / 'completed.parquet', [])
    alias = _write_alias_parquet(tmp_path / 'alias.parquet', [])

    with pytest.raises(ValueError, match='unknown fields'):
        validate_spec(
            dict(spec, docmeta_v6_1=dict(completed_no_llm=completed, sha_dup_alias=alias, extra=1)),
            base=base.parent,
        )
    with pytest.raises(ValueError, match='requires: sha_dup_alias'):
        validate_spec(dict(spec, docmeta_v6_1=dict(completed_no_llm=completed)), base=base.parent)


def test_omitting_docmeta_v6_1_leaves_baseline_profile_and_outputs_untouched(tmp_path):
    spec, _, _ = real_model_spec(tmp_path)
    built = execute(validate_spec(spec, base=tmp_path))
    profile = json.loads((Path(built['scratch']) / 'profile.json').read_text())['profile']
    assert 'docmeta_v6_1' not in profile
    assert not (Path(built['scratch']) / 'evidence/docmeta_v6_1.parquet').exists()


def test_docmeta_v6_1_end_to_end_pinning_sql_execution_and_fail_closed_checks(tmp_path, capsys):
    spec, base_spec, doc = _seed_two_doc_spec(tmp_path)
    completed_path = tmp_path / 'completed_no_llm_v6_1.parquet'
    alias_path = tmp_path / 'sha_dup_alias_v6_1.parquet'

    # Case 1: Completed canonical doc + self-consistent pending_llm alias using pa.null() package_id
    # matching the production sha_dup_alias_v6_1.parquet schema.
    completed_pin = _write_direct_parquet(completed_path, [dict(
        link_key=doc['link_key'],
        doc_key=doc['doc_key'],
        saved_body=doc['saved_body'],
        package_id='CHRG-119hhrg12345',
        disposition='upstream_spicydocs_xml',
        v6_route='upstream_spicydocs_synthesized',
        zero_llm_source='spicydocs_govinfo_hearing',
        filename=doc['filename'],
        effective_format='pdf',
        primary_kind='hearing_transcript',
        status='completed',
        congress=119,
        chamber='house',
        committees=['hsag00'],
        docmeta_json='{"status":"completed","text_quality":"native","primary_kind":"hearing_transcript"}',
        strict_v4_valid=True,
    )])
    alias_pin = _write_alias_parquet(alias_path, [], nullable_package=True)

    run_spec = dict(
        spec,
        output=str(tmp_path / 'dm-release'),
        scratch=str(tmp_path / 'dm-model'),
        docmeta_v6_1=dict(
            bundle_version='docmeta-v6_1-20261116',
            completed_no_llm=completed_pin,
            sha_dup_alias=alias_pin,
        ),
    )

    # Custody check: --plan reports pinned docmeta_v6_1, and tampered sha256 fails before runtime.
    spec_file = tmp_path / 'dm-spec.json'
    spec_file.write_text(json.dumps(run_spec))
    assert main(['--spec', str(spec_file), '--plan']) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned['inputs']['docmeta_v6_1']['bundle_version'] == 'docmeta-v6_1-20261116'

    bad_spec = dict(
        run_spec,
        docmeta_v6_1=dict(run_spec['docmeta_v6_1'], completed_no_llm=dict(completed_pin, sha256='0' * 64)),
    )
    with pytest.raises(ValueError, match='Pinned model input changed'):
        execute(validate_spec(bad_spec, base=tmp_path))

    # Execute with pinned docmeta_v6_1 bundle.
    validated = validate_spec(run_spec, base=tmp_path)
    built = execute(validated)
    base_manifest = json.loads((Path(base_spec['output']) / 'manifest.json').read_text())
    assert built['release_id'] == base_manifest['release_id']
    assert built['rows'] == {entry['name']: entry['rows'] for entry in base_manifest['files']}

    profile = json.loads((Path(built['scratch']) / 'profile.json').read_text())['profile']
    assert profile['docmeta_v6_1'] == {
        'bundle_version': 'docmeta-v6_1-20261116',
        'completed_no_llm': {'sha256': completed_pin['sha256'], 'size': completed_pin['size']},
        'sha_dup_alias': {'sha256': alias_pin['sha256'], 'size': alias_pin['size']},
    }

    evidence_rows = pq.read_table(Path(built['scratch']) / 'evidence/docmeta_v6_1.parquet').to_pylist()
    assert len(evidence_rows) == 1
    assert evidence_rows[0]['list_row'] == 0
    assert evidence_rows[0]['link_key'] == doc['link_key']
    assert evidence_rows[0]['doc_key'] == doc['doc_key']
    assert evidence_rows[0]['resolution_state'] == 'direct'
    assert evidence_rows[0]['is_alias'] is False
    assert evidence_rows[0]['committees'] == ['hsag00']
    assert evidence_rows[0]['strict_v4_valid'] is True

    # Fail-closed check: orphan doc_key not in details must fail native invariants before manifest.
    orphan_path = tmp_path / 'orphan_completed.parquet'
    orphan_pin = _write_direct_parquet(orphan_path, [dict(
        link_key=b'\x99' * 8,
        doc_key='missing-doc-key',
        saved_body=b'\x88' * 32,
        package_id=None,
        disposition='upstream_spicydocs_xml',
        v6_route='upstream_spicydocs_synthesized',
        zero_llm_source='spicydocs_govinfo_hearing',
        filename='orphan.pdf',
        effective_format='pdf',
        primary_kind='hearing_transcript',
        status='completed',
        congress=119,
        chamber='house',
        committees=[],
        docmeta_json='{"status":"completed","text_quality":"native"}',
        strict_v4_valid=True,
    )])
    bad_orphan = validate_spec(
        dict(
            spec,
            output=str(tmp_path / 'orphan-release'),
            scratch=str(tmp_path / 'orphan-model'),
            docmeta_v6_1=dict(completed_no_llm=orphan_pin, sha_dup_alias=alias_pin),
        ),
        base=tmp_path,
    )
    with pytest.raises(ValueError, match='Release key invariant failed'):
        execute(bad_orphan)
    assert not (tmp_path / 'orphan-release/manifest.json').exists()


def test_docmeta_v6_1_alias_inheritance_and_llm_results_in_native_datafusion(tmp_path):
    """Verify completed + optional llm_results + sha_dup_alias canonical inheritance & pa.null() union."""
    from viewer_publication.docmeta_v6_1 import docmeta_inputs_and_prelude, docmeta_release_artifacts
    from viewer_publication.archive_format import _settings

    lk_comp = b'\x01' * 8
    lk_llm = b'\x02' * 8
    lk_alias_comp = b'\x03' * 8
    lk_alias_pending = b'\x04' * 8

    sb_comp = b'\x11' * 32
    sb_llm = b'\x22' * 32
    sb_pending = b'\x44' * 32

    completed_pin = _write_direct_parquet(tmp_path / 'completed.parquet', [dict(
        link_key=lk_comp,
        doc_key='doc-comp',
        saved_body=sb_comp,
        package_id='CHRG-118hhrg10001',
        disposition='upstream_spicydocs_xml',
        v6_route='upstream_spicydocs_synthesized',
        zero_llm_source='spicydocs_govinfo_hearing',
        filename='comp.pdf',
        effective_format='pdf',
        primary_kind='hearing_transcript',
        status='completed',
        congress=118,
        chamber='house',
        committees=['hsif00'],
        docmeta_json='{"status":"completed","text_quality":"native"}',
        strict_v4_valid=True,
    )])
    llm_pin = _write_direct_parquet(tmp_path / 'llm_results.parquet', [dict(
        link_key=lk_llm,
        doc_key='doc-llm',
        saved_body=sb_llm,
        package_id='BILLS-118hr42ih',
        disposition='llm_completed',
        v6_route='deterministic_enriched_open_kind',
        docmeta_source='gemma4_e2b_v6_1',
        filename='llm.pdf',
        effective_format='pdf',
        primary_kind='bill_text',
        status='completed',
        congress=118,
        chamber='house',
        committees=[],
        docmeta_json='{"status":"completed","text_quality":"native","primary_kind":"bill_text"}',
        strict_v4_valid=True,
    )], source_col='docmeta_source')
    alias_pin = _write_alias_parquet(tmp_path / 'alias.parquet', [
        dict(
            link_key=lk_alias_comp,
            doc_key='doc-alias-comp',
            saved_body=sb_comp,
            package_id=None,
            disposition='target_sraw_sha_dup',
            sub_disposition='sraw_sha_dup_html',
            v6_route='sha_dup_alias',
            filename='',
            effective_format='html',
            canonical_link_key=lk_comp,
            canonical_doc_key='doc-comp',
            canonical_partition_bucket='completed_no_llm',
            canonical_v6_route='upstream_spicydocs_synthesized',
        ),
        dict(
            link_key=lk_alias_pending,
            doc_key='doc-alias-missing-llm',
            saved_body=sb_pending,
            package_id=None,
            disposition='target_sraw_sha_dup',
            sub_disposition='sraw_sha_dup_html',
            v6_route='sha_dup_alias',
            filename='',
            effective_format='html',
            canonical_link_key=b'\x99' * 8,
            canonical_doc_key='doc-not-in-llm-yet',
            canonical_partition_bucket='llm_queue',
            canonical_v6_route='deterministic_enriched_open_kind',
        ),
    ], nullable_package=True)

    details_table = pa.table([
        pa.array([0, 1, 2, 3], pa.int32()),
        pa.array([lk_comp, lk_llm, lk_alias_comp, lk_alias_pending], pa.binary(8)),
        pa.array(['doc-comp', 'doc-llm', 'doc-alias-comp', 'doc-alias-missing-llm'], pa.string()),
        pa.array([sb_comp, sb_llm, sb_comp, sb_pending], pa.binary(32)),
        pa.array([None, None, None, None], pa.string()),
    ], names=['list_row', 'link_key', 'doc_key', 'saved_body', 'package_id'])
    details_path = tmp_path / 'details.parquet'
    pq.write_table(details_table, details_path)

    dm_inputs, dm_prelude = docmeta_inputs_and_prelude(dict(
        completed_no_llm=completed_pin,
        sha_dup_alias=alias_pin,
        llm_results=llm_pin,
    ))
    dm_steps, dm_extra, dm_diags = docmeta_release_artifacts(
        evidence=tmp_path,
        settings=_settings('whole', ['list_row'], footer_limit=4 << 20),
        root=ROOT,
    )
    inputs = dm_inputs + [dict(name='details', kind='parquet', path=str(details_path))]
    steps = dm_prelude + dm_steps
    out = run_job(
        tmp_path,
        NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=inputs,
        steps=steps,
        outputs=dm_extra,
        queries=[
            *dm_diags,
            dict(name='rows', sql=(ROOT / SQL_FILE).read_text()),
        ],
    )
    assert out['docmeta_v6_1_invariants'] == [dict(
        duplicate_docmeta_link_keys=0,
        duplicate_docmeta_doc_keys=0,
        missing_release_documents=0,
        saved_body_mismatches=0,
        missing_completed_canonical_aliases=0,
        invalid_direct_docmeta_rows=0,
        invalid_inherited_aliases=0,
    )]
    by_doc = {row['doc_key']: row for row in out['rows']}
    assert set(by_doc) == {'doc-comp', 'doc-llm', 'doc-alias-comp', 'doc-alias-missing-llm'}
    assert by_doc['doc-llm']['docmeta_source'] == 'gemma4_e2b_v6_1'
    assert by_doc['doc-alias-comp']['resolution_state'] == 'sha_dup_alias_inherited'
    assert by_doc['doc-alias-comp']['docmeta_json'] == by_doc['doc-comp']['docmeta_json']
    assert by_doc['doc-alias-comp']['package_id'] == 'CHRG-118hhrg10001'
    assert by_doc['doc-alias-comp']['committees'] == ['hsif00']
    assert by_doc['doc-alias-missing-llm']['resolution_state'] == 'sha_dup_alias_pending_llm'
    assert by_doc['doc-alias-missing-llm']['docmeta_json'] is None


def test_real_docmeta_v6_1_bundle_manifest_and_sql_partition_join_when_present(tmp_path):
    """If the local .cache docmeta-v6_1 bundle exists, verify SHA pins + real 64,582+188 SQL join."""
    manifest_path = REAL_DOCMETA_BUNDLE / 'MANIFEST_v6_1.json'
    if not manifest_path.is_file():
        pytest.skip('Local .cache docmeta-v6_1 bundle not present')

    from viewer_publication.docmeta_v6_1 import docmeta_inputs_and_prelude, docmeta_release_artifacts
    from viewer_publication.archive_format import _settings

    manifest = json.loads(manifest_path.read_text())
    files_by_path = manifest['files_by_path']
    comp_rel = 'parquets_v6_1/completed_no_llm_v6_1.parquet'
    alias_rel = 'parquets_v6_1/sha_dup_alias_v6_1.parquet'
    comp_meta = files_by_path[comp_rel]
    alias_meta = files_by_path[alias_rel]
    comp_path = REAL_DOCMETA_BUNDLE / comp_rel
    alias_path = REAL_DOCMETA_BUNDLE / alias_rel

    bundle = dict(
        bundle_version=manifest['bundle_id'],
        completed_no_llm=dict(path=str(comp_path), sha256=comp_meta['sha256'], size=comp_meta['size']),
        sha_dup_alias=dict(path=str(alias_path), sha256=alias_meta['sha256'], size=alias_meta['size']),
    )
    dm_inputs, dm_prelude = docmeta_inputs_and_prelude(bundle)
    dm_steps, _dm_extra, _dm_diags = docmeta_release_artifacts(
        evidence=tmp_path,
        settings=_settings('whole', ['list_row'], footer_limit=4 << 20),
        root=ROOT,
    )
    out = run_job(
        tmp_path,
        NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=dm_inputs,
        steps=dm_prelude + dm_steps,
        outputs=[],
        queries=[
            dict(
                name='counts',
                sql="""SELECT
                    count(*) AS total_rows,
                    count(DISTINCT link_key) AS distinct_links,
                    count(DISTINCT doc_key) AS distinct_docs,
                    count(*) FILTER (WHERE resolution_state='direct') AS direct_rows,
                    count(*) FILTER (WHERE resolution_state='sha_dup_alias_inherited') AS inherited_aliases,
                    count(*) FILTER (WHERE resolution_state='sha_dup_alias_pending_llm') AS pending_llm_aliases,
                    count(*) FILTER (WHERE canonical_partition_bucket='completed_no_llm' AND resolution_state<>'sha_dup_alias_inherited') AS broken_completed_aliases,
                    count(*) FILTER (WHERE resolution_state<>'sha_dup_alias_pending_llm' AND (docmeta_json IS NULL OR strict_v4_valid IS DISTINCT FROM true)) AS invalid_json_or_v4
                FROM docmeta_v6_1_unified""",
            ),
        ],
    )
    assert out['counts'] == [dict(
        total_rows=64582 + 188,
        distinct_links=64582 + 188,
        distinct_docs=64582 + 188,
        direct_rows=64582,
        inherited_aliases=2,
        pending_llm_aliases=186,
        broken_completed_aliases=0,
        invalid_json_or_v4=0,
    )]
