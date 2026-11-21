"""Join Explorer's row-number keys and link keys to the pinned body-text export."""

import json

import duckdb
import pyarrow as pa

from pdf_source_evidence import EXPORT, OUT, fingerprint, load, release_files, require


def release_db(root):
    artifact = load(root / OUT / "v13-readback.json")
    require(
        artifact["export"] == EXPORT
        and all(fingerprint(root / OUT / n) == digest for n, digest in artifact["files"].items()),
        "v13 projection identity",
    )
    db = duckdb.connect()
    db.execute("SET threads=2")
    db.execute("SET memory_limit='1GB'")
    for name, path in release_files(
        root, ["detail", "list", "sources", "urls", "url_state", "recoveries"]
    ).items():
        db.read_parquet(str(path), file_row_number=True).create_view(name)
    for name, path in [
        ("selected", "selected-readings"),
        ("export", "v13-metadata"),
        ("history", "capture-history"),
    ]:
        db.read_parquet(str(root / OUT / (path + ".parquet"))).create_view(name)
    db.execute("""CREATE VIEW docs AS SELECT d.file_row_number AS list_row,
        lower(hex(d.link_key)) AS doc_id, lower(hex(d.saved_body)) AS saved_body,
        l.filename,l.title,l.hidden,d.saved_kind,l.format FROM detail d JOIN list l USING(file_row_number)""")
    mismatch = db.execute("""SELECT count(*) FROM detail d FULL JOIN list l USING(file_row_number)
        WHERE d.file_row_number IS NULL OR l.file_row_number IS NULL OR
        (d.filename,d.title,d.hidden,d.saved_kind,d.format) IS DISTINCT FROM
        (l.filename,l.title,l.hidden,l.saved_kind,l.format)""").fetchone()[0]
    require(not mismatch, "list and detail ordinal mismatch")
    return db


def query(db, sql):
    return db.execute(sql).to_arrow_table().to_pylist()


def exposure(db, shas):
    """Keep saved, alternate and recovery associations distinct even at a shared URL."""
    db.register("wanted", pa.table({"sha": sorted(shas)}))
    associations = {
        s: {"documents": [], "recoveries": [], "alternates": [], "readings": [], "export": None} for s in shas
    }
    for r in query(db, "SELECT d.* FROM docs d JOIN wanted w ON w.sha=d.saved_body ORDER BY list_row"):
        associations[r["saved_body"]]["documents"].append(r)
    for r in query(
        db,
        """SELECT w.sha, d.*,r.kind,r.ordinal,r.recovered_url,r.identity_note
            FROM recoveries r JOIN wanted w ON r.body=unhex(w.sha)
            JOIN detail x ON r.list_row=x.file_row_number AND r.file_row_number >= x.rec_start
                AND r.file_row_number < x.rec_start + x.rec_len
            JOIN docs d USING(list_row) ORDER BY list_row,ordinal""",
    ):
        associations[r.pop("sha")]["recoveries"].append(r)
    for r in query(
        db,
        """SELECT w.sha,d.* FROM detail x, unnest(x.alternates) a(item), wanted w, docs d
            WHERE a.item.body=unhex(w.sha) AND d.list_row=x.file_row_number ORDER BY list_row""",
    ):
        associations[r.pop("sha")]["alternates"].append(r)
    for r in query(
        db,
        """SELECT w.sha,r.parser,r.parser_version,r.status,r.error_type FROM selected r
            JOIN wanted w ON r.body_sha=unhex(w.sha) ORDER BY sha,parser,parser_version""",
    ):
        associations[r.pop("sha")]["readings"].append(r)
    for r in query(
        db,
        """SELECT w.sha,lower(hex(e.text_sha256)) AS text_sha256,e.page_offsets
            FROM export e JOIN wanted w ON e.saved_body=unhex(w.sha)""",
    ):
        state = associations[r.pop("sha")]
        require(state["export"] is None, "duplicate selected text")
        state["export"] = r
    return associations


def serializable(row):
    return json.loads(json.dumps(row, default=lambda value: value.isoformat()))
