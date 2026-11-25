"""Phase 4 organization exposure, release-notes reporting, and two-release split determinism (ct-lvdf)."""
import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from docspec_client.client import NativeDatasets

from test_org_entities_phase1 import (
    _make_decision,
    _mrow,
    _org_sha16,
    _spicy_fixture,
    _write_decisions_jsonl,
)
from test_witness_identity import _cg_json, _pdf_bytes, _stage_raw


def test_org_phase4_publishes_tables_and_release_notes(tmp_path):
    """When publish_org_entities=True, build_release exports the 4 org tables, registers them
    in manifest.json and schema.json, runs release foreign-key/1-hop checks, and render_notes
    reports linked share by appearances and retired org IDs by cause (and stays clean on legacy)."""
    from viewer_publication.archive_model import build_release
    from viewer_publication.release_gate import render_notes

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()

    cg_201 = _cg_json(201, '2026-10-20T00:00:00Z', 'h201')
    doc_201 = _pdf_bytes('testimony-201')
    captures = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/201?format=json', data=cg_201, format='json', family='congress/meetings'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/201/HHRG-118-IF00-Wstate-DoeJ-20240501.pdf', data=doc_201, format='pdf', suffix='.pdf'),
    ]
    meetings = [dict(record_sha=sha(cg_201), source='congress_gov', meetings=[_mrow(201)])]
    appearances = [
        dict(record_sha=sha(cg_201), source='congress_gov', event_id=201, collection_state='present', appearances=[
            dict(source_locator='cg:1', name_key='alice one', name='Alice One', given='Alice', family='One',
                 organization='Pacific Solar Alliance', display_order=1),
            dict(source_locator='cg:2', name_key='bob two', name='Bob Two', given='Bob', family='Two',
                 organization='Pacific Solar Alliances', display_order=2),
            dict(source_locator='cg:3', name_key='carol three', name='Carol Three', given='Carol', family='Three',
                 organization='Brookings Institution', display_order=3),
            dict(source_locator='cg:4', name_key='dave four', name='Dave Four', given='Dave', family='Four',
                 organization='   ', display_order=4),
        ]),
    ]

    staged_1 = _stage_raw(tmp_path / 'stage_1', engine, captures)
    out_1 = tmp_path / 'rel1'
    m1 = build_release(
        **staged_1,
        engine=engine,
        output=out_1,
        scratch=tmp_path / 'scr1',
        meeting_records=meetings,
        appearance_records=appearances,
        spicy_regs=_spicy_fixture(),
        include_entities=True,
        publish_org_entities=True,
        org_release_label='rel-p4-1',
    )
    file_names = {f['name'] for f in m1['files']}
    assert {'organizations.parquet', 'organization_ids.parquet', 'witness_organizations.parquet', 'organization_redirects.parquet'} <= file_names
    for name in ('organizations.parquet', 'organization_ids.parquet', 'witness_organizations.parquet', 'organization_redirects.parquet'):
        assert (out_1 / name).is_file()

    # Probe exact bag keys from Release 1.
    w_orgs_1 = {r['raw_text']: r for r in pq.read_table(out_1 / 'witness_organizations.parquet').to_pylist()}
    bag_a = w_orgs_1['Pacific Solar Alliance']['bag_key']
    bag_b = w_orgs_1['Pacific Solar Alliances']['bag_key']
    bag_c = w_orgs_1['Brookings Institution']['bag_key']
    dec_r2 = _write_decisions_jsonl(tmp_path / 'dec_r2.jsonl', [
        _make_decision('dec_merge_solar', f'bag:{bag_a}', 'same', f'bag:{bag_b}', decided_at='2026-11-20T00:00:00Z'),
        _make_decision('dec_wiki_brookings', f'bag:{bag_c}', 'same', 'wikidata:Q49048', decided_at='2026-11-20T00:00:00Z'),
    ])

    staged_2 = _stage_raw(tmp_path / 'stage_2', engine, captures)
    out_2 = tmp_path / 'rel2'
    m2 = build_release(
        **staged_2,
        engine=engine,
        output=out_2,
        scratch=tmp_path / 'scr2',
        meeting_records=meetings,
        appearance_records=appearances,
        spicy_regs=_spicy_fixture(),
        include_entities=True,
        publish_org_entities=True,
        org_decision_files=[dec_r2],
        prior_org_release=out_1,
        org_release_label='rel-p4-2',
    )
    assert m2['files']
    org_ids_2 = pq.read_table(out_2 / 'organization_ids.parquet').to_pylist()
    assert any(r['scheme'] == 'wikidata' and r['value'] == 'Q49048' for r in org_ids_2)
    redirects_2 = pq.read_table(out_2 / 'organization_redirects.parquet').to_pylist()
    assert len(redirects_2) == 3
    assert all(r['event'] == 'merged' for r in redirects_2)

    # Check release notes reporting on rel2 (and graceful omission on a legacy candidate without org tables).
    causes_r2 = dict(base_release_id=m1['release_id'], candidate_release_id=m2['release_id'], groups=[])
    notes_with_orgs = render_notes(causes_r2, out_1, out_2)
    assert '## Organizations' in notes_with_orgs
    assert '2 organizations published; 3 of 4 canonical appearances (75.0%) linked to an organization.' in notes_with_orgs
    assert 'Retired organization IDs by cause: merged: 3.' in notes_with_orgs

    legacy_dir = tmp_path / 'legacy_dir'
    legacy_dir.mkdir()
    (legacy_dir / 'manifest.json').write_bytes((out_1 / 'manifest.json').read_bytes())
    notes_legacy = render_notes(dict(base_release_id=m1['release_id'], candidate_release_id=m1['release_id'], groups=[]), out_1, legacy_dir)
    assert '## Organizations' not in notes_legacy

    # Verify render_notes intersects witness_organizations with canonical (superseded_by IS NULL) witnesses.
    import shutil
    import pyarrow as pa
    sup_dir = tmp_path / 'sup_dir'
    shutil.copytree(out_2, sup_dir)
    w_existing = pq.read_table(sup_dir / 'witnesses.parquet').to_pylist()
    sup_row = dict(w_existing[0], witness_key='wk-superseded-dup', superseded_by=w_existing[0]['witness_key'])
    pq.write_table(pa.Table.from_pylist([*w_existing, sup_row], schema=pq.read_schema(sup_dir / 'witnesses.parquet')), sup_dir / 'witnesses.parquet')
    wo_existing = pq.read_table(sup_dir / 'witness_organizations.parquet').to_pylist()
    wo_sup_row = dict(wo_existing[0], witness_key='wk-superseded-dup')
    pq.write_table(pa.Table.from_pylist([*wo_existing, wo_sup_row], schema=pq.read_schema(sup_dir / 'witness_organizations.parquet')), sup_dir / 'witness_organizations.parquet')
    notes_sup = render_notes(causes_r2, out_1, sup_dir)
    assert '2 organizations published; 3 of 4 canonical appearances (75.0%) linked to an organization.' in notes_sup


def test_org_phase4_two_release_split_equal_count_determinism(tmp_path):
    """Across two consecutive build_release runs (second reading first as prior_org_release),
    a normalization split replacing the old anchor (including equal count of inherited distinct
    verbatim strings in reversed input order) picks the smaller new bag key in UTF-8 byte order
    deterministically, and every prior org_id resolves directly or through one hop."""
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()

    cg_301 = _cg_json(301, '2026-10-20T00:00:00Z', 'h301')
    doc_301 = _pdf_bytes('testimony-301')
    captures = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/301?format=json', data=cg_301, format='json', family='congress/meetings'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/301/HHRG-118-IF00-Wstate-DoeJ-20240501.pdf', data=doc_301, format='pdf', suffix='.pdf'),
    ]
    meetings = [dict(record_sha=sha(cg_301), source='congress_gov', meetings=[_mrow(301)])]
    raw_apps = [
        # Equal-count split pair (1 distinct verbatim string each):
        dict(source_locator='cg:1', name_key='s one', name='S One', given='S', family='One',
             organization='Blue Harbor Maritime', display_order=1),
        dict(source_locator='cg:2', name_key='s two', name='S Two', given='S', family='Two',
             organization='Red Mountain Timber', display_order=2),
        # Asymmetric split pair (2 distinct verbatim strings vs 1):
        dict(source_locator='cg:3', name_key='a one', name='A One', given='A', family='One',
             organization='Silver River Energy', display_order=3),
        dict(source_locator='cg:4', name_key='a two', name='A Two', given='A', family='Two',
             organization='Silver River Energy, Inc.', display_order=4),
        dict(source_locator='cg:5', name_key='a three', name='A Three', given='A', family='Three',
             organization='Golden Valley Coal', display_order=5),
    ]

    # Probe bag keys cleanly first.
    staged_probe = _stage_raw(tmp_path / 'stage_probe', engine, captures)
    out_probe = tmp_path / 'probe'
    build_release(
        **staged_probe,
        engine=engine,
        output=out_probe,
        scratch=tmp_path / 'scr_probe',
        meeting_records=meetings,
        appearance_records=[dict(record_sha=sha(cg_301), source='congress_gov', event_id=301, collection_state='present', appearances=raw_apps)],
        spicy_regs=_spicy_fixture(),
        include_entities=True,
        publish_org_entities=True,
        org_release_label='probe',
    )
    bags = {r['raw_text']: r['bag_key'] for r in pq.read_table(out_probe / 'witness_organizations.parquet').to_pylist()}
    bs1, bs2 = bags['Blue Harbor Maritime'], bags['Red Mountain Timber']
    ba1, ba2 = bags['Silver River Energy'], bags['Golden Valley Coal']
    assert bs1 != bs2
    assert bags['Silver River Energy, Inc.'] == ba1

    dec_rel1 = _write_decisions_jsonl(tmp_path / 'dec_rel1.jsonl', [
        _make_decision('dec_eq', f'bag:{bs1}', 'same', f'bag:{bs2}', decided_at='2026-11-20T00:00:00Z'),
        _make_decision('dec_asym', f'bag:{ba1}', 'same', f'bag:{ba2}', decided_at='2026-11-20T00:00:00Z'),
    ])
    dec_rel2 = _write_decisions_jsonl(tmp_path / 'dec_rel2.jsonl', [
        _make_decision('dec_eq', f'bag:{bs1}', 'same', f'bag:{bs2}', decided_at='2026-11-20T00:00:00Z'),
        _make_decision('dec_eq_wd', f'bag:{bs1}', 'withdraw', f'bag:{bs2}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_eq'),
        _make_decision('dec_asym', f'bag:{ba1}', 'same', f'bag:{ba2}', decided_at='2026-11-20T00:00:00Z'),
        _make_decision('dec_asym_wd', f'bag:{ba1}', 'withdraw', f'bag:{ba2}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_asym'),
    ])

    def _run_two_releases(tag: str, app_list: list[dict]):
        app_rec = [dict(record_sha=sha(cg_301), source='congress_gov', event_id=301, collection_state='present', appearances=app_list)]
        s1 = _stage_raw(tmp_path / f's1_{tag}', engine, captures)
        o1 = tmp_path / f'rel1_{tag}'
        build_release(
            **s1,
            engine=engine,
            output=o1,
            scratch=tmp_path / f'scr1_{tag}',
            meeting_records=meetings,
            appearance_records=app_rec,
            spicy_regs=_spicy_fixture(),
            include_entities=True,
            publish_org_entities=True,
            org_decision_files=[dec_rel1],
            org_release_label='r1',
        )
        s2 = _stage_raw(tmp_path / f's2_{tag}', engine, captures)
        o2 = tmp_path / f'rel2_{tag}'
        build_release(
            **s2,
            engine=engine,
            output=o2,
            scratch=tmp_path / f'scr2_{tag}',
            meeting_records=meetings,
            appearance_records=app_rec,
            spicy_regs=_spicy_fixture(),
            include_entities=True,
            publish_org_entities=True,
            org_decision_files=[dec_rel2],
            prior_org_release=o1,
            org_release_label='r2',
        )
        orgs1 = {r['org_id']: r for r in pq.read_table(o1 / 'organizations.parquet').to_pylist()}
        orgs2 = {r['org_id']: r for r in pq.read_table(o2 / 'organizations.parquet').to_pylist()}
        red2 = {r['old_org_id']: r for r in pq.read_table(o2 / 'organization_redirects.parquet').to_pylist()}

        # Every prior org_id resolves directly in live orgs2 OR through exactly 1 redirect hop!
        for old_id in orgs1:
            if old_id not in orgs2:
                assert old_id in red2
                assert red2[old_id]['org_id'] in orgs2

        # Neither split org holds the old decision:dec_eq anchor; smaller UTF-8 bag_key wins tie.
        eq_old_id = _org_sha16('org-v1', 'decision:dec_eq')
        eq_winner_id = _org_sha16('org-v1', f'bag:{min(bs1, bs2)}')
        asym_old_id = _org_sha16('org-v1', 'decision:dec_asym')
        asym_winner_id = _org_sha16('org-v1', f'bag:{ba1}')
        assert eq_old_id not in orgs2
        assert red2[eq_old_id] == dict(old_org_id=eq_old_id, org_id=eq_winner_id, event='split_from', release='r2')
        assert asym_old_id not in orgs2
        assert red2[asym_old_id] == dict(old_org_id=asym_old_id, org_id=asym_winner_id, event='split_from', release='r2')
        return orgs2, red2

    orgs_fwd, red_fwd = _run_two_releases('fwd', raw_apps)
    orgs_rev, red_rev = _run_two_releases('rev', list(reversed(raw_apps)))
    assert red_fwd == red_rev
    assert set(orgs_fwd) == set(orgs_rev)


def test_org_phase4_controller_job_and_ledger_plumbing(tmp_path):
    """Verify full controller/job/ledger plumbing: archive_model_job spec + execute with
    publish_org_entities & org_decision_files, release_gate.fetch_base & prior_links carrying
    prior_organizations/prior_organization_redirects/prior_witness_organizations, legacy
    base tolerance, and prepare_model_inputs sibling ledger auto-wiring (archive_controller path)."""
    from congress_api.retention.provenance import file_pin
    from viewer_publication import archive_model_job
    from viewer_publication.archive_model import prepare_model_inputs
    from viewer_publication.release_gate import fetch_base, prior_links

    from archive_job_fixture import real_model_spec, spicy_pin
    from test_org_entities_phase1 import _make_decision, _write_decisions_jsonl

    job_r1_dir = tmp_path / 'job_r1'
    job_r1_dir.mkdir()
    base_spec, _digest, _html = real_model_spec(job_r1_dir, entities=True)
    # Build minimal meeting & appearance records with an explicit org name via staged fixture.
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()
    cg_401 = _cg_json(401, '2026-10-20T00:00:00Z', 'h401')
    doc_401 = _pdf_bytes('testimony-401')
    captures = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/401?format=json', data=cg_401, format='json', family='congress/meetings'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/401/HHRG-118-IF00-Wstate-DoeJ-20240501.pdf', data=doc_401, format='pdf', suffix='.pdf'),
    ]
    raw_dir = tmp_path / 'raw_data'
    raw_dir.mkdir()
    staged_dir = tmp_path / 'staged_data'
    staged = _stage_raw(staged_dir, engine, captures)

    # Write local meeting/appearance/spicy files to feed archive_model_job spec.
    from congress_api.lake import appearance_records as ar_lake, meeting_records as mr_lake
    mr_path = tmp_path / 'meeting_records.parquet'
    ar_path = tmp_path / 'appearance_records.parquet'
    pq.write_table(mr_lake.table([dict(
        record_sha=bytes.fromhex(sha(cg_401)),
        parser_version=base_spec['parser_versions']['meeting_records']['congress_gov'],
        source='congress_gov',
        meetings=[_mrow(401)],
    )]), mr_path)
    pq.write_table(ar_lake.table([dict(
        record_sha=bytes.fromhex(sha(cg_401)),
        parser_version=base_spec['parser_versions']['appearance_records']['congress_gov'],
        source='congress_gov',
        event_id=401,
        package_id=None,
        declared_base=None,
        collection_state='present',
        appearances=[
            dict(source_locator='cg:1', name_key='eve one', name='Eve One', given='Eve', family='One',
                 organization='Pacific Solar Alliance', display_order=1),
            dict(source_locator='cg:2', name_key='frank two', name='Frank Two', given='Frank', family='Two',
                 organization='Pacific Solar Alliances', display_order=2),
        ],
    )]), ar_path)

    spicy_dir = tmp_path / 'spicy_dir'
    spicy_dir.mkdir()
    spicy_file = Path(spicy_pin(
        spicy_dir,
        spicy_committees=[dict(
            system_code='hsif00',
            name='Energy and Commerce',
            chamber='house',
            committee_type='standing',
            parent_system_code=None,
            website_url='https://energycommerce.house.gov',
            is_current=True,
            history=[],
        )],
    )['path'])

    def _job_spec(tag: str, org_decisions=()):
        s = dict(base_spec)
        for k in ('captures', 'readings', 'filename_readings'):
            s[k] = dict(kind='parquet', path=str(staged[k]), **file_pin(staged[k]))
        s['meeting_records'] = dict(kind='parquet', path=str(mr_path), **file_pin(mr_path))
        s['appearance_records'] = dict(kind='parquet', path=str(ar_path), **file_pin(ar_path))
        s['spicy_regs'] = dict(path=str(spicy_file), **file_pin(spicy_file))
        s['publish_org_entities'] = True
        s['org_decision_files'] = list(org_decisions)
        s['output'] = str(tmp_path / f'out_{tag}')
        s['scratch'] = str(tmp_path / f'scr_{tag}')
        spec_path = tmp_path / f'spec_{tag}.json'
        spec_path.write_text(json.dumps(s))
        return archive_model_job.load_spec(spec_path)

    spec1 = _job_spec('r1')
    res1 = archive_model_job.execute(spec1)
    out1 = Path(res1['output'])
    assert {'organizations.parquet', 'organization_ids.parquet', 'witness_organizations.parquet', 'organization_redirects.parquet'} <= set(res1['rows'])

    # Test release_gate.fetch_base against Release 1.
    def _local_reader(release_id):
        def _read(name):
            return (out1 / name).open('rb')
        return _read

    m1 = json.loads((out1 / 'manifest.json').read_text())
    base_dir, prior_l, base_ret, _ = fetch_base(_local_reader, m1['release_id'], tmp_path / 'fetched_base')
    assert (base_dir / 'organizations.parquet').is_file()
    assert (base_dir / 'organization_redirects.parquet').is_file()
    assert (base_dir / 'witness_organizations.parquet').is_file()
    for pname in ('prior_organizations.parquet', 'prior_organization_redirects.parquet', 'prior_witness_organizations.parquet'):
        assert Path(prior_l).with_name(pname).is_file()

    # Check prepare_model_inputs (archive_controller path) discovers sibling org priors from prior_links.
    with archive_model_job.model_arguments(spec1, allow_existing_output=True) as args1:
        args_prep = dict(args1)
        prep = prepare_model_inputs(
            **args_prep,
            parser_versions=spec1['parser_versions'],
            catalog_version=spec1['catalog_version'],
            engine=engine,
            scratch=tmp_path / 'ctrl_prep_scratch',
            prior_links=prior_l,
            base_retired=base_ret,
            include_org_entities=True,
            publish_org_entities=True,
        )
        prior_input = next(i for i in prep['inputs'] if i['name'] == 'prior_organizations')
        assert Path(prior_input['path']) == Path(prior_l).with_name('prior_organizations.parquet').resolve()

    # Release 2 via archive_model_job with --ledger-base equivalent and org_decision_files provenance!
    w_orgs1 = {r['raw_text']: r for r in pq.read_table(out1 / 'witness_organizations.parquet').to_pylist()}
    dec_path = Path(_write_decisions_jsonl(tmp_path / 'dec_job.jsonl', [
        _make_decision('dec_job_merge', f"bag:{w_orgs1['Pacific Solar Alliance']['bag_key']}", 'same',
                       f"bag:{w_orgs1['Pacific Solar Alliances']['bag_key']}", decided_at='2026-11-22T00:00:00Z'),
    ]))
    spec2 = _job_spec('r2', org_decisions=[dict(key='provenance/org_decisions/job.jsonl', path=str(dec_path), **file_pin(dec_path))])
    prior2, retired2 = archive_model_job.ledger_files(spec2, base=out1)
    res2 = archive_model_job.execute(spec2, prior_links=prior2, base_retired=retired2)
    assert {'prior_organizations', 'prior_organization_redirects', 'prior_witness_organizations'} <= set(res2['ledger'])
    out2 = Path(res2['output'])
    redirects2 = pq.read_table(out2 / 'organization_redirects.parquet').to_pylist()
    assert len(redirects2) == 2
    assert all(r['event'] == 'merged' and r['org_id'] == _org_sha16('org-v1', 'decision:dec_job_merge') for r in redirects2)

    # Also verify prior_links tolerates a legacy base directory without org tables (writes empty schemas).
    legacy_base = tmp_path / 'legacy_base'
    legacy_base.mkdir()
    for fname in ('manifest.json', 'links.parquet', 'detail.parquet', 'list.parquet', 'sources.parquet'):
        (legacy_base / fname).write_bytes((out1 / fname).read_bytes())
    leg_prior, _ = prior_links(legacy_base, [], tmp_path / 'legacy_ledger')
    assert pq.read_table(Path(leg_prior).with_name('prior_organizations.parquet')).num_rows == 0

