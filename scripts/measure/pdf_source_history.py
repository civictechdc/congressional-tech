"""Read immutable capture and reading history for the two November 20 reconciliations."""

import gzip
import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin

from lxml import html

from congress_api.lake import body_text_selection
from congress_api.lake.tables import table_input
from congress_api.retention.provenance import parquet_output
from docspec_client.client import NativeDatasets
import pyarrow as pa
import pyarrow.parquet as pq

from pdf_source_evidence import (
    BUCKET,
    CLEANUP,
    RELEASE,
    SSOT,
    INVENTORY,
    OCR,
    OUT,
    SELECTION_FILE,
    archive_arg,
    lines,
    load,
    remote,
    require,
    write,
)

METADATA = {
    "captures": "captures_df55_20261113/metadata/00016-01a1fa3e-a2d5-78e3-a679-e12a9847988c.gz.metadata.json",
    "readings": "body_text_readings/metadata/00010-01a1faa2-9633-7060-933a-c58ad7c361f5.gz.metadata.json",
}


def receipt_provenance(root, inventory):
    previous = root / "ticket-fixes-20261117/inventory/current-history.json"
    missing = {r["body_sha256"] for r in inventory if not r["targets"]}
    observations = defaultdict(dict)
    for r in load(previous)["rows"]:
        if r["body_sha256"] in missing:
            observations[r["receipt_key"]].setdefault(r["receipt_line"], []).append(r)
    raw_path = (
        OCR / "repairs/corpus-assessment-20261113/house-response-detection-20261114/repair-02/outcomes.jsonl"
    )
    raw = {r["body_sha256"]: Path(r["source_path"]) for r in lines(root / raw_path)}
    found = {}
    for key, wanted_lines in sorted(observations.items()):
        with gzip.open(root.parent / "docspec-catalog/r2-immutable" / key) as stream:
            for number, line in enumerate(stream, 1):
                if number not in wanted_lines:
                    continue
                record = json.loads(line)
                for history in wanted_lines[number]:
                    sha = history["body_sha256"]
                    index = history["capture_index"]
                    fact = dict(
                        receipt_key=key,
                        receipt_line=number,
                        capture_index=index,
                        source_file=record["source_file"],
                        source_line=record["source_line"],
                        http_requested_url=history["requested_url"],
                    )
                    if record["captures"]:
                        cap = record["captures"][index]
                        event, evidence, field = cap["pointer"]
                        require(
                            cap["sha256"] == sha and (evidence, field) == ("evidence", "html"),
                            "receipt pointer",
                        )
                        parent = record["record"][event]
                        data = raw[sha].read_bytes()
                        actions = html.fromstring(data).xpath("//form/@action")
                        require(
                            sha256(data).hexdigest() == sha
                            and actions == [f"./ByEvent.aspx?EventID={event}"],
                            "receipt meeting differs from saved form",
                        )
                        fact.update(
                            kind="embedded_house_meeting_fallback",
                            pointer=cap["pointer"],
                            parent_status=parent["status"],
                            parent_urls=parent["urls"],
                            source_inputs=parent["replay"]["inputs"],
                            form_action=actions[0],
                            source_url=urljoin("https://docs.house.gov/Committee/Calendar/", actions[0]),
                            url_basis="receipt event ID and verified HTML form action at House calendar",
                        )
                    else:
                        ref = record["file_references"][index]
                        require(
                            ref["sha256"] == ref["source_sha256"] == sha
                            and ref["status"] == "verified"
                            and ref["original_path"].endswith(
                                "https_www_appropriations_senate_gov_hearings_PageNum_rs_0.html"
                            ),
                            "Senate file reference",
                        )
                        fact.update(
                            kind="retained_senate_listing_security_response",
                            original_path=ref["original_path"],
                            source_url="https://www.appropriations.senate.gov/hearings?PageNum_rs=0",
                            url_basis="reconstructed from retained filename and Senate listing URL pattern",
                        )
                    require(sha not in found, "duplicate receipt provenance")
                    found[sha] = fact
                if number == max(wanted_lines):
                    break
    require(set(found) == missing and len(found) == 188, "unexplained historical source")
    return found


def collect_history(root):
    out = root / OUT
    client, _ = remote(root)
    inputs = []
    for name, suffix in METADATA.items():
        key = "__r2_data_catalog/ct-archive-v2/archive_r1b/" + suffix
        metadata = json.loads(gzip.decompress(client.get_object(Bucket=BUCKET, Key=key)["Body"].read()))
        inputs.append(
            table_input(
                name,
                dict(
                    metadata_location=f"s3://{BUCKET}/{key}",
                    table_uuid=metadata["table-uuid"],
                    snapshot=metadata["current-snapshot-id"],
                    schema_id=metadata["current-schema-id"],
                ),
            )
        )
    inventory = list(lines(root / INVENTORY))
    keys = {r["body_sha256"] for r in inventory + load(out / "zero-page-structure.json")}
    keys.update(w for r in inventory for w in r.get("duplicate_wrapper_body_sha256", []))
    # The universal empty digest is meaningful only at the Cornwell URL.
    keys.discard(sha256(b"").hexdigest())
    provenance = receipt_provenance(root, inventory)
    write(out / "receipt-provenance.json", provenance)
    proposal = load(root / OCR / "repairs/response-roles-offline-20261113/deferred-source-proposal.json")
    landings = proposal["unresolved"] + proposal["excluded_resolved"]
    keys.update(r["source_body_sha256"] for r in landings)
    urls = sorted(
        {url for r in inventory for url in r["source_urls"]}
        | {r["source_url"] for r in provenance.values()}
        | {r[k] for r in landings for k in ("source_url", "target_url")}
        | {r["target_url"].replace("&download=1", "?download=1") for r in landings}
    )
    keys_sql = ",".join("decode('" + s + "','hex')" for s in sorted(keys))
    urls_sql = ",".join("'" + u.replace("'", "''") + "'" for u in urls)
    history_sql = f"""SELECT receipt_key,receipt_line,capture_index,mode,family,
        requested_url,url,context_url,original_url,recovered_url,original_path,member_path,
        outcome,http_status,complete,retrieved_at,bytes,stored_bytes,media_type,
        encode(sha256,'hex') AS body_sha256 FROM captures WHERE sha256 IN ({keys_sql}) OR """ + " OR ".join(
        f"{col} IN ({urls_sql})" for col in ("requested_url", "url", "original_url", "recovered_url")
    )
    pointer = load(out / "v13-pointer.json")
    selected = body_text_selection.load(SELECTION_FILE, pointer["parser_versions"])
    choices = out / "selection-keys.parquet"
    pq.write_table(pa.Table.from_pylist(selected["overrides"]), choices)
    inputs.append(table_input("body_text_choices", choices))
    sql = body_text_selection.selected_sql(
        "readings",
        selected,
        incremental_versions=pointer["incremental_versions"],
        columns=["body_sha", "parser", "parser_version", "status", "error_type"],
    )
    run_projection(
        root,
        "history",
        inputs,
        [
            ("capture-history", history_sql, ["receipt_key", "receipt_line", "capture_index"]),
            ("selected-readings", sql, ["body_sha", "parser"]),
        ],
    )


def native_text_metadata(root):
    """The public export omits OCR fields. Check them at its exact native snapshot."""
    out = root / OUT
    client, _ = remote(root)
    published = json.load(client.get_object(Bucket=BUCKET, Key="viewer-publications/manifest.json")["Body"])
    require(published["release_id"] == RELEASE, "Explorer release changed")
    write(out / "explorer-pointer.json", published)
    pointer = load(out / "v13-pointer.json")
    pdfs = load(root / CLEANUP / "result.json")["cases"]
    wanted = {bytes.fromhex(r["body_sha256"]) for r in pdfs}
    wanted.update(
        pq.read_table(root / SSOT / "staged/warc_compose/readings.parquet", columns=["body_sha"])[
            "body_sha"
        ].to_pylist()
    )
    target = out / "cleanup-body-keys.parquet"
    pq.write_table(pa.table({"body_sha": pa.array(sorted(wanted), pa.binary(32))}), target)
    inputs = [
        table_input("wanted", target),
        table_input("body_text", pointer["body_text"]),
        table_input("selected_readings", out / "selected-readings.parquet"),
    ]
    sql = """SELECT t.body_sha,t.parser,t.parser_version,t.text_sha256,t.page_offsets,t.ocr_pages,t.macos_build
             FROM (SELECT r.body_sha,r.parser,r.parser_version FROM wanted w JOIN selected_readings r
                   ON w.body_sha=r.body_sha) k JOIN body_text t USING(body_sha,parser,parser_version)"""
    run_projection(root, "native-metadata", inputs, [("native-cleanup-metadata", sql, ["body_sha"])])


def run_projection(root, name, inputs, tables):
    out = root / OUT
    config = load(root / "remote-runtime/runtime.json")
    write(out / "read-runtime.json", dict(config, workspace=str(out / "read-workspace")))
    with TemporaryDirectory(dir=out) as temp:
        stage = Path(temp)
        outputs = [parquet_output(stage, table, sql, order) for table, sql, order in tables]
        job = out / (name + "-job.json")
        write(job, dict(scratch=str(stage / "scratch"), inputs=inputs, steps=[], outputs=outputs, queries=[]))
        with NativeDatasets.from_config(out / "read-runtime.json") as engine:
            result = engine.run_job(job, log=out / (name + "-engine.log"))
        for item in outputs:
            path = Path(item["path"])
            path.replace(out / path.name)
        write(out / (name + "-result.json"), result)


if __name__ == "__main__":
    root = archive_arg()
    collect_history(root)
    native_text_metadata(root)
