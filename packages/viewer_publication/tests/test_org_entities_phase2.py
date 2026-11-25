"""Unit tests for Phase 2 RefSpec federal agency resolution (ct-w34j)."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from congress_api.retention import provenance
from viewer_publication import archive_model_job, archive_publish_job, refspec_inputs
from viewer_publication.archive_model import build_org_entities

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _write_appearances(path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    schema = pa.schema([
        ('witness_key', pa.string()),
        ('name', pa.string()),
        ('name_key', pa.string()),
        ('role', pa.string()),
        ('organization', pa.string()),
        ('on_behalf_of', pa.string()),
        ('title', pa.string()),
        ('witness_type', pa.string()),
        ('party', pa.string()),
        ('source', pa.string()),
        ('event_id', pa.int64()),
        ('hearing_id', pa.string()),
        ('meeting_key', pa.string()),
        ('event_date', pa.string()),
        ('chamber', pa.string()),
        ('committee', pa.string()),
        ('committee_code', pa.string()),
        ('committee_names', pa.list_(pa.string())),
        ('document_urls', pa.list_(pa.string())),
        ('page_url', pa.string()),
        ('record_sha_hex', pa.string()),
        ('source_url', pa.string()),
        ('parser_version', pa.string()),
        ('capture_observed_at', pa.string()),
    ])
    full_rows = []
    for idx, row in enumerate(rows):
        full_rows.append({
            'witness_key': row['witness_key'],
            'name': row.get('name', f'Witness {idx}'),
            'name_key': row.get('name_key', f'witness {idx}'),
            'role': None,
            'organization': row.get('organization'),
            'on_behalf_of': row.get('on_behalf_of'),
            'title': row.get('title'),
            'witness_type': row.get('witness_type'),
            'party': None,
            'source': row.get('source', 'house_xml'),
            'event_id': row.get('event_id', 1000 + idx),
            'hearing_id': None,
            'meeting_key': None,
            'event_date': '2026-10-01',
            'chamber': 'House',
            'committee': None,
            'committee_code': None,
            'committee_names': [],
            'document_urls': [],
            'page_url': None,
            'record_sha_hex': f'{idx:064x}',
            'source_url': 'https://example.invalid/w',
            'parser_version': 'v1',
            'capture_observed_at': '2026-10-01T00:00:00Z',
        })
    pq.write_table(pa.Table.from_pylist(full_rows, schema=schema), path)
    return path


def test_refspec_pin_verification_and_tamper_refusal(tmp_path: pathlib.Path):
    """AC #1: checked-in RefSpec 1.3 tables verify cleanly; mismatched bytes/sha256/size refuse."""
    tables = refspec_inputs.fetch_pinned()
    assert pq.read_metadata(tables['organizations']).num_rows == 472
    assert pq.read_metadata(tables['aliases']).num_rows == 63
    assert pq.read_metadata(tables['current_successors']).num_rows == 15

    # Checked-in job specs validate end-to-end with RefSpec pin.
    jobs_dir = ROOT / 'model' / 'jobs'
    assert archive_model_job.load_spec(jobs_dir / 'publish-model.json')['refspec']['path'].endswith('refspec.json')
    assert archive_publish_job.load_spec(jobs_dir / 'publish.json')

    # Tampering 1 byte in a vendored RefSpec parquet table or view-manifest refuses.
    copy_dir = tmp_path / 'refspec'
    shutil.copytree(ROOT / 'model' / 'jobs' / 'refspec', copy_dir)
    manifest_copy = copy_dir / 'refspec.json'
    assert refspec_inputs.fetch_pinned(manifest_copy)

    # Wrong manifest digest refuses.
    with pytest.raises(ValueError, match='sha256 mismatch'):
        refspec_inputs.fetch_pinned(manifest_copy, expected_sha256='0' * 64)

    # Corrupted parquet file refuses.
    org_pq = copy_dir / 'agency-registry-view' / 'tables' / 'agency-registry-organizations.parquet'
    orig_org_bytes = org_pq.read_bytes()
    data = bytearray(orig_org_bytes)
    data[0] ^= 0xFF
    org_pq.write_bytes(bytes(data))
    with pytest.raises(ValueError, match='mismatch'):
        refspec_inputs.fetch_pinned(manifest_copy)
    org_pq.write_bytes(orig_org_bytes)

    # Corrupted view-manifest.json refuses.
    vm_path = copy_dir / 'agency-registry-view' / 'view-manifest.json'
    orig_vm_bytes = vm_path.read_bytes()
    vm_data = bytearray(orig_vm_bytes)
    vm_data[10] ^= 0x01
    vm_path.write_bytes(bytes(vm_data))
    with pytest.raises(ValueError, match='view-manifest'):
        refspec_inputs.fetch_pinned(manifest_copy)
    vm_path.write_bytes(orig_vm_bytes)

    # Table row-count mismatch refuses even if sha256/size in refspec.json match the altered file.
    succ_pq = copy_dir / 'agency-registry-view' / 'tables' / 'agency-registry-current-successors.parquet'
    succ_tbl = pq.read_table(succ_pq).slice(0, 14)
    pq.write_table(succ_tbl, succ_pq)
    altered_bytes = succ_pq.read_bytes()
    m_obj = json.loads(manifest_copy.read_text())
    m_obj['tables']['current_successors']['sha256'] = hashlib.sha256(altered_bytes).hexdigest()
    m_obj['tables']['current_successors']['size'] = len(altered_bytes)
    # Keep rows: 15 to verify row-count pin enforcement.
    manifest_copy.write_text(json.dumps(m_obj, indent=2) + '\n')
    with pytest.raises(ValueError, match='row count mismatch'):
        refspec_inputs.fetch_pinned(manifest_copy)


def test_archive_model_job_profile_and_selective_refspec_wiring(tmp_path: pathlib.Path):
    """AC #1 job integration: archive_model_job check_inputs/model_arguments,
    prepare_model_inputs profile['refspec'], and archive_selective refspec forwarding."""
    from types import SimpleNamespace
    from archive_job_fixture import model_spec as make_model_spec, real_model_spec, spicy_input
    from congress_api.lake.filenames import current_version as catalog_version
    from congress_api.lake.daily import ALL_TABLE_NAMES
    from congress_api.retention.provenance import file_pin
    from viewer_publication import archive_selective
    from viewer_publication.archive_model import prepare_model_inputs

    # 1. archive_model_job check_inputs + model_arguments happy path & tamper refusal
    ref_copy = tmp_path / 'refspec_copy'
    shutil.copytree(ROOT / 'model' / 'jobs' / 'refspec', ref_copy)
    manifest_path = ref_copy / 'refspec.json'

    spec_val = make_model_spec(tmp_path / 'job1')
    for tbl_name in ('captures', 'readings', 'filename_readings'):
        p = pathlib.Path(spec_val[tbl_name]['path'])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(tbl_name.encode())
        spec_val[tbl_name] = dict(kind='parquet', path=str(p), **file_pin(p))
    spec_val['refspec'] = dict(path=str(manifest_path), **file_pin(manifest_path))

    spec_file = tmp_path / 'job1_spec.json'
    spec_file.write_text(json.dumps(spec_val))
    loaded = archive_model_job.load_spec(spec_file)
    checked = archive_model_job.check_inputs(loaded)
    with archive_model_job.model_arguments(loaded, verified_files=checked) as args:
        assert 'refspec' in args
        assert {'organizations', 'aliases', 'current_successors'} <= set(args['refspec']['tables'])
        assert args['refspec']['pin']['release_key'] == 'agency-registry-2026-09-26'

    # Tampered RefSpec table is refused by check_inputs and model_arguments.
    bad_tbl = ref_copy / 'agency-registry-view' / 'tables' / 'agency-registry-aliases.parquet'
    orig_aliases = bad_tbl.read_bytes()
    bad_tbl.write_bytes(b'corrupted-aliases')
    with pytest.raises(ValueError, match='Pinned model input changed'):
        archive_model_job.check_inputs(loaded)
    with pytest.raises(ValueError, match='mismatch|Pinned model input changed'):
        with archive_model_job.model_arguments(loaded):
            pass
    bad_tbl.write_bytes(orig_aliases)

    # 2. prepare_model_inputs(..., refspec=...) records profile['refspec']
    prep_dir = tmp_path / 'prep'
    prep_dir.mkdir()
    real_spec, _digest, _html = real_model_spec(prep_dir, entities=True)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        prepared = prepare_model_inputs(
            captures=real_spec['captures']['path'],
            readings=real_spec['readings']['path'],
            filename_readings=real_spec['filename_readings']['path'],
            parser_versions=real_spec['parser_versions'],
            catalog_version=real_spec['catalog_version'],
            meeting_records=real_spec['meeting_records']['path'],
            appearance_records=real_spec['appearance_records']['path'],
            spicy_regs=spicy_input(),
            include_entities=True,
            include_org_entities=True,
            refspec=manifest_path,
            engine=engine,
            scratch=tmp_path / 'prep_scratch',
        )
        ref_prof = prepared['profile']['profile'].get('refspec')
        assert ref_prof is not None
        assert ref_prof['schema_version'] == '1.3'
        assert ref_prof['release_key'] == 'agency-registry-2026-09-26'
        assert ref_prof['view_manifest_sha256'] == '7a806ea060c0c7a0ee37a991f443edc1a1f9ba74a1f5e1007db1e4e28cb23b7d'

    # 3. archive_selective forwards model.refspec cleanly
    sel_dir = tmp_path / 'sel'
    (sel_dir / 'raw').mkdir(parents=True)
    receipt_inv = sel_dir / 'receipts.json'
    receipt_inv.write_text('{}')
    src_counts = sel_dir / 'counts.json'
    src_counts.write_text('{}')
    tpl = sel_dir / 'tpl.json'
    tpl.write_text(json.dumps({
        'version': 1,
        'captures': {'kind': 'native_table', 'metadata_location': 's3://b/c', 'table_uuid': '0'*32, 'snapshot': 1, 'schema_id': 0},
        'readings': {'kind': 'native_table', 'metadata_location': 's3://b/r', 'table_uuid': '1'*32, 'snapshot': 1, 'schema_id': 0},
        'filename_readings': {'kind': 'native_table', 'metadata_location': 's3://b/f', 'table_uuid': '2'*32, 'snapshot': 1, 'schema_id': 0},
        'parser_versions': real_spec['parser_versions'],
        'catalog_version': catalog_version(),
        'output': str(sel_dir / 'out'),
        'scratch': str(sel_dir / 'scr'),
    }))
    pub_tpl = sel_dir / 'pub.json'
    pub_tpl.write_text('{}')
    sel_val = {
        'base': {
            t: {'kind': 'native_table', 'metadata_location': f's3://b/{t}', 'table_uuid': '0'*32, 'snapshot': 1, 'schema_id': 0}
            for t in ALL_TABLE_NAMES
        },
        'raw_root': str(sel_dir / 'raw'),
        'receipt_inventory': {'path': str(receipt_inv), **file_pin(receipt_inv)},
        'source_counts': {'path': str(src_counts), **file_pin(src_counts)},
        'provenance': {'recoveries': [], 'reviews': [], 'unreadable': []},
        'where': {'captures': "receipt_key LIKE '%a.jsonl.gz'"},
        'differential_rows': 1,
        'model': {
            'template': str(tpl),
            'engine_config': os.environ['DOCSPEC_JOB_CONFIG'],
            'refspec': {'path': str(manifest_path), **file_pin(manifest_path)},
        },
        'publish_template': str(pub_tpl),
    }
    validated = archive_selective.validate_selective(
        sel_val,
        base=sel_dir,
        catalog_root=str(sel_dir / 'cat'),
        tables={t: {'namespace': ['fixture']} for t in ALL_TABLE_NAMES},
    )
    assert validated['model']['refspec']['sha256'] == file_pin(manifest_path)['sha256']
    run_stub = SimpleNamespace(
        selective=validated,
        state={'pins': {}},
        work=sel_dir / 'work',
        spec={},
    )
    forwarded_model = archive_selective._model_value(run_stub)
    assert forwarded_model['refspec'] == validated['model']['refspec']


def test_refspec_agency_linking_succession_parent_and_false_positive_guards(tmp_path: pathlib.Path):
    """Phase 2 matches RefSpec names, inversions, abbreviations, aliases, REF-072 successors,
    sets parent_org_id, outranks bag/decision anchors, and blocks state/private false positives."""
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    appearances = _write_appearances(tmp_path / 'appearances.parquet', [
        # Federal Commerce + NOAA child (tests parent_org_id)
        {'witness_key': 'w_comm', 'organization': 'U.S. Department of Commerce'},
        {'witness_key': 'w_noaa', 'organization': 'National Oceanic and Atmospheric Administration'},
        # GAO convergence (AC #4 sample)
        {'witness_key': 'w_gao1', 'organization': 'Government Accountability Office'},
        {'witness_key': 'w_gao2', 'organization': 'General Accounting Office'},
        {'witness_key': 'w_gao3', 'organization': 'GAO'},
        # REF-072 single successor: HCFA (559) -> CMS (45)
        {'witness_key': 'w_hcfa', 'organization': 'Health Care Finance Administration'},
        {'witness_key': 'w_cms', 'organization': 'Centers for Medicare & Medicaid Services'},
        # noFrRecord alias target: Capitol Police
        {'witness_key': 'w_cap', 'organization': 'United States Capitol Police'},
        # State/local/private/bio false-positive traps -> MUST NOT get fr_agency anchor
        {'witness_key': 'w_ohio_epa', 'organization': 'Ohio Environmental Protection Agency'},
        {'witness_key': 'w_epa_state_ohio', 'organization': 'Environmental Protection Agency, State of Ohio'},
        {'witness_key': 'w_wa_epa', 'organization': 'Environmental Protection Agency, State of Washington'},
        {'witness_key': 'w_la_va', 'organization': 'USAF, Secretary, Louisiana Department of Veterans Affairs'},
        {'witness_key': 'w_mi_va', 'organization': "Michigan Department of Veterans' Affairs, Veterans Health Administration"},
        {'witness_key': 'w_md_dot', 'organization': 'Department of Transportation, State of Maryland'},
        {'witness_key': 'w_nyc_edu', 'organization': 'Department of Education, City of New York'},
        {'witness_key': 'w_former_dod', 'organization': 'Metis Solutions (former Assistant Secretary, U.S. Department of Defense)'},
        {'witness_key': 'w_ihs_markit', 'organization': 'Center on Global Energy Policy, Columbia University and Senior Vice President, IHS'},
        {'witness_key': 'w_arts_univ', 'organization': 'College of Humanities, Arts, and Social Sciences, University of California, Riverside'},
    ])

    # Also test tier precedence: wikidata decision attached to GAO should stay subordinate to fr_agency:213.
    # Run once cleanly first to capture GAO bag_key, then run with wikidata decision.
    boot = build_org_entities(
        appearance_records_resolved=appearances,
        engine=engine,
        output=tmp_path / 'boot_out',
        scratch=tmp_path / 'boot_scratch',
        refspec=ROOT / 'model' / 'jobs' / 'refspec' / 'refspec.json',
    )
    boot_wo = {r['witness_key']: r for r in pq.read_table(boot['outputs']['witness_organizations.parquet']).to_pylist()}
    gao_bag = boot_wo['w_gao1']['bag_key']

    decisions_file = tmp_path / 'decisions.jsonl'
    decisions_file.write_text(json.dumps({
        'id': 'dec_gao_wd',
        'subject': f'bag:{gao_bag}',
        'verdict': 'same',
        'object': 'wikidata:Q12345',
        'note': 'wikidata link',
        'reviewer': 'test',
        'decided_at': '2026-11-08T00:00:00Z',
        'supersedes': None,
    }) + '\n')

    res = build_org_entities(
        appearance_records_resolved=appearances,
        engine=engine,
        output=tmp_path / 'out',
        scratch=tmp_path / 'scratch',
        org_decision_files=[decisions_file],
        refspec=ROOT / 'model' / 'jobs' / 'refspec' / 'refspec.json',
    )
    orgs = {r['org_id']: r for r in pq.read_table(res['outputs']['organizations.parquet']).to_pylist()}
    wo = {r['witness_key']: r for r in pq.read_table(res['outputs']['witness_organizations.parquet']).to_pylist()}
    org_ids = pq.read_table(res['outputs']['organization_ids.parquet']).to_pylist()

    # GAO witnesses converge onto one org_id with fr_agency:213 outranking wikidata:Q12345
    assert wo['w_gao1']['org_id'] == wo['w_gao2']['org_id'] == wo['w_gao3']['org_id']
    gao_org = orgs[wo['w_gao1']['org_id']]
    assert gao_org['anchor'] == 'fr_agency:213'
    assert gao_org['display_name'] == 'Government Accountability Office'
    assert gao_org['kind'] == 'government'
    assert wo['w_gao1']['method'] == 'registry'
    assert wo['w_gao1']['score'] == 1.0
    assert ('fr_agency', '213') in {(r['scheme'], r['value']) for r in org_ids if r['org_id'] == gao_org['org_id']}
    assert ('wikidata', 'Q12345') in {(r['scheme'], r['value']) for r in org_ids if r['org_id'] == gao_org['org_id']}

    # REF-072 successor bridge: HCFA resolves to CMS (fr_agency:45)
    assert wo['w_hcfa']['org_id'] == wo['w_cms']['org_id']
    assert orgs[wo['w_hcfa']['org_id']]['anchor'] == 'fr_agency:45'

    # Parent org link: NOAA (parent Commerce Department fr_agency:74)
    noaa_org = orgs[wo['w_noaa']['org_id']]
    comm_org = orgs[wo['w_comm']['org_id']]
    assert noaa_org['parent_org_id'] == comm_org['org_id']

    # noFrRecord alias target: Capitol Police
    cap_org = orgs[wo['w_cap']['org_id']]
    assert cap_org['anchor'] == 'refspec_target:urn:ref:federal-hierarchy-org:500193110'
    assert cap_org['kind'] == 'government'

    # State/local/private traps stay completely off RefSpec federal anchors
    for trap_key in ('w_ohio_epa', 'w_epa_state_ohio', 'w_wa_epa', 'w_la_va', 'w_mi_va', 'w_md_dot', 'w_nyc_edu', 'w_former_dod', 'w_ihs_markit', 'w_arts_univ'):
        trap_org = orgs[wo[trap_key]['org_id']]
        assert not trap_org['anchor'].startswith('fr_agency:'), f'{trap_key} falsely anchored to {trap_org["anchor"]}'
        assert not trap_org['anchor'].startswith('refspec_target:'), f'{trap_key} falsely anchored to {trap_org["anchor"]}'

    # Rebuild determinism
    res2 = build_org_entities(
        appearance_records_resolved=appearances,
        engine=engine,
        output=tmp_path / 'out2',
        scratch=tmp_path / 'scratch2',
        org_decision_files=[decisions_file],
        refspec=ROOT / 'model' / 'jobs' / 'refspec' / 'refspec.json',
    )
    for fname in ('organizations.parquet', 'organization_ids.parquet', 'witness_organizations.parquet'):
        assert pq.read_table(res['outputs'][fname]).to_pylist() == pq.read_table(res2['outputs'][fname]).to_pylist()


def test_org_decisions_rejects_agency_alias_rows(tmp_path: pathlib.Path):
    """AC #5: org_decisions holds zero agency alias rows; provenance validator and engine invariants refuse them."""
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    appearances = _write_appearances(tmp_path / 'appearances.parquet', [
        {'witness_key': 'w_epa', 'organization': 'U.S. Environmental Protection Agency'},
    ])
    bad_row = {
        'id': 'bad_alias_1',
        'subject': 'agency_alias:epa',
        'verdict': 'same',
        'object': 'fr_agency:145',
        'note': 'disallowed agency alias in org_decisions',
        'reviewer': 'test',
        'decided_at': '2026-11-08T00:00:00Z',
        'supersedes': None,
    }
    bad_decision = tmp_path / 'bad_org_decisions.jsonl'
    bad_decision.write_text(json.dumps(bad_row) + '\n')

    # Provenance validator refuses agency alias assertions (also test bag:subject -> fr_agency:object).
    with pytest.raises(ValueError):
        provenance.validate_provenance('org_decisions', bad_row)
    with pytest.raises(ValueError):
        provenance.validate_provenance('org_decisions', {**bad_row, 'subject': 'bag:0123456789abcdef'})

    # Defensive SQL/invariant guard inside build_org_entities also refuses it.
    with pytest.raises(ValueError, match='rejected_org_decision_agency_aliases'):
        build_org_entities(
            appearance_records_resolved=appearances,
            engine=engine,
            output=tmp_path / 'out',
            scratch=tmp_path / 'scratch',
            org_decision_files=[bad_decision],
            refspec=ROOT / 'model' / 'jobs' / 'refspec' / 'refspec.json',
        )
