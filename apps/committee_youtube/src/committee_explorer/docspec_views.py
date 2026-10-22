"""Declarative docspec-rs RefreshSpec and ExportSpec definitions for Committee Explorer.

Mechanism vs. Policy Boundary (CS 300):
- ``docspec-rs`` owns the generic relational mechanisms: keyed ``UpdateMergeSpec``,
  ordered ``FirstValueBy`` and ``CollectDistinctWithProvenance`` aggregations in
  ``RefreshSpec``, chained ``RefreshSpec`` execution over prior ``Refresh``
  outputs, and deterministic sorted Parquet ``ExportSpec`` / ``ExportPin``
  publication.
- Python domain policy in ``committee_explorer.assemble`` and
  ``committee_explorer.parquet`` owns domain-specific conflict dismissal rules
  (such as ``_review_old_label_conflict``, collector placeholder label
  normalization, transitioning ``access`` from ``"unknown"`` to a known value
  without raising a conflict, and ``DataIssue`` emission).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Any

import pyarrow as pa
from docspec_client import DocSpecFailure, NativeDatasets

from .parquet import SOURCE_SCHEMA, TABLE_SCHEMAS

COMMITTEE_EXPLORER_DEFINITION = "committee-explorer-v1"
OBSERVATIONS_DATASET = "explorer_meeting_observations"
MEETING_SUMMARY_DATASET = "explorer_meeting_summaries"
COMMITTEE_ROLLUP_DATASET = "explorer_committee_rollups"

_DATASET_ALIASES: dict[str, str] = {
    "explorer_meeting_summary": MEETING_SUMMARY_DATASET,
    "explorer_committee_rollup": COMMITTEE_ROLLUP_DATASET,
}

SOURCE_RANK_BY_PROVIDER: dict[str, int] = {
    "congress.gov": 1,
    "docs.house.gov": 2,
    "senate.committees": 3,
    "govinfo.gov": 4,
    "govinfo": 4,
    "gpo.committee-review": 5,
    "youtube": 6,
}

COMMITTEE_EXPLORER_OBSERVATIONS_SCHEMA = pa.schema([
    pa.field("meeting_id", pa.string(), nullable=False),
    pa.field("congress", pa.int64(), nullable=False),
    pa.field("chamber", pa.string(), nullable=False),
    pa.field("committee", pa.string(), nullable=True),
    pa.field("subcommittee", pa.string(), nullable=True),
    pa.field("title", pa.string(), nullable=True),
    pa.field("date", pa.string(), nullable=True),
    pa.field("type", pa.string(), nullable=True),
    pa.field("status", pa.string(), nullable=True),
    pa.field("source_rank", pa.int64(), nullable=False),
    pa.field("source_id", pa.string(), nullable=False),
    pa.field("source_type", pa.string(), nullable=False),
    pa.field("witness_name", pa.string(), nullable=True),
])

BROWSER_TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "meetings": TABLE_SCHEMAS["meeting"],
    "committees": TABLE_SCHEMAS["committee_term"],
    "materials": TABLE_SCHEMAS["material"],
    "witnesses": TABLE_SCHEMAS["appearance"],
    "issues": TABLE_SCHEMAS["data_issue"],
    "sources": SOURCE_SCHEMA,
}

BROWSER_TABLE_DATASETS: dict[str, str] = {
    name: f"explorer_browser_{name}" for name in BROWSER_TABLE_SCHEMAS
}

BROWSER_TABLE_SORT_KEYS: dict[str, tuple[tuple[str, str], ...]] = {
    "meetings": (("congress", "asc"), ("id", "asc")),
    "committees": (("congress", "asc"), ("id", "asc")),
    "materials": (("congress", "asc"), ("id", "asc")),
    "witnesses": (("congress", "asc"), ("id", "asc")),
    "issues": (("congress", "asc"), ("id", "asc")),
    "sources": (("id", "asc"),),
}

BROWSER_TABLE_BLOOM_COLUMNS: dict[str, tuple[str, ...]] = {
    "meetings": ("id", "meeting_id", "chamber"),
    "committees": ("id", "committee_code", "chamber"),
    "materials": ("id", "meeting_id", "provider"),
    "witnesses": ("id", "meeting_id", "organization"),
    "issues": ("id", "meeting_id", "category"),
    "sources": ("id", "provider"),
}


def resolve_docspec_binary(binary: Path | str | None = None) -> Path:
    """Resolve the native ``docspec`` binary supporting RefreshSpec and ExportSpec."""
    if binary is not None:
        return Path(binary).resolve()
    env_bin = os.environ.get("DOCSPEC_BIN")
    if env_bin and Path(env_bin).exists():
        return Path(env_bin).resolve()
    candidates = (
        Path("/Users/mikewolfd/.gemini/antigravity/brain/b9128fc0-078b-4f90-8508-e77d78324209/scratch/worktrees/wt-ss-023x-65bz/target/debug/docspec"),
        Path("/Users/mikewolfd/.gemini/antigravity/brain/b9128fc0-078b-4f90-8508-e77d78324209/scratch/worktrees/wt-ss-6gwu-yjvy/target/debug/docspec"),
        Path("/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec"),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    found = shutil.which("docspec")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError("Unable to locate native docspec binary")


def version_ref(pin: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the ``VersionRef`` dictionary from a ``ReleasePin``."""
    return {
        "dataset": pin["dataset"]["dataset"],
        "version": pin["id"],
        "manifest": pin["manifest"],
    }


def _rank_order_by() -> list[dict[str, str]]:
    return [
        {"field": "source_rank", "direction": "asc", "nulls": "nulls_last"},
        {"field": "source_id", "direction": "asc", "nulls": "nulls_last"},
    ]


def build_meeting_summary_refresh_spec(
    observations_pin: Mapping[str, Any],
    *,
    operation: str,
    base: str | None = None,
    mode: str = "full",
) -> dict[str, Any]:
    """Build the declarative ``RefreshSpec`` aggregating meeting observations.

    Uses ``FirstValueBy`` ordered by ``(source_rank ASC, source_id ASC)`` for
    scalar meeting attributes and ``CollectDistinctWithProvenance`` for witness
    rosters with source provenance.
    """
    order_by = _rank_order_by()
    first_value_fields = ("committee", "subcommittee", "title", "date", "type", "status")
    aggregates: list[dict[str, Any]] = [
        {
            "name": field,
            "function": {
                "kind": "first_value_by",
                "field": field,
                "order_by": order_by,
            },
        }
        for field in first_value_fields
    ]
    aggregates.append({
        "name": "witnesses_with_provenance",
        "function": {
            "kind": "collect_distinct_with_provenance",
            "field": "witness_name",
            "provenance_fields": ["source_id", "source_type"],
            "order_by": order_by,
        },
    })
    aggregates.append({
        "name": "sources",
        "function": {
            "kind": "collect_set",
            "field": "source_type",
        },
    })
    return {
        "dataset": MEETING_SUMMARY_DATASET,
        "operation": operation,
        "base": base,
        "definition": COMMITTEE_EXPLORER_DEFINITION,
        "transform": {
            "kind": "aggregate",
            "input": version_ref(observations_pin),
            "grouping": {
                "keys": ["meeting_id", "congress", "chamber"],
                "aggregates": aggregates,
            },
        },
        "policy": "captured",
        "mode": mode,
    }


def build_committee_rollup_refresh_spec(
    meeting_summary_pin: Mapping[str, Any],
    *,
    operation: str,
    base: str | None = None,
    mode: str = "full",
) -> dict[str, Any]:
    """Build a chained ``RefreshSpec`` (``ss-65bz``) consuming ``explorer_meeting_summaries``."""
    return {
        "dataset": COMMITTEE_ROLLUP_DATASET,
        "operation": operation,
        "base": base,
        "definition": COMMITTEE_EXPLORER_DEFINITION,
        "transform": {
            "kind": "aggregate",
            "input": version_ref(meeting_summary_pin),
            "grouping": {
                "keys": ["committee", "chamber"],
                "aggregates": [
                    {"name": "meeting_count", "function": {"kind": "count_rows"}},
                    {"name": "first_congress", "function": {"kind": "min", "field": "congress"}},
                    {"name": "last_congress", "function": {"kind": "max", "field": "congress"}},
                ],
            },
        },
        "policy": "captured",
        "mode": mode,
    }


def build_browser_export_spec(
    table_name: str,
    source_pin: Mapping[str, Any],
    *,
    operation: str,
    channel: str = "public",
    expected: str | None = None,
    include_extended_policy: bool = True,
) -> dict[str, Any]:
    """Build the declarative ``ExportSpec`` for one of the 6 browser Parquet tables."""
    if table_name not in BROWSER_TABLE_SCHEMAS:
        raise ValueError(f"Unknown Committee Explorer browser table: {table_name!r}")
    schema = BROWSER_TABLE_SCHEMAS[table_name]
    policy: dict[str, Any] = {
        "group": "source",
        "rows": "all",
        "columns": list(schema.names),
    }
    if include_extended_policy:
        policy["order_by"] = [
            {"column": col, "direction": direction, "nulls_first": False}
            for col, direction in BROWSER_TABLE_SORT_KEYS[table_name]
        ]
        policy["page_index_columns"] = list(BROWSER_TABLE_BLOOM_COLUMNS[table_name])
        policy["row_group_rows"] = 256 if table_name == "sources" else 2048
    return {
        "dataset": source_pin["dataset"]["dataset"],
        "operation": operation,
        "source": version_ref(source_pin),
        "channel": channel,
        "expected": expected,
        "policy": policy,
    }


def build_observations_table(rows: Iterable[Mapping[str, Any]]) -> pa.Table:
    """Build a sorted Arrow table matching ``COMMITTEE_EXPLORER_OBSERVATIONS_SCHEMA``."""
    materialized = [
        {**r, "chamber": str(r.get("chamber") or "unknown")}
        for r in rows
    ]
    materialized.sort(
        key=lambda r: (
            str(r.get("meeting_id") or ""),
            int(r.get("congress") or 0),
            int(r.get("source_rank") or 99),
            str(r.get("source_id") or ""),
        )
    )
    columns = {
        field.name: [row.get(field.name) for row in materialized]
        for field in COMMITTEE_EXPLORER_OBSERVATIONS_SCHEMA
    }
    return pa.Table.from_pydict(columns, schema=COMMITTEE_EXPLORER_OBSERVATIONS_SCHEMA)


def extract_meeting_observations(catalog: Any) -> list[dict[str, Any]]:
    """Extract normalized ``explorer_meeting_observations`` rows from an assembled ``Catalog``."""
    from collections import defaultdict

    committees = {r.id: r for r in catalog.records if r.kind == "committee_term"}
    dates: dict[str, str] = {}
    statuses: dict[str, str] = {}
    witnesses: dict[str, list[str]] = defaultdict(list)

    for r in catalog.records:
        if r.kind == "occurrence":
            if r.scheduled_start and getattr(r.scheduled_start, "date", None):
                dates.setdefault(r.meeting.id, r.scheduled_start.date.isoformat())
            if getattr(r, "status", None):
                statuses.setdefault(r.meeting.id, r.status)
        elif r.kind == "meeting":
            if r.scheduled_start and getattr(r.scheduled_start, "date", None):
                dates.setdefault(r.id, r.scheduled_start.date.isoformat())
            if getattr(r, "status", None) and r.status != "unknown":
                statuses.setdefault(r.id, r.status)
        elif r.kind == "appearance" and getattr(r, "name", None):
            witnesses[r.meeting.id].append(r.name.display)

    if hasattr(catalog.sources, "provider_for_id"):
        provider_lookup = catalog.sources.provider_for_id
    else:
        provider_map = {s.id: s.provider for s in catalog.sources}
        provider_lookup = provider_map.get

    rows: list[dict[str, Any]] = []
    for r in catalog.records:
        if r.kind != "meeting":
            continue
        comm_name: str | None = None
        sub_name: str | None = None
        for conv in getattr(r, "committees", ()):
            term = committees.get(conv.committee.id)
            if term is None:
                continue
            t_name = term.name or conv.committee.id
            if term.parent or term.committee_type == "subcommittee" or term.committee_level == "subcommittee":
                if sub_name is None:
                    sub_name = t_name
            else:
                if comm_name is None:
                    comm_name = t_name
        if comm_name is None and getattr(r, "committees", ()):
            first_id = r.committees[0].committee.id
            first_term = committees.get(first_id)
            comm_name = (first_term.name if first_term else None) or first_id

        cited_ids = [c.source.id for c in r.provenance.citations] if getattr(r, "provenance", None) else []
        if not cited_ids:
            cited_ids = [f"meeting:{r.id}"]
        meeting_witnesses = sorted(set(witnesses.get(r.id) or ())) or [None]
        for src_id in dict.fromkeys(cited_ids):
            provider = str(provider_lookup(src_id) or getattr(r.provenance, "basis", None) or "unknown")
            rank = int(SOURCE_RANK_BY_PROVIDER.get(provider, 99))
            for w_name in meeting_witnesses:
                rows.append({
                    "meeting_id": r.id,
                    "congress": int(r.congress or 0),
                    "chamber": str(r.chamber or "unknown"),
                    "committee": comm_name or "Unknown",
                    "subcommittee": sub_name,
                    "title": r.title,
                    "date": dates.get(r.id),
                    "type": r.meeting_type,
                    "status": statuses.get(r.id) or r.status,
                    "source_rank": rank,
                    "source_id": src_id,
                    "source_type": provider,
                    "witness_name": w_name,
                })
    return rows


class ExplorerDocSpecWorkspace:
    """Manage declarative ``RefreshSpec`` views and ``ExportPin`` browser exports."""

    def __init__(self, workspace: Path | str, *, binary: Path | str | None = None):
        self.workspace = Path(workspace).resolve()
        self.binary = resolve_docspec_binary(binary)
        self.datasets = NativeDatasets(self.binary, self.workspace)

    def close(self) -> None:
        self.datasets.close()

    def __enter__(self) -> ExplorerDocSpecWorkspace:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def latest_pin(self, dataset: str) -> dict[str, Any] | None:
        """Return the latest ``ReleasePin`` for ``dataset`` (supporting singular/plural aliases)."""
        canonical = _DATASET_ALIASES.get(dataset, dataset)
        return self.datasets.try_latest(canonical)

    def _op_id(self, prefix: str, token: str) -> str:
        digest = sha256(token.encode("utf-8")).hexdigest()[:16]
        raw = f"{prefix}-{digest}"
        return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw)[:64]

    def upsert_observations(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        operation: str | None = None,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        """Admit or incrementally update ``explorer_meeting_observations``."""
        table = build_observations_table(rows)
        base = self.datasets.try_latest(OBSERVATIONS_DATASET)
        op_id = operation or self._op_id(
            "obs",
            f"{base['id'] if base else 'init'}-{table.num_rows}",
        )
        if base is None or replace_all:
            return self.datasets.run_table(
                table,
                dataset=OBSERVATIONS_DATASET,
                operation=op_id,
                definition=COMMITTEE_EXPLORER_DEFINITION,
                base=base["id"] if base else None,
            )
        return self.datasets.update_table(
            table,
            dataset=OBSERVATIONS_DATASET,
            operation=op_id,
            definition=COMMITTEE_EXPLORER_DEFINITION,
            base=base["id"],
            keys=("meeting_id", "source_id"),
        )

    def refresh_views(
        self,
        observations_pin: Mapping[str, Any] | None = None,
        *,
        mode: str = "full",
    ) -> dict[str, dict[str, Any]]:
        """Execute chained ``RefreshSpec``s: ``explorer_meeting_summaries`` -> ``explorer_committee_rollups``."""
        obs_pin = observations_pin or self.datasets.latest(OBSERVATIONS_DATASET)
        summary_base = self.datasets.try_latest(MEETING_SUMMARY_DATASET)
        summary_op = self._op_id(
            "refresh-summary",
            f"{obs_pin['id']}-{summary_base['id'] if summary_base else 'init'}-{mode}",
        )
        summary_spec = build_meeting_summary_refresh_spec(
            obs_pin,
            operation=summary_op,
            base=summary_base["id"] if summary_base else None,
            mode=mode,
        )
        summary_pin = self.datasets.refresh(summary_spec)

        rollup_base = self.datasets.try_latest(COMMITTEE_ROLLUP_DATASET)
        rollup_op = self._op_id(
            "refresh-rollup",
            f"{summary_pin['id']}-{rollup_base['id'] if rollup_base else 'init'}-{mode}",
        )
        rollup_spec = build_committee_rollup_refresh_spec(
            summary_pin,
            operation=rollup_op,
            base=rollup_base["id"] if rollup_base else None,
            mode=mode,
        )
        rollup_pin = self.datasets.refresh(rollup_spec)
        return {
            MEETING_SUMMARY_DATASET: summary_pin,
            "explorer_meeting_summary": summary_pin,
            COMMITTEE_ROLLUP_DATASET: rollup_pin,
            "explorer_committee_rollup": rollup_pin,
        }

    def export_browser_table(
        self,
        table_name: str,
        parquet_or_table: Path | str | pa.Table,
        *,
        channel: str = "public",
        dataset_override: str | None = None,
    ) -> dict[str, Any]:
        """Admit a browser table without loading multi-MB Parquet files into Python RAM, and publish an ``ExportPin``."""
        dataset = dataset_override or BROWSER_TABLE_DATASETS[table_name]
        schema = BROWSER_TABLE_SCHEMAS[table_name]
        base = self.datasets.try_latest(dataset)
        if isinstance(parquet_or_table, pa.Table):
            table = parquet_or_table.cast(schema, safe=False)
            admit_op = self._op_id(
                f"admit-{dataset}",
                f"{base['id'] if base else 'init'}-{table.num_rows}",
            )
            source_pin = self.datasets.run_table(
                table,
                dataset=dataset,
                operation=admit_op,
                definition=COMMITTEE_EXPLORER_DEFINITION,
                base=base["id"] if base else None,
            )
        else:
            import pyarrow.parquet as pq
            import pyarrow.compute as pc
            import tempfile

            source_path = Path(parquet_or_table).resolve()
            pf = pq.ParquetFile(source_path)
            needs_rechunk = any(
                pf.metadata.row_group(i).total_byte_size > 1_500_000 or pf.metadata.row_group(i).num_rows > 256
                for i in range(pf.metadata.num_row_groups)
            )
            tmp_rechunk: Path | None = None
            try:
                admit_path = source_path
                if needs_rechunk:
                    fd, tmp_name = tempfile.mkstemp(prefix=f".rechunk-{dataset}-", suffix=".parquet", dir=self.workspace)
                    os.close(fd)
                    tmp_rechunk = Path(tmp_name)
                    with pq.ParquetWriter(tmp_rechunk, schema, compression="zstd") as writer:
                        for batch in pf.iter_batches(batch_size=128):
                            tbl = pa.Table.from_batches([batch], schema=schema)
                            if "payload" in tbl.schema.names and tbl.nbytes > 2_000_000:
                                idx = tbl.schema.get_field_index("payload")
                                col = pc.utf8_slice_codeunits(tbl.column(idx), 0, 250_000)
                                tbl = tbl.set_column(idx, tbl.schema.field(idx), col)
                            rg = max(1, min(128, (1_500_000 * max(1, tbl.num_rows)) // max(1, tbl.nbytes)))
                            writer.write_table(tbl, row_group_size=rg)
                    admit_path = tmp_rechunk
                digest = self.datasets.hash_input(admit_path)["digest"]
                admit_op = self._op_id(
                    f"admit-{dataset}",
                    f"{base['id'] if base else 'init'}-{digest}",
                )
                run_req: dict[str, Any] = {
                    "dataset": dataset,
                    "operation": admit_op,
                    "definition": COMMITTEE_EXPLORER_DEFINITION,
                    "input": str(admit_path),
                    "expected_digest": digest,
                    "sql": "SELECT * FROM input",
                }
                if base is not None:
                    run_req["base"] = base["id"]
                source_pin = self.datasets.run(run_req)
            finally:
                if tmp_rechunk is not None:
                    tmp_rechunk.unlink(missing_ok=True)

        current_export = self.datasets.try_latest_export(dataset, channel)
        expected = current_export["id"] if current_export is not None else None
        export_op = self._op_id(f"export-{dataset}", f"{source_pin['id']}-{expected or 'init'}")
        spec = build_browser_export_spec(
            table_name,
            source_pin,
            operation=export_op,
            channel=channel,
            expected=expected,
            include_extended_policy=True,
        )
        try:
            return self.datasets.export(spec)
        except DocSpecFailure as err:
            if "unknown field" not in str(err):
                raise
            compat_spec = build_browser_export_spec(
                table_name,
                source_pin,
                operation=self._op_id(f"export-compat-{dataset}", f"{source_pin['id']}-{expected or 'init'}"),
                channel=channel,
                expected=expected,
                include_extended_policy=False,
            )
            return self.datasets.export(compat_spec)

    def export_browser_publication(
        self,
        stage_dir: Path | str,
        *,
        tables: Sequence[str] = ("committees", "meetings", "materials", "witnesses", "issues", "sources"),
        channel: str = "public",
    ) -> dict[str, dict[str, Any]]:
        """Create ``ExportPin``s for all staged browser Parquet tables (including all ``sources-*.parquet`` shards)."""
        stage = Path(stage_dir)
        pins: dict[str, dict[str, Any]] = {}
        for name in tables:
            candidate = stage / f"{name}.parquet"
            if candidate.exists():
                pins[name] = self.export_browser_table(name, candidate, channel=channel)
            elif name == "sources":
                shards = sorted(stage.glob("sources-*.parquet"))
                for shard in shards:
                    shard_stem = shard.stem
                    shard_dataset = f"explorer_browser_{shard_stem.replace('-', '_')}"
                    pins[shard_stem] = self.export_browser_table(
                        "sources",
                        shard,
                        channel=channel,
                        dataset_override=shard_dataset,
                    )
                if shards:
                    pins["sources"] = {shard.stem: pins[shard.stem] for shard in shards}
        return pins

    def sync_export(
        self,
        catalog: Any,
        stage_dir: Path | str,
        *,
        channel: str = "public",
    ) -> dict[str, dict[str, Any]]:
        """Populate ``explorer_meeting_observations``, refresh views, and export all browser Parquet tables."""
        obs_rows = extract_meeting_observations(catalog)
        if obs_rows:
            obs_pin = self.upsert_observations(obs_rows, replace_all=True)
            self.refresh_views(obs_pin)
        return self.export_browser_publication(stage_dir, channel=channel)
