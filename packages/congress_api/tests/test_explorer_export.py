"""Offline integration checks cover evidence, stable IDs and publication failure."""
import gzip
import json
import socket
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from committee_explorer.export import export
from congress_api.parsers.house import parsed as house_reader_parsed
from congress_api.parsers.xml import parse_xml

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures/meeting_inventory"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_create_connection = socket.create_connection
    real_connect = socket.socket.connect
    def check_create_connection(address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return real_create_connection(address, *args, **kwargs)
        raise AssertionError("offline export attempted network access")
    def check_connect(self, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address)
        raise AssertionError("offline export attempted network access")
    monkeypatch.setattr(socket, "create_connection", check_create_connection)
    monkeypatch.setattr(socket.socket, "connect", check_connect)


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


def published_sources(tmp_path):
    """The current Parquet publication's complete source rows, including retained history sources."""
    import pyarrow.parquet as pq
    pointer = json.loads((tmp_path / "public/CURRENT.json").read_text())
    directory = tmp_path / "public" / Path(pointer["manifest_path"]).parent
    manifest = json.loads((tmp_path / "public" / pointer["manifest_path"]).read_text())
    rows = []
    for part in manifest["partitions"]:
        if part["schema_name"] == "committee_explorer.parquet.source_record":
            rows.extend(pq.read_table(directory / part["path"]).to_pylist())
    return rows


@pytest.mark.parametrize("valid", [True, False])
def test_transcript_snapshot_and_representation_use_one_read(tmp_path, monkeypatch, valid):
    meetings = write_meetings(tmp_path, [native()])
    transcript = tmp_path / "transcript.json"
    payload = {"schema_version": "1.0", "header": {"title": "Retained hearing", "chamber": "house"},
               "participants": {}, "turns": [], "future": {"keep": None}}
    raw = b"\xef\xbb\xbf" + json.dumps(payload, indent=2).encode() if valid else b"{not json}"
    transcript.write_bytes(raw)
    read_bytes = Path.read_bytes

    def changing_file(path):
        data = read_bytes(path)
        if path == transcript:
            # A second read would see a different source than the input snapshot.
            path.write_bytes(b"changed after capture")
        return data

    monkeypatch.setattr(Path, "read_bytes", changing_file)
    manifest, catalog = run(tmp_path, meetings, transcript_files=[transcript])
    snapshot = next(s for s in manifest.inputs if s.provider == "transcript-artifact")
    source = next(s for s in catalog.sources if s.provider == "transcript-artifact")
    representation = next(r for r in catalog.records if r.kind == "representation" and r.retained)
    assert snapshot.artifact.sha256 == source.retained.sha256 == representation.sha256 == sha256(raw).hexdigest()
    assert source.input_snapshot_id == snapshot.id
    assert representation.byte_size == len(raw)
    assert representation.retained.uri == transcript.as_uri()
    assert representation.locations == ()
    if valid:
        assert source.payload == payload
        assert representation.content_schema.version == "1.0"
    else:
        assert source.payload == {"filename": transcript.name}
        assert representation.content_schema is None
        assert any(r.kind == "data_issue" and r.subject.id == representation.id and r.impact == "blocks_use"
                   for r in catalog.records)


def test_native_and_house_preserve_source_shape(tmp_path):
    row = native()
    canceled = {**row, "eventId": "106246", "meetingStatus": "Canceled", "witnesses": [], "relatedItems": {}, "meetingDocuments": []}
    path = write_meetings(tmp_path, [canceled, row])
    root = parse_xml((FIXTURES / "house-formats.xml").read_bytes())
    saved = house_reader_parsed(root, None, "", "absent")
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
    import pyarrow.parquet as pq
    pointer = json.loads((tmp_path / "public/CURRENT.json").read_text())
    directory = tmp_path / "public" / Path(pointer["manifest_path"]).parent
    assert pq.read_table(directory / "meetings.parquet").num_rows == 2
    assert any(p.media_type == "application/vnd.apache.parquet" for p in manifest.partitions)


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
    source = next(s for s in catalog.sources if s.provider == 'congress.gov' and s.payload.get('eventId') == row['eventId'])
    assert len(source.payload["committees"]) == 3


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
    # Issue history retains this decision source; the next export must reuse it
    # from there rather than record the same decision as a new observation.
    _, third = run(tmp_path, path, issue_decisions=decisions)
    replay = next(r for r in third.records if r.kind == 'data_issue' and r.id == original.id)
    assert replay.resolution == closed.resolution
    assert not any(s.provider == 'curated-issue-decisions' for s in third.sources)  # Retained, not reloaded.
    decision_sources = [s for s in published_sources(tmp_path) if s["provider"] == "curated-issue-decisions"]
    assert [s["id"] for s in decision_sources] == [c.source.id for c in closed.resolution.provenance.citations]


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


def test_youtube_cache_preserves_snapshot_channels_rows_and_export_limit(tmp_path):
    folder = tmp_path / "youtube"
    folder.mkdir()
    channels = [{"handle": "@first", "channelId": "UC-first", "title": "Comité", "future": None},
                {"handle": "@second", "channelId": "UC-second"}]
    first = {"videoId": "zzzzzzzzzzz", "title": "Later ID", "future": {"keep": [None, 0]}}
    second = {"videoId": "abcdefghijk", "title": "Earlier ID", "channelId": "UC-native"}
    data = {"youtube_videos_@first": {"7": first}, "youtube_channels": {"3": channels[0], "1": channels[1]},
            "youtube_videos_@second": {"9": second}}
    body = json.dumps(data, ensure_ascii=False, indent=2).encode()
    cache = folder / "youtube_02.json"
    cache.write_bytes(body)
    # Missing indexes are still skipped by the exporter; empty caches are retained.
    empty = folder / "youtube_03.json"
    empty.write_bytes(b"{}")
    manifest, catalog = run(tmp_path, write_meetings(tmp_path, []), youtube_dir=folder, limit=1)
    snapshots = [s for s in manifest.inputs if s.provider == "youtube"]
    assert [s.artifact.sha256 for s in snapshots] == [sha256(body).hexdigest(), sha256(b"{}").hexdigest()]
    sources = [s for s in catalog.sources if s.provider == "youtube"]
    assert sorted((s.payload for s in sources), key=lambda p: json.dumps(p, sort_keys=True)) == sorted(
        [*channels, second], key=lambda p: json.dumps(p, sort_keys=True))
    assert {s.input_snapshot_id for s in sources} == {snapshots[0].id}
    materials = [r for r in catalog.records if r.kind == "material"]
    assert len(materials) == 1 and materials[0].title == "Earlier ID"
    # Table handles are retained channel observations, never injected as row IDs.
    assert next(r for r in catalog.records if r.kind == "channel").identifiers[0].value == "UC-native"
    assert cache.read_bytes() == body
    assert empty.read_bytes() == b"{}"


@pytest.mark.parametrize("body,error", [(b"{not json}", json.JSONDecodeError), (b"[]", AttributeError),
                                       (b'{"youtube_videos_x": []}', AttributeError),
                                       (b'{"youtube_channels": null}', AttributeError)])
def test_youtube_cache_export_keeps_malformed_input_failures(tmp_path, body, error):
    folder = tmp_path / "youtube"
    folder.mkdir()
    cache = folder / "youtube_00.json"
    cache.write_bytes(body)
    with pytest.raises(error):
        run(tmp_path, write_meetings(tmp_path, []), youtube_dir=folder)
    assert cache.read_bytes() == body
    assert not (tmp_path / "public/CURRENT.json").exists()


def test_manifest_parquet_tables_and_docspec_views_resolve_every_record_and_source(tmp_path):
    import pyarrow.parquet as pq
    from committee_explorer.docspec_views import (
        COMMITTEE_ROLLUP_DATASET,
        MEETING_SUMMARY_DATASET,
        ExplorerDocSpecWorkspace,
    )
    from committee_explorer.browser import verify

    path = write_meetings(tmp_path, [native()])
    ds_dir = tmp_path / "docspec-ws"
    manifest, catalog = run(tmp_path, path, docspec_workspace=ds_dir)
    verify(tmp_path / "public")
    pointer = json.loads((tmp_path / "public/CURRENT.json").read_text())
    directory = tmp_path / "public" / Path(pointer["manifest_path"]).parent
    assert not (directory / "catalog.json").exists()
    assert not (directory / "indexes/locations.json").exists()

    published_ids = set()
    for table_file in ("meetings.parquet", "committees.parquet", "materials.parquet", "witnesses.parquet", "issues.parquet", "sources.parquet"):
        assert (directory / table_file).exists()
        for row in pq.read_table(directory / table_file, columns=["id"]).to_pylist():
            published_ids.add(row["id"])
    for record in (*catalog.records, *catalog.sources):
        if record.kind in ("meeting", "committee_term", "material", "appearance", "data_issue", "source_record"):
            assert record.id in published_ids

    pins = json.loads((tmp_path / "state/export-pins.json").read_text())
    assert set(pins) == {"committees", "meetings", "materials", "witnesses", "issues", "sources"}

    # Verify export() automatically populated and refreshed explorer_meeting_summaries & explorer_committee_rollups
    with ExplorerDocSpecWorkspace(ds_dir) as ds_ws:
        summary_pin = ds_ws.latest_pin("explorer_meeting_summaries")
        rollup_pin = ds_ws.latest_pin("explorer_committee_rollups")
        assert summary_pin is not None
        assert rollup_pin is not None
        auto_summaries = ds_ws.datasets.read_arrow(summary_pin).to_pylist()
        assert len(auto_summaries) == 1
        assert auto_summaries[0]["committee"] == "Rules"

        # Also verify multi-observation priority & provenance refresh (including differing committee names on same meeting_id)
        ds_ws.upsert_observations([
            {
                "meeting_id": "m-106245",
                "congress": 115,
                "chamber": "House",
                "committee": "Rules",
                "subcommittee": "Subcommittee",
                "title": "Official Congress.gov Title",
                "date": "2017-07-12",
                "type": "Markup",
                "status": "Scheduled",
                "source_rank": 1,
                "source_id": "src-congress",
                "source_type": "congress.gov",
                "witness_name": "Alex Smith",
            },
            {
                "meeting_id": "m-106245",
                "congress": 115,
                "chamber": "House",
                "committee": "House Committee on Rules",
                "subcommittee": None,
                "title": "Fallback House XML Title",
                "date": "2017-07-12",
                "type": "Markup",
                "status": "Scheduled",
                "source_rank": 2,
                "source_id": "src-house",
                "source_type": "docs.house.gov",
                "witness_name": "Alex Smith",
            },
        ])
        refreshed = ds_ws.refresh_views()
        summary_rows = ds_ws.datasets.read_arrow(refreshed[MEETING_SUMMARY_DATASET]).to_pylist()
        m_rows = [r for r in summary_rows if r["meeting_id"] == "m-106245"]
        assert len(m_rows) == 1
        m_row = m_rows[0]
        assert m_row["committee"] == "Rules"
        assert m_row["title"] == "Official Congress.gov Title"
        assert m_row["witnesses_with_provenance"][0]["value"] == "Alex Smith"
        rollup_rows = ds_ws.datasets.read_arrow(refreshed[COMMITTEE_ROLLUP_DATASET]).to_pylist()
        assert len(rollup_rows) >= 1


def test_spilled_sources_and_sharded_docspec_publication_keep_checksums(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from committee_explorer.assemble import _SOURCE_CACHE_LIMIT, SpilledSourceSequence, _SpilledSources
    from committee_explorer.docspec_views import ExplorerDocSpecWorkspace
    from committee_explorer.parquet import SOURCE_SCHEMA, TABLE_SCHEMAS
    from committee_meeting.provenance import Identifier, SourceRecord

    spilled = _SpilledSources()
    total = _SOURCE_CACHE_LIMIT + 300
    for i in range(total):
        rec = SourceRecord(
            id=f"src-{i:04d}",
            provider="congress.gov" if i % 2 == 0 else "govinfo",
            input_snapshot_id=f"snap-{i % 3}",
            identifier=Identifier(scheme="test", value=str(i)),
            payload={"index": i},
        )
        spilled[("source_record", rec.id)] = rec

    assert len(spilled) == total
    assert len(spilled._cache) <= _SOURCE_CACHE_LIMIT
    seq = SpilledSourceSequence(spilled)
    assert len(seq) == total
    assert seq.provider_counts() == {"congress.gov": total // 2, "govinfo": total - total // 2}
    assert seq.input_snapshot_ids() == {"snap-0", "snap-1", "snap-2"}
    assert seq[0].id == "src-0000"
    assert seq[-1].id == f"src-{total - 1:04d}"
    assert [r.id for r in seq[:3]] == ["src-0000", "src-0001", "src-0002"]
    spilled.close()

    # Verify multi-shard sources-1.parquet / sources-2.parquet export and byte-identical preservation
    stage = tmp_path / "stage"
    stage.mkdir()
    for kind, fname in (
        ("committee_term", "committees.parquet"),
        ("meeting", "meetings.parquet"),
        ("material", "materials.parquet"),
        ("appearance", "witnesses.parquet"),
        ("data_issue", "issues.parquet"),
    ):
        pq.write_table(pa.Table.from_pylist([], schema=TABLE_SCHEMAS[kind]), stage / fname)
    for shard_idx in (1, 2):
        pq.write_table(
            pa.Table.from_pylist([{"id": f"s-{shard_idx}", "kind": "source_record", "provider": "test"}], schema=SOURCE_SCHEMA),
            stage / f"sources-{shard_idx}.parquet",
        )
    before_bytes = {p.name: p.read_bytes() for p in stage.glob("*.parquet")}
    with ExplorerDocSpecWorkspace(tmp_path / "ds-sharded") as ds_ws:
        pins = ds_ws.export_browser_publication(stage)
    after_bytes = {p.name: p.read_bytes() for p in stage.glob("*.parquet")}
    assert before_bytes == after_bytes
    assert set(pins["sources"]) == {"sources-1", "sources-2"}


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


def test_direct_committee_documents_do_not_claim_a_meeting_match(tmp_path):
    import csv
    row = native()
    path = tmp_path / 'gpo.csv'
    base = {'congress': '115', 'chamber': 'House', 'committee_code': 'hsru00',
            'committee_name': 'Rules', 'event_id': '', 'hearing_dates': '',
            'held_date': '2017-07-12', 'title': row['title']}
    packages = [dict(base, package_id='CHRG-115hhrg100', event_id=row['eventId']),
                dict(base, package_id='CHRG-115hhrg200', held_date='2017-01-01')]
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=packages[0])
        writer.writeheader()
        writer.writerows(packages)
    _, catalog = run(tmp_path, write_meetings(tmp_path, [row]), gpo_path=path)
    materials = {r.identifiers[0].value: r for r in catalog.records
                 if r.kind == 'material' and r.identifiers and r.identifiers[0].scheme == 'govinfo.package'}
    unmatched = materials['CHRG-115hhrg200']
    links = [r for r in catalog.records if r.kind == 'material_link' and r.material.id == unmatched.id]
    assert {r.subject.kind for r in links} == {'committee_term'}
    issue = next(r for r in catalog.records if r.kind == 'data_issue' and r.subject.id == unmatched.id and r.category == 'unlinked')
    assert issue.status == 'open'


def test_official_senate_event_exports_without_a_native_meeting(tmp_path):
    url = 'https://www.indian.senate.gov/hearings/source-roundtable/'
    state = tmp_path / 'senate.json.gz'
    event = {'title': 'Roundtable on tribal infrastructure', 'date': '2026-08-26',
             'date_text': 'August 26, 2026', 'type': 'Roundtable', 'url': url}
    state.write_bytes(gzip.compress(json.dumps({'indian.senate.gov': {
        'pages': {url: {'title': event['title'], 'event': event, 'events': [], 'documents': [], 'witnesses': []}}
    }}).encode()))
    _, catalog = run(tmp_path, write_meetings(tmp_path, []), senate_state=state)
    meeting, = [r for r in catalog.records if r.kind == 'meeting']
    assert meeting.meeting_type == 'roundtable'
    assert meeting.congress == 119
    assert meeting.identifiers[0].scheme == 'senate.committee:page'
    term = next(r for r in catalog.records if r.kind == 'committee_term' and r.id == meeting.committees[0].committee.id)
    assert term.identifiers[0].value == 'slia00'
    assert term.committee_type == 'other'


def test_roundtable_enrichment_keeps_the_committee_source_selection(tmp_path):
    row = {**native(), 'chamber': 'Senate', 'congress': 119, 'type': 'Hearing',
           'committees': [{'systemCode': 'slia00', 'name': 'Indian Affairs'}]}
    url = 'https://www.indian.senate.gov/hearings/source-roundtable/'
    state = tmp_path / 'senate.json.gz'
    page = {'title': 'Roundtable', 'event': {'title': 'Roundtable', 'date': '2026-08-04',
            'type': 'Roundtable', 'url': url}, 'events': [row['eventId']], 'documents': [], 'witnesses': []}
    state.write_bytes(gzip.compress(json.dumps({'indian.senate.gov': {'pages': {url: page}}}).encode()))
    _, catalog = run(tmp_path, write_meetings(tmp_path, [row]), senate_state=state)
    meeting, = [r for r in catalog.records if r.kind == 'meeting']
    assert meeting.meeting_type == 'roundtable'
    field = next(f for f in meeting.field_evidence if f.path == '/meeting_type')
    citation, = field.selected.citations
    source = next(s for s in catalog.sources if s.id == citation.source.id)
    assert source.provider == 'senate.committees'
    assert citation.selector == '/event/type'
    assert source.payload['event']['type'] == 'Roundtable'
    assert {a.value for a in field.alternatives} == {'hearing'}
    assert 'convening committee' in field.selection_reason


def test_official_nominee_csv_and_senate_state_share_one_appearance(tmp_path):
    import csv

    url = 'https://www.indian.senate.gov/hearings/nomination-hearing-to-consider-mark-cruz-to-be-director-of-the-indian-health-service-department-of-health-and-human-services/'
    row = {'_url': 'https://api.congress.gov/v3/committee-meeting/119/senate/338584',
           'eventId': '338584', 'congress': 119, 'chamber': 'Senate', 'date': '2026-06-24T14:00:00Z',
           'title': 'Hearings to examine the nomination of Mark Cruz, of Oregon, to be Director of the Indian Health Service, Department of Health and Human Services.',
           'type': 'Open Hearing', 'meetingStatus': 'Scheduled',
           'committees': [{'systemCode': 'slia00', 'name': 'Senate Indian Affairs'}]}
    witness = {'name': 'Mark Cruz', 'position': 'Nominee, Director of the Indian Health Service',
               'organization': 'U.S. Department of Health and Human Services, Salem, Oregon', 'page': url}
    state = tmp_path / 'senate.json.gz'
    state.write_bytes(gzip.compress(json.dumps({'indian.senate.gov': {'pages': {url: {
        'title': 'Nomination Hearing to consider Mark Cruz', 'events': ['338584'], 'documents': [], 'witnesses': [witness]
    }}}}).encode()))
    recovered = tmp_path / 'meeting_witnesses.csv'
    csv_row = {key: witness[key] for key in ('name', 'position', 'organization')}
    csv_row.update(event_id='338584', source='senate committee page', **{'from': url})
    with recovered.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_row))
        writer.writeheader()
        writer.writerow(csv_row)

    _, catalog = run(tmp_path, write_meetings(tmp_path, [row]), senate_state=state, recovered_witnesses=recovered)
    appearance, = [record for record in catalog.records if record.kind == 'appearance']
    assert appearance.name.display == witness['name']
    assert appearance.affiliation.position == witness['position']
    assert appearance.roles == ('witness', 'nominee')
    sources = {source.id: source for source in catalog.sources}
    assert {sources[citation.source.id].provider for citation in appearance.provenance.citations} == {'senate.committees', 'recovered-witnesses'}
