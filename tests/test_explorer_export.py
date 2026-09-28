"""Offline integration checks cover evidence, stable IDs and publication failure."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import socket

import pytest

from committee_explorer.export import export
from congress_api.house import records as house_reader
from congress_api.xml import parse_xml

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures/meeting_inventory"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline export attempted network access")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def write_meetings(tmp_path, rows):
    path = tmp_path / "meetings.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(r).encode() for r in rows)))
    return path


def native():
    return {"_url": "https://api.congress.gov/v3/committee-meeting/115/house/106245", "eventId": "106245", "congress": 115,
            "chamber": "House", "title": "Rules consideration", "type": "Markup", "meetingStatus": "Scheduled", "date": "2017-07-12T15:00:00Z",
            "committees": [{"systemCode": "hsru00", "name": "Rules"}, {"systemCode": "hsru01", "name": "Subcommittee"}],
            "witnesses": [{"name": "Alex Smith", "organization": "First office"}],
            "meetingDocuments": [{"name": "Listed statement without file", "documentType": "Statement"}],
            "relatedItems": {"bills": [{"type": "HR", "number": "2810", "congress": 115}, {"type": "HR", "number": "5", "congress": 115}]}}


def run(tmp_path, path, **kw):
    return export(meetings=path, output_dir=tmp_path / "public", state_dir=tmp_path / "state", as_of=NOW, **kw)


def test_native_and_house_preserve_source_shape(tmp_path):
    row = native()
    canceled = {**row, "eventId": "106246", "meetingStatus": "Canceled", "witnesses": [], "relatedItems": {}, "meetingDocuments": []}
    path = write_meetings(tmp_path, [canceled, row])
    root = parse_xml((FIXTURES / "house-formats.xml").read_bytes())
    saved = house_reader.parsed(root, None, "", "absent")
    state = tmp_path / "house.json.gz"
    state.write_bytes(gzip.compress(json.dumps({"106245": saved}).encode()))
    manifest, catalog = run(tmp_path, path, house_state=state)
    assert len([r for r in catalog.records if r.kind == "meeting"]) == 2
    assert any(r.kind == "occurrence" and r.status == "canceled" for r in catalog.records)
    assert len([r for r in catalog.records if r.kind == "legislative_item"]) == 2
    expected = {f.get("doc-url") for f in root.iter("file")}
    urls = {loc.url for r in catalog.records if r.kind == "representation" for loc in r.locations}
    assert urls == expected
    assert len([r for r in catalog.records if r.kind == "material" and r.title == "Listed statement without file"]) == 1
    assert all(s.retrieved_at is None for s in catalog.sources)
    assert any(s.status == "not_collected" and s.provider == "transcript-artifact" for s in manifest.source_scopes)
    pointer = json.loads((tmp_path / "public/CURRENT.json").read_text())
    directory = tmp_path / "public" / Path(pointer["manifest_path"]).parent
    index = json.loads((directory / "indexes/meetings.json").read_text())
    assert len(index["rows"]) == 2
    assert all(p.media_type == "application/json" for p in manifest.partitions)


def test_ids_survive_reorder_and_mutable_facts(tmp_path):
    a, b = native(), {**native(), "eventId": "106246", "witnesses": []}
    path = write_meetings(tmp_path, [a, b])
    _, first = run(tmp_path, path)
    a["title"] = "Updated title"
    a["witnesses"][0]["organization"] = "New reported affiliation"
    write_meetings(tmp_path, [b, a])
    _, second = run(tmp_path, path)
    for kind in ("meeting", "occurrence", "appearance", "committee", "committee_term"):
        assert {r.id for r in first.records if r.kind == kind} == {r.id for r in second.records if r.kind == kind}


def test_failed_export_does_not_replace_working_pointer(tmp_path):
    path = write_meetings(tmp_path, [native()])
    run(tmp_path, path)
    pointer = (tmp_path / "public/CURRENT.json").read_bytes()
    write_meetings(tmp_path, [{**native(), "congress": 0}])
    with pytest.raises(ValueError):
        run(tmp_path, path)
    assert (tmp_path / "public/CURRENT.json").read_bytes() == pointer


def test_repeated_issue_keeps_identity_and_detection_time(tmp_path):
    row = native()
    row["date"] = "invalid date"
    path = write_meetings(tmp_path, [row])
    _, first = run(tmp_path, path)
    _, second = export(meetings=path, output_dir=tmp_path / "public", state_dir=tmp_path / "state", as_of=NOW.replace(day=28))
    issues1 = {r.id: r.detected_at for r in first.records if r.kind == "data_issue"}
    issues2 = {r.id: r.detected_at for r in second.records if r.kind == "data_issue"}
    assert issues1 == issues2


def test_omitted_issue_is_not_silently_closed(tmp_path):
    row = native()
    row["date"] = "invalid date"
    path = write_meetings(tmp_path, [row])
    _, first = run(tmp_path, path)
    row["date"] = "2017-07-12"
    write_meetings(tmp_path, [row])
    _, second = run(tmp_path, path)
    assert {r.id for r in first.records if r.kind == "data_issue"} <= {r.id for r in second.records if r.kind == "data_issue" and r.status == "open"}


def test_bounded_export_declares_selected_population(tmp_path):
    path = write_meetings(tmp_path, [native(), {**native(), "eventId": "106246"}])
    manifest, catalog = run(tmp_path, path, limit=1)
    assert manifest.source_scopes[0].status == "partial"
    assert len([r for r in catalog.records if r.kind == "meeting"]) == 1


def test_native_repeated_committee_retains_evidence_without_duplicate_link(tmp_path):
    row = native()
    row["committees"].append(row["committees"][0])
    _, catalog = run(tmp_path, write_meetings(tmp_path, [row]))
    meeting = next(r for r in catalog.records if r.kind == "meeting")
    assert len(meeting.committees) == 2
    assert any(r.kind == "data_issue" and r.category == "duplicate" for r in catalog.records)
    assert len(catalog.sources[0].payload["committees"]) == 3


def test_documented_issue_resolution_retains_original_evidence(tmp_path):
    row = native()
    row["date"] = "invalid"
    path = write_meetings(tmp_path, [row])
    _, first = run(tmp_path, path)
    original = next(r for r in first.records if r.kind == "data_issue")
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([{"issue_id": original.id, "status": "dismissed", "explanation": "The source intentionally gives no usable date; preserve the limitation."}]))
    _, second = run(tmp_path, path, issue_decisions=decisions)
    closed = next(r for r in second.records if r.kind == "data_issue" and r.id == original.id)
    assert closed.status == "dismissed"
    assert closed.provenance == original.provenance
    assert closed.resolution.provenance.basis == "curated"
    assert closed.detected_at == original.detected_at


def test_explicit_youtube_id_unifies_native_link_and_cache_metadata(tmp_path):
    row = native()
    row["videos"] = [{"url": "https://www.youtube.com/watch?v=abcdefghijk"}]
    folder = tmp_path / "youtube"
    folder.mkdir()
    (folder / "youtube_00.json").write_text(json.dumps({"youtube_videos_channel": {"1": {"videoId": "abcdefghijk", "title": "Full hearing", "caption": False, "duration": 90}}}))
    _, catalog = run(tmp_path, write_meetings(tmp_path, [row]), youtube_dir=folder)
    materials = [r for r in catalog.records if r.kind == "material" and r.details.type == "recording"]
    assert len(materials) == 1
    assert materials[0].title == "Full hearing"
    assert not any(r.kind == "data_issue" and r.category == "unlinked" and r.subject.id == materials[0].id for r in catalog.records)


def test_manifest_locations_resolve_every_record_and_source(tmp_path):
    import hashlib
    path = write_meetings(tmp_path, [native()])
    manifest, catalog = run(tmp_path, path)
    pointer = json.loads((tmp_path / "public/CURRENT.json").read_text())
    directory = tmp_path / "public" / Path(pointer["manifest_path"]).parent
    descriptor = json.loads((directory / "indexes/locations.json").read_text())
    assert descriptor["bucket_algorithm"] == "sha256-prefix-2"
    buckets = {b: json.loads((directory / p).read_text())["locations"] for b,p in descriptor["buckets"].items()}
    for record in (*catalog.records, *catalog.sources):
        key = record.kind + "/" + record.id
        bucket = hashlib.sha256(key.encode()).hexdigest()[:2]
        chunk = json.loads((directory / buckets[bucket][key]).read_text())
        assert any(r["id"] == record.id and r["kind"] == record.kind for r in chunk.get("records", chunk.get("sources", [])))
    for part in manifest.partitions:
        if part.role in ("details", "sources"):
            assert part.byte_size <= descriptor["chunk_byte_budget"]
    from committee_meeting import Catalog
    reread = Catalog.model_validate_json((directory / "catalog.json").read_bytes())
    assert reread == catalog


def test_curated_recordings_retain_evidence_and_reuse_video_identity(tmp_path):
    import csv
    row = native()
    row['videos'] = [{'url': 'https://www.youtube.com/watch?v=abcdefghijk'}]
    path = write_meetings(tmp_path, [row])
    recordings = tmp_path / 'recordings.csv'
    with recordings.open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['event_id', 'recording', 'found_by', 'note'])
        writer.writeheader()
        writer.writerow({'event_id': row['eventId'], 'recording': 'abcdefghijk', 'found_by': 'manual review', 'note': 'Preserve the association\nexplanation.'})
        writer.writerow({'event_id': '999999', 'recording': 'https://example.org/video', 'found_by': 'event page', 'note': 'Unlinked source.'})
    _, catalog = run(tmp_path, path, recordings_path=recordings)
    materials = [r for r in catalog.records if r.kind == 'material' and r.details.type == 'recording']
    assert len(materials) == 2
    links = [r for r in catalog.records if r.kind == 'material_link' and r.role == 'recording']
    assert len(links) == 1
    assert links[0].coverage == 'unknown'
    assert any(s.provider == 'curated-recordings' and s.payload['note'] == 'Preserve the association\nexplanation.' for s in catalog.sources)
    assert any(r.kind == 'data_issue' and r.category == 'unlinked' for r in catalog.records)
