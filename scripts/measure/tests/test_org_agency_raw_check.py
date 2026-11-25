"""Tests for scripts/measure/org_agency_raw_check.py (ct-w34j)."""
from __future__ import annotations

import pathlib

import pyarrow as pa
import pyarrow.parquet as pq

from measure import org_agency_raw_check

ROOT = pathlib.Path(__file__).resolve().parents[3]
REFSPEC_TABLES = ROOT / 'model' / 'jobs' / 'refspec' / 'agency-registry-view' / 'tables'


def test_planted_state_epa_link_is_flagged(tmp_path: pathlib.Path):
    """AC #3: planted state-EPA -> federal-EPA link must be flagged by verify_planted_state_epa and run_check."""
    planted = org_agency_raw_check.verify_planted_state_epa(REFSPEC_TABLES)
    assert planted['planted_flagged'] is True
    assert all(c['flagged'] for c in planted['cases'])
    wa_ok, _ = org_agency_raw_check.judge_linked_row(
        raw_text='Environmental Protection Agency, State of Washington',
        anchor='fr_agency:145',
        display_name='Environmental Protection Agency',
        refspec_lookup=None,
    )
    assert wa_ok is False

    # Full table check with clean links passes, then planting a state-EPA -> federal-EPA row fails.
    witnesses_p = tmp_path / 'witnesses.parquet'
    pq.write_table(pa.table({
        'witness_key': ['w_fed', 'w_state'],
        'organization': ['U.S. Environmental Protection Agency', 'Ohio Environmental Protection Agency'],
        'on_behalf_of': [None, None],
        'witness_type': ['Government - Federal', 'Government - State'],
        'source': ['house_xml', 'house_xml'],
    }), witnesses_p)

    rel_dir = tmp_path / 'release'
    rel_dir.mkdir()
    pq.write_table(pa.table({
        'org_id': ['org_fed_epa', 'org_ohio_epa'],
        'display_name': ['Environmental Protection Agency', 'Ohio Environmental Protection Agency'],
        'anchor': ['fr_agency:145', 'bag:ohio_bag'],
    }), rel_dir / 'organizations.parquet')
    pq.write_table(pa.table({
        'witness_key': ['w_fed', 'w_state'],
        'field': ['organization', 'organization'],
        'org_id': ['org_fed_epa', 'org_ohio_epa'],
        'raw_text': ['U.S. Environmental Protection Agency', 'Ohio Environmental Protection Agency'],
    }), rel_dir / 'witness_organizations.parquet')

    clean_report = org_agency_raw_check.run_check(
        witnesses_path=witnesses_p,
        release_dir=rel_dir,
        refspec_tables_dir=REFSPEC_TABLES,
    )
    assert clean_report['wrong_in_sample'] == 0
    assert clean_report['exhaustive_state_leaks_count'] == 0
    assert clean_report['unread_records_count'] == 0

    # Plant state-EPA -> federal-EPA wrong link into release output.
    pq.write_table(pa.table({
        'witness_key': ['w_fed', 'w_state'],
        'field': ['organization', 'organization'],
        'org_id': ['org_fed_epa', 'org_fed_epa'],
        'raw_text': ['U.S. Environmental Protection Agency', 'Ohio Environmental Protection Agency'],
    }), rel_dir / 'witness_organizations.parquet')

    planted_report = org_agency_raw_check.run_check(
        witnesses_path=witnesses_p,
        release_dir=rel_dir,
        refspec_tables_dir=REFSPEC_TABLES,
    )
    assert planted_report['wrong_in_sample'] >= 1
    assert planted_report['exhaustive_state_leaks_count'] == 1
    assert planted_report['wrong_rows'][0]['witness_key'] == 'w_state'


def test_unread_raw_records_are_named(tmp_path: pathlib.Path):
    """Any raw witness text absent from witness_organizations must be explicitly reported."""
    witnesses_p = tmp_path / 'witnesses.parquet'
    pq.write_table(pa.table({
        'witness_key': ['w_missing'],
        'organization': ['U.S. Department of Agriculture'],
        'on_behalf_of': [None],
    }), witnesses_p)
    rel_dir = tmp_path / 'release'
    rel_dir.mkdir()
    pq.write_table(pa.schema([
        ('org_id', pa.string()),
        ('display_name', pa.string()),
        ('anchor', pa.string()),
    ]).empty_table(), rel_dir / 'organizations.parquet')
    pq.write_table(pa.schema([
        ('witness_key', pa.string()),
        ('field', pa.string()),
        ('org_id', pa.string()),
        ('raw_text', pa.string()),
    ]).empty_table(), rel_dir / 'witness_organizations.parquet')

    report = org_agency_raw_check.run_check(
        witnesses_path=witnesses_p,
        release_dir=rel_dir,
        refspec_tables_dir=REFSPEC_TABLES,
    )
    assert report['unread_records_count'] == 1
    assert report['unread_records'][0]['witness_key'] == 'w_missing'
