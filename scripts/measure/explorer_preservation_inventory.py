"""Inventory retained Explorer fields and row references against one native candidate.

This is migration accounting, not a raw-source check or publication approval.
It never imports producers, builds a model, contacts a source or changes a pin.
Key/URL presence deliberately does not claim preservation of all row values.
Run under archive_watchdog; outputs must live in the main archive-release cache.
"""

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


LEGACY_TABLES = ("committees", "meetings", "materials", "witnesses", "issues", "sources")
NATIVE_TABLES = ("committees", "meetings", "sources", "videos", "channels", "recording_matches", "meeting_coverage", "committee_records")
NATIVE_INPUTS = ("captures", "readings", "filename_readings", "meeting_records", "appearance_records", "video_records", "committee_records", "playlist_records")
REQUIRED_CSV = {
    "gpo_hearing_video_coverage", "gpo_hearing_videos", "gpo_hearings", "hearing_text_sources",
    "hearing_video_overrides", "house_amendments_found", "house_documents_found", "house_witnesses_found",
    "meeting_completeness", "meeting_recordings_found", "meeting_witnesses", "meetings_without_records",
    "senate_documents_found", "senate_hearing_pages_found", "senate_witnesses_found", "youtube_event_id_report",
}


def identity(path, expected=None):
    """Hash incrementally; reject a wrong retained artifact before interpreting it."""
    path = Path(path)
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    result = dict(path=str(path.resolve()), sha256=digest.hexdigest(), size=path.stat().st_size)
    if expected and result["sha256"] != expected:
        raise ValueError(f"digest mismatch: {path}")
    return result


def fields(schema, prefix=""):
    """Include containers and nested leaves, so arrays cannot hide extra fields."""
    for field in schema:
        name = prefix + field.name
        yield name, str(field.type)
        kind = field.type
        if pa.types.is_list(kind) or pa.types.is_large_list(kind):
            kind = kind.value_type
            name += "[]"
        if pa.types.is_struct(kind):
            yield from fields(kind, name + ".")


def observe(value, kind, name, counts):
    counter = counts[name]
    counter["values"] += 1
    if value is None:
        counter["null"] += 1
        return
    if value == "" or value == []:
        counter["empty"] += 1
    if pa.types.is_list(kind) or pa.types.is_large_list(kind):
        for item in value:
            if pa.types.is_struct(kind.value_type) and item is not None:
                for child in kind.value_type:
                    observe(item.get(child.name), child.type, name + "[]." + child.name, counts)
    elif pa.types.is_struct(kind):
        for child in kind:
            observe(value.get(child.name), child.type, name + "." + child.name, counts)


def parquet_profile(path):
    source = pq.ParquetFile(path)
    counts = {name: Counter(values=0, null=0, empty=0) for name, _ in fields(source.schema_arrow)}
    fact_labels = Counter()
    # Witness occurrences have their own owner. Inspect their physical schema only.
    if Path(path).stem != "witnesses":
        for batch in source.iter_batches(batch_size=512, use_threads=False):
            for row in batch.to_pylist():
                for field in source.schema_arrow:
                    observe(row[field.name], field.type, field.name, counts)
                for fact in row.get("facts") or []:
                    if isinstance(fact, dict):
                        fact_labels[str(fact.get("label"))] += 1
    return dict(rows=source.metadata.num_rows,
                fields={name: dict(type=kind, **counts[name]) for name, kind in fields(source.schema_arrow)},
                fact_labels=dict(sorted(fact_labels.items())),
                scan="schema_only_ct-x78c" if Path(path).stem == "witnesses" else "all_rows")


def csv_profile(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        counts = {name: Counter(values=0, null=0, empty=0) for name in reader.fieldnames}
        rows = 0
        for row in reader:
            rows += 1
            if None in row:
                raise ValueError(f"unexpected extra CSV fields: {path}:{rows + 1}")
            for name, value in row.items():
                counts[name]["values"] += 1
                counts[name]["null" if value is None else "empty" if value == "" else "present"] += 1
    return dict(rows=rows, fields={name: dict(type="CSV string", **count) for name, count in counts.items()})


def sql_path(path):
    return "'" + str(Path(path).resolve()).replace("'", "''") + "'"


def native_input_comparison(selected, candidate):
    """Compare the entire selector, not snapshot numbers alone."""
    out = {}
    for name in NATIVE_INPUTS:
        left, right = selected.get(name), candidate.get(name)
        out[name] = dict(selected=left, candidate=right, same=left is not None and left == right)
    for name in ("recording_decision_files", "spicy_regs", "parser_versions"):
        left, right = selected.get(name), candidate.get(name)
        if name == "spicy_regs":
            left, right = ({k: v for k, v in value.items() if k != "path"} if value else value for value in (left, right))
        elif name == "recording_decision_files":
            left, right = ([{k: v for k, v in item.items() if k != "path"} for item in value] if value else value for value in (left, right))
        out[name] = dict(selected=selected.get(name), candidate=candidate.get(name),
                         same=left is not None and left == right)
    return out


def upstream_inventory(spec_path):
    """Read pinned upstream schemas, without rescanning member-vote payloads.

    Table digests below are declared pins, not a new content verification.
    Existing import/custody evidence owns verification of their payloads.
    """
    spec = json.loads(spec_path.read_text())
    pin = spec["spicy_regs"]
    path = (spec_path.parent / pin["path"]).resolve()
    result = dict(manifest=identity(path, pin["sha256"]), tables={})
    manifest = json.loads(path.read_text())
    result["generations"] = manifest["generations"]
    for name, table in manifest["tables"].items():
        member = path.parent / table["path"]
        item = dict(pin=table, status="declared_pin_local_payload_unavailable")
        if member.is_file():
            source = pq.ParquetFile(member)
            item.update(status="schema_footer_read_payload_hash_reused", physical_rows=source.metadata.num_rows,
                        fields=dict(fields(source.schema_arrow)))
        result["tables"][name] = item
    return result


def row_ledgers(db, legacy, native, output):
    """One row per old physical row; preserve nulls and repeated IDs via row number.

    These dispositions establish discovery or retention, not value equivalence.
    The referenced hash-pinned legacy file remains required for every disposition.
    """
    old = lambda name: f"read_parquet({sql_path(legacy / (name + '.parquet'))})"
    new = lambda name: f"read_parquet({sql_path(native / (name + '.parquet'))})"
    db.execute(f"""CREATE TEMP TABLE event_map AS
        SELECT m.id, max(try_cast(split_part(s.identifier_value,'|',4) AS BIGINT)) AS event_id
        FROM {old('meetings')} m, unnest(m.source_ids) x(sid), {old('sources')} s
        WHERE s.id=x.sid AND s.identifier_scheme='congress.gov:record' GROUP BY m.id""")
    db.execute(f"CREATE TEMP TABLE native_urls AS SELECT DISTINCT url FROM {new('sources')} WHERE url IS NOT NULL")
    db.execute(f"""INSERT INTO native_urls SELECT 'https://www.youtube.com/watch?v='||substr(video_key,9)
        FROM {new('videos')} WHERE starts_with(video_key,'youtube:')""")
    normalize = lambda value: f"replace({value},'http://','https://')"
    predicates = {
        "committees": (f"EXISTS(SELECT 1 FROM {new('committees')} n WHERE n.system_code=o.committee_code)", "committee_code_present_values_unverified", "committee_code_absent"),
        "meetings": (f"EXISTS(SELECT 1 FROM event_map e JOIN {new('meetings')} n USING(event_id) WHERE e.id=o.id)", "event_present_values_owned_ct-r4rd", "no_native_event_mapping"),
        "materials": (f"EXISTS(SELECT 1 FROM native_urls n WHERE {normalize('n.url')}={normalize('o.recording_url')}) OR EXISTS(SELECT 1 FROM unnest(o.files) f(item), native_urls n WHERE {normalize('n.url')}={normalize('f.item.url')})", "some_url_present_values_unverified", "no_native_material_url"),
        "sources": (f"EXISTS(SELECT 1 FROM native_urls n WHERE {normalize('n.url')}={normalize('o.url')})", "url_present_source_values_unverified", "retained_source_reference_only"),
        "issues": ("false", "unused", "retained_issue_history_requires_equivalence_review"),
    }
    result = {}
    for name, (predicate, present, absent) in predicates.items():
        target = output / (name + "-rows.parquet")
        db.execute(f"""COPY (SELECT row_number() OVER () AS legacy_row, o.id AS legacy_id,
            CASE WHEN {predicate} THEN '{present}' ELSE '{absent}' END AS disposition
            FROM {old(name)} o) TO {sql_path(target)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
        counts = dict(db.execute(f"SELECT disposition,count(*) FROM read_parquet({sql_path(target)}) GROUP BY 1").fetchall())
        result[name] = dict(rows=sum(counts.values()), dispositions=counts, ledger=identity(target))
    result["witnesses"] = dict(owner="ct-x78c", status="occurrence_ledger_not_duplicated")
    return result


def decision_acceptance(db, path, native):
    """Check every retained decision reference and its actual exported values.

    Channel, lock, found_by and origin stay in the pinned provenance JSONL;
    they are not native recording_matches fields. Conflicts stay unresolved.
    """
    rows = db.execute(f"SELECT source_ref,subject_kind,subject_id,decision,video_key,url,note,status FROM read_parquet({sql_path(native / 'recording_matches.parquet')}) WHERE basis='curated'").fetchall()
    by_ref = {}
    for row in rows:
        by_ref.setdefault(row[0], []).append(row[1:])
    counts, gaps, seen = Counter(), [], set()
    with path.open() as source:
        for number, line in enumerate(source, 1):
            record = json.loads(line)
            if record["id"] in seen:
                raise ValueError("duplicate decision ID requires occurrence accounting")
            seen.add(record["id"])
            if record.get("supersedes"):
                raise ValueError("decision history requires active/superseded accounting")
            expected = Counter((ref if ref.startswith(("http://", "https://")) else "youtube:" + ref, ref.startswith(("http://", "https://"))) for ref in record["video_refs"])
            if not expected:
                expected[(None, False)] = 1
            actual = by_ref.pop("recording_decisions:" + record["id"], [])
            observed = Counter((url or video, url is not None) for _, _, _, video, url, _, _ in actual)
            bad = observed != expected
            for kind, subject, verdict, _, _, note, status in actual:
                bad |= (kind, subject, verdict) != (record["subject_kind"], record["subject_id"], record["verdict"])
                # A dispute is appended to the note, and may change the status.
                expected_note = record.get("note")
                if record.get("disputed_by"):
                    expected_note = " | ".join(value for value in (expected_note, "disputed by " + record["disputed_by"]) if value is not None)
                    bad |= status not in ("unresolved", "conflicting")
                bad |= note != expected_note
            counts["different_or_missing" if bad else "preserved"] += 1
            if bad:
                gaps.append(dict(line=number, id=record["id"], actual_rows=len(actual)))
    return dict(decisions=dict(counts), gaps=gaps, unexpected_candidate_references=sorted(by_ref),
                accepted=not gaps and not by_ref)


def decision_source_acceptance(path, data):
    """Compare retained provenance with every original curated CSV field.

    This reading does not call the importer. CSV ordering supplies the original
    occurrence; provenance must name the actual file digest for that occurrence.
    """
    with path.open() as source:
        decisions = [json.loads(line) for line in source]
    offset, gaps, checked = 0, [], 0
    for filename in ("hearing_video_overrides.csv", "meeting_recordings_found.csv"):
        source_path = data / filename
        digest = identity(source_path)["sha256"]
        with source_path.open(newline="") as source:
            for number, row in enumerate(csv.DictReader(source), 2):
                record = decisions[offset] if offset < len(decisions) else {}
                offset += 1
                if filename == "hearing_video_overrides.csv":
                    expected = dict(subject_kind="package", subject_id=row["package_id"], verdict=row["verdict"],
                                    video_refs=row["video_ids"].split(), channel=row["channel"] or None,
                                    lock=row["lock"] or None, note=row["note"] or None, found_by=None)
                else:
                    expected = dict(subject_kind="event", subject_id=row["event_id"], verdict="found",
                                    video_refs=[row["recording"]] if row["recording"] else [], channel=None,
                                    lock=None, note=row["note"] or None, found_by=row["found_by"] or None)
                origin = record.get("origin", {})
                bad = [name for name, value in expected.items() if record.get(name) != value]
                if origin.get("sha256") != digest or Path(origin.get("path", "")).name != filename:
                    bad.append("origin")
                checked += 1
                if bad:
                    gaps.append(dict(file=filename, line=number, fields=bad))
    return dict(checked=checked, extra_decisions=max(0, len(decisions) - offset), gaps=gaps,
                accepted=not gaps and offset == len(decisions))


def issue_accounting(db, legacy):
    """Keep finite historical issue classes, including actual adjudications.

    Historical history is retained by reference. Association and source-shape
    classes still require native reconciliation; their old status is not a
    decision about the candidate.
    """
    classes = []
    for title, status, count in db.execute(f"SELECT title,status,count(*) FROM read_parquet({sql_path(legacy / 'issues.parquet')}) GROUP BY 1,2 ORDER BY 1,2").fetchall():
        if status in ("resolved", "dismissed"):
            disposition = "historical_adjudication_retained"
        elif title.startswith("Sources disagree about"):
            disposition = "historical_conflict_alternatives_retained"
        elif "Legacy House state" in title:
            disposition = "source_shape_gap_requires_native_reconciliation"
        elif any(term in title for term in ("association", "assigned", "ownership", "identity review", "correspondence review")):
            disposition = "association_gap_requires_native_reconciliation"
        elif any(term in title for term in ("retained decision", "clips_only")):
            disposition = "inferred_recording_observation_requires_native_destination"
        else:
            disposition = "historical_source_diagnostic_retained"
        classes.append(dict(title=title, status=status, rows=count, disposition=disposition))
    q = f"read_parquet({sql_path(legacy / 'sources.parquet')})"
    adjudications = db.execute(f"SELECT count(*),count(DISTINCT retained_sha256),count(*) FILTER(WHERE retained_uri IS NOT NULL) FROM {q} WHERE provider='curated-issue-decisions'").fetchone()
    return dict(classes=classes, rows=sum(item["rows"] for item in classes),
                adjudication_sources=dict(rows=adjudications[0], distinct_body_digests=adjudications[1], retained_locators=adjudications[2]),
                qualification="Class dispositions do not approve retirement or establish candidate equivalence. Original JSON and raw-body custody remain distinct.")


def run(args):
    started = time.monotonic()
    missing = REQUIRED_CSV - {path.stem for path in args.data.glob("*.csv")}
    if missing:
        raise ValueError("missing retained CSV inputs: " + ", ".join(sorted(missing)))
    args.output.mkdir(parents=True, exist_ok=False)
    old_manifest = json.loads((args.legacy / "manifest.json").read_text())
    manifest = json.loads((args.candidate / "manifest.json").read_text())
    old_pins = {row["path"]: row["sha256"] for row in old_manifest["partitions"]}
    new_pins = {row["name"]: row["sha256"] for row in manifest["files"]}
    candidate_spec = json.loads(args.candidate_spec.read_text())
    decision_files = candidate_spec["recording_decision_files"]
    if len(decision_files) != 1:
        raise ValueError("this retained comparison requires exactly one decision file")
    decision_identity = identity(args.decisions, decision_files[0]["sha256"])
    if decision_identity["size"] != decision_files[0]["size"]:
        raise ValueError("decision file size mismatch")
    report = dict(result_kind="retention_inventory_with_scoped_value_checks", publication_approved=False,
                  legacy_release=old_manifest["publication_id"], candidate_release=manifest["release_id"],
                  source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  legacy_manifest=identity(args.legacy / "manifest.json"), candidate_manifest=identity(args.candidate / "manifest.json"),
                  legacy_inputs=old_manifest["inputs"], legacy_tables={}, retained_csv={}, candidate_files={},
                  limits=["Row key/URL presence is not full value preservation.", "Witness occurrences: ct-x78c; meeting value parity: ct-r4rd.",
                          "Legacy-only values remain required in hash-pinned inputs; no retirement or publication approval."])
    for name in LEGACY_TABLES:
        path = args.legacy / (name + ".parquet")
        report["legacy_tables"][name] = dict(identity=identity(path, old_pins[path.name]), **parquet_profile(path))
    for path in sorted(args.data.glob("*.csv")):
        report["retained_csv"][path.name] = dict(identity=identity(path), **csv_profile(path))
    for name in NATIVE_TABLES:
        path = args.candidate / (name + ".parquet")
        report["candidate_files"][name] = identity(path, new_pins[path.name])
    report["decisions_identity"] = decision_identity
    report["tool_identity"] = identity(Path(__file__))
    report["decision_source_fields"] = decision_source_acceptance(args.decisions, args.data)
    report["selected_spec"] = identity(args.selected_spec)
    report["candidate_spec"] = identity(args.candidate_spec)
    report["input_comparison"] = native_input_comparison(json.loads(args.selected_spec.read_text()), candidate_spec)
    report["upstream"] = dict(selected=upstream_inventory(args.selected_spec), candidate=upstream_inventory(args.candidate_spec))
    root = args.selected_spec.resolve().parents[2]
    report["reference_inputs"] = {}
    for relative in ("packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv",
                     "packages/congress_shared/src/congress_shared/data/congress_metadata.json",
                     "model/registries/archive-layouts.json"):
        path = root / relative
        item = dict(identity=identity(path))
        if path.suffix == ".csv":
            item.update(csv_profile(path))
        else:
            item["value"] = json.loads(path.read_text())
        report["reference_inputs"][relative] = item
    with duckdb.connect(config=dict(memory_limit="384MB", threads=1, preserve_insertion_order=True)) as db:
        report["rows"] = row_ledgers(db, args.legacy, args.candidate, args.output)
        report["recording_decisions"] = decision_acceptance(db, args.decisions, args.candidate)
        report["issue_classes"] = issue_accounting(db, args.legacy)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["input_file_bytes"] = sum(v["identity"]["size"] for v in report["legacy_tables"].values()) + sum(v["identity"]["size"] for v in report["retained_csv"].values()) + sum(v["size"] for v in report["candidate_files"].values())
    (args.output / "inventory.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(candidate=report["candidate_release"], rows={k: v.get("dispositions", v) for k, v in report["rows"].items()}, recording_decisions=report["recording_decisions"], elapsed_seconds=report["elapsed_seconds"]), indent=2))
    return 0 if report["recording_decisions"]["accepted"] and report["decision_source_fields"]["accepted"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("legacy", "candidate", "data", "decisions", "selected-spec", "candidate-spec", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
