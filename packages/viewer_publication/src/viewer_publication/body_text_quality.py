"""Keep text-quality measurements attached to the reading they actually measured.

These checks establish identity, not source completeness. Historical measurements
remain available in the input generation and the invalidation journal.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

IDENTITY = ("body_sha256", "parser", "parser_version", "text_sha256")
MEASUREMENT_FIELDS = ("measurement_file", "measurement_family", "measurement_band", "measured_text_bytes")


def _identity(row):
    values = tuple(row.get(key) for key in IDENTITY)
    return values if all(isinstance(value, str) and value for value in values) else None


def _json_measurements(value):
    """Read supported whole-reading observations, never infer identity from a filename."""
    if isinstance(value, list):
        for item in value:
            yield from _json_measurements(item)
    elif isinstance(value, dict):
        identity = value.get("identity", value)
        if isinstance(identity, dict) and _identity(identity):
            yield dict(value, **identity)
        elif isinstance(value.get("rows"), list):
            yield from _json_measurements(value["rows"])


def measurement_identities(path):
    """Return exact identities and optional byte counts from one retained reference."""
    path = Path(path)
    if path.suffix == ".parquet":
        pf = pq.ParquetFile(path)
        names = set(pf.schema_arrow.names)
        if not set(IDENTITY) <= names:
            return {}
        columns = list(IDENTITY) + [name for name in ("text_bytes", "band", "measurement_family") if name in names]
        rows = (row for batch in pf.iter_batches(columns=columns, batch_size=4096)
                for row in batch.to_pylist())
    elif path.suffix == ".jsonl":
        rows = (row for line in path.read_text().splitlines() if line.strip()
                for row in _json_measurements(json.loads(line)))
    else:
        rows = _json_measurements(json.loads(path.read_text()))
    result = {}
    for row in rows:
        if identity := _identity(row):
            measured = dict(text_bytes=row.get("text_bytes"),
                            band=row.get("band", row.get("fts_triage", {}).get("band")),
                            family=row.get("measurement_family"))
            if identity in result and result[identity] != measured:
                raise ValueError(f"Conflicting measurement values in {path}: {identity}")
            result[identity] = measured
    return result


def reconcile_measurements(current_state, output, history):
    """Validate every claimed-current reference; clear only unsupported associations.

    Read narrow measurement columns once per referenced file. Text Parquets are
    never opened. Outputs are create-only so the original generation remains intact.
    """
    current_state, output, history = map(Path, (current_state, output, history))
    if output.exists() or history.exists():
        raise FileExistsError("Quality reconciliation outputs must be new paths")
    pf = pq.ParquetFile(current_state)
    references = set()
    for batch in pf.iter_batches(columns=["current_measurement_available", "measurement_file"]):
        references.update(row["measurement_file"] for row in batch.to_pylist()
                          if row["current_measurement_available"] and row["measurement_file"])
    indexes, failures = {}, {}
    for ref in sorted(references):
        try:
            indexes[ref] = measurement_identities(ref)
        except (OSError, json.JSONDecodeError, pa.ArrowInvalid) as error:
            failures[ref] = f"{type(error).__name__}: {error}"
            indexes[ref] = {}
    counts = Counter()
    with history.open("x") as journal, pq.ParquetWriter(output, pf.schema_arrow, compression="zstd") as writer:
        for batch in pf.iter_batches(batch_size=4096):
            rows = batch.to_pylist()
            for row in rows:
                counts["rows"] += 1
                if not row["current_measurement_available"]:
                    continue
                counts["claimed_current"] += 1
                identity = _identity(row)
                measured = indexes.get(row["measurement_file"], {})
                reason = None
                if identity not in measured:
                    reason = "measurement_identity_unavailable_or_different"
                elif (measured[identity]["text_bytes"] is not None and row["measured_text_bytes"] is not None
                      and measured[identity]["text_bytes"] != row["measured_text_bytes"]):
                    reason = "measurement_byte_count_differs"
                elif measured[identity]["band"] is not None and measured[identity]["band"] != row["measurement_band"]:
                    reason = "measurement_band_differs"
                elif measured[identity]["family"] is not None and measured[identity]["family"] != row["measurement_family"]:
                    reason = "measurement_family_differs"
                if reason:
                    journal.write(json.dumps({"reason": reason, "previous_state": row}, sort_keys=True) + "\n")
                    row["current_measurement_available"] = False
                    for key in MEASUREMENT_FIELDS:
                        row[key] = None
                    counts[reason] += 1
                    counts["invalidated"] += 1
                else:
                    if row["measurement_band"] is not None and measured[identity]["band"] is None:
                        journal.write(json.dumps({"reason": "measurement_band_not_recorded", "previous_state": row}, sort_keys=True) + "\n")
                        row["measurement_band"] = None
                        counts["unrecorded_bands_cleared"] += 1
                    counts["verified_current"] += 1
            writer.write_table(pa.Table.from_pylist(rows, schema=pf.schema_arrow))
    return {**counts, "measurement_files": len(references), "unreadable_references": failures,
            "scope": "Exact measurement identity, recorded byte counts/bands/family; source fidelity not inferred"}
