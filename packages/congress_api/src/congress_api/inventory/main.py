"""meeting-inventory: join weekly records after both committee-source readers.

Read Congress.gov meetings, GPO hearings/video matches, YouTube caches, curated
meeting recordings and the six House/Senate CSVs. Write hearing_text_sources.csv,
meetings_without_records.csv, meeting_completeness.csv and meeting_witnesses.csv.
Persist only caption observations, Senate probe answers and parsed witness lists
in --state-dir/inventory.json.gz. No research directory or home cache is required.
--seed-cache is a one-time, read-only import; optional caption-index arguments
import later manual downloads without running a caption fetch or transcription.
"""
import argparse
import datetime as dt
from pathlib import Path

from congress_api import http
from congress_api.committees import codes_of
from congress_api.inventory import captions, completeness, text_sources
from congress_api.inventory.common import read_csv, read_meetings, read_state, source_args, write_csv, write_state
from congress_shared.globals import DEFAULT_CHANNELS_CSV

TEXT_FIELDS = "event_id congress chamber type date committees title gpo_packages youtube_ids senate_urls other_recordings committee_transcripts text_source documents rescheduled_to not_held".split()
NONE_FIELDS = "event_id congress chamber type date committees title documents".split()


def main(meetings, state_dir, output_dir, gpo_path, videos_path, tinydb_dir, recordings,
         channels_csv_path=DEFAULT_CHANNELS_CSV, seed_cache=None, offline=False, as_of=None,
         youtube_caption_index=None, senate_caption_index=None):
    ms, gpo = read_meetings(meetings), read_csv(gpo_path)
    path = state_dir / "inventory.json.gz"
    state = read_state(path)
    captions.import_observations(state, seed_cache, youtube_caption_index, senate_caption_index)
    days = sorted({(comm, m["date"][:10]) for m in ms if not m.get("videos") for comm in text_sources.senate_comms(m, codes_of(m))})
    probes = state.setdefault("probes", {})
    count = 0
    try:
        for comm, day in days:
            key = f"{comm}|{day}"
            if key in probes or (as_of - dt.date.fromisoformat(day)).days < 7:
                continue
            if offline:
                raise RuntimeError(f"Missing saved Senate probe: {key}")
            probes[key] = {"urls": captions.probe_day(comm, day), "checked": as_of.isoformat(), "source": "HEAD"}
            count += 1
        documents = read_csv(output_dir / "house_documents_found.csv") + read_csv(output_dir / "senate_documents_found.csv")
        rows = text_sources.build(ms, gpo, read_csv(channels_csv_path), tinydb_dir, documents,
            read_csv(output_dir / "senate_hearing_pages_found.csv"), read_csv(recordings),
            {(comm, day): probes.get(f"{comm}|{day}", {}).get("urls", []) for comm, day in days}, state.get("youtube", {}), state.get("senate", {}))
        index = {r["event_id"]: r for r in rows}
        recorded = {r["package_id"] for r in read_csv(videos_path) if r["status"] in ("full_recording", "full_recording_offsite")}
        inventory, witnesses = completeness.build(ms, index, recorded, read_csv(output_dir / "house_witnesses_found.csv"),
            read_csv(output_dir / "senate_witnesses_found.csv"), documents, {r["package_id"]: r for r in gpo}, state, as_of, offline, seed_cache)
    finally:
        ## Partial source progress and failed checks survive a local or CI failure.
        write_state(path, state)
    none = [{k: r[k] for k in NONE_FIELDS} for r in rows if r["text_source"] == "no_video" and not r["rescheduled_to"] and not r["not_held"]]
    for name, data, fields in (("hearing_text_sources", rows, TEXT_FIELDS), ("meetings_without_records", none, NONE_FIELDS),
                               ("meeting_completeness", inventory, completeness.FIELDS), ("meeting_witnesses", witnesses, completeness.WITNESS_FIELDS)):
        write_csv(output_dir / f"{name}.csv", data, fields)
        print(f"{name}: {len(data)} rows")
    print(f"Senate probe: {len(days)} committee-days, {count} fetched; HTTP {dict(http.COUNTS)}")


def parse_args_and_run():
    p = argparse.ArgumentParser(description=__doc__)
    source_args(p)
    p.add_argument("--gpo-path", type=Path, required=True)
    p.add_argument("--videos-path", type=Path, required=True)
    p.add_argument("--tinydb_dir", type=Path, required=True)
    p.add_argument("--recordings", type=Path, required=True)
    p.add_argument("--channels-csv-path", type=Path, default=DEFAULT_CHANNELS_CSV)
    p.add_argument("--youtube-caption-index", type=Path)
    p.add_argument("--senate-caption-index", type=Path)
    main(**vars(p.parse_args()))
