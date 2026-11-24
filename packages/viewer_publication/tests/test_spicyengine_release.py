"""Release pinning, resumable preparation, and visible document identities."""
import json
from datetime import date
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication import spicyengine_release as release
from viewer_publication.archive_format import release_identity


@pytest.mark.parametrize("committee_directory", [True, False])
def test_publication_replay(tmp_path, monkeypatch, committee_directory):
    archive = tmp_path / "origin" / "viewer-publications"
    stage = archive / "releases" / "staging"
    stage.mkdir(parents=True)
    text_dir = tmp_path / "origin" / "derived" / "body_text"
    text_dir.mkdir(parents=True)
    body_key = bytes.fromhex("ab" * 32)
    doc = dict(link_key=b"12345678", saved_body=body_key, hidden=False, saved_suffix=".gz",
               title="Housing report", filename="report.pdf", package_id="HR-1", format="pdf",
               document_date=date(2026, 11, 20), document_date_status="accepted", congress=119, chambers=["house"],
               committee_keys=["hsap00", "ssap00", "retired", "other1", "other2"], document_kind="report", document_family="legislative",
               src_start=0, src_len=2)
    detail = pa.Table.from_pylist([doc, doc | {"link_key": b"87654321", "src_start": 2, "src_len": 1, "saved_suffix": ""}, doc | {"hidden": True},
                                   doc | {"link_key": b"no-text!", "saved_body": None}])
    pq.write_table(detail, stage / "detail.parquet")
    pq.write_table(pa.Table.from_pylist([
        dict(ordinal=0, url="https://example.gov/a.pdf", listed_on=None, link_text="Report", member_path=None, is_saved=True),
        dict(ordinal=1, url="https://example.gov/alternate.pdf", listed_on="https://example.gov/hearing", link_text="Exhibit", member_path=None, is_saved=False),
        dict(ordinal=0, url="https://example.gov/hearing.zip", listed_on=None, link_text="Archive", member_path="a.pdf", is_saved=True),
    ]), stage / "sources.parquet")
    if committee_directory:
        house = dict(system_code="hsap00", chamber="house", name="Appropriations Committee",
                     names=[{"name": "Committee on Appropriations"}, {"name": "Former Appropriations Panel"}])
        other = dict(system_code="other1", chamber="joint", name="Joint Example Committee", names=[])
        rows = [house, house | {"system_code": "ssap00", "chamber": "senate"}, other, other | {"system_code": "other2"},
                house | {"system_code": "retired", "name": "House Historical Committee", "names": []},
                house | {"system_code": "unused"}]
        pq.write_table(pa.Table.from_pylist(rows), stage / "committees.parquet")
    files = []
    for f in sorted(stage.glob("*.parquet")):
        raw = f.read_bytes()
        files.append(dict(name=f.name, sha256=sha256(raw).hexdigest(), size=len(raw), rows=pq.read_metadata(f).num_rows))
    release_id = release_identity(1, files)
    manifest = dict(schema_version=1, files=files, release_id=release_id)
    (stage / "manifest.json").write_text(json.dumps(manifest))
    stage.rename(stage.with_name(release_id))
    (archive / "manifest.json").write_text(json.dumps({"release_id": release_id}))
    body = text_dir / "body.parquet"
    pq.write_table(pa.Table.from_pylist([dict(saved_body=body_key, text="housing evidence", page_offsets=[0], text_sha256=b"X"*32)]), body)
    digest = sha256(body.read_bytes()).hexdigest()
    detail_entry = next(f for f in files if f["name"] == "detail.parquet")
    pointer = dict(release_id=release_id, sha256=digest, bytes=body.stat().st_size,
                   key=f"derived/body_text/{digest}.parquet", detail={k: detail_entry[k] for k in ("sha256","size")})
    body.rename(text_dir / f"{digest}.parquet")
    (text_dir / "current.json").write_text(json.dumps(pointer))
    origin = (tmp_path / "origin").as_uri()
    root = tmp_path / "local"
    work = release.update(root, origin=origin)
    rows = pq.read_table(work / "prepared").to_pylist()
    assert len(rows) == 3 and len({r["member_key"] for r in rows}) == 3
    assert rows[0]["document_date"] == date(2026, 11, 20)
    assert sum(r["body"] == "housing evidence" and r["page_offsets"] == [0] for r in rows) == 2
    assert sum(r["text_status"] == "No text in this export" for r in rows) == 1
    by_key = {r["member_key"]: r for r in rows}
    primary = by_key[b"12345678".hex()]
    assert primary["listed_on"] == "https://example.gov/hearing" and primary["pdf_url"] == "https://example.gov/a.pdf"
    child = by_key[b"87654321".hex()]
    assert child["listed_on"] is None and child["pdf_url"] == f"{release.ORIGIN}/bodies/sha256/ab/{body_key.hex()}"
    definition = json.loads((work / "dataset.json").read_text())
    assert definition["release_id"] == release_id
    if committee_directory:
        assert definition["facet_labels"]["committee_keys"] == {
            "hsap00": "House Committee on Appropriations", "ssap00": "Senate Committee on Appropriations",
            "retired": "House Historical Committee", "other1": "Joint Example Committee (other1)",
            "other2": "Joint Example Committee (other2)"}
        assert definition["facet_aliases"]["committee_keys"]["hsap00"] == ["Appropriations Committee", "Former Appropriations Panel"]
    else:
        assert "committee_keys" not in definition["facet_labels"]
    assert definition["facet_labels"]["chambers"]["house"] == "House"
    assert definition["facet_labels"]["document_kind"]["questions-for-record"] == "Questions for the Record"
    assert definition["facet_help"]["document_family"]["description"] != definition["facet_help"]["document_kind"]["description"]
    assert primary["committee_keys"] == doc["committee_keys"]
    assert definition["excerpt_key"] == "text_sha256" and primary["text_sha256"] == (b"X"*32).hex()
    assert definition["fields"]["listed_on"] == "listed_on" and definition["fields"]["pdf_url"] == "pdf_url"
    assert "source_links" not in definition and not (work / "source-links.parquet").exists()
    assert not list((work / "downloads").glob("*.parquet"))
    (text_dir / f"{digest}.parquet").unlink()
    # Upgrade a release prepared before committee names shipped, with its document input offline.
    (work / "prepared.json").write_text(json.dumps({"records": len(rows)}))
    shard = next((work / "prepared").glob("*.parquet"))
    shard_time = shard.stat().st_mtime_ns
    if committee_directory:
        wrong = tmp_path / "wrong-release"
        wrong.mkdir()
        (wrong / "committees.parquet").write_bytes(b"unrelated release")
        with pytest.raises(ValueError, match="Local committees.parquet differs"):
            release.update(root, origin=origin, saved=work / "pin.json", local=wrong)
    assert release.update(root, origin=origin, saved=work / "pin.json") == work
    assert shard.stat().st_mtime_ns == shard_time
    assert json.loads((work / "dataset.json").read_text()) == definition
    # An already-prepared v1 index is replayed without reading or rebuilding bodies.
    old = root / "search-v1" / release_id / digest
    old.mkdir(parents=True)
    (old / "prepared.json").write_text((work / "prepared.json").read_text())
    assert release.update(root, origin=origin, saved=work / "pin.json") == old
    old_links = {r["id"].split(":")[1]:r for r in pq.read_table(old / "source-links.parquet").to_pylist()}
    for key, row in by_key.items():
        assert (row["listed_on"],row["pdf_url"]) == (old_links.get(key,{}).get("listed_on"),old_links.get(key,{}).get("pdf_url"))
    assert json.loads((old / "dataset.json").read_text())["source_links"] == str(old / "source-links.parquet")
    (text_dir / "current.json").write_text(json.dumps(pointer | {"release_id": "0"*64}))
    with pytest.raises(ValueError, match="same immutable release"):
        release.update(root, origin=origin)
    def unexpected(*args):
        raise AssertionError("Pinned replay reopened upstream data")
    monkeypatch.setattr(release, "open_object", unexpected)
    assert release.update(root, origin=origin, saved=work / "pin.json") == old


def test_document_filter_help_covers_classification_families():
    from house_naming import document_families

    vocabulary = release.filter_vocabulary({})
    labels, help_text = vocabulary["facet_labels"], vocabulary["facet_help"]
    assert set(document_families(labels["document_kind"])) <= set(labels["document_family"])
    for field in ("document_family", "document_kind"):
        assert labels[field].keys() == help_text[field]["values"].keys()
        assert all(value.strip() for value in help_text[field]["values"].values())
    assert labels["document_kind"]["crs-report"] == "CRS Report"
    assert help_text["document_family"]["values"]["statement"] != help_text["document_kind"]["values"]["statement"]


def test_transfer_resumes_a_pinned_partial(tmp_path, monkeypatch):
    from io import BytesIO

    payload = b"complete congressional export"
    target = tmp_path / "body.parquet"
    target.with_suffix(".part").write_bytes(payload[:8])
    offsets = []

    class Remainder(BytesIO):
        status = 206
        headers = {"Content-Range": f"bytes 8-{len(payload)-1}/{len(payload)}"}

    def resume(origin, key, offset):
        offsets.append(offset)
        return Remainder(payload[offset:])

    monkeypatch.setattr(release, "open_object", resume)
    release.download("unused", "object", target, sha256(payload).hexdigest(), len(payload))
    assert offsets == [8] and target.read_bytes() == payload
