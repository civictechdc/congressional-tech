"""Keyword passage builds: full, incremental hard-link reuse, idempotence and refusals."""
import hashlib
import json
import os
from bisect import bisect_right

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication import passage_keywords as keywords

SOURCE = "archive-documents"


def document(key, title, body, offsets=None):
    return dict(source_id=SOURCE, member_key=key, title=title, body=body,
                text_sha256=hashlib.sha256(body.encode()).hexdigest(), page_offsets=offsets)


def passages(doc, *spans):
    """Serving rows for (field, start, end) spans, with independently computed ASCII page anchors."""
    rows = []
    for field, start, end in spans:
        text = doc[field][start:end]
        page = page_at = None
        if field == "body" and doc["page_offsets"]:
            page = bisect_right(doc["page_offsets"], start)
            page_at = start - doc["page_offsets"][page - 1]
        rows.append(dict(source_id=SOURCE, member_key=doc["member_key"], source_field=field,
                         text_sha256=doc["text_sha256"] if field == "body" else None,
                         char_start=start, char_end=end, excerpt=text[:5], page=page, page_at=page_at,
                         vector=[0.5, 0.25]))
    return rows


def write_prepared(directory, parts):
    directory.mkdir(parents=True)
    for name, docs in parts.items():
        pq.write_table(pa.Table.from_pylist(docs), directory / f"{name}.parquet")
    return directory


def write_serving(directory, files):
    directory.mkdir(parents=True)
    for name, rows in files.items():
        pq.write_table(pa.Table.from_pylist(rows), directory / f"{name}.parquet")
    return directory


def keyword_rows(directory):
    return pq.read_table(sorted(directory.glob("*.parquet"))).to_pylist()


A = document("a", "Alpha hearing", "Alpha testimony about rural broadband access", [0, 20])
B = document("b", "Bravo report", "Bravo findings on appropriations")
C = document("c", "Café résumé", "Témoignage sur l'accès à Internet en zone rurale")
D = document("d", "Delta memo", "Delta memo on the farm bill")


def release_one(tmp_path):
    prepared = write_prepared(tmp_path / "r1" / "prepared", {
        "archive-00": [A, B], "archive-01": [C], "archive-02": [D]})
    # Serving files need not align with prepared shards.
    serving = write_serving(tmp_path / "r1" / "serving", {
        "archive-00": passages(A, ("title", 0, 5), ("body", 0, 15), ("body", 25, 40)) + passages(B, ("body", 0, 14)),
        "archive-01": passages(C, ("title", 0, 11), ("body", 3, 20)) + passages(D, ("body", 0, 10))})
    return prepared, serving


def test_full_build_slices_text_verifies_and_is_idempotent(tmp_path):
    prepared, serving = release_one(tmp_path)
    output = tmp_path / "r1" / "keywords"
    manifest = keywords.ensure_keywords(serving, prepared, output, release_id="a" * 64,
                                        expected_passages=7, expected_documents=4)
    assert {p.name for p in output.iterdir()} == {"archive-00.parquet", "archive-01.parquet", "archive-02.parquet",
                                                  "manifest.json"}
    assert manifest["passages"] == 7 and manifest["documents"] == 4 and manifest["reused"] == 0
    assert json.loads((output / "manifest.json").read_text()) == manifest
    texts = {d["member_key"]: d for d in (A, B, C, D)}
    rows = keyword_rows(output)
    assert len(rows) == 7
    for row in rows:
        assert row["text"] == texts[row["member_key"]][row["source_field"]][row["char_start"]:row["char_end"]]
        assert row["excerpt"] in row["text"]
    assert {(r["page"], r["page_at"]) for r in rows if r["member_key"] == "a" and r["source_field"] == "body"} == {
        (1, 0), (2, 5)}
    assert next(r["text"] for r in rows if r["member_key"] == "c" and r["source_field"] == "title") == "Café résumé"
    for path in output.glob("*.parquet"):
        assert pq.read_schema(path).equals(keywords.KEYWORD_SCHEMA)
        assert path.stat().st_mode & 0o777 == 0o444
    assert sorted(p.name for p in output.parent.iterdir()) == ["keywords", "prepared", "serving"]
    # A rerun with the same serving files changes nothing; different serving files are refused.
    times = {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
    assert keywords.ensure_keywords(serving, prepared, output, release_id="a" * 64) == manifest
    assert {p.name: p.stat().st_mtime_ns for p in output.iterdir()} == times
    pq.write_table(pa.Table.from_pylist(passages(D, ("title", 0, 5))), serving / "extra.parquet")
    with pytest.raises(ValueError, match="already exists"):
        keywords.ensure_keywords(serving, prepared, output, release_id="a" * 64)


def test_incremental_build_hard_links_unchanged_files_and_rebuilds_changed_documents(tmp_path):
    prepared, serving = release_one(tmp_path)
    first = tmp_path / "r1" / "keywords"
    keywords.ensure_keywords(serving, prepared, first, release_id="a" * 64)
    changed = document("d", "Delta memo", "Delta memo on the revised farm bill")
    added = document("e", "Echo notice", "Echo notice of a markup session")
    prepared2 = write_prepared(tmp_path / "r2" / "prepared", {
        "archive-00": [A, B, added], "archive-01": [C], "archive-02": [changed]})
    serving2 = write_serving(tmp_path / "r2" / "serving", {
        "archive-00": passages(A, ("title", 0, 5), ("body", 0, 15), ("body", 25, 40)) + passages(B, ("body", 0, 14)),
        "archive-01": passages(C, ("title", 0, 11), ("body", 3, 20)) + passages(changed, ("body", 0, 18)),
        "delta": passages(added, ("body", 0, 11))})
    second = tmp_path / "r2" / "keywords"
    manifest = keywords.ensure_keywords(serving2, prepared2, second, release_id="b" * 64, previous=first,
                                        expected_passages=8, expected_documents=5)
    assert manifest["reused"] == 2
    names = {p.name for p in second.glob("*.parquet")}
    assert names == {"archive-00.parquet", "archive-01.parquet", "delta-bbbbbbbbbbbb.parquet"}
    for name in ("archive-00.parquet", "archive-01.parquet"):
        assert (second / name).stat().st_ino == (first / name).stat().st_ino
    delta = pq.read_table(second / "delta-bbbbbbbbbbbb.parquet").to_pylist()
    assert {r["member_key"] for r in delta} == {"d", "e"}
    assert next(r["text"] for r in delta if r["member_key"] == "d") == "Delta memo on the "
    # Chained reuse: the next release links release two's own delta too.
    third = tmp_path / "r3" / "keywords"
    third.parent.mkdir()
    again = keywords.ensure_keywords(serving2, prepared2, third, release_id="c" * 64, previous=second)
    assert again["reused"] == 3 and again["fingerprint"] == manifest["fingerprint"]


def test_changed_custody_or_text_is_rebuilt_not_reused(tmp_path):
    prepared, serving = release_one(tmp_path)
    first = tmp_path / "r1" / "keywords"
    keywords.ensure_keywords(serving, prepared, first, release_id="a" * 64)
    # Same passage coordinates but a different title text must not reuse the old slices.
    retitled = document("b", "Bravo final report", B["body"])
    prepared2 = write_prepared(tmp_path / "r2" / "prepared", {
        "archive-00": [A, retitled], "archive-01": [C], "archive-02": [D]})
    # Replacing a file breaks its custody stamp even with identical bytes.
    replaced = first / "archive-01.parquet"
    data = replaced.read_bytes()
    os.chmod(first, 0o755)
    replaced.unlink()
    replaced.write_bytes(data)
    manifest = keywords.ensure_keywords(serving, prepared2, tmp_path / "r2" / "keywords", release_id="b" * 64,
                                        previous=first)
    assert manifest["reused"] == 1
    assert [e["name"] for e in manifest["files"] if "reused_from" in e] == ["archive-02.parquet"]
    assert len(keyword_rows(tmp_path / "r2" / "keywords")) == 7


@pytest.mark.parametrize("problem, message", [
    ("excerpt", "Excerpt is not a verbatim part"),
    ("anchor", "Page anchor"),
    ("body_sha", "different body text version"),
    ("orphan", "not in the prepared release"),
    ("uncovered", "have no passages"),
    ("count", "not the declared"),
])
def test_invalid_inputs_are_refused_without_publishing(tmp_path, problem, message):
    prepared, serving = release_one(tmp_path)
    rows = pq.read_table(serving / "archive-01.parquet").to_pylist()
    expected = None
    if problem == "excerpt":
        rows[0]["excerpt"] = "absent"
    elif problem == "anchor":
        rows = pq.read_table(serving / "archive-00.parquet").to_pylist()
        rows[1]["page_at"] = 3
        pq.write_table(pa.Table.from_pylist(rows), serving / "archive-00.parquet")
        rows = None
    elif problem == "body_sha":
        for r in rows:
            if r["source_field"] == "body":
                r["text_sha256"] = "0" * 64
    elif problem == "orphan":
        rows += passages(document("z", "Zulu", "Zulu text body"), ("body", 0, 4))
    elif problem == "uncovered":
        rows = [r for r in rows if r["member_key"] != "d"]
    else:
        expected = 99
    if rows is not None:
        pq.write_table(pa.Table.from_pylist(rows), serving / "archive-01.parquet")
    output = tmp_path / "r1" / "keywords"
    with pytest.raises(ValueError, match=message):
        keywords.ensure_keywords(serving, prepared, output, release_id="a" * 64, expected_passages=expected)
    assert sorted(p.name for p in output.parent.iterdir()) == ["prepared", "serving"]


def test_cli_builds_and_prints_manifest(tmp_path, monkeypatch, capsys):
    prepared, serving = release_one(tmp_path)
    output = tmp_path / "r1" / "keywords"
    monkeypatch.setattr("sys.argv", [
        "passage_keywords", "--serving", str(serving), "--prepared", str(prepared),
        "--output", str(output), "--release-id", "a" * 64,
        "--expected-passages", "7", "--expected-documents", "4",
    ])
    keywords.main()
    printed = json.loads(capsys.readouterr().out)
    assert printed["release_id"] == "a" * 64 and printed["passages"] == 7 and printed["documents"] == 4
    assert (output / "manifest.json").is_file()


def test_stamp_keywords_manifest_seeds_existing_dir_and_enables_hardlink_reuse(tmp_path, monkeypatch, capsys):
    prepared, serving = release_one(tmp_path)
    kw_dir = tmp_path / "r1" / "keywords"
    keywords.ensure_keywords(serving, prepared, kw_dir, release_id="a" * 64)
    # Remove manifest.json to simulate a pre-manifest live keywords/ directory.
    (kw_dir / "manifest.json").unlink()
    before_stats = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns) for p in kw_dir.glob("*.parquet")}

    monkeypatch.setattr("sys.argv", [
        "passage_keywords", "--stamp-manifest", "--serving", str(serving), "--prepared", str(prepared),
        "--output", str(kw_dir), "--release-id", "a" * 64,
        "--expected-passages", "7", "--expected-documents", "4",
    ])
    keywords.main()
    stamped = json.loads(capsys.readouterr().out)
    assert stamped["passages"] == 7 and stamped["documents"] == 4 and stamped["reused"] == 0
    assert (kw_dir / "manifest.json").stat().st_mode & 0o777 == 0o444
    # No existing Parquet file was rewritten.
    assert {p.name: (p.stat().st_ino, p.stat().st_mtime_ns) for p in kw_dir.glob("*.parquet")} == before_stats
    # Idempotent rerun returns the same manifest.
    assert keywords.stamp_keywords_manifest(serving, prepared, kw_dir, release_id="a" * 64) == stamped

    # Subsequent incremental release hard-links every shard from the stamped directory.
    next_dir = tmp_path / "r2" / "keywords"
    next_dir.parent.mkdir()
    reused = keywords.ensure_keywords(serving, prepared, next_dir, release_id="b" * 64, previous=kw_dir)
    assert reused["reused"] == 3
    for name, (ino, _) in before_stats.items():
        assert (next_dir / name).stat().st_ino == ino


def test_unified_build_emits_float16_fsl_reuses_hardlinks_and_invalidates_changed_vectors(
    tmp_path, monkeypatch, capsys
):
    prepared, serving = release_one(tmp_path)
    first = tmp_path / "r1" / "unified"
    manifest = keywords.build_unified_passages(
        serving, prepared, first, release_id="a" * 64, dimensions=2, expected_passages=7, expected_documents=4
    )
    assert manifest["layout"] == "unified" and manifest["dimensions"] == 2
    assert manifest["passages"] == 7 and manifest["documents"] == 4 and manifest["reused"] == 0
    expected_schema = keywords.unified_schema(2)
    assert expected_schema.field("vector").type == pa.list_(pa.float16(), 2)
    for path in first.glob("*.parquet"):
        assert pq.read_schema(path).equals(expected_schema)
        assert path.stat().st_mode & 0o777 == 0o444
    rows = keyword_rows(first)
    assert len(rows) == 7
    assert all(len(r["vector"]) == 2 and r["vector"] == [0.5, 0.25] for r in rows)
    # Idempotent rerun on unchanged serving files.
    assert keywords.build_unified_passages(serving, prepared, first, release_id="a" * 64, dimensions=2) == manifest

    # Release 2: unchanged shards archive-00 and archive-01 hard-link, while a vector-only change on doc D rebuilds!
    r2_rows = pq.read_table(serving / "archive-01.parquet").to_pylist()
    for row in r2_rows:
        if row["member_key"] == "d":
            row["vector"] = [0.25, 0.5]
    serving2 = tmp_path / "r2" / "serving"
    serving2.mkdir(parents=True)
    pq.write_table(pq.read_table(serving / "archive-00.parquet"), serving2 / "archive-00.parquet")
    pq.write_table(pa.Table.from_pylist(r2_rows), serving2 / "archive-01.parquet")
    second = tmp_path / "r2" / "unified"
    manifest2 = keywords.build_unified_passages(
        serving2, prepared, second, release_id="b" * 64, dimensions=2, previous=first
    )
    assert manifest2["reused"] == 2
    assert (second / "archive-00.parquet").stat().st_ino == (first / "archive-00.parquet").stat().st_ino
    assert (second / "archive-01.parquet").stat().st_ino == (first / "archive-01.parquet").stat().st_ino
    delta_rows = pq.read_table(second / "delta-bbbbbbbbbbbb.parquet").to_pylist()
    assert [r["member_key"] for r in delta_rows] == ["d"]
    assert delta_rows[0]["vector"] == [0.25, 0.5]

    # Wrong dimension or non-finite vector is rejected without publishing.
    bad_dir = tmp_path / "bad_vec"
    bad_dir.mkdir()
    with pytest.raises(ValueError, match="non-4-d vectors"):
        keywords.build_unified_passages(serving, prepared, bad_dir / "unified", release_id="a" * 64, dimensions=4)
    assert not (bad_dir / "unified").exists()

    inf_serving = tmp_path / "inf_serving"
    inf_serving.mkdir()
    inf_rows = pq.read_table(serving / "archive-01.parquet").to_pylist()
    inf_rows[0]["vector"] = [float("inf"), 0.0]
    pq.write_table(pq.read_table(serving / "archive-00.parquet"), inf_serving / "archive-00.parquet")
    pq.write_table(pa.Table.from_pylist(inf_rows), inf_serving / "archive-01.parquet")
    with pytest.raises(ValueError, match="must be finite"):
        keywords.build_unified_passages(inf_serving, prepared, bad_dir / "unified", release_id="a" * 64, dimensions=2)
    assert not (bad_dir / "unified").exists()

    # CLI --build-unified --dimensions works end-to-end.
    cli_out = tmp_path / "r3" / "unified"
    cli_out.parent.mkdir()
    monkeypatch.setattr("sys.argv", [
        "passage_keywords", "--build-unified", "--dimensions", "2",
        "--serving", str(serving2), "--prepared", str(prepared), "--output", str(cli_out),
        "--release-id", "c" * 64, "--previous", str(second),
    ])
    keywords.main()
    cli_manifest = json.loads(capsys.readouterr().out)
    assert cli_manifest["layout"] == "unified" and cli_manifest["reused"] == 3
