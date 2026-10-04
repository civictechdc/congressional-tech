"""Retain caption receipts and import existing caption/probe observations."""

import datetime as dt
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from congress_api.models.media import ArchiveProbe, CaptionReceipt
from congress_api.parsers.senate_player import parse_player_url
from congress_api.parsers.observations import last_successful_caption_check
from congress_api.retention.tables import read_csv

RECEIPTS = "caption_receipts"


def receipt_path(out_dir: Path, url: str) -> Path:
    """Stable per-record path, including harmless player URL query variations."""
    parsed = parse_player_url(url)
    key = "|".join(parsed) if parsed else url
    return Path(out_dir) / RECEIPTS / (sha256(key.encode()).hexdigest() + ".json")


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_receipt(out_dir: Path, url: str, receipt: dict) -> None:
    path = receipt_path(out_dir, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt["observed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if receipt.get('outcome') == 'error' and path.exists():
        previous = json.loads(path.read_text())
        successful = last_successful_caption_check(previous)
        if successful:
            receipt['last_successful'] = successful
    _write_text(path, json.dumps(CaptionReceipt.model_validate(receipt).source_dict(), ensure_ascii=False, indent=2) + "\n")


def import_observations(state, seed_cache=None, youtube_index=None, senate_index=None):
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
