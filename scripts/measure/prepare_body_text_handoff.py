"""Bind retained text and quality state to one release without rereading text payloads."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from viewer_publication.body_text_export import file_facts
from viewer_publication.body_text_ssot import BodyTextSSOT


def pin(path):
    path = Path(path).resolve()
    facts = file_facts(path)
    return dict(path=str(path), sha256=facts["sha256"], size=facts["size"])


def prepare(*, export, source_handoff, release_manifest, detail, quality_state, output,
            inventory_manifest=None, export_verification=None, candidate_outcomes=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    reader = BodyTextSSOT(export)
    source_path = Path(source_handoff).resolve()
    source = json.loads(source_path.read_text())
    if source["release_id"] != reader.pointer["release_id"]:
        raise ValueError("Accepted source handoff names a different export release")
    manifest = json.loads(Path(release_manifest).read_text())
    detail_pin = pin(detail)
    declared = next(row for row in manifest["files"] if row["name"] == "detail.parquet")
    if any(detail_pin[key] != declared[key] for key in ("sha256", "size")):
        raise ValueError("Detail bytes do not match the intended release manifest")
    selection_path = Path(source["selection"]["path"])
    selection_pin = pin(selection_path)
    if (selection_pin["sha256"] != reader.pointer["selection"]["sha256"]
            or selection_pin["sha256"] != source["selection"]["sha256"]
            or selection_pin["size"] != source["selection"]["bytes"]):
        raise ValueError("Accepted selection does not match the text export")
    selection = json.loads(selection_path.read_text())
    source_qualification = pin(source["qualification"]["path"])
    if (source_qualification["sha256"] != source["qualification"]["sha256"]
            or source_qualification["size"] != source["qualification"]["bytes"]):
        raise ValueError("Source qualification differs from its handoff")
    inventory_binding = None
    if inventory_manifest is not None:
        inventory_meta = json.loads(Path(inventory_manifest).read_text())
        archive_root = Path(__file__).resolve().parents[2]/".cache/archive-release"
        inventory_file = archive_root / inventory_meta["inventory"]["path"]
        inventory_pin = pin(inventory_file)
        if (inventory_pin["sha256"] != inventory_meta["inventory"]["sha256"]
                or inventory_pin["size"] != inventory_meta["inventory"]["bytes"]):
            raise ValueError("Recovery inventory differs from its manifest")
        inventory_rows = [json.loads(line) for line in inventory_file.read_text().splitlines() if line.strip()]
        covered = {row["body_sha256"] for row in inventory_rows}
        for row in inventory_rows:
            covered.update(row.get("duplicate_wrapper_body_sha256", []))
        missing = [row["body_sha256"] for row in selection["excluded_bodies"]
                   if row["source_role"] == "error_response" and row["body_sha256"] not in covered]
        if missing:
            raise ValueError(f"Error exclusions missing from recovery inventory: {missing}")
        inventory_binding = dict(manifest=pin(inventory_manifest), inventory=inventory_pin,
                                 error_exclusions_reconciled=True)
    integrity = dict(fresh_checks="size, footer, rows; per-row digest on text read",
                     full_file_hash_verified_this_run=False)
    if export_verification is not None:
        prior_verification = json.loads(Path(export_verification).read_text())["export_parquet"]
        if any(prior_verification[key] != reader.pointer[key] for key in ("sha256", "bytes", "footer_sha256", "rows")):
            raise ValueError("Retained export verification names a different export")
        if prior_verification.get("all_row_sha256_verified") is not True:
            raise ValueError("Retained verification does not establish text row integrity")
        integrity["retained_verification"] = pin(export_verification)
    excluded = pa.table({name: [row[name] for row in selection["excluded_bodies"]]
                         for name in ("body_sha256", "source_role")})
    con = duckdb.connect(config={"memory_limit": "512MB", "threads": 2})
    try:
        con.register("excluded", excluded)
        con.read_parquet(str(Path(detail).resolve())).create_view("detail_input")
        con.read_parquet(str(reader.export_path)).create_view("export_input")
        con.read_parquet(str(Path(quality_state).resolve())).create_view("q")
        con.execute("CREATE VIEW d AS SELECT lower(hex(saved_body)) body_sha256, min(format) format FROM detail_input WHERE saved_body IS NOT NULL GROUP BY saved_body")
        con.execute("CREATE VIEW e AS SELECT lower(hex(saved_body)) body_sha256, lower(hex(text_sha256)) text_sha256 FROM export_input")
        # All inputs are narrow keys/state. No text column is decoded.
        query = """SELECT d.body_sha256,d.format,e.text_sha256,q.parser,q.parser_version,
          CASE WHEN x.body_sha256 IS NOT NULL OR q.source_excluded_from_prose THEN 'excluded'
               WHEN q.known_held_bad_output THEN 'held'
               WHEN e.body_sha256 IS NOT NULL AND q.text_sha256 IS DISTINCT FROM e.text_sha256 THEN 'unassessed'
               WHEN e.text_sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
                 THEN CASE WHEN q.known_valid_empty THEN 'valid_empty' ELSE 'unassessed_empty' END
               WHEN e.body_sha256 IS NOT NULL THEN 'available'
               WHEN d.format NOT IN ('pdf','html','xml','warc') THEN 'unsupported'
               WHEN q.current_state IN ('error','unreadable','size_limit','memory_limit','deadline') THEN 'refused'
               ELSE 'missing' END AS text_status,
          q.current_state,q.quality_scope,q.current_measurement_available,x.source_role
          FROM d LEFT JOIN e USING(body_sha256) LEFT JOIN q USING(body_sha256)
          LEFT JOIN excluded x USING(body_sha256) ORDER BY d.body_sha256"""
        coverage = con.execute(query).to_arrow_table()
        if coverage.num_rows != con.execute("SELECT count(*) FROM d").fetchone()[0]:
            raise ValueError("Duplicate body keys in export, quality state or exclusions")
        unused = con.execute("SELECT count(*) FROM e ANTI JOIN d USING(body_sha256)").fetchone()[0]
    finally:
        con.close()
    coverage_path = output / "coverage.parquet"
    pq.write_table(coverage, coverage_path, compression="zstd", row_group_size=4096)
    counts = Counter(coverage.column("text_status").to_pylist())
    gaps = Counter((row["text_status"], row["format"]) for row in coverage.select(["text_status", "format"]).to_pylist()
                   if row["text_status"] not in {"available", "valid_empty"})
    handoff = dict(version=1, release_id=manifest["release_id"],
                   source_release_id=reader.pointer["release_id"], export_sha256=reader.pointer["sha256"],
                   export_path=str(reader.export_path), export_pointer=pin(reader.pointer_path),
                   detail=detail_pin, release_manifest=pin(release_manifest),
                   selection=selection_pin, current_quality_state=pin(quality_state),
                   source_handoff=pin(source_path), catalog_pins=source["catalog_pins"],
                   source_qualification=source_qualification,
                   coverage=pin(coverage_path), counts=dict(counts), unused_export_bodies=unused,
                   recovery_inventory=inventory_binding, export_integrity=integrity,
                   candidate_outcomes=pin(candidate_outcomes) if candidate_outcomes is not None else None,
                   coverage_by_outcome_and_format={f"{status}:{fmt}": n for (status, fmt), n in sorted(gaps.items())},
                   qualification="Exact selected identity and explicit coverage; source-review limits remain in source_handoff")
    (output / "handoff.json").write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n")
    return handoff


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("export", "source-handoff", "release-manifest", "detail", "quality-state", "output"):
        parser.add_argument("--" + name, required=True)
    for name in ("inventory-manifest", "export-verification", "candidate-outcomes"):
        parser.add_argument("--" + name)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({"release_id": result["release_id"], "counts": result["counts"],
                      "coverage_by_outcome_and_format": result["coverage_by_outcome_and_format"]}, indent=2))
