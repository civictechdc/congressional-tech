"""Phase 1 organization entity resolution, Ban-Park-You taxonomy, redirects, and invariants (ct-6him)."""
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets

from archive_job_fixture import spicy_input
from test_witness_identity import _cg_json, _pdf_bytes, _stage_raw


def _org_sha16(prefix: str, value: str) -> str:
    return hashlib.sha256((prefix + value).encode('utf-8')).hexdigest()[:16]


def _spicy_fixture():
    return spicy_input(
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
        spicy_members=[],
        spicy_member_terms=[],
    )


def _mrow(eid, *, date_str='2024-05-01'):
    return dict(
        event_id=str(eid),
        chamber='house',
        congress=118,
        session=2,
        updated='2026-10-20T00:00:00Z',
        title=f'Hearing {eid}',
        meeting_date=date_str,
        meeting_type='HHRG',
        status='Scheduled',
        sittings=[],
        committees=[dict(system_code='hsif00', name='Energy and Commerce', chamber='house', role='host')],
        subject_keys=[],
        transcript_jackets=[],
        videos=[],
        document_urls=[],
        document_references=[],
        collection_states=dict(
            sittings='present', committees='present', subject_keys='empty',
            transcript_jackets='empty', videos='empty', document_urls='empty',
        ),
        access='open',
        access_basis='default',
        not_held=False,
        title_key=f'hearing {eid}',
        reschedule_candidate=False,
    )


def _write_decisions_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n' for r in rows))
    return str(path)


def _make_decision(
    dec_id: str,
    subject: str,
    verdict: str,
    obj: str,
    *,
    decided_at: str = '2026-11-22T12:00:00Z',
    supersedes: str | None = None,
    note: str = 'Phase 1 org adjudication',
    reviewer: str = 'tester',
) -> dict:
    return dict(
        id=dec_id,
        subject=subject,
        verdict=verdict,
        object=obj,
        note=note,
        reviewer=reviewer,
        decided_at=decided_at,
        supersedes=supersedes,
    )


def _write_appearance_parquet(path: Path, rows: list[dict]) -> Path:
    schema = pa.schema([
        ('witness_key', pa.string()),
        ('occasion', pa.string()),
        ('source', pa.string()),
        ('record_sha', pa.string()),
        ('source_locator', pa.string()),
        ('event_id', pa.int64()),
        ('package_id', pa.string()),
        ('page_url', pa.string()),
        ('name', pa.string()),
        ('rank', pa.string()),
        ('credentials', pa.string()),
        ('position', pa.string()),
        ('organization', pa.string()),
        ('on_behalf_of', pa.string()),
        ('location', pa.string()),
        ('panel', pa.string()),
        ('panel_order', pa.int32()),
        ('display_order', pa.int32()),
        ('witness_type', pa.string()),
        ('testified', pa.bool_()),
        ('bioguide_id', pa.string()),
        ('name_key', pa.string()),
        ('listing_status', pa.string()),
        ('last_listed_on', pa.string()),
        ('unlisted_since', pa.string()),
        ('unlisted_by_record_sha', pa.string()),
    ])
    defaults = {
        'occasion': 'meeting:100',
        'source': 'congress_gov',
        'record_sha': '0' * 64,
        'event_id': 100,
        'package_id': None,
        'page_url': None,
        'rank': None,
        'credentials': None,
        'position': 'Witness',
        'on_behalf_of': None,
        'location': None,
        'panel': 'Panel 1',
        'panel_order': 1,
        'witness_type': 'witness',
        'testified': True,
        'bioguide_id': None,
        'listing_status': 'listed',
        'last_listed_on': None,
        'unlisted_since': None,
        'unlisted_by_record_sha': None,
    }
    normalized = []
    for idx, row in enumerate(rows):
        item = dict(defaults)
        item.setdefault('source_locator', f'loc:{idx}')
        item.setdefault('display_order', idx + 1)
        item.setdefault('name', f'Witness {idx}')
        item.setdefault('name_key', f'witness {idx}')
        item.update(row)
        normalized.append(item)
    table = pa.Table.from_pylist(normalized, schema=schema)
    pq.write_table(table, path)
    return path


def _app_row(witness_key: str, org: str | None, *, on_behalf_of: str | None = None, name: str = 'Jane Witness'):
    return dict(
        witness_key=witness_key,
        name=name,
        name_key=name.lower(),
        organization=org,
        on_behalf_of=on_behalf_of,
    )


def test_build_release_org_entities_byte_identical_normalization_taxonomy_and_witness_preservation(tmp_path):
    """Full build_release with include_org_entities=True produces byte-identical outputs across
    rebuilds, leaves witnesses.parquet & manifest.json byte-unchanged vs include_org_entities=False,
    exercises L2 normalization & location guards, token-bag auto-merge, place/scope exclusions,
    and Ban-Park-You taxonomy categories."""
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha = lambda b: hashlib.sha256(b).hexdigest()

    cg_101 = _cg_json(101, '2026-10-20T00:00:00Z', 'h101')
    doc_101 = _pdf_bytes('testimony-101')
    captures = [
        dict(url='https://api.congress.gov/v3/committee-meeting/118/house/101?format=json', data=cg_101, format='json', family='congress/meetings'),
        dict(url='https://docs.house.gov/meetings/IF/IF00/20240501/101/HHRG-118-IF00-Wstate-DoeJ-20240501.pdf', data=doc_101, format='pdf', suffix='.pdf'),
    ]
    meetings = [dict(record_sha=sha(cg_101), source='congress_gov', meetings=[_mrow(101)])]
    appearances = [
        dict(record_sha=sha(cg_101), source='congress_gov', event_id=101, collection_state='present', appearances=[
            # Token-bag auto-merge (punctuation, stopword, order, U.S./United States, trailing City, ST)
            dict(source_locator='cg:1', name_key='a one', name='A One', given='A', family='One',
                 organization='The U.S. Chamber of Commerce, Washington, DC', display_order=1),
            dict(source_locator='cg:2', name_key='a two', name='A Two', given='A', family='Two',
                 organization='Chamber of Commerce, United States', display_order=2),
            dict(source_locator='cg:2b', name_key='a twob', name='A Twob', given='A', family='Twob',
                 organization='Commerce Chamber', display_order=3),
            # Campus preservation after "University of ", plus L2 city/state preservation inside campus name
            dict(source_locator='cg:3', name_key='a three', name='A Three', given='A', family='Three',
                 organization='University of California, Los Angeles, CA', display_order=3),
            dict(source_locator='cg:4', name_key='a four', name='A Four', given='A', family='Four',
                 organization='University of California, Los Angeles', display_order=4),
            # Non-location comma preserved when no trailing state (", Nature Conservancy")
            dict(source_locator='cg:5', name_key='a five', name='A Five', given='A', family='Five',
                 organization='Public Policy, Nature Conservancy', display_order=5),
            # Place/scope exclusion pairs: MUST NOT enter org_review_queue despite high Lev/Jaccard
            dict(source_locator='cg:6', name_key='a six', name='A Six', given='A', family='Six',
                 organization='Virginia Council of Churches', display_order=6),
            dict(source_locator='cg:7', name_key='a seven', name='A Seven', given='A', family='Seven',
                 organization='West Virginia Council of Churches', display_order=7),
            dict(source_locator='cg:8', name_key='a eight', name='A Eight', given='A', family='Eight',
                 organization='National Farmers Union Coalition', display_order=8),
            dict(source_locator='cg:9', name_key='a nine', name='A Nine', given='A', family='Nine',
                 organization='International Farmers Union Coalition', display_order=9),
            # Valid fuzzy candidate pair (singular/plural spelling typo, same rarest token, Jaccard >= 0.75, Lev >= 0.85)
            dict(source_locator='cg:10', name_key='a ten', name='A Ten', given='A', family='Ten',
                 organization='American Solar Energy Policy Research Education Advocacy Network', display_order=10),
            dict(source_locator='cg:11', name_key='a eleven', name='A Eleven', given='A', family='Eleven',
                 organization='American Solar Energy Policy Research Education Advocacy Networks', display_order=11),
            # Deferred "Co." stripping after trailing ", CO" + Ban-Park-You categories + on_behalf_of extraction
            dict(source_locator='cg:12', name_key='a twelve', name='A Twelve', given='A', family='Twelve',
                 organization='Ford Motor Co., Denver, CO', on_behalf_of='AFL-CIO', display_order=12),
            dict(source_locator='cg:13', name_key='a thirteen', name='A Thirteen', given='A', family='Thirteen',
                 organization='Brookings Institution', on_behalf_of='Congressional Budget Office', display_order=13),
            dict(source_locator='cg:14', name_key='a fourteen', name='A Fourteen', given='A', family='Fourteen',
                 organization='U.S. Department of Energy', on_behalf_of='American Bar Association', display_order=14),
            # Stopword-only & empty strings
            dict(source_locator='cg:15', name_key='a fifteen', name='A Fifteen', given='A', family='Fifteen',
                 organization='The Inc.', on_behalf_of='   ', display_order=15),
            # Regression guards: multi-comma org before ", Washington, DC", bare City+State preservation,
            # multiset token-bag multiplicity preservation, and pure-stopword empty-bag fallback.
            dict(source_locator='cg:16', name_key='a sixteen', name='A Sixteen', given='A', family='Sixteen',
                 organization='International and Regulatory Affairs, Continental Airlines, Inc., Washington, DC', display_order=16),
            dict(source_locator='cg:17', name_key='a seventeen', name='A Seventeen', given='A', family='Seventeen',
                 organization='Malta, Montana', on_behalf_of='Malta & Co., Inc.', display_order=17),
            dict(source_locator='cg:18', name_key='a eighteen', name='A Eighteen', given='A', family='Eighteen',
                 organization='University of Maryland University College, College Park, MD',
                 on_behalf_of='University of Maryland, College Park, MD', display_order=18),
            dict(source_locator='cg:19', name_key='a nineteen', name='A Nineteen', given='A', family='Nineteen',
                 organization='Of The', on_behalf_of='Boulder, CO', display_order=19),
        ]),
    ]

    def _run_build(tag: str, *, include_org: bool):
        staged = _stage_raw(tmp_path / f'stage_{tag}', engine, captures)
        out_dir = tmp_path / f'out_{tag}'
        scratch_dir = tmp_path / f'scratch_{tag}'
        manifest = build_release(
            **staged,
            engine=engine,
            output=out_dir,
            scratch=scratch_dir,
            meeting_records=meetings,
            appearance_records=appearances,
            spicy_regs=_spicy_fixture(),
            include_entities=True,
            include_org_entities=include_org,
        )
        return out_dir, scratch_dir, manifest

    out_base, _, manifest_base = _run_build('base', include_org=False)
    out_r1, scratch_r1, manifest_r1 = _run_build('r1', include_org=True)
    out_r2, scratch_r2, manifest_r2 = _run_build('r2', include_org=True)

    # 1. Existing witness table, manifest, and release_id are byte-unchanged.
    assert (out_base / 'witnesses.parquet').read_bytes() == (out_r1 / 'witnesses.parquet').read_bytes()
    assert (out_base / 'manifest.json').read_bytes() == (out_r1 / 'manifest.json').read_bytes()
    assert manifest_base['release_id'] == manifest_r1['release_id']
    assert manifest_r1['release_id'] == manifest_r2['release_id']

    # Witness text values are untouched.
    witness_rows = pq.read_table(out_r1 / 'witnesses.parquet').to_pylist()
    assert any(r['organization'] == 'The U.S. Chamber of Commerce, Washington, DC' for r in witness_rows)
    assert any(r['organization'] == 'Ford Motor Co., Denver, CO' and r['on_behalf_of'] == 'AFL-CIO' for r in witness_rows)

    # 2. Byte-identical Parquet outputs across two independent clean rebuilds.
    org_dir_r1 = scratch_r1 / 'evidence' / 'org_entities'
    org_dir_r2 = scratch_r2 / 'evidence' / 'org_entities'
    org_files = [
        'organizations.parquet',
        'organization_ids.parquet',
        'witness_organizations.parquet',
        'organization_redirects.parquet',
        'org_review_queue.parquet',
        'org_decisions_conflicts.parquet',
        'org_strings.parquet',
    ]
    for fname in org_files:
        assert (org_dir_r1 / fname).exists(), f'Missing {fname}'
        assert (org_dir_r1 / fname).read_bytes() == (org_dir_r2 / fname).read_bytes(), f'{fname} not byte-identical across rebuilds'

    # 3. Verify normalization + token-bag auto-merge + taxonomy + on_behalf_of.
    strings_rows = pq.read_table(org_dir_r1 / 'org_strings.parquet').to_pylist()
    strings_by_raw = {raw: r for r in strings_rows for raw in r['raw_texts']}
    assert strings_by_raw['The U.S. Chamber of Commerce, Washington, DC']['string_key'] == strings_by_raw['Chamber of Commerce, United States']['string_key']
    assert strings_by_raw['Commerce Chamber']['string_key'] != strings_by_raw['Chamber of Commerce, United States']['string_key']
    assert strings_by_raw['Commerce Chamber']['bag_key'] == strings_by_raw['The U.S. Chamber of Commerce, Washington, DC']['bag_key']
    assert strings_by_raw['University of California, Los Angeles, CA']['l2_text'] == 'university of california, los angeles'
    assert strings_by_raw['University of California, Los Angeles, CA']['bag_key'] == strings_by_raw['University of California, Los Angeles']['bag_key']
    assert strings_by_raw['Public Policy, Nature Conservancy']['l2_text'] == 'public policy, nature conservancy'
    assert strings_by_raw['Ford Motor Co., Denver, CO']['l2_text'] == 'ford motor'
    assert strings_by_raw['The Inc.']['l2_text'] == 'the inc'  # non-empty fallback
    # Regression assertions: multi-comma before ", Washington, DC", bare City+State preservation,
    # multiset bag multiplicities, and pure-stopword empty-bag fallback.
    assert 'continental airlines' in strings_by_raw['International and Regulatory Affairs, Continental Airlines, Inc., Washington, DC']['l2_text']
    assert strings_by_raw['Malta, Montana']['l2_text'] == 'malta, montana'
    assert strings_by_raw['Malta, Montana']['bag_key'] != strings_by_raw['Malta & Co., Inc.']['bag_key']
    assert (
        strings_by_raw['University of Maryland University College, College Park, MD']['bag_key']
        != strings_by_raw['University of Maryland, College Park, MD']['bag_key']
    )
    assert len(strings_by_raw['Of The']['bag_key']) == 16
    assert strings_by_raw['Of The']['bag_text'] == ''
    assert strings_by_raw['Boulder, CO']['l2_text'] == 'boulder, co'

    orgs = pq.read_table(org_dir_r1 / 'organizations.parquet').to_pylist()
    orgs_by_name = {r['display_name']: r for r in orgs}

    chamber = orgs_by_name.get('Chamber of Commerce, United States') or orgs_by_name.get('The U.S. Chamber of Commerce, Washington, DC') or orgs_by_name.get('Commerce Chamber')
    assert chamber is not None
    assert chamber['appearance_count'] == 3
    assert chamber['taxonomy_parent'] == 'business'
    assert chamber['taxonomy_category'] == 'trade_association'

    assert orgs_by_name['Ford Motor Co., Denver, CO']['taxonomy_parent'] == 'business'
    assert orgs_by_name['Ford Motor Co., Denver, CO']['taxonomy_category'] == 'corporation'
    assert orgs_by_name['AFL-CIO']['taxonomy_parent'] == 'labor'
    assert orgs_by_name['AFL-CIO']['taxonomy_category'] == 'labor_union'
    assert orgs_by_name['Brookings Institution']['taxonomy_parent'] == 'research'
    assert orgs_by_name['Brookings Institution']['taxonomy_category'] == 'think_tank_and_university'
    assert orgs_by_name['Congressional Budget Office']['taxonomy_parent'] == 'congressional'
    assert orgs_by_name['Congressional Budget Office']['taxonomy_category'] == 'congressional'
    assert orgs_by_name['U.S. Department of Energy']['taxonomy_parent'] == 'bureaucrat'
    assert orgs_by_name['U.S. Department of Energy']['taxonomy_category'] == 'bureaucrat'
    assert orgs_by_name['American Bar Association']['taxonomy_parent'] == 'other'
    assert orgs_by_name['American Bar Association']['taxonomy_category'] == 'lawyers_and_lobbyists'
    assert orgs_by_name['Public Policy, Nature Conservancy']['taxonomy_parent'] == 'nonprofit'
    assert orgs_by_name['Public Policy, Nature Conservancy']['taxonomy_category'] == 'nonprofit'

    # on_behalf_of rows exist in witness_organizations alongside organization rows.
    w_orgs = pq.read_table(org_dir_r1 / 'witness_organizations.parquet').to_pylist()
    assert any(r['field'] == 'on_behalf_of' and r['raw_text'] == 'AFL-CIO' for r in w_orgs)
    assert all(r['raw_text'] != '   ' for r in w_orgs)

    # 4. Place/scope exclusions vs valid fuzzy queue pair + candidate pair stats reported.
    queue = pq.read_table(org_dir_r1 / 'org_review_queue.parquet').to_pylist()
    assert len(queue) == 1
    pair = queue[0]
    assert pair['queue_kind'] == 'fuzzy_pair'
    texts = {pair['display_text_a'], pair['display_text_b']}
    assert texts == {
        'American Solar Energy Policy Research Education Advocacy Network',
        'American Solar Energy Policy Research Education Advocacy Networks',
    }
    assert pair['jaccard'] >= 0.75
    assert pair['lev_ratio'] >= 0.85

    result_r1 = json.loads((scratch_r1 / 'result.json').read_text())
    queries_r1 = {q['name']: q['data'] for q in result_r1['queries']}
    assert 'org_fuzzy_candidate_stats' in queries_r1
    cand_stats = queries_r1['org_fuzzy_candidate_stats'][0]
    assert cand_stats['distinct_bags'] >= 10
    assert cand_stats['qualified_candidate_pairs'] == 1
    assert cand_stats['review_queue_pairs'] == 1
    assert cand_stats['organization_count'] == len(orgs)


def test_org_fuzzy_queue_decisions_wikidata_witness_overrides_and_conflicts(tmp_path):
    """Test standalone build_org_entities with fuzzy queueing, same/different/unsure/withdraw
    adjudication, wikidata anchor precedence, witness overrides + witness_key_map remapping,
    and transitive different-conflict detection leaving conflicted nodes unmerged."""
    from viewer_publication.archive_model import build_org_entities

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])

    # Note: identical token spelling on non-differing tokens with single-token diff where overlap >= 4/5 = 0.80:
    # "Center for Renewable Clean Energy Policy" -> {center, clean, energy, policy, renewable}
    # "Center for Renewable Clean Energy Policies" -> Wait: use identical tokens where L2 text differs by typo or punctuation?
    # Better: "American Association of Wind Energy Producers" (5 tokens) vs "American Associations of Wind Energy Producers" ->
    # tokens: {american, association, energy, producers, wind} vs {american, associations, energy, producers, wind}:
    # intersection=4, union=6 -> 0.66. To get Jaccard >= 0.75: 7 distinct tokens + 1 differing = 7/9 = 0.777 >= 0.75!
    # E.g. "American Solar Energy Policy Research Education Advocacy Network" (8 tokens) vs
    #      "American Solar Energy Policy Research Education Advocacy Networks" (intersection=7, union=9, J=0.777, Lev=62/63=0.984)
    # Or "Institute for Clean Air Water Climate Science Policy" (7 tokens: air,clean,climate,institute,policy,science,water)
    # vs "Institute for Clean Air Water Climate Science Policies" (6/8 = 0.75 exactly!)
    app_rows = [
        # Pair 1: merged via 'same' decision
        _app_row('1111111111111111', 'Environmental Clean Air Water Soil Protection Fund'),
        _app_row('1111111111111112', 'Environmental Clean Air Water Soil Protection Funds'),
        # Pair 2: active 'different' ruling -> excluded from queue, kept unmerged
        _app_row('2222222222222221', 'Institute for Clean Air Water Climate Science Policy'),
        _app_row('2222222222222222', 'Institute for Clean Air Water Climate Science Policies'),
        # Pair 3: active 'unsure' hold -> excluded from queue, kept unmerged
        _app_row('3333333333333331', 'Coalition for Public Health Safety Research Policy Reform'),
        _app_row('3333333333333332', 'Coalition for Public Health Safety Research Policy Reforms'),
        # Pair 4: undecided valid candidate pair -> MUST appear in org_review_queue
        _app_row('4444444444444441', 'American Solar Energy Policy Research Education Advocacy Network'),
        _app_row('4444444444444442', 'American Solar Energy Policy Research Education Advocacy Networks'),
        # Place/scope exclusion (West Virginia vs Virginia; both 7+ tokens so Jaccard >= 0.75 otherwise!)
        _app_row('5555555555555551', 'Virginia Alliance Clean Water Renewable Energy Policy'),
        _app_row('5555555555555552', 'West Virginia Alliance Clean Water Renewable Energy Policy'),
        # Wikidata link target
        _app_row('6666666666666661', 'Massachusetts Institute of Technology'),
        # Per-witness overrides (same string "Common Advisory Board" on 3 witnesses):
        _app_row('7777777777777771', 'Common Advisory Board', on_behalf_of='Client Side Org'),
        _app_row('7777777777777772', 'Common Advisory Board'),
        _app_row('7777777777777773', 'Common Advisory Board'),
        # Transitive conflict cluster (bag_h same bag_i, bag_i same bag_j, bag_h different bag_j)
        _app_row('8888888888888881', 'Apex Harbor Logistics Group'),
        _app_row('8888888888888882', 'Summit Ridge Logistics Group'),
        _app_row('8888888888888883', 'Beacon Creek Logistics Group'),
    ]
    app_path = _write_appearance_parquet(tmp_path / 'appearance_records_resolved.parquet', app_rows)

    # First run without decisions to read exact computed bag_keys for our synthetic strings.
    bootstrap_res = build_org_entities(
        appearance_records_resolved=app_path,
        engine=engine,
        output=tmp_path / 'boot_out',
        scratch=tmp_path / 'boot_scratch',
        release_label='boot',
    )
    boot_w = pq.read_table(bootstrap_res['outputs']['witness_organizations.parquet']).to_pylist()
    bag_by_w = {(r['witness_key'], r['field']): r['bag_key'] for r in boot_w}

    b_env1 = bag_by_w[('1111111111111111', 'organization')]
    b_env2 = bag_by_w[('1111111111111112', 'organization')]
    b_inst1 = bag_by_w[('2222222222222221', 'organization')]
    b_inst2 = bag_by_w[('2222222222222222', 'organization')]
    b_coal1 = bag_by_w[('3333333333333331', 'organization')]
    b_coal2 = bag_by_w[('3333333333333332', 'organization')]
    b_mit = bag_by_w[('6666666666666661', 'organization')]
    b_common = bag_by_w[('7777777777777771', 'organization')]
    b_h = bag_by_w[('8888888888888881', 'organization')]
    b_i = bag_by_w[('8888888888888882', 'organization')]
    b_j = bag_by_w[('8888888888888883', 'organization')]

    # witness_key_map remaps an old witness_key -> '7777777777777771'.
    wkm_path = tmp_path / 'witness_key_map.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(old_key='0000000000000099', witness_key='7777777777777771', status='unambiguous'),
    ], schema=pa.schema([('old_key', pa.string()), ('witness_key', pa.string()), ('status', pa.string())])), wkm_path)

    decisions = [
        # Env pair: first marked different, superseded by same, plus wikidata upgrade!
        _make_decision('dec_env_old', f'bag:{b_env1}', 'different', f'bag:{b_env2}', decided_at='2026-11-20T00:00:00Z'),
        _make_decision('dec_env_same', f'bag:{b_env1}', 'same', f'bag:{b_env2}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_env_old'),
        # Different pair (later flipped and then withdrawn to leave 'different' active? Just plain 'different')
        _make_decision('dec_diff', f'bag:{b_inst1}', 'different', f'bag:{b_inst2}'),
        # Unsure pair
        _make_decision('dec_unsure', f'bag:{b_coal1}', 'unsure', f'bag:{b_coal2}'),
        # Wikidata link for MIT
        _make_decision('dec_mit_wd', f'bag:{b_mit}', 'same', 'wikidata:Q49108'),
        # Witness override via remapped old witness key: splits 7771 into MIT without merging Common Advisory Board!
        _make_decision('dec_w_mit', 'witness:0000000000000099', 'same', f'bag:{b_mit}'),
        # Witness negative override: splits 7772 away from Common Advisory Board (leaving 7773 alone in Common)
        _make_decision('dec_w_split', 'witness:7777777777777772', 'different', f'bag:{b_common}'),
        # Temporary merge decision that gets withdrawn (must have zero effect!)
        _make_decision('dec_withdrawn', f'bag:{b_coal1}', 'same', f'bag:{b_mit}', decided_at='2026-11-20T00:00:00Z'),
        _make_decision('dec_withdraw_op', f'bag:{b_coal1}', 'withdraw', f'bag:{b_mit}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_withdrawn'),
        # Transitive conflict on H, I, J
        _make_decision('dec_hi', f'bag:{b_h}', 'same', f'bag:{b_i}'),
        _make_decision('dec_ij', f'bag:{b_i}', 'same', f'bag:{b_j}'),
        _make_decision('dec_hj_diff', f'bag:{b_h}', 'different', f'bag:{b_j}'),
    ]
    dec_file = _write_decisions_jsonl(tmp_path / 'org_decisions.jsonl', decisions)

    res = build_org_entities(
        appearance_records_resolved=app_path,
        witness_key_map=wkm_path,
        org_decision_files=[dec_file],
        engine=engine,
        output=tmp_path / 'out',
        scratch=tmp_path / 'scratch',
        release_label='rel-test',
    )

    stats = res['stats']
    assert stats['qualified_candidate_pairs'] >= 1
    assert stats['review_queue_pairs'] == 1
    assert stats['decision_conflict_items'] == 1

    orgs = {r['org_id']: r for r in pq.read_table(res['outputs']['organizations.parquet']).to_pylist()}
    w_orgs = {(r['witness_key'], r['field']): r for r in pq.read_table(res['outputs']['witness_organizations.parquet']).to_pylist()}
    org_ids = pq.read_table(res['outputs']['organization_ids.parquet']).to_pylist()
    queue = pq.read_table(res['outputs']['org_review_queue.parquet']).to_pylist()
    conflicts = pq.read_table(res['outputs']['org_decisions_conflicts.parquet']).to_pylist()

    # Env pair merged onto decision:dec_env_same
    expected_env_org = _org_sha16('org-v1', 'decision:dec_env_same')
    assert w_orgs[('1111111111111111', 'organization')]['org_id'] == expected_env_org
    assert w_orgs[('1111111111111112', 'organization')]['org_id'] == expected_env_org
    assert orgs[expected_env_org]['anchor'] == 'decision:dec_env_same'

    # Different & Unsure stayed unmerged and excluded from queue
    assert w_orgs[('2222222222222221', 'organization')]['org_id'] != w_orgs[('2222222222222222', 'organization')]['org_id']
    assert w_orgs[('3333333333333331', 'organization')]['org_id'] != w_orgs[('3333333333333332', 'organization')]['org_id']

    # MIT uses wikidata:Q49108 precedence (> decision:) AND 7771 (organization) joined MIT while 7771 (on_behalf_of) kept Client Side Org!
    expected_mit_org = _org_sha16('org-v1', 'wikidata:Q49108')
    assert w_orgs[('6666666666666661', 'organization')]['org_id'] == expected_mit_org
    assert w_orgs[('7777777777777771', 'organization')]['org_id'] == expected_mit_org
    assert w_orgs[('7777777777777771', 'on_behalf_of')]['org_id'] != expected_mit_org
    assert orgs[expected_mit_org]['anchor'] == 'wikidata:Q49108'
    assert ('wikidata', 'Q49108') in {(r['scheme'], r['value']) for r in org_ids if r['org_id'] == expected_mit_org}

    # 7772 split off via 'different', while 7773 kept Common Advisory Board!
    assert w_orgs[('7777777777777772', 'organization')]['org_id'] == _org_sha16('org-v1', 'witness:7777777777777772')
    assert w_orgs[('7777777777777773', 'organization')]['org_id'] == _org_sha16('org-v1', f'bag:{b_common}')

    # Conflicted component (H, I, J) stayed UNMERGED and surfaced conflict in both tables!
    oid_h = w_orgs[('8888888888888881', 'organization')]['org_id']
    oid_i = w_orgs[('8888888888888882', 'organization')]['org_id']
    oid_j = w_orgs[('8888888888888883', 'organization')]['org_id']
    assert len({oid_h, oid_i, oid_j}) == 3
    assert all(orgs[oid]['has_conflict'] is True for oid in (oid_h, oid_i, oid_j))
    assert len(conflicts) == 1
    assert conflicts[0]['decision_id'] == 'dec_hj_diff'

    # Review queue contains exactly 1 conflict item + 1 valid fuzzy pair (Solar Energy Advocacy Network/Networks)
    assert len(queue) == 2
    assert queue[0]['queue_kind'] == 'decision_conflict'
    assert queue[0]['conflict_decision_id'] == 'dec_hj_diff'
    assert queue[1]['queue_kind'] == 'fuzzy_pair'
    assert {queue[1]['display_text_a'], queue[1]['display_text_b']} == {
        'American Solar Energy Policy Research Education Advocacy Network',
        'American Solar Energy Policy Research Education Advocacy Networks',
    }
    assert queue[1]['jaccard'] >= 0.75
    assert queue[1]['lev_ratio'] >= 0.85


def test_org_redirects_merge_split_equal_tie_and_restore_one_hop(tmp_path):
    """Test multi-release 1-hop organization_redirects for merged, split_from (equal-count
    inherited spellings tie-broken by ascending UTF-8 bag_key in BOTH forward & reversed input
    order), restored, and 3-release transitive 1-hop carry."""
    from viewer_publication.archive_model import build_org_entities

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])

    # Base fixture appearances:
    # - Group XY (merge -> withdraw -> restore):
    #   X = "Pacific Solar Alliance", Y = "Pacific Solar Alliances"
    # - Group SPLIT_EQ (merged in rel1, split in rel2 with EQUAL 1 distinct old spelling each):
    #   S1 = "Blue Harbor Maritime", S2 = "Red Mountain Timber"
    # - Group SPLIT_ASYM (merged in rel1, split in rel2 with 2 distinct old spellings vs 1):
    #   A1a = "Silver River Energy", A1b = "Silver River Energy Inc", A2 = "Golden Valley Coal"
    base_rows = [
        _app_row('w_x1', 'Pacific Solar Alliance'),
        _app_row('w_y1', 'Pacific Solar Alliances'),
        _app_row('w_s1', 'Blue Harbor Maritime'),
        _app_row('w_s2', 'Red Mountain Timber'),
        _app_row('w_a1a', 'Silver River Energy'),
        _app_row('w_a1b', 'Silver River Energy, Inc.'),
        _app_row('w_a2', 'Golden Valley Coal'),
    ]
    app_fwd = _write_appearance_parquet(tmp_path / 'app_fwd.parquet', base_rows)
    app_rev = _write_appearance_parquet(tmp_path / 'app_rev.parquet', list(reversed(base_rows)))

    # Probe exact bag_keys first.
    probe = build_org_entities(
        appearance_records_resolved=app_fwd,
        engine=engine,
        output=tmp_path / 'probe_out',
        scratch=tmp_path / 'probe_scratch',
        release_label='probe',
    )
    bags = {r['witness_key']: r['bag_key'] for r in pq.read_table(probe['outputs']['witness_organizations.parquet']).to_pylist()}
    bx, by = bags['w_x1'], bags['w_y1']
    bs1, bs2 = bags['w_s1'], bags['w_s2']
    ba1a, ba1b, ba2 = bags['w_a1a'], bags['w_a1b'], bags['w_a2']
    assert ba1a == ba1b  # Same bag ("silver river energy") with 2 distinct verbatim spellings!
    assert bs1 != bs2

    winner_eq_bag = min(bs1, bs2)
    winner_eq_org = _org_sha16('org-v1', f'bag:{winner_eq_bag}')
    expected_asym_org = _org_sha16('org-v1', f'bag:{ba1a}')
    expected_x_org = _org_sha16('org-v1', f'bag:{bx}')
    expected_y_org = _org_sha16('org-v1', f'bag:{by}')

    # Release 1 decisions: S1+S2 merged (`dec_eq`), A1+A2 merged (`dec_asym`), X and Y separate!
    dec_rel1 = _write_decisions_jsonl(tmp_path / 'dec_rel1.jsonl', [
        _make_decision('dec_eq', f'bag:{bs1}', 'same', f'bag:{bs2}', decided_at='2026-11-20T00:00:00Z'),
        _make_decision('dec_asym', f'bag:{ba1a}', 'same', f'bag:{ba2}', decided_at='2026-11-20T00:00:00Z'),
    ])

    def _run_chain(order_tag: str, app_path: Path):
        rel1 = build_org_entities(
            appearance_records_resolved=app_path,
            org_decision_files=[dec_rel1],
            engine=engine,
            output=tmp_path / f'rel1_{order_tag}',
            scratch=tmp_path / f'scr_rel1_{order_tag}',
            release_label='rel1',
        )
        eq_old_org = _org_sha16('org-v1', 'decision:dec_eq')
        asym_old_org = _org_sha16('org-v1', 'decision:dec_asym')

        # Release 2: withdraw dec_eq & dec_asym (splits!), AND merge X + Y (`dec_merge_xy`)!
        dec_rel2 = _write_decisions_jsonl(tmp_path / f'dec_rel2_{order_tag}.jsonl', [
            _make_decision('dec_eq', f'bag:{bs1}', 'same', f'bag:{bs2}', decided_at='2026-11-20T00:00:00Z'),
            _make_decision('dec_eq_wd', f'bag:{bs1}', 'withdraw', f'bag:{bs2}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_eq'),
            _make_decision('dec_asym', f'bag:{ba1a}', 'same', f'bag:{ba2}', decided_at='2026-11-20T00:00:00Z'),
            _make_decision('dec_asym_wd', f'bag:{ba1a}', 'withdraw', f'bag:{ba2}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_asym'),
            _make_decision('dec_merge_xy', f'bag:{bx}', 'same', f'bag:{by}', decided_at='2026-11-21T00:00:00Z'),
        ])
        rel2 = build_org_entities(
            appearance_records_resolved=app_path,
            org_decision_files=[dec_rel2],
            prior_org_release=rel1['output'],
            engine=engine,
            output=tmp_path / f'rel2_{order_tag}',
            scratch=tmp_path / f'scr_rel2_{order_tag}',
            release_label='rel2',
        )
        red2 = {r['old_org_id']: r for r in pq.read_table(rel2['outputs']['organization_redirects.parquet']).to_pylist()}
        xy_merged_org = _org_sha16('org-v1', 'decision:dec_merge_xy')

        # Verify Release 2 merge + equal-count split tie-break + asymmetric split!
        assert red2[expected_x_org] == dict(old_org_id=expected_x_org, org_id=xy_merged_org, event='merged', release='rel2')
        assert red2[expected_y_org] == dict(old_org_id=expected_y_org, org_id=xy_merged_org, event='merged', release='rel2')
        assert red2[eq_old_org] == dict(old_org_id=eq_old_org, org_id=winner_eq_org, event='split_from', release='rel2')
        assert red2[asym_old_org] == dict(old_org_id=asym_old_org, org_id=expected_asym_org, event='split_from', release='rel2')

        # Release 3: restore X and Y (withdraw dec_merge_xy), AND upgrade winner_eq_bag -> wikidata:Q777777!
        dec_rel3 = _write_decisions_jsonl(tmp_path / f'dec_rel3_{order_tag}.jsonl', [
            _make_decision('dec_eq', f'bag:{bs1}', 'same', f'bag:{bs2}', decided_at='2026-11-20T00:00:00Z'),
            _make_decision('dec_eq_wd', f'bag:{bs1}', 'withdraw', f'bag:{bs2}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_eq'),
            _make_decision('dec_asym', f'bag:{ba1a}', 'same', f'bag:{ba2}', decided_at='2026-11-20T00:00:00Z'),
            _make_decision('dec_asym_wd', f'bag:{ba1a}', 'withdraw', f'bag:{ba2}', decided_at='2026-11-21T00:00:00Z', supersedes='dec_asym'),
            _make_decision('dec_merge_xy', f'bag:{bx}', 'same', f'bag:{by}', decided_at='2026-11-21T00:00:00Z'),
            _make_decision('dec_restore_xy', f'bag:{bx}', 'withdraw', f'bag:{by}', decided_at='2026-11-22T00:00:00Z', supersedes='dec_merge_xy'),
            _make_decision('dec_wiki_eq', f'bag:{winner_eq_bag}', 'same', 'wikidata:Q777777', decided_at='2026-11-22T00:00:00Z'),
        ])
        rel3 = build_org_entities(
            appearance_records_resolved=app_path,
            org_decision_files=[dec_rel3],
            prior_org_release=rel2['output'],
            engine=engine,
            output=tmp_path / f'rel3_{order_tag}',
            scratch=tmp_path / f'scr_rel3_{order_tag}',
            release_label='rel3',
        )
        red3 = {r['old_org_id']: r for r in pq.read_table(rel3['outputs']['organization_redirects.parquet']).to_pylist()}
        live3 = {r['org_id'] for r in pq.read_table(rel3['outputs']['organizations.parquet']).to_pylist()}
        wiki_org = _org_sha16('org-v1', 'wikidata:Q777777')

        # 1. Restored orgs emit 'restored' pointing to self!
        assert red3[expected_x_org] == dict(old_org_id=expected_x_org, org_id=expected_x_org, event='restored', release='rel3')
        assert red3[expected_y_org] == dict(old_org_id=expected_y_org, org_id=expected_y_org, event='restored', release='rel3')
        # 2. Previous merged org splits cleanly in 1 hop to min(bx, by)!
        expected_xy_split_winner = _org_sha16('org-v1', f'bag:{min(bx, by)}')
        assert red3[xy_merged_org] == dict(old_org_id=xy_merged_org, org_id=expected_xy_split_winner, event='split_from', release='rel3')
        # 3. Historical eq_old_org rewrites in 1 hop directly to live wiki_org (zero 2-hop chains)!
        assert red3[winner_eq_org] == dict(old_org_id=winner_eq_org, org_id=wiki_org, event='merged', release='rel3')
        assert red3[eq_old_org] == dict(old_org_id=eq_old_org, org_id=wiki_org, event='merged', release='rel3')
        # Carried asym_old_org keeps its release 'rel2' since target didn't move!
        assert red3[asym_old_org] == dict(old_org_id=asym_old_org, org_id=expected_asym_org, event='split_from', release='rel2')
        # Every redirect target is a live org_id (strictly 1-hop)!
        assert all(row['org_id'] in live3 for row in red3.values())
        return red2, red3

    fwd_r2, fwd_r3 = _run_chain('fwd', app_fwd)
    rev_r2, rev_r3 = _run_chain('rev', app_rev)
    assert fwd_r2 == rev_r2
    assert fwd_r3 == rev_r3


def test_org_sql_explain_plans_clean(tmp_path):
    """Run EXPLAIN on standalone Phase 1 org SQL stages to confirm zero plan errors and no CrossJoin in fuzzy blocking."""
    from congress_api.retention.provenance import explain, json_input
    from viewer_publication.archive_model import ROOT, org_entity_inputs, org_entity_steps

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    app_path = _write_appearance_parquet(
        tmp_path / 'appearance_records_resolved.parquet',
        [
            _app_row('1111111111111111', 'American Clean Air Alliance'),
            _app_row('1111111111111112', 'American Clean Air Alliances'),
        ],
    )
    inputs = [dict(name='appearance_records_resolved', kind='parquet', path=str(app_path))]
    wkm_inp = json_input(tmp_path, 'witness_key_map', [], old_key='Utf8', witness_key='Utf8', status='Utf8')
    inputs.append(wkm_inp)
    inputs += org_entity_inputs(tmp_path, root=ROOT)

    # Check EXPLAIN on org-strings.sql directly over appearance_records_resolved.
    plan_strings = explain(engine, (Path(ROOT) / 'model/sql/org-strings.sql').read_text(), dict(appearance_records_resolved=str(app_path)))
    assert 'physical_plan_error' not in plan_strings
    assert 'CrossJoinExec' not in plan_strings['physical_plan']

    # Check that org_entity_steps contains no duplicate step names and passes model_sql relation checks cleanly.
    from congress_api.lake.model_sql import check_relations
    steps = org_entity_steps(root=ROOT)
    step_names = [s['name'] for s in steps]
    assert len(step_names) == len(set(step_names))
    check_relations(inputs, steps)
