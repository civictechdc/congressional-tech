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


def test_staged_resolution_prefers_active_staged_and_rejects_mismatch(tmp_path):
    origin_root = tmp_path / "origin"
    archive = origin_root / "viewer-publications"
    text_dir = origin_root / "derived" / "body_text"
    archive.mkdir(parents=True)
    text_dir.mkdir(parents=True)

    r_old = "a" * 64
    r_new = "b" * 64
    sha_old = "1" * 64
    sha_new = "2" * 64
    (archive / "manifest.json").write_text(json.dumps({"release_id": r_old}))
    (text_dir / "current.json").write_text(json.dumps({
        "release_id": r_old, "sha256": sha_old, "key": f"derived/body_text/{sha_old}.parquet",
    }))

    origin = origin_root.as_uri()
    # Without staged files, prefer_staged falls back cleanly to live pointers.
    assert release.resolve(origin, prefer_staged=True)["release_id"] == r_old

    # Once staged archive points to r_new without staged body_text yet, prefer_staged refuses (keeps old live online).
    (archive / "staged.json").write_text(json.dumps({"release_id": r_new, "previous_release_id": r_old}))
    with pytest.raises(ValueError, match="same immutable release"):
        release.resolve(origin, prefer_staged=True)

    # Matching staged pointers resolve r_new while default resolve() still resolves r_old.
    (text_dir / "staged.json").write_text(json.dumps({
        "release_id": r_new, "sha256": sha_new, "key": f"derived/body_text/{sha_new}.parquet",
    }))
    assert release.resolve(origin)["release_id"] == r_old
    assert release.resolve(origin, staged=True)["release_id"] == r_new
    assert release.resolve(origin, prefer_staged=True)["release_id"] == r_new
    assert release.resolve(origin, prefer_staged=True, expected_release_id=r_new)["release_id"] == r_new
    with pytest.raises(ValueError, match="differs from expected"):
        release.resolve(origin, prefer_staged=True, expected_release_id=r_old)

    # A stale staged pointer whose previous_release_id no longer matches live falls back to live.
    (archive / "manifest.json").write_text(json.dumps({"release_id": "c" * 64}))
    (text_dir / "current.json").write_text(json.dumps({
        "release_id": "c" * 64, "sha256": sha_new, "key": f"derived/body_text/{sha_new}.parquet",
    }))
    assert release.resolve(origin, prefer_staged=True)["release_id"] == "c" * 64


def test_listed_on_normalization_zip_exclusion_and_title_fallbacks(tmp_path):
    archive = tmp_path / "origin" / "viewer-publications"
    stage = archive / "releases" / "staging"
    stage.mkdir(parents=True)
    text_dir = tmp_path / "origin" / "derived" / "body_text"
    text_dir.mkdir(parents=True)
    body_key = bytes.fromhex("cd" * 32)
    base = dict(saved_body=body_key, hidden=False, saved_suffix=".gz", title=None, filename="doc.pdf",
                package_id=None, format="pdf", document_date=date(2026, 11, 20), document_date_status="accepted",
                congress=115, chambers=["house"], committee_keys=["hshm00"], document_kind=["committee-transcript"],
                document_family=["transcript"])

    sources_rows = []
    docs = []

    def add_doc(key, doc_overrides, src_rows):
        start = len(sources_rows)
        for ordinal, row in enumerate(src_rows):
            sources_rows.append(dict(ordinal=ordinal, member_path=None, is_saved=True, link_text="", listed_on=None) | row)
        docs.append(base | {"link_key": key, "src_start": start, "src_len": len(src_rows)} | doc_overrides)

    # 1. Card #9: api.congress.gov committee-meeting JSON URL -> deterministic human event URL
    add_doc(b"card0009", {"filename": "HHRG-115-HM11-Transcript-20180109.pdf"}, [
        dict(url="https://www.congress.gov/115/meeting/house/106754/documents/HHRG-115-HM11-Transcript-20180109.pdf",
             listed_on="https://api.congress.gov/v3/committee-meeting/115/house/106754?format=json"),
    ])
    # 2. English ordinal suffixes for congress numbers (101st, 102nd, 103rd, 112th)
    add_doc(b"ord101st", {"filename": "s101.pdf"}, [
        dict(url="https://www.congress.gov/101/meeting/senate/99999/documents/s101.pdf",
             listed_on="https://api.congress.gov/v3/committee-meeting/101/senate/99999?format=json"),
    ])
    add_doc(b"ord102nd", {"filename": "h102.pdf"}, [
        dict(url="https://www.congress.gov/102/meeting/house/88888/documents/h102.pdf",
             listed_on="https://api.congress.gov/v3/committee-meeting/102/house/88888"),
    ])
    add_doc(b"ord103rd", {"filename": "h103.pdf"}, [
        dict(url="https://www.congress.gov/103/meeting/house/77777/documents/h103.pdf",
             listed_on="https://api.congress.gov/v3/committee-meeting/103/house/77777?format=json"),
    ])
    add_doc(b"ord112th", {"filename": "h112.pdf"}, [
        dict(url="https://www.congress.gov/112/meeting/house/100033/documents/h112.pdf",
             listed_on="https://api.congress.gov/v3/committee-meeting/112/house/100033?format=json"),
    ])
    # 3. Card #19: ordinal=0 is api.govinfo.gov/packages/.../mods, ordinal=1 is human GovInfo details URL
    add_doc(b"card0019", {"title": "EXAMINING TRADE ENFORCEMENT", "filename": "CHRG-118shrg64101.pdf",
                          "package_id": "CHRG-118shrg64101", "congress": 118}, [
        dict(url="https://www.govinfo.gov/content/pkg/CHRG-118shrg64101/pdf/CHRG-118shrg64101.pdf",
             listed_on="https://api.govinfo.gov/packages/CHRG-118shrg64101/mods"),
        dict(url="https://www.govinfo.gov/content/pkg/CHRG-118shrg64101.zip",
             listed_on="https://www.govinfo.gov/app/details/CHRG-118shrg64101",
             link_text="ZIP", member_path="CHRG-118shrg64101/html/CHRG-118shrg64101.htm"),
    ])
    # 4. Native higher-ordinal committee web page beats ordinal-0 api.congress.gov URL
    add_doc(b"humanalt", {"filename": "stmt.pdf"}, [
        dict(url="https://www.congress.gov/115/meeting/house/106754/documents/stmt.pdf",
             listed_on="https://api.congress.gov/v3/committee-meeting/115/house/106754?format=json"),
        dict(url="https://agriculture.house.gov/uploadedfiles/stmt.pdf",
             listed_on="https://agriculture.house.gov/calendar/eventsingle.aspx?EventID=2403", is_saved=False),
    ])
    # 5. GovInfo API mods and metadata mods.xml with no human sibling -> deterministic GovInfo details URL
    add_doc(b"govimods", {"title": "Committee Report", "filename": "CRPT-108hrpt155.pdf", "package_id": "CRPT-108hrpt155"}, [
        dict(url="https://www.govinfo.gov/content/pkg/CRPT-108hrpt155/pdf/CRPT-108hrpt155.pdf",
             listed_on="https://api.govinfo.gov/packages/CRPT-108hrpt155/mods"),
    ])
    add_doc(b"modsxml0", {"title": "Senate Hearing", "filename": "CHRG-118shrg57030.pdf", "package_id": "CHRG-118shrg57030"}, [
        dict(url="https://www.govinfo.gov/content/pkg/CHRG-118shrg57030/pdf/CHRG-118shrg57030.pdf",
             listed_on="https://www.govinfo.gov/metadata/pkg/CHRG-118shrg57030/mods.xml"),
    ])
    # 6. Congress.gov hearing API: maps via package_id when present, suppressed when package_id is NULL
    add_doc(b"hrgapipk", {"title": "House Hearing", "filename": "CHRG-114hhrg20543.pdf", "package_id": "CHRG-114hhrg20543"}, [
        dict(url="https://congress.gov/114/chrg/CHRG-114hhrg20543/CHRG-114hhrg20543.pdf",
             listed_on="https://api.congress.gov/v3/hearing/114/house/20543?format=json"),
    ])
    add_doc(b"hrgapino", {"filename": "CHRG-117hhrg44535-add10.htm", "format": "html"}, [
        dict(url="https://www.congress.gov/117/chrg/CHRG-117hhrg44535-add10/generated/CHRG-117hhrg44535-add10.htm",
             listed_on="https://api.congress.gov/v3/hearing/117/house/10?format=json"),
    ])
    # 7. Unmappable machine URLs (nochamber, /wp-json/, self-linking summary API) -> suppressed to None
    add_doc(b"nochambr", {"filename": "HHRG-114-HM09-20151117-SD001.pdf"}, [
        dict(url="https://www.congress.gov/114/meeting/house/104064/documents/HHRG-114-HM09-20151117-SD001.pdf",
             listed_on="https://api.congress.gov/v3/committee-meeting/114/nochamber/104064?format=json"),
    ])
    add_doc(b"wpjson00", {"filename": "commerce-testimony.pdf"}, [
        dict(url="https://www.commerce.senate.gov/services/files/testimony.pdf",
             listed_on="https://www.commerce.senate.gov/wp-json/wp/v2/meeting/43032"),
    ])
    add_doc(b"selflink", {"title": "Details Page", "filename": "CHRG-118shrg64101.htm", "package_id": "CHRG-118shrg64101"}, [
        dict(url="https://www.govinfo.gov/app/details/CHRG-118shrg64101",
             listed_on="https://api.govinfo.gov/packages/CHRG-118shrg64101/summary"),
    ])
    # 8. Orphaned raw .zip container (CHRG-106hhrg69534.zip) excluded while titled sibling PDF & extracted zip member stay
    add_doc(b"ziporphn", {"format": "zip", "filename": "CHRG-106hhrg69534.zip", "congress": 106, "saved_body": None}, [
        dict(url="https://www.govinfo.gov/content/pkg/CHRG-106hhrg69534.zip",
             listed_on="https://www.govinfo.gov/app/details/CHRG-106hhrg69534", link_text="ZIP"),
    ])
    add_doc(b"zipsib00", {"title": "GAO ASSESSMENT OF HAITI", "filename": "CHRG-106hhrg69534.pdf",
                          "package_id": "CHRG-106hhrg69534", "congress": 106}, [
        dict(url="https://www.govinfo.gov/content/pkg/CHRG-106hhrg69534/pdf/CHRG-106hhrg69534.pdf"),
    ])
    add_doc(b"zipmembr", {"title": "IMPROVING SECURITY", "filename": "CHRG-107hhrg82954.pdf",
                          "package_id": "CHRG-107hhrg82954", "congress": 107}, [
        dict(url="https://www.govinfo.gov/content/pkg/CHRG-107hhrg82954.zip",
             listed_on="https://www.govinfo.gov/app/details/CHRG-107hhrg82954",
             link_text="ZIP", member_path="CHRG-107hhrg82954/pdf/CHRG-107hhrg82954.pdf"),
    ])
    # 9. Untitled title fallback priority: meeting_ref_title > usable link_text > filename (generic link words skipped)
    add_doc(b"mreftitl", {"filename": "HHRG-113-AP19-20130418-SD001.pdf"}, [
        dict(url="https://docs.house.gov/meetings/AP/AP19/20130418/100700/HHRG-113-AP19-20130418-SD001.pdf",
             link_text="Download Testimony"),
    ])
    add_doc(b"goodltxt", {"filename": "01-15-25_hearing_memo.pdf"}, [
        dict(url="https://committee.house.gov/files/01-15-25_hearing_memo.pdf",
             link_text="Rural Broadband Oversight Memorandum"),
    ])
    add_doc(b"badltxt0", {"filename": "01-15-25_rcs_opening_statement.pdf"}, [
        dict(url="https://committee.house.gov/files/01-15-25_rcs_opening_statement.pdf",
             link_text="please click here"),
    ])
    add_doc(b"lbltxt00", {"filename": "041415_HoltzEakin_Testimony.pdf"}, [
        dict(url="https://committee.house.gov/files/041415_HoltzEakin_Testimony.pdf",
             link_text="Witness Testimony"),
    ])
    add_doc(b"archwins", {"title": "Authoritative Archive Title", "filename": "override.pdf"}, [
        dict(url="https://docs.house.gov/meetings/AP/AP19/20130418/100700/HHRG-113-AP19-20130418-SD001.pdf",
             link_text="Secondary Link Text"),
    ])

    pq.write_table(pa.Table.from_pylist(docs), stage / "detail.parquet")
    pq.write_table(pa.Table.from_pylist(sources_rows), stage / "sources.parquet")
    pq.write_table(pa.Table.from_pylist([
        dict(event_id=100700, document_references=[
            dict(ordinal=0, url="https://docs.house.gov/meetings/AP/AP19/20130418/100700/HHRG-113-AP19-20130418-SD001.pdf",
                 name="  Opening Statement of Chairman Hal Rogers  ", description=None),
            dict(ordinal=1, url="https://committee.house.gov/files/041415_HoltzEakin_Testimony.pdf",
                 name="Witness Testimony", description=None),
        ]),
    ]), stage / "meetings.parquet")

    files = []
    for f in sorted(stage.glob("*.parquet")):
        raw = f.read_bytes()
        files.append(dict(name=f.name, sha256=sha256(raw).hexdigest(), size=len(raw), rows=pq.read_metadata(f).num_rows))
    release_id = release_identity(1, files)
    (stage / "manifest.json").write_text(json.dumps(dict(schema_version=1, files=files, release_id=release_id)))
    stage.rename(stage.with_name(release_id))
    (archive / "manifest.json").write_text(json.dumps({"release_id": release_id}))

    body = text_dir / "body.parquet"
    pq.write_table(pa.Table.from_pylist([dict(saved_body=body_key, text="evidence", page_offsets=[0], text_sha256=b"Y" * 32)]), body)
    digest = sha256(body.read_bytes()).hexdigest()
    detail_entry = next(f for f in files if f["name"] == "detail.parquet")
    pointer = dict(release_id=release_id, sha256=digest, bytes=body.stat().st_size,
                   key=f"derived/body_text/{digest}.parquet", detail={k: detail_entry[k] for k in ("sha256", "size")})
    body.rename(text_dir / f"{digest}.parquet")
    (text_dir / "current.json").write_text(json.dumps(pointer))

    work = release.update(tmp_path / "local", origin=(tmp_path / "origin").as_uri())
    assert work.parent.parent.name == "search-v3"
    rows = {r["member_key"]: r for r in pq.read_table(work / "prepared").to_pylist()}

    assert b"ziporphn".hex() not in rows
    assert b"zipsib00".hex() in rows and rows[b"zipsib00".hex()]["title"] == "GAO ASSESSMENT OF HAITI"
    assert b"zipmembr".hex() in rows and rows[b"zipmembr".hex()]["title"] == "IMPROVING SECURITY"

    assert rows[b"card0009".hex()]["listed_on"] == "https://www.congress.gov/event/115th-congress/house-event/106754"
    assert rows[b"ord101st".hex()]["listed_on"] == "https://www.congress.gov/event/101st-congress/senate-event/99999"
    assert rows[b"ord102nd".hex()]["listed_on"] == "https://www.congress.gov/event/102nd-congress/house-event/88888"
    assert rows[b"ord103rd".hex()]["listed_on"] == "https://www.congress.gov/event/103rd-congress/house-event/77777"
    assert rows[b"ord112th".hex()]["listed_on"] == "https://www.congress.gov/event/112th-congress/house-event/100033"
    assert rows[b"card0019".hex()]["listed_on"] == "https://www.govinfo.gov/app/details/CHRG-118shrg64101"
    assert rows[b"humanalt".hex()]["listed_on"] == "https://agriculture.house.gov/calendar/eventsingle.aspx?EventID=2403"
    assert rows[b"govimods".hex()]["listed_on"] == "https://www.govinfo.gov/app/details/CRPT-108hrpt155"
    assert rows[b"modsxml0".hex()]["listed_on"] == "https://www.govinfo.gov/app/details/CHRG-118shrg57030"
    assert rows[b"hrgapipk".hex()]["listed_on"] == "https://www.govinfo.gov/app/details/CHRG-114hhrg20543"
    assert rows[b"hrgapino".hex()]["listed_on"] is None
    assert rows[b"nochambr".hex()]["listed_on"] is None
    assert rows[b"wpjson00".hex()]["listed_on"] is None
    assert rows[b"selflink".hex()]["listed_on"] is None

    assert rows[b"mreftitl".hex()]["title"] == "Opening Statement of Chairman Hal Rogers"
    assert rows[b"goodltxt".hex()]["title"] == "Rural Broadband Oversight Memorandum"
    assert rows[b"badltxt0".hex()]["title"] == "01-15-25_rcs_opening_statement.pdf"
    assert rows[b"lbltxt00".hex()]["title"] == "041415_HoltzEakin_Testimony.pdf"
    assert rows[b"archwins".hex()]["title"] == "Authoritative Archive Title"
    assert not list((work / "downloads").glob("*.parquet"))


def _make_minimal_origin(tmp_path, *, title="Housing report"):
    archive = tmp_path / "origin" / "viewer-publications"
    stage = archive / "releases" / "staging"
    stage.mkdir(parents=True)
    text_dir = tmp_path / "origin" / "derived" / "body_text"
    text_dir.mkdir(parents=True)
    body_key = bytes.fromhex("ef" * 32)
    doc = dict(link_key=b"12345678", saved_body=body_key, hidden=False, saved_suffix=".gz",
               title=title, filename="report.pdf", package_id="HR-1", format="pdf",
               document_date=date(2026, 11, 20), document_date_status="accepted", congress=119, chambers=["house"],
               committee_keys=[], document_kind=["report"], document_family=["legislative"],
               src_start=0, src_len=1)
    pq.write_table(pa.Table.from_pylist([doc]), stage / "detail.parquet")
    pq.write_table(pa.Table.from_pylist([
        dict(ordinal=0, url="https://example.gov/a.pdf", listed_on="https://example.gov/hearing",
             link_text="Report", member_path=None, is_saved=True),
    ]), stage / "sources.parquet")
    files = []
    for f in sorted(stage.glob("*.parquet")):
        raw = f.read_bytes()
        files.append(dict(name=f.name, sha256=sha256(raw).hexdigest(), size=len(raw), rows=pq.read_metadata(f).num_rows))
    release_id = release_identity(1, files)
    (stage / "manifest.json").write_text(json.dumps(dict(schema_version=1, files=files, release_id=release_id)))
    stage.rename(stage.with_name(release_id))
    (archive / "manifest.json").write_text(json.dumps({"release_id": release_id}))
    body = text_dir / "body.parquet"
    pq.write_table(pa.Table.from_pylist([dict(saved_body=body_key, text="housing evidence", page_offsets=[0],
                                              text_sha256=b"Z" * 32)]), body)
    digest = sha256(body.read_bytes()).hexdigest()
    detail_entry = next(f for f in files if f["name"] == "detail.parquet")
    pointer = dict(release_id=release_id, sha256=digest, bytes=body.stat().st_size,
                   key=f"derived/body_text/{digest}.parquet", detail={k: detail_entry[k] for k in ("sha256", "size")})
    body.rename(text_dir / f"{digest}.parquet")
    (text_dir / "current.json").write_text(json.dumps(pointer))
    return (tmp_path / "origin").as_uri(), release_id


def test_passage_drop_guard_blocks_bare_publish_and_supports_override_and_attach(tmp_path, monkeypatch):
    import subprocess
    import sys

    origin, release_id = _make_minimal_origin(tmp_path)
    root = tmp_path / "local"
    prepared = release.update(root, origin=origin)
    definition = json.loads((prepared / "dataset.json").read_text())
    other_release = "0" * 64
    new_revision = "a" * 64
    live_passages = {
        "release_id": other_release,
        "config_version": "b" * 64,
        "model": "BAAI/bge-small-en-v1.5",
        "dimensions": 384,
        "passages": 1000,
        "documents": 1,
        "parquet": "/srv/spicyengine/input/passages/old/*.parquet",
    }

    calls = []
    status_state = {}

    def fake_run(args, **kwargs):
        calls.append(list(args))
        cmd = args[1]
        if cmd == "status":
            return subprocess.CompletedProcess(
                args, status_state.get("rc", 0),
                stdout=status_state.get("stdout", ""),
                stderr=status_state.get("stderr", ""),
            )
        if cmd == "publish":
            return subprocess.CompletedProcess(
                args, 0,
                stdout=json.dumps({"operation": "installed", "revision": new_revision, "records": 1}),
                stderr="",
            )
        if cmd == "attach-passages":
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        raise AssertionError(f"Unexpected engine command: {args}")

    monkeypatch.setattr(release.subprocess, "run", fake_run)

    # 1. Refuses bare publish when live SpicyEngine has attached passages on a different release.
    status_state.update(rc=0, stderr="", stdout=json.dumps({
        "revision": "b" * 64,
        "dataset": definition | {"release_id": other_release, "input": {"parquet": "/srv/other/serving/*.parquet"}},
        "passages": live_passages,
        "records": 1,
    }))
    with pytest.raises(RuntimeError, match="Refusing to publish .* without passages"):
        release.update(root, origin=origin, engine="/bin/fake-spicyengine")
    assert [c[1] for c in calls] == ["status"]

    # 2. Fails closed on unexpected status errors (e.g. missing DB password or unreachable daemon).
    calls.clear()
    status_state.update(rc=1, stdout="", stderr="Set SPICYENGINE_DATABASE_PASSWORD before using the local database")
    with pytest.raises(RuntimeError, match="Unable to inspect live SpicyEngine status"):
        release.update(root, origin=origin, engine="/bin/fake-spicyengine")
    assert [c[1] for c in calls] == ["status"]

    # 3. Allows initial publish when no dataset is published yet.
    calls.clear()
    status_state.update(rc=1, stdout="", stderr="Publish a dataset before searching")
    release.update(root, origin=origin, engine="/bin/fake-spicyengine")
    assert [c[1] for c in calls] == ["status", "publish"]

    # 4. Allows bare publish when live passages stay intact (identical dataset or compatible facet metadata only).
    calls.clear()
    status_state.update(rc=0, stderr="", stdout=json.dumps({
        "revision": "b" * 64,
        "dataset": definition | {"facet_labels": {"chambers": {"house": "Old Label"}}},
        "passages": live_passages | {"release_id": release_id},
        "records": 1,
    }))
    release.update(root, origin=origin, engine="/bin/fake-spicyengine")
    assert [c[1] for c in calls] == ["status", "publish"]

    # 5. Allows bare publish with explicit --allow-drop-passages override (skips status guard).
    calls.clear()
    status_state.update(rc=0, stderr="", stdout=json.dumps({
        "revision": "b" * 64,
        "dataset": definition | {"release_id": other_release},
        "passages": live_passages,
        "records": 1,
    }))
    release.update(root, origin=origin, engine="/bin/fake-spicyengine", allow_drop_passages=True)
    assert [c[1] for c in calls] == ["publish"]

    # 6. Rejects mismatched passages manifest BEFORE calling publish.
    calls.clear()
    bad_manifest = tmp_path / "bad-passages.json"
    bad_manifest.write_text(json.dumps(live_passages))
    with pytest.raises(ValueError, match="differs from target release"):
        release.update(root, origin=origin, engine="/bin/fake-spicyengine", passages_manifest=bad_manifest)
    assert calls == []

    bad_docs = tmp_path / "bad-docs-passages.json"
    bad_docs.write_text(json.dumps(live_passages | {"release_id": release_id, "documents": 99}))
    with pytest.raises(ValueError, match="differs from prepared rows"):
        release.update(root, origin=origin, engine="/bin/fake-spicyengine", passages_manifest=bad_docs)
    assert calls == []

    # 7. Valid passages manifest publishes, stamps config_version with the new revision, and runs attach-passages.
    calls.clear()
    good_manifest = tmp_path / "good-passages.json"
    good_manifest.write_text(json.dumps({
        "release_id": release_id,
        "model": "BAAI/bge-small-en-v1.5",
        "dimensions": 384,
        "passages": 12,
        "documents": 1,
        "parquet": "/srv/spicyengine/input/passages/new/*.parquet",
        "keyword_parquet": "/srv/spicyengine/input/passages/new-kw/*.parquet",
    }))
    work = release.update(root, origin=origin, engine="/bin/fake-spicyengine", passages_manifest=good_manifest)
    assert [c[1] for c in calls] == ["publish", "attach-passages"]
    stamped_path = work / "passages-attach.json"
    assert calls[1][2] == str(stamped_path)
    stamped = json.loads(stamped_path.read_text())
    assert stamped["config_version"] == new_revision
    assert stamped["release_id"] == release_id
    assert stamped["keyword_parquet"] == "/srv/spicyengine/input/passages/new-kw/*.parquet"

    # 8. CLI parses --allow-drop-passages and --passages-manifest and passes them through to update().
    recorded = {}

    def fake_update(root_arg, **kwargs):
        recorded["root"] = root_arg
        recorded.update(kwargs)
        return work

    monkeypatch.setattr(release, "update", fake_update)
    monkeypatch.setattr(
        sys, "argv",
        ["spicyengine_release", "--root", str(root), "--engine", "/bin/fake-spicyengine",
         "--allow-drop-passages", "--passages-manifest", str(good_manifest)],
    )
    release.main()
    assert recorded["allow_drop_passages"] is True
    assert recorded["passages_manifest"] == good_manifest
