"""Singular `body_text` Parquet (`export.parquet` + `current.json`) reader and consumer helpers.

Provides verified, zero-drift consumption of the published/staged `body_text` export across:
  1. Reader & page-view consumers (exact UTF-8 byte-offset `slice_pages` respecting truncated rows).
  2. `DocMeta` & `corpus_quality` consumers (bounded `head_tail_window` preserving both `p1..p2`
     headers and tail signers/rosters/colophons on `>8,000`-char HTMLs and multi-page PDFs).
  3. SereneDB full-text indexing (`iter_serenedb_documents` streaming `detail.parquet` + `export.parquet`
     without redundant text sidecars).
  4. Point & batch lookups (`get_many`) using Parquet row-group `[min, max]` pruning on ordered
     `saved_body` keys (`row_group_rows = 256`).
"""
from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from viewer_publication.body_text_export import COLUMNS, file_facts, footer_sha256

TAIL_JOINER_SINGLE_PAGE = "\n\n[... middle omitted ...]\n\n"


def _verify_file_pin(path: Path, pin: dict[str, Any], *, label: str) -> None:
    if path.stat().st_size != pin.get("size", pin.get("bytes")):
        raise ValueError(f"{label} byte size differs from its pin")
    if file_facts(path)["sha256"] != pin.get("sha256"):
        raise ValueError(f"{label} digest differs from its pin")


@dataclass(frozen=True, slots=True)
class BodyTextRecord:
    """Verified single-body record from `export.parquet`."""

    saved_body: bytes
    text: str
    page_offsets: tuple[int, ...]
    text_sha256: bytes

    @property
    def saved_body_hex(self) -> str:
        return self.saved_body.hex()

    @property
    def text_sha256_hex(self) -> str:
        return self.text_sha256.hex()

    @property
    def declared_page_count(self) -> int:
        return len(self.page_offsets)

    def slice_pages(self, *, start_page: int = 0, max_pages: int | None = 2) -> str:
        return slice_pages(self.text, self.page_offsets, start_page=start_page, max_pages=max_pages)

    def head_tail_window(
        self,
        *,
        max_chars: int = 8000,
        head_pages: int = 2,
        tail_chars: int = 2400,
    ) -> str:
        return head_tail_window(
            self.text,
            self.page_offsets,
            max_chars=max_chars,
            head_pages=head_pages,
            tail_chars=tail_chars,
        )


def _normalize_sha_bytes(value: bytes | str) -> bytes:
    if isinstance(value, bytes):
        if len(value) != 32:
            raise ValueError(f"Expected 32-byte saved_body digest, got {len(value)} bytes")
        return value
    if isinstance(value, str):
        clean = value.strip().lower()
        if len(clean) != 64:
            raise ValueError(f"Expected 64-hex saved_body digest, got {value!r}")
        return bytes.fromhex(clean)
    raise TypeError(f"Unsupported saved_body digest type: {type(value).__name__}")


def resolve_ssot_paths(path_or_dir: str | Path) -> tuple[Path, Path | None]:
    """Resolve `(export_parquet_path, pointer_json_path_or_None)` from a directory, pointer, or Parquet path."""
    target = Path(path_or_dir).resolve()
    if target.is_dir():
        pointer_path = target / "current.json"
        export_path = target / "export.parquet"
        if export_path.is_file():
            return export_path, pointer_path if pointer_path.is_file() else None
        if pointer_path.is_file():
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            named = Path(pointer.get("key", "")).name
            cand = target / named
            if named and cand.is_file():
                return cand, pointer_path
        raise FileNotFoundError(f"No export.parquet or pointer-named Parquet found in {target}")

    if target.name == "current.json" and target.is_file():
        pointer = json.loads(target.read_text(encoding="utf-8"))
        sibling = target.parent / "export.parquet"
        if sibling.is_file():
            return sibling, target
        named = Path(pointer.get("key", "")).name
        cand = target.parent / named
        if named and cand.is_file():
            return cand, target
        raise FileNotFoundError(f"Pointer {target} has no matching Parquet file beside it")

    if target.is_file():
        sibling_ptr = target.parent / "current.json"
        return target, sibling_ptr if sibling_ptr.is_file() else None

    raise FileNotFoundError(f"Body-text SSOT path does not exist: {target}")


def verify_ssot_export(
    path_or_dir: str | Path,
    *,
    require_pointer: bool = True,
    verify_file_sha256: bool = True,
) -> dict[str, Any]:
    """Verify `export.parquet` structure, footer digest, row count, and optional full-file SHA-256 against `current.json`."""
    export_path, pointer_path = resolve_ssot_paths(path_or_dir)
    if require_pointer and pointer_path is None:
        raise ValueError(f"Missing current.json pointer alongside {export_path}")

    pf = pq.ParquetFile(export_path)
    cols = list(pf.schema_arrow.names)
    if cols != COLUMNS:
        raise ValueError(f"Invalid body_text export columns {cols}; expected {COLUMNS}")

    actual_size = export_path.stat().st_size
    actual_rows = pf.metadata.num_rows
    actual_footer = footer_sha256(export_path)

    pointer: dict[str, Any] | None = None
    if pointer_path is not None:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if pointer.get("bytes") != actual_size:
            raise ValueError(
                f"Export byte size mismatch: pointer={pointer.get('bytes')} actual={actual_size}"
            )
        if pointer.get("rows") != actual_rows:
            raise ValueError(
                f"Export row count mismatch: pointer={pointer.get('rows')} actual={actual_rows}"
            )
        if pointer.get("footer_sha256") != actual_footer:
            raise ValueError(
                f"Export footer_sha256 mismatch: pointer={pointer.get('footer_sha256')} actual={actual_footer}"
            )
        if verify_file_sha256:
            facts = file_facts(export_path)
            if facts["sha256"] != pointer.get("sha256"):
                raise ValueError(
                    f"Export sha256 mismatch: pointer={pointer.get('sha256')} actual={facts['sha256']}"
                )

    return {
        "export_path": str(export_path),
        "pointer_path": str(pointer_path) if pointer_path is not None else None,
        "rows": actual_rows,
        "num_row_groups": pf.metadata.num_row_groups,
        "bytes": actual_size,
        "footer_sha256": actual_footer,
        "pointer": pointer,
    }


def split_pages_utf8(text: str, page_offsets: Sequence[int]) -> list[str]:
    """Split `text` into per-page strings using UTF-8 byte offsets from `body_text.page_offsets`.

    Respects `body_text_export` truncation: offsets beyond `len(text.encode('utf-8'))` represent
    pages cut by `max_text_json_bytes` and are omitted cleanly.
    """
    if not page_offsets:
        return [text] if text else []
    encoded = text.encode("utf-8")
    total_bytes = len(encoded)
    valid_offsets = [int(o) for o in page_offsets if 0 <= int(o) <= total_bytes]
    if not valid_offsets:
        return [text]
    pages: list[str] = []
    for idx, start_b in enumerate(valid_offsets):
        if idx + 1 < len(valid_offsets):
            next_b = valid_offsets[idx + 1]
            # Consecutive pages are joined by a single '\n' byte in spicy-docs / body_text.py.
            end_b = next_b - 1 if next_b > start_b and encoded[next_b - 1 : next_b] == b"\n" else next_b
        else:
            end_b = total_bytes
        pages.append(encoded[start_b:end_b].decode("utf-8", errors="replace"))
    return pages


def slice_pages(
    text: str,
    page_offsets: Sequence[int],
    *,
    start_page: int = 0,
    max_pages: int | None = 2,
) -> str:
    """Extract a contiguous page range `[start_page, start_page + max_pages)` in O(slice_bytes)."""
    if start_page < 0:
        raise ValueError("start_page must be >= 0")
    if max_pages is not None and max_pages <= 0:
        return ""
    if not page_offsets:
        return text if start_page == 0 else ""

    encoded = text.encode("utf-8")
    total_bytes = len(encoded)
    n_pages = len(page_offsets)
    if start_page >= n_pages:
        return ""
    start_b = int(page_offsets[start_page])
    if start_b >= total_bytes:
        return ""

    end_page = n_pages if max_pages is None else min(n_pages, start_page + max_pages)
    if end_page >= n_pages:
        end_b = total_bytes
    else:
        raw_next = int(page_offsets[end_page])
        if raw_next > total_bytes:
            end_b = total_bytes
        else:
            end_b = raw_next - 1 if raw_next > start_b and encoded[raw_next - 1 : raw_next] == b"\n" else raw_next
    return encoded[start_b:end_b].decode("utf-8", errors="replace")


def head_tail_window(
    text: str,
    page_offsets: Sequence[int],
    *,
    max_chars: int = 8000,
    head_pages: int = 2,
    tail_chars: int = 2400,
) -> str:
    """Construct a bounded head+tail document window for `DocMeta` and `corpus_quality` consumers.

    - Single-page documents (e.g. long committee HTMLs/WARCs `> max_chars`): preserves both the
      top masthead/headline/opening prose AND the bottom `tail_chars` (signers, dates, colophons).
    - Multi-page documents (PDFs & multi-page WARCs): extracts `p1..p{head_pages}` via UTF-8 byte
      offsets, and when the document has pages beyond `head_pages`, appends the last surviving
      page's tail so letter signers, witness rosters, and GPO colophons at the end of a PDF are
      never lost while keeping total output `<= max_chars`.
    """
    if max_chars <= 0 or not text:
        return ""
    eff_tail = max(0, min(tail_chars, max_chars // 3))

    # Single-page (HTML / XML / 1-page PDF)
    if len(page_offsets) <= 1:
        if len(text) <= max_chars:
            return text
        if eff_tail == 0 or max_chars <= len(TAIL_JOINER_SINGLE_PAGE) + 32:
            return text[:max_chars]
        head_budget = max_chars - eff_tail - len(TAIL_JOINER_SINGLE_PAGE)
        return f"{text[:head_budget]}{TAIL_JOINER_SINGLE_PAGE}{text[-eff_tail:]}"

    # Multi-page (PDF / multi-page WARC)
    head_txt = slice_pages(text, page_offsets, start_page=0, max_pages=head_pages)
    encoded = text.encode("utf-8")
    total_bytes = len(encoded)
    surviving_indices = [i for i, off in enumerate(page_offsets) if 0 <= int(off) < total_bytes]
    if not surviving_indices:
        return text[:max_chars]

    last_idx = surviving_indices[-1]
    if last_idx < head_pages:
        # All surviving pages are already inside head_txt
        if len(head_txt) <= max_chars:
            return head_txt
        if eff_tail == 0 or max_chars <= len(TAIL_JOINER_SINGLE_PAGE) + 32:
            return head_txt[:max_chars]
        head_budget = max_chars - eff_tail - len(TAIL_JOINER_SINGLE_PAGE)
        return f"{head_txt[:head_budget]}{TAIL_JOINER_SINGLE_PAGE}{head_txt[-eff_tail:]}"

    # Extract last surviving page text in O(last_page_bytes) without decoding middle pages
    last_page_txt = slice_pages(text, page_offsets, start_page=last_idx, max_pages=1).strip()
    if not last_page_txt or eff_tail == 0:
        return head_txt[:max_chars]

    last_slice = last_page_txt[-eff_tail:] if len(last_page_txt) > eff_tail else last_page_txt
    marker = f"\n\n[... page {last_idx + 1} tail ...]\n\n"
    if len(head_txt) + len(marker) + len(last_slice) <= max_chars:
        return f"{head_txt}{marker}{last_slice}"
    if max_chars <= len(marker) + 32:
        return head_txt[:max_chars]
    head_budget = max_chars - len(marker) - len(last_slice)
    if head_budget < 64:
        # Shrink tail proportionally on very small max_chars budgets
        last_slice = last_slice[-(max_chars // 4) :]
        head_budget = max(0, max_chars - len(marker) - len(last_slice))
    return f"{head_txt[:head_budget]}{marker}{last_slice}"


class BodyTextSSOT:
    """Verified reader over the singular `body_text` `export.parquet` + `current.json`."""

    def __init__(
        self,
        path_or_dir: str | Path,
        *,
        require_pointer: bool = True,
        verify_file_sha256: bool = False,
    ) -> None:
        info = verify_ssot_export(
            path_or_dir,
            require_pointer=require_pointer,
            verify_file_sha256=verify_file_sha256,
        )
        self.export_path = Path(info["export_path"])
        self.pointer_path = Path(info["pointer_path"]) if info["pointer_path"] else None
        self.pointer: dict[str, Any] | None = info["pointer"]
        self.rows: int = int(info["rows"])
        self.num_row_groups: int = int(info["num_row_groups"])
        self._rg_bounds: list[tuple[bytes, bytes]] | None = None

    def _load_row_group_bounds(self, pf: pq.ParquetFile) -> list[tuple[bytes, bytes]]:
        if self._rg_bounds is not None:
            return self._rg_bounds
        bounds: list[tuple[bytes, bytes]] = []
        meta = pf.metadata
        for rg_idx in range(meta.num_row_groups):
            stats = meta.row_group(rg_idx).column(0).statistics
            if stats is not None and stats.has_min_max and stats.min is not None and stats.max is not None:
                mn = bytes(stats.min) if not isinstance(stats.min, bytes) else stats.min
                mx = bytes(stats.max) if not isinstance(stats.max, bytes) else stats.max
                bounds.append((mn, mx))
            else:
                bounds.append((b"\x00" * 32, b"\xff" * 32))
        self._rg_bounds = bounds
        return bounds

    @staticmethod
    def _row_to_record(row: dict[str, Any], *, verify_hash: bool = True) -> BodyTextRecord:
        sb = bytes(row["saved_body"])
        txt = row["text"]
        tsha = bytes(row["text_sha256"])
        if verify_hash:
            actual = sha256(txt.encode("utf-8")).digest()
            if actual != tsha:
                raise ValueError(
                    f"Integrity check failed for saved_body {sb.hex()}: "
                    f"expected text_sha256={tsha.hex()}, got {actual.hex()}"
                )
        offs = tuple(int(x) for x in (row["page_offsets"] or ()))
        return BodyTextRecord(
            saved_body=sb,
            text=txt,
            page_offsets=offs,
            text_sha256=tsha,
        )

    def iter_records(
        self,
        *,
        batch_size: int = 256,
        verify_row_hashes: bool = True,
    ) -> Iterator[BodyTextRecord]:
        """Stream verified `BodyTextRecord` items in ascending `saved_body` order."""
        pf = pq.ParquetFile(self.export_path)
        for batch in pf.iter_batches(batch_size=batch_size, columns=COLUMNS):
            for row in batch.to_pylist():
                yield self._row_to_record(row, verify_hash=verify_row_hashes)

    def get_many(
        self,
        saved_body_shas: Iterable[bytes | str],
        *,
        verify_row_hashes: bool = True,
    ) -> dict[bytes, BodyTextRecord]:
        """Fetch an arbitrary subset of `saved_body` keys using Parquet row-group min/max pruning."""
        targets = sorted({_normalize_sha_bytes(k) for k in saved_body_shas})
        if not targets:
            return {}

        pf = pq.ParquetFile(self.export_path)
        bounds = self._load_row_group_bounds(pf)
        matching_rgs: list[int] = []
        for rg_idx, (mn, mx) in enumerate(bounds):
            pos = bisect.bisect_left(targets, mn)
            if pos < len(targets) and targets[pos] <= mx:
                matching_rgs.append(rg_idx)

        if not matching_rgs:
            return {}

        target_set = set(targets)
        found: dict[bytes, BodyTextRecord] = {}
        for rg_idx in matching_rgs:
            tbl = pf.read_row_group(rg_idx, columns=COLUMNS)
            for row in tbl.to_pylist():
                sb = bytes(row["saved_body"])
                if sb in target_set:
                    found[sb] = self._row_to_record(row, verify_hash=verify_row_hashes)
        return found

    def get(self, saved_body_sha: bytes | str, *, verify_row_hash: bool = True) -> BodyTextRecord | None:
        key = _normalize_sha_bytes(saved_body_sha)
        return self.get_many([key], verify_row_hashes=verify_row_hash).get(key)

    def iter_serenedb_documents(
        self,
        detail_parquet: str | Path,
        *,
        max_pages: int | None = None,
        verify_row_hashes: bool = True,
        batch_size: int = 512,
        limit: int | None = None,
        handoff: str | Path | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Read every detail row against pinned text, preserving explicit coverage outcomes.

        A newer release or a legacy export without a detail pin requires an explicit
        reconciled handoff. Missing/held/excluded text yields ``text=None`` and its
        ``text_status``; callers can select searchable rows without losing the inventory.
        """
        detail_p = Path(detail_parquet).resolve()
        if batch_size <= 0 or (limit is not None and limit < 0):
            raise ValueError("batch_size must be positive and limit nonnegative")
        binding = self._bind_detail(detail_p, handoff=handoff)
        exp_q = str(self.export_path).replace("'", "''")
        det_q = str(detail_p).replace("'", "''")
        coverage_join = ""
        status_sql = "CASE WHEN e.saved_body IS NULL THEN 'missing' WHEN e.text='' THEN 'unassessed_empty' ELSE 'available' END"
        digest_sql = "lower(hex(e.text_sha256))"
        if handoff is not None:
            coverage_p = Path(binding["coverage"]["path"])
            _verify_file_pin(coverage_p, binding["coverage"], label="coverage")
            coverage_q = str(coverage_p).replace("'", "''")
            coverage_join = f"LEFT JOIN read_parquet('{coverage_q}') c ON d.saved_body=from_hex(c.body_sha256)"
            status_sql = "coalesce(c.text_status, 'unassessed')"
            digest_sql = "c.text_sha256"
        lim_sql = f"LIMIT {int(limit)}" if limit is not None else ""
        con = duckdb.connect(config={"memory_limit": "1GB", "threads": 2})
        try:
            if handoff is not None and con.execute(
                f"SELECT body_sha256 FROM read_parquet('{coverage_q}') GROUP BY body_sha256 HAVING count(*)<>1 LIMIT 1"
            ).fetchone():
                raise ValueError("Coverage contains duplicate body identities")
            if handoff is not None and con.execute(
                f"""SELECT 1 FROM read_parquet('{det_q}') d ANTI JOIN read_parquet('{coverage_q}') c
                    ON d.saved_body=from_hex(c.body_sha256) WHERE d.saved_body IS NOT NULL LIMIT 1"""
            ).fetchone():
                raise ValueError("Coverage omits a release body identity")
            cur = con.execute(
                f"""
                WITH d_raw AS (
                    SELECT row_number() OVER () - 1 AS list_row, *
                    FROM read_parquet('{det_q}')
                ), d_selected AS (
                    SELECT * FROM d_raw ORDER BY list_row {lim_sql}
                )
                SELECT
                    d.list_row,
                    lower(hex(d.link_key)) AS link_key_hex,
                    lower(hex(d.saved_body)) AS saved_body_hex,
                    COALESCE(d.filename, '') AS filename,
                    d.title,
                    d.format,
                    d.congress,
                    d.chambers,
                    d.committee_keys,
                    CAST(d.document_date AS VARCHAR) AS document_date,
                    e.text,
                    e.page_offsets,
                    e.text_sha256,
                    {status_sql} AS text_status,
                    {digest_sql} AS selected_text_sha256
                FROM d_selected d
                LEFT JOIN read_parquet('{exp_q}') e ON d.saved_body = e.saved_body
                {coverage_join}
                ORDER BY d.list_row
                """
            )
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                for r in rows:
                    status = r[13]
                    if status not in {"available", "valid_empty", "missing", "excluded", "unsupported",
                                      "held", "refused", "unassessed", "unassessed_empty"}:
                        raise ValueError(f"Unknown text coverage outcome: {status}")
                    txt = r[10]
                    if status in {"available", "valid_empty"} and txt is None:
                        raise ValueError(f"Coverage claims missing text is available: {r[2]}")
                    if status not in {"available", "valid_empty"}:
                        txt = None
                    offs = tuple(int(x) for x in (r[11] or ()))
                    tsha = bytes(r[12]) if txt is not None else None
                    if tsha is not None and tsha.hex() != r[14]:
                        raise ValueError(f"Selected text digest differs from coverage: {r[2]}")
                    if status == "valid_empty" and txt:
                        raise ValueError(f"Coverage claims nonempty text is a valid empty: {r[2]}")
                    if status == "available" and txt == "":
                        raise ValueError(f"Coverage claims unqualified empty text is available: {r[2]}")
                    if verify_row_hashes and txt is not None and sha256(txt.encode("utf-8")).digest() != tsha:
                        raise ValueError(f"Integrity check failed on saved_body {r[2]}")
                    body_out = (
                        slice_pages(txt, offs, start_page=0, max_pages=max_pages)
                        if max_pages is not None and txt is not None
                        else txt
                    )
                    yield {
                        "list_row": int(r[0]),
                        "link_key_hex": r[1],
                        "saved_body_hex": r[2],
                        "filename": r[3],
                        "title": r[4],
                        "format": r[5],
                        "congress": int(r[6]) if r[6] is not None else None,
                        "chambers": list(r[7] or ()),
                        "committee_keys": list(r[8] or ()),
                        "document_date": r[9],
                        "text": body_out,
                        "text_status": status,
                        "release_id": binding.get("release_id"),
                        "page_offsets": list(offs),
                        "declared_page_count": len(offs),
                        "text_sha256": tsha.hex() if tsha is not None else None,
                    }
        finally:
            con.close()

    def _bind_detail(self, detail: Path, *, handoff: str | Path | None) -> dict[str, Any]:
        pointer = self.pointer or {}
        binding = pointer
        if handoff is not None:
            handoff_path = Path(handoff).resolve()
            binding = json.loads(handoff_path.read_text())
            if (binding.get("version") != 1
                    or binding.get("export_sha256") != pointer.get("sha256")
                    or binding.get("source_release_id") != pointer.get("release_id")
                    or not binding.get("release_id")):
                raise ValueError("Handoff does not bind this text export and its source release")
            if binding.get("coverage") is None:
                raise ValueError("A reconciled handoff requires explicit coverage")
            if self.pointer_path is None or not isinstance(binding.get("export_pointer"), dict):
                raise ValueError("A reconciled handoff requires its retained export pointer pin")
            _verify_file_pin(self.pointer_path, binding["export_pointer"], label="export pointer")
            binding = dict(binding)
            binding["coverage"] = dict(binding["coverage"])
            coverage_path = Path(binding["coverage"]["path"])
            if not coverage_path.is_absolute():
                binding["coverage"]["path"] = str(handoff_path.parent / coverage_path)
        pin = binding.get("detail")
        if not isinstance(pin, dict):
            raise ValueError("Export has no detail binding; provide a reconciled handoff")
        _verify_file_pin(detail, pin, label="detail/release")
        return binding

    def iter_docmeta_windows(
        self,
        detail_parquet: str | Path,
        *,
        max_chars: int = 8000,
        head_pages: int = 2,
        tail_chars: int = 2400,
        verify_row_hashes: bool = True,
        batch_size: int = 512,
        limit: int | None = None,
        handoff: str | Path | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream bounded `head_tail_window` slices per `detail.parquet` row directly from `export.parquet`."""
        for doc in self.iter_serenedb_documents(
            detail_parquet,
            max_pages=None,
            verify_row_hashes=verify_row_hashes,
            batch_size=batch_size,
            limit=limit,
            handoff=handoff,
        ):
            full_text = doc.pop("text")
            if full_text is None:
                doc["p12_text"] = None
                doc["full_text_chars"] = None
                yield doc
                continue
            offs = doc["page_offsets"]
            doc["p12_text"] = head_tail_window(
                full_text,
                offs,
                max_chars=max_chars,
                head_pages=head_pages,
                tail_chars=tail_chars,
            )
            doc["full_text_chars"] = len(full_text)
            yield doc
