from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from congress_api.retention import (
    WEEKLY_TABLE_KEYS,
    WEEKLY_TABLE_MERGES,
    WEEKLY_TABLE_SCHEMAS,
    WeeklyRetentionTables,
    captions,
    gpo,
    house,
    jsonl,
    meetings,
    rejected_pages,
    senate,
    tables,
    transcripts,
)


def _meeting_record(event_id: str, *, title: str = "Hearing", update_date: str = "2026-01-10T00:00:00Z") -> dict:
    url = f"https://api.congress.gov/v3/committee-meeting/118/house/{event_id}?format=json"
    return {
        "_url": url,
        "eventId": event_id,
        "congress": 118,
        "chamber": "House",
        "title": title,
        "type": "Hearing",
        "date": "2026-01-10T15:00:00Z",
        "meetingStatus": "Scheduled",
        "updateDate": update_date,
        "committees": [{"name": "House Energy", "systemCode": "hsif00"}],
        "meetingDocuments": [],
        "witnessDocuments": [],
        "witnesses": [],
        "videos": [],
    }


def test_weekly_table_schemas_keys_and_merges_cover_all_datasets() -> None:
    expected = {
        "congress_meetings",
        "congress_committees",
        "house_events",
        "senate_events",
        "gpo_hearings",
        "gpo_observations",
        "youtube_videos",
        "captions",
        "transcripts",
        "rejected_pages",
    }
    assert set(WEEKLY_TABLE_SCHEMAS) == expected
    assert set(WEEKLY_TABLE_KEYS) == expected
    assert set(WEEKLY_TABLE_MERGES) == expected
    for dataset in expected:
        schema_names = set(WEEKLY_TABLE_SCHEMAS[dataset].names)
        for key in WEEKLY_TABLE_KEYS[dataset]:
            assert key in schema_names
        merge_spec = WEEKLY_TABLE_MERGES[dataset]
        assert merge_spec["order_by"] in schema_names


def test_incremental_meetings_and_committees_retention_tables(tmp_path: Path) -> None:
    with WeeklyRetentionTables(tmp_path / "docspec-ws") as wt:
        m1 = _meeting_record("115001", title="Original Title", update_date="2026-01-10T00:00:00Z")
        m2 = _meeting_record("115002", title="Second Hearing", update_date="2026-01-11T00:00:00Z")
        records = {m1["_url"]: m1, m2["_url"]: m2}

        parquet_path = tmp_path / "meetings.parquet"
        meetings.write(records, parquet_path, tables=wt)

        # Incremental update of a single meeting key without rewriting all records
        m1_updated = _meeting_record("115001", title="Updated Title", update_date="2026-01-15T00:00:00Z")
        meetings.upsert_meetings({m1_updated["_url"]: m1_updated}, wt)

        # Key-scoped lookup reads only the requested URL
        by_url = meetings.read_by_urls([m1["_url"]], tables=wt)
        assert list(by_url) == [m1["_url"]]
        assert by_url[m1["_url"]]["title"] == "Updated Title"

        # Full streaming read includes both keys with the updated value
        all_rows = meetings.read_meetings(tables=wt)
        assert {r["eventId"]: r["title"] for r in all_rows} == {
            "115001": "Updated Title",
            "115002": "Second Hearing",
        }

        # Parquet file reader also works directly
        parquet_rows = meetings.read_meetings(parquet_path)
        assert [r["eventId"] for r in parquet_rows] == ["115001", "115002"]

        # Committees via jsonl.write
        committees = {
            "https://api.congress.gov/v3/committee/house/hsif00": {
                "systemCode": "hsif00",
                "chamber": "House",
                "name": "Energy and Commerce",
                "updateDate": "2026-01-10T00:00:00Z",
            }
        }
        jsonl.write(
            committees,
            tmp_path / "committees.parquet",
            dataset="congress_committees",
            tables=wt,
        )
        comm_table = wt.read_table("congress_committees")
        assert comm_table.num_rows == 1
        assert comm_table.column("system_code").to_pylist() == ["hsif00"]


def test_incremental_gpo_house_senate_and_youtube_tables(tmp_path: Path) -> None:
    with WeeklyRetentionTables(tmp_path / "docspec-ws") as wt:
        # GPO hearings with UpdateMergeSpec latest_or_backfill
        initial_hearings = {
            "CHRG-118hhrg1": {
                "package_id": "CHRG-118hhrg1",
                "congress": "118",
                "chamber": "HOUSE",
                "committee_name": "Committee on Energy and Commerce",
                "issued_date": "2026-01-10",
                "last_modified": "2026-01-10T00:00:00Z",
                "title": "Initial Title",
                "govinfo_url": "https://www.govinfo.gov/app/details/CHRG-118hhrg1",
            }
        }
        gpo.write_csv(initial_hearings, tmp_path / "gpo.parquet", weekly_tables=wt)

        # Partial update omits committee_name (None), updates title with newer last_modified
        partial_update = {
            "CHRG-118hhrg1": {
                "package_id": "CHRG-118hhrg1",
                "congress": "118",
                "chamber": "HOUSE",
                "committee_name": None,
                "issued_date": "2026-01-10",
                "last_modified": "2026-01-12T00:00:00Z",
                "title": "Revised Title",
            }
        }
        gpo.upsert_hearings(partial_update, wt)
        gpo_table = wt.read_keys("gpo_hearings", ["CHRG-118hhrg1"])
        row = gpo_table.to_pylist()[0]
        assert row["title"] == "Revised Title"
        assert row["committee_name"] == "Committee on Energy and Commerce"

        # GPO observations
        obs = gpo.observation(
            b"<mods/>",
            "https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg1/mods.xml",
            "application/xml",
            retrieved_at="2026-01-10T12:00:00Z",
        )
        gpo_records = {
            "CHRG-118hhrg1": {
                "package_id": "CHRG-118hhrg1",
                "mods_sha256": obs["sha256"],
                "observations": {"mods": obs},
            }
        }
        gpo.write(gpo_records, tmp_path / "gpo_obs.parquet", weekly_tables=wt)
        obs_table = wt.read_keys("gpo_observations", ["CHRG-118hhrg1"])
        assert obs_table.num_rows == 1
        obs_row = obs_table.to_pylist()[0]
        assert obs_row["package_id"] == "CHRG-118hhrg1"
        assert obs_row["retrieved_at"] == "2026-01-10T12:00:00Z"

        # House, Senate, and Inventory state via realistic path-dispatched tables.write_state / tables.read_state
        house_payload = {
            "115001": {
                "imported_at": "2026-01-10T00:00:00Z",
                "witness_status": "present",
                "seed": "research cache",
                "urls": [],
            }
        }
        senate_payload = {
            "www.energy.senate.gov": {
                "pages": {"https://www.energy.senate.gov/hearings/test": {"title": "Senate Hearing"}},
                "listings": {},
                "workflow": {},
            }
        }
        inventory_payload = {
            "youtube": {"vid-abc": "asr"},
            "senate": {"energy011026": "srt"},
            "probes": {"energy|2026-01-10": {"urls": [], "checked": "2026-01-10", "source": "cache"}},
        }
        tables.write_state(tmp_path / "house.json.gz", house_payload, weekly_tables=wt)
        tables.write_state(tmp_path / "senate.json.gz", senate_payload, weekly_tables=wt)
        tables.write_state(tmp_path / "inventory.json.gz", inventory_payload, weekly_tables=wt)

        house_rows = wt.read_keys("house_events", ["115001"]).to_pylist()
        assert len(house_rows) == 1
        assert house_rows[0]["witness_status"] == "present"

        senate_table = wt.read_table("senate_events")
        assert senate_table.num_rows == 1
        assert senate_table.column("domain")[0].as_py() == "www.energy.senate.gov"

        assert tables.read_state(tmp_path / "house.json.gz")["115001"]["witness_status"] == "present"
        assert "www.energy.senate.gov" in tables.read_state(tmp_path / "senate.json.gz")
        loaded_inv = tables.read_state(tmp_path / "inventory.json.gz")
        assert loaded_inv["youtube"]["vid-abc"] == "asr"
        assert loaded_inv["senate"]["energy011026"] == "srt"

        # Verify chunked upsert_rows over a generator does not require materializing all rows at once
        from congress_api.retention.weekly_tables import house_event_to_row

        wt.upsert_rows(
            "house_events",
            (
                house_event_to_row(f"11500{i}", {"imported_at": "2026-01-12T00:00:00Z", "witness_status": "absent"})
                for i in range(2, 7)
            ),
            chunk_size=2,
        )
        assert wt.read_table("house_events").num_rows == 6


def test_incremental_captions_transcripts_and_rejected_pages_tables(tmp_path: Path) -> None:
    with WeeklyRetentionTables(tmp_path / "docspec-ws") as wt:
        # Captions: first a successful observation with kind='asr', then an error receipt
        captions.upsert_captions(
            {
                "youtube": {"vid123": "asr"},
                "caption_observations": {
                    "youtube": {
                        "vid123": {
                            "source": "youtube",
                            "video_id": "vid123",
                            "outcome": "ok",
                            "kind": "asr",
                            "observed_at": "2026-01-10T00:00:00Z",
                            "last_successful": {"observed_at": "2026-01-10T00:00:00Z", "kind": "asr"},
                        }
                    }
                },
            },
            wt,
        )
        # Subsequent transient error receipt without kind or last_successful preserves kind & last_successful_json via latest_or_backfill
        captions.upsert_captions(
            {
                "caption_observations": {
                    "youtube": {
                        "vid123": {
                            "source": "youtube",
                            "video_id": "vid123",
                            "outcome": "error",
                            "observed_at": "2026-01-11T00:00:00Z",
                        }
                    }
                },
            },
            wt,
        )
        cap_rows = wt.read_table("captions").to_pylist()
        assert len(cap_rows) == 1
        assert cap_rows[0]["outcome"] == "error"
        assert cap_rows[0]["kind"] == "asr"
        assert cap_rows[0]["receipt_json"] is not None

        # Transcripts capture
        fake_response = SimpleNamespace(
            text='{"segments": []}',
            sdk_http_response=SimpleNamespace(body='{"candidates": []}'),
        )
        transcripts.retain_response(
            fake_response,
            tmp_path / "transcripts",
            model="gemini-2.5-pro",
            start=0.0,
            end=60.0,
            attempt=1,
            weekly_tables=wt,
        )
        captures = transcripts.read_captures(wt)
        assert len(captures) == 1
        first_capture = next(iter(captures.values()))
        assert first_capture["model"] == "gemini-2.5-pro"

        # Rejected pages
        rejected_pages.retain_rejected_page(
            tmp_path / "meetings.json.gz",
            {"error": "bad gateway"},
            url="https://api.congress.gov/v3/committee-meeting/118",
            offset=250,
            weekly_tables=wt,
        )
        retained_rejected = rejected_pages.read_rejected_pages(weekly_tables=wt)
        assert len(retained_rejected) == 1
        assert retained_rejected[0]["offset"] == 250
        assert retained_rejected[0]["response"] == {"error": "bad gateway"}


def test_sync_weekly_tables_cli_and_explorer_state_pack(tmp_path: Path):
    import gzip
    from committee_explorer.state import pack, unpack
    from congress_api.cli import sync_weekly_tables

    pipeline_dir = tmp_path / "pipeline-data"
    inv_dir = pipeline_dir / "meeting-inventory"
    yt_dir = pipeline_dir / "youtube"
    data_dir = tmp_path / "data"
    inv_dir.mkdir(parents=True)
    yt_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (inv_dir / "house.json.gz").write_bytes(
        gzip.compress(json.dumps({"118555": {"title": "House Hearing", "checked": "2026-10-01"}}).encode())
    )
    (inv_dir / "senate.json.gz").write_bytes(
        gzip.compress(
            json.dumps(
                {
                    "judiciary.senate.gov": {
                        "pages": {"https://www.judiciary.senate.gov/h1": {"title": "Senate Hearing", "checked": "2026-10-01"}}
                    }
                }
            ).encode()
        )
    )
    (inv_dir / "inventory.json.gz").write_bytes(
        gzip.compress(
            json.dumps(
                {
                    "youtube": {"vid01": {"kind": "asr", "checked": "2026-10-01"}},
                    "caption_observations": {"youtube": {"vid01": {"checked_at": "2026-10-01", "outcome": "present"}}},
                }
            ).encode()
        )
    )
    (pipeline_dir / "congress_meetings.jsonl.gz").write_bytes(
        gzip.compress(
            (
                json.dumps(
                    {
                        "_url": "https://api.congress.gov/v3/committee-meeting/118/house/118555",
                        "eventId": "118555",
                        "congress": 118,
                        "chamber": "House",
                        "meetingStatus": "Scheduled",
                    }
                )
                + "\n"
            ).encode()
        )
    )
    (pipeline_dir / "congress_committees.jsonl.gz").write_bytes(
        gzip.compress(
            (
                json.dumps(
                    {
                        "_url": "https://api.congress.gov/v3/committee/118/house/hsju00",
                        "congress": 118,
                        "committee": {
                            "systemCode": "hsju00",
                            "chamber": "House",
                            "updateDate": "2026-10-01T00:00:00Z",
                        },
                    }
                )
                + "\n"
            ).encode()
        )
    )
    (data_dir / "gpo_hearings.csv").write_text(
        "package_id,congress,chamber,committee_code,committee_name,event_id,hearing_dates,held_date,title\n"
        "CHRG-118hhrg1,118,House,hsju00,Judiciary,118555,2024-05-01,2024-05-01,Oversight\n",
        encoding="utf-8",
    )
    (yt_dir / "youtube_00.json").write_text(
        json.dumps({"youtube_videos_@test": {"1": {"videoId": "vid01", "publishedAt": "2026-10-01T00:00:00Z", "title": "Hearing Video"}}}),
        encoding="utf-8",
    )

    ws_dir = tmp_path / "weekly-ws"
    rc = sync_weekly_tables.main(
        [
            "--workspace",
            str(ws_dir),
            "--pipeline-data",
            str(pipeline_dir),
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc == 0

    with WeeklyRetentionTables(ws_dir) as wt:
        assert wt.latest_version("house_events") is not None
        assert wt.latest_version("senate_events") is not None
        assert wt.latest_version("captions") is not None
        assert wt.latest_version("congress_meetings") is not None
        assert wt.latest_version("congress_committees") is not None
        assert wt.latest_version("gpo_hearings") is not None
        assert wt.latest_version("youtube_videos") is not None

    # Verify committee_explorer.state packs and unpacks export-pins.json alongside publication.json
    state_in = tmp_path / "state-in"
    state_packed = tmp_path / "state-packed"
    state_out = tmp_path / "state-out"
    state_in.mkdir()
    (state_in / "ids.json").write_text("{}", encoding="utf-8")
    (state_in / "publication.json").write_text('{"publication_id": "pub1"}', encoding="utf-8")
    (state_in / "export-pins.json").write_text('{"meetings": {"id": "pin1"}}', encoding="utf-8")
    pack(state_in, state_packed)
    assert unpack(state_packed, state_out) is True
    assert json.loads((state_out / "export-pins.json").read_text(encoding="utf-8")) == {"meetings": {"id": "pin1"}}
