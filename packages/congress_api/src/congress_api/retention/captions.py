"""Retain caption receipts and import existing caption/probe observations."""

import datetime as dt
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from congress_shared.custody import write_atomic_bytes

from congress_api.models.media import ArchiveProbe, CaptionReceipt
from congress_api.parsers.senate_player import parse_player_url
from congress_api.parsers.observations import last_successful_caption_check
from congress_api.retention.tables import read_csv
from congress_api.retention.weekly_tables import WeeklyRetentionTables, caption_to_row

RECEIPTS = "caption_receipts"


def receipt_path(out_dir: Path, url: str) -> Path:
    """Stable per-record path, including harmless player URL query variations."""
    parsed = parse_player_url(url)
    key = "|".join(parsed) if parsed else url
    return Path(out_dir) / RECEIPTS / (sha256(key.encode()).hexdigest() + ".json")


def _write_text(path: Path, text: str) -> None:
    write_atomic_bytes(path, text.encode("utf-8"), temp_mode="fixed")


def _write_receipt(
    out_dir: Path,
    url: str,
    receipt: dict,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
) -> None:
    path = receipt_path(out_dir, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt["observed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if receipt.get('outcome') == 'error' and path.exists():
        previous = json.loads(path.read_text())
        successful = last_successful_caption_check(previous)
        if successful:
            receipt['last_successful'] = successful
    validated = CaptionReceipt.model_validate(receipt).source_dict()
    _write_text(path, json.dumps(validated, ensure_ascii=False, indent=2) + "\n")
    if weekly_tables is not None:
        source = str(validated.get("source") or ("youtube" if validated.get("video_id") else "senate"))
        native_id = str(validated.get("video_id") or validated.get("filename") or url)
        weekly_tables.upsert_rows(
            "captions",
            [caption_to_row(source, native_id, kind=validated.get("kind"), receipt=validated)],
        )


def upsert_captions(state: dict, weekly_tables: WeeklyRetentionTables):
    """Incrementally admit or update ``captions`` rows from a state dict."""
    obs_by_source = state.get("caption_observations") or {}

    def _rows():
        for source in ("youtube", "senate"):
            kinds = state.get(source) if isinstance(state.get(source), dict) else {}
            receipts = obs_by_source.get(source) if isinstance(obs_by_source.get(source), dict) else {}
            all_ids = sorted(set(kinds) | set(receipts))
            for native_id in all_ids:
                yield caption_to_row(
                    source,
                    native_id,
                    kind=kinds.get(native_id),
                    receipt=receipts.get(native_id),
                )

    return weekly_tables.upsert_rows("captions", _rows())


def read_captions(weekly_tables: WeeklyRetentionTables) -> dict:
    """Read caption kinds and receipt observations from the incremental ``captions`` table."""
    result: dict = {}
    for row in weekly_tables.iter_rows("captions"):
        source = row.get("source")
        native_id = row.get("native_id")
        if not source or not native_id:
            continue
        if row.get("kind") is not None:
            result.setdefault(source, {})[native_id] = row["kind"]
        if row.get("receipt_json"):
            result.setdefault("caption_observations", {}).setdefault(source, {})[native_id] = json.loads(row["receipt_json"])
    return result


def import_observations(
    state,
    seed_cache=None,
    youtube_index=None,
    senate_index=None,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
):
    for source, index, key in (("youtube", youtube_index, "video_id"), ("senate", senate_index, "filename")):
        path = index or (seed_cache / source / "captions_index.csv" if seed_cache else None)
        if path:
            path = Path(path)
            if path.exists():
                state.setdefault(source, {}).update({r[key]: r["kind"] for r in read_csv(path)})
            # Receipts contain scope/time and file pointers, never caption bytes.
            # Include failed-only checks even when they have no successful CSV row.
            for receipt_path in sorted((path.parent / 'caption_receipts').glob('*.json')):
                receipt = json.loads(receipt_path.read_text())
                native_id = receipt.get(key)
                if not isinstance(native_id, str) or not native_id:
                    continue
                receipt = CaptionReceipt.model_validate(receipt).source_dict()
                state.setdefault('caption_observations', {}).setdefault(source, {})[native_id] = receipt
    if seed_cache and not state.get("probes"):
        path = seed_cache / "senate/probe_cache.json"
        if path.exists():
            state["probes"] = {key: ArchiveProbe(urls=urls, checked=dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).date().isoformat(),
                                     source="research HEAD cache").source_dict() for key, urls in json.loads(path.read_text()).items()}
    if weekly_tables is not None:
        upsert_captions(state, weekly_tables)
