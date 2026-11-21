"""Reconcile qualified PDF cleanup and archive composition with the November 20 delivery."""

from collections import Counter
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
from viewer_publication.body_text_slices import slice_pages

from pdf_source_evidence import (
    CLEANUP,
    EXPORT,
    OCR,
    OUT,
    RELEASE,
    SELECTION,
    SSOT,
    archive_arg,
    fingerprint,
    load,
    require,
    selection,
    write,
)
from pdf_source_release import exposure, release_db

EARLY = OCR / "repairs/selection-offline-20261113"
ASSESSMENT = OCR / "repairs/corpus-assessment-20261113"
QUEUE = ASSESSMENT / "exception-queue-20261114/final/review-inventory.parquet"
SCREEN = ASSESSMENT / "current-pdf-quality-screen-20261115/sorted-inputs.parquet"


def verify_selected(row, live, expected_digest, version, sample=None):
    sha = row["body_sha"].hex()
    digest = sha256(row["text"].encode()).hexdigest()
    require(digest == row["text_sha256"].hex() == expected_digest, f"{sha} qualified digest")
    documents = live["documents"]
    require(
        len(documents) == 1 and documents[0]["hidden"] is False and documents[0]["saved_body"] == sha,
        f"{sha} expected one unhidden Explorer record for the exact saved body",
    )
    require(
        live["export"] == dict(text_sha256=digest, page_offsets=row["page_offsets"]), f"{sha} export mismatch"
    )
    require(
        live["readings"]
        == [dict(parser=row["parser"], parser_version=version, status="completed", error_type=None)]
        and row["parser_version"] == version,
        f"{sha} reading identity",
    )
    if sample is not None:
        require(
            sample["text"] == row["text"]
            and sample["text_sha256"].hex() == digest
            and sample["page_offsets"] == row["page_offsets"],
            f"{sha} delivered text or page map",
        )


def unassessed_scope(root, db, assessed):
    db.register("assessed_cleanup", pa.table({"sha": sorted(assessed)}))
    db.read_parquet(str(root / SCREEN)).create_view("historical_screen")
    db.read_parquet(str(root / QUEUE)).create_view("historical_queue")
    # Some historical PDFs have no selected text or no current document. Keep those rows.
    scope = db.sql("""WITH pdf_docs AS (
        SELECT saved_body AS sha,list(doc_id ORDER BY list_row) AS doc_ids
        FROM docs WHERE format='pdf' AND saved_body IS NOT NULL GROUP BY saved_body
    ), pdf_readings AS (SELECT lower(hex(body_sha)) AS sha,parser_version,status
        FROM selected WHERE parser='pdf_text'), population AS (
        SELECT sha FROM pdf_docs UNION SELECT sha FROM pdf_readings
        UNION SELECT body_sha256 FROM historical_screen
        UNION SELECT body_sha256 FROM historical_queue WHERE parser='pdf_text'
    ) SELECT p.sha AS body_sha256,h.parser_version AS historical_parser_version,h.text_sha256 AS historical_text_sha256,
        r.parser_version AS selected_parser_version,r.status AS selected_reading_status,
        d.doc_ids,lower(hex(e.text_sha256)) AS delivered_text_sha256
        FROM population p LEFT JOIN historical_screen h ON p.sha=h.body_sha256
        LEFT JOIN pdf_readings r USING(sha) LEFT JOIN pdf_docs d USING(sha)
        LEFT JOIN export e ON unhex(p.sha)=e.saved_body
        ANTI JOIN assessed_cleanup a ON a.sha=p.sha ORDER BY p.sha""")
    path = root / OUT / "ct-kfsd-unassessed.parquet"
    scope.write_parquet(str(path), compression="zstd")
    stats = db.execute(
        "SELECT count(*),count(DISTINCT body_sha256),count(delivered_text_sha256) FROM read_parquet(?)",
        [str(path)],
    ).fetchone()
    require(stats[0] == stats[1], "repeated SHA in unassessed historical scope")
    return dict(
        file=path.name,
        sha256=fingerprint(path),
        bodies=stats[0],
        with_v13_text=stats[2],
        population="Union of frozen PDF screen, historical exception queue PDFs, pinned PDF readings, "
        "and release saved PDFs, excluding all assessed cleanup/control and composed archive SHAs.",
    )


def reconcile(root):
    out = root / OUT
    earlier = {r["body_sha256"]: r for r in load(root / EARLY / "exposure.json")["cases"]}
    previous = {r["body_sha256"]: r for r in load(root / CLEANUP / "result.json")["cases"]}
    new = {
        r["body_sha256"]: r
        for r in load(root / SSOT / "review_packets/pdf_repairs_metadata.json")
        if r["cohort"] == "gpo_cleanup_loss_renormalized"
    }
    require(
        len(earlier) == 14
        and len(new) == 18
        and set(earlier).isdisjoint(new)
        and set(previous) == set(earlier) | set(new),
        "32-case partition",
    )
    policy = selection()
    overrides = {(r["body_sha256"], r["parser"]): r for r in policy["overrides"]}
    staged = root / SSOT / "staged"
    archive_fields = {
        r["body_sha"].hex(): {f["field"]: f["value"] for f in r["fields"]}
        for r in pq.read_table(
            staged / "warc_compose/readings.parquet", columns=["body_sha", "fields"]
        ).to_pylist()
    }
    sample = {r["saved_body"].hex(): r for r in pq.read_table(out / "v13-reviewed-text.parquet").to_pylist()}
    review = load(root / SSOT / "review_packets/warc_review_packet.json")
    sampled_archives = {r["saved_body_hex"]: r for r in review["cases"]}
    require(
        len(archive_fields) == 8505
        and len(sampled_archives) == 24
        and set(sample) == set(previous) | set(sampled_archives),
        "archive and text sample populations",
    )
    pointer = load(out / "v13-pointer.json")
    require(pointer["coverage"]["truncated"] == 0, "v13 has truncated rows")
    db = release_db(root)
    live = exposure(db, set(previous) | set(archive_fields))
    queue = {
        r["body_sha256"]: r
        for r in pq.read_table(
            root / QUEUE,
            filters=[("owner_ticket", "=", "ct-kfsd")],
            columns=["body_sha256", "prior_review_cases", "disposition", "proposed_action"],
        ).to_pylist()
    }
    require(len(queue) == 4 and queue.keys() <= earlier.keys(), "unaccounted retained cleanup queue")
    native_rows = pq.read_table(out / "native-cleanup-metadata.parquet").to_pylist()
    native = {r["body_sha"].hex(): r for r in native_rows}
    require(len(native_rows) == len(native) and set(native) == set(live), "native metadata coverage")
    rows = {}
    for path in [
        root / EARLY / "retained-text.parquet",
        staged / "pdf_repairs/body_text.parquet",
        staged / "warc_compose/body_text.parquet",
    ]:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=64):
            for r in batch.to_pylist():
                sha = r["body_sha"].hex()
                if sha not in live:
                    continue
                override = overrides.get((sha, r["parser"]))
                version = override["parser_version"] if override else policy["baseline_versions"][r["parser"]]
                if r["parser_version"] != version:
                    continue
                expected = override["text_sha256"] if override else earlier[sha]["baseline_text_sha256"]
                require(
                    all(r[k] == v for k, v in native[sha].items()),
                    f"{sha} native text or OCR metadata differs",
                )
                verify_selected(r, live[sha], expected, version, sample.get(sha))
                require(sha not in rows, f"{sha} duplicate qualified input")
                row = dict(
                    body_sha256=sha,
                    parser=r["parser"],
                    parser_version=version,
                    status=live[sha]["readings"][0]["status"],
                    text_sha256=expected,
                    selected_source="override" if override else "baseline",
                    char_len=len(r["text"]),
                    utf8_bytes=len(r["text"].encode()),
                    page_count=len(r["page_offsets"]),
                    ocr_pages=r["ocr_pages"],
                    macos_build=r["macos_build"],
                    truncated=False,
                    page_offsets=r["page_offsets"],
                    documents=live[sha]["documents"],
                    recoveries=live[sha]["recoveries"],
                    alternates=live[sha]["alternates"],
                    readback="actual_v13_text" if sha in sample else "v13_digest_and_page_map",
                )
                rows[sha] = row
                if sha in archive_fields:
                    row.update(
                        cohort="composed_archive",
                        payload=archive_fields[sha],
                        directly_reviewed_archive=sha in sampled_archives,
                    )
                    if sha in sampled_archives:
                        case = sampled_archives[sha]
                        require(
                            case["payload_sha256"] == row["payload"]["payload_sha256"]
                            and case["text_sha256"] == expected,
                            "archive sample provenance",
                        )
                    continue
                require(
                    previous[sha]["text_sha256"] == expected
                    and previous[sha]["bytes"] == row["utf8_bytes"]
                    and previous[sha]["page_slots"] == row["page_count"],
                    "prior cleanup qualification",
                )
                if sha in earlier:
                    old = earlier[sha]
                    require(
                        expected == old["selected_text_sha256"] and r["ocr_pages"] == old["ocr_pages"],
                        "source-qualified identity",
                    )
                    unchanged = old["action"] == "exact_carry_forward"
                    require(
                        unchanged == (expected == old["baseline_text_sha256"]), "control baseline equality"
                    )
                    row.update(
                        cohort="unchanged_control" if unchanged else "earlier_correction",
                        case_id=old["case_id"],
                        baseline_text_sha256=old["baseline_text_sha256"],
                    )
                else:
                    require(new[sha]["text_sha256"] == expected, "additional correction identity")
                    row.update(cohort="later_correction")
                if sha in queue:
                    id_ = row["case_id"]
                    page = 56 if id_ == "S017" else 0
                    text = slice_pages(sample[sha]["text"], row["page_offsets"], start_page=page, max_pages=1)
                    require(
                        text == (root / CLEANUP / (id_ + ".selected-page.txt")).read_text(),
                        f"{id_} restored passage",
                    )
                    row.update(
                        historical_queue=queue[sha],
                        restored_physical_page=page + 1,
                        restored_page_sha256=sha256(text.encode()).hexdigest(),
                    )
    require(set(rows) == set(live), "missing delivery case")
    counts = Counter(r["cohort"] for r in rows.values())
    require(
        counts == dict(unchanged_control=6, earlier_correction=8, later_correction=18, composed_archive=8505),
        "cleanup counts",
    )
    boundary = unassessed_scope(root, db, rows)
    db.close()
    data = dict(
        release=RELEASE,
        export=EXPORT,
        selection=SELECTION,
        counts=counts,
        inputs={
            str(path): fingerprint(root / path)
            for path in [
                EARLY / "exposure.json",
                CLEANUP / "result.json",
                SSOT / "review_packets/pdf_repairs_metadata.json",
                SSOT / "review_packets/warc_review_packet.json",
                QUEUE,
                SCREEN,
                OUT / "native-cleanup-metadata.parquet",
                OUT / "selected-readings.parquet",
                OUT / "v13-readback.json",
            ]
        },
        native_body_text=pointer["body_text"],
        doc_id_basis="Hex Explorer link_key. list_row is zero-based in the pinned release.",
        readback_basis="Parser, version and status from selected native readings. Source means v13 override "
        "or baseline. Character length comes from digest-matched text. OCR metadata matches the pinned native snapshot. "
        "Zero truncated rows in the published pointer applies to every row.",
        source_reviews=[
            str(EARLY / "data-review.md"),
            str(SSOT / "pdf_review/review.md"),
            str(SSOT / "warc_review/review.md"),
        ],
        diagnostics_bytes=8308326,
        diagnostics_files=14,
        unassessed=boundary,
        cases=[rows[s] for s in sorted(rows)],
    )
    write(out / "ct-kfsd-reconciliation.json", data)
    docs = {k: sum(len(r["documents"]) for r in rows.values() if r["cohort"] == k) for k in counts}
    (out / "ct-kfsd-summary.md").write_text(
        f"""# PDF cleanup delivery on November 20

Explorer release `{RELEASE}` has saved-body associations with verified text in v13 object `{EXPORT}`, selection `{SELECTION}`.

| Cohort | Bodies | Saved document rows |
| --- | ---: | ---: |
"""
        + "".join(f"| {k} | {counts[k]} | {docs[k]} |\n" for k in sorted(counts))
        + f"""
All four retained cleanup cases in the historical queue (S017, S055, S138 and S150) match their reviewed passage on the published page. The six controls preserve their entire baseline text, including legitimate running content. C015 retains its known handwriting omission. Fourteen diagnostic files from the earlier qualification total 8,308,326 bytes.

Each of the 8,537 bodies has one unhidden Explorer record. The native export snapshot confirms all 8,537 OCR page maps and build fields. The JSON ledger names each public link key, list row, saved SHA, selected version, text digest, page map and OCR provenance. Published text bytes were read for all 32 PDFs and 24 directly reviewed archive samples. Every other composed archive row matched its qualified text digest and page map. The 24 source reviews do not extend to the remaining archive files. Hosted search is outside this readback.

The unassessed Parquet names {boundary['bodies']:,} other historical or current PDF bodies, including {boundary['with_v13_text']:,} with a v13 row. Its union and exact hash are in the JSON ledger. A prior mechanical screen or an existing text row does not establish cleanup fidelity. No additional OCR ran.
"""
    )
    print(counts, docs, boundary["bodies"])


if __name__ == "__main__":
    reconcile(archive_arg())
