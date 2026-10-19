"""Retained YouTube facts have explicit time meanings and bounded evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import csv
import subprocess
import sys

import pytest
from tinydb import TinyDB

from youtube_api.interpretation import source_time, availability_facts
from youtube_api.analyze import main as analyze

NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


@pytest.mark.parametrize('basis', ['playlist_added', 'video_publication'])
def test_adjacent_congress_ranges_count_boundary_videos_once(tmp_path, basis):
    channels = tmp_path / 'channels.csv'
    channels.write_text('committee,systemCode,handle,secondary\nCommittee,hsru00,test,\n')
    with TinyDB(tmp_path / 'youtube_00.json') as db:
        db.table('youtube_videos_test').insert_multiple([
            {'videoId': str(index), 'title': 'EventID', 'description': '',
             'publishedAt': timestamp, 'videoPublishedAt': timestamp}
            for index, timestamp in enumerate([
                '2025-01-02T23:59:59Z', '2025-01-03T00:00:00Z',
                '2025-01-03T12:00:00Z', '2025-01-03T23:59:59Z',
            ])
        ])
    output = tmp_path / 'report.csv'
    analyze.main(output_path=output, tinydb_dir=tmp_path, channels_csv_path=channels,
                 nthreads=1, date_basis=basis)
    with output.open() as stream:
        counts = {row['congress_number']: int(row['total_videos']) for row in csv.DictReader(stream)}
    assert counts['118'] == 1 and counts['119'] == 3
    assert sum(counts.values()) == 4


def test_time_basis_never_substitutes_playlist_addition_for_publication():
    row = {"publishedAt": "2025-01-04T01:00:00Z", "videoPublishedAt": "2024-12-31T23:00:00-05:00"}
    original = deepcopy(row)
    added = source_time(row, basis="playlist_added")
    published = source_time(row, basis="video_publication")
    assert added.field == "publishedAt" and added.original == row["publishedAt"]
    assert published.field == "videoPublishedAt" and published.original == row["videoPublishedAt"]
    assert published.instant == datetime(2025, 1, 1, 4, tzinfo=timezone.utc)
    assert row == original
    assert source_time({"publishedAt": row["publishedAt"]}, basis="video_publication").instant is None


@pytest.mark.parametrize("value", [None, "", "invalid", "2025-01-01T12:00:00", 123])
def test_invalid_or_missing_times_remain_unknown(value):
    assert source_time({"videoPublishedAt": value}, basis="video_publication").instant is None


def test_api_absence_requires_valid_observation_time_and_keeps_its_scope():
    row = {"available": False, "caption": False, "details_checked_at": "2026-09-26T12:00:00Z"}
    facts = availability_facts(row, evaluated_at=NOW)
    assert facts.api.status == "not_found"
    assert facts.api.field == "available"
    assert facts.api.observed_at == datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    assert "videos.list" in facts.api.scope and "web player was not checked" in facts.api.scope
    assert facts.captions.status == "unknown"
    assert "automatic captions" in facts.captions.scope
    for checked in (None, "broken", "2026-09-28T00:00:00Z", "2026-09-26T12:00:00"):
        unknown = availability_facts({**row, "details_checked_at": checked}, evaluated_at=NOW)
        assert unknown.api.status == "unknown" and unknown.api.observed_at is None


@pytest.mark.parametrize("caption", [False, None, "true"])
def test_unconfirmed_captions_do_not_establish_absence(caption):
    assert availability_facts({"caption": caption}, evaluated_at=NOW).captions.status == "unknown"
    assert availability_facts({}, evaluated_at=NOW).captions.field is None
    assert availability_facts({"caption": True}, evaluated_at=NOW).captions.status == "available"


def test_real_analysis_caller_chooses_basis_without_fallback(tmp_path):
    db = TinyDB(tmp_path / 'youtube_00.json')
    rows = [
        {"videoId": "different", "title": "EventID", "description": "", "caption": True,
         "publishedAt": "2025-01-04T00:00:00Z", "videoPublishedAt": "2024-12-31T00:00:00Z"},
        {"videoId": "legacy", "title": "EventID", "description": "", "caption": False,
         "publishedAt": "2025-01-04T00:00:00Z"},
        {"videoId": "end-day", "title": "", "description": "", "caption": None,
         "publishedAt": "2025-01-05T23:59:59Z"},
        {"videoId": "unknown", "title": "", "description": "", "caption": None},
    ]
    db.table("youtube_videos_test").insert_multiple(rows)
    analyze.set_global_tinydb({'committee_name_or_index': 0, 'tinydb_dir': tmp_path})
    args = ("Committee", "test", 119, {"start": "2025-01-03", "end": "2025-01-05"}, "house")
    playlist = analyze.generate_report_for_congress_number(*args, date_basis="playlist_added")
    assert playlist.total_videos == 2 and playlist.with_captions == 1
    assert analyze.generate_report_for_congress_number(*args).total_videos == 2
    publication = analyze.generate_report_for_congress_number(*args, date_basis="video_publication")
    assert publication.total_videos == 0 and publication.with_captions == 0
    assert db.table("youtube_videos_test").all() == rows


def test_analysis_cli_passes_explicit_basis(tmp_path):
    channels = tmp_path / 'channels.csv'
    channels.write_text('committee,systemCode,handle,secondary\nCommittee,hsru00,test,\n')
    with TinyDB(tmp_path / 'youtube_00.json') as db:
        db.table('youtube_videos_test').insert({
            'videoId': 'different', 'title': 'EventID', 'description': '',
            'publishedAt': '2025-01-04T00:00:00Z', 'videoPublishedAt': '2024-12-31T00:00:00Z',
        })
    output = tmp_path / 'report.csv'
    subprocess.run([
        sys.executable, '-m', 'youtube_api.analyze.main', '--date-basis', 'video_publication',
        '--channels-csv-path', str(channels), '--tinydb_dir', str(tmp_path),
        '--output-path', str(output), '--nthreads', '1',
    ], check=True, capture_output=True, text=True)
    with output.open() as stream:
        counts = {row['congress_number']: int(row['total_videos']) for row in csv.DictReader(stream)}
    assert counts['118'] == 1 and counts['119'] == 0


def test_interpretation_imports_only_standard_library():
    import ast
    from pathlib import Path
    import sys
    import youtube_api.interpretation as interpretation
    tree = ast.parse(Path(interpretation.__file__).read_text())
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert all(module.split(".")[0] in sys.stdlib_module_names for module in modules)
