"""Retain received Congress.gov pages that fail source interpretation."""

import json
from datetime import UTC, datetime
from pathlib import Path

from congress_shared.custody import write_atomic_bytes

from congress_api.retention.weekly_tables import (
    WeeklyRetentionTables,
    is_parquet_path,
    iter_parquet_rows,
    rejected_page_to_row,
    write_parquet_table,
)


def retain_rejected_page(
    output: Path,
    response,
    *,
    url: str,
    offset: int,
    weekly_tables: WeeklyRetentionTables | None = None,
) -> Path:
    retrieved_at = datetime.now(UTC).isoformat()
    if weekly_tables is not None:
        weekly_tables.upsert_rows(
            "rejected_pages",
            [rejected_page_to_row(url=url, offset=offset, retrieved_at=retrieved_at, response=response)],
        )
    if is_parquet_path(output):
        existing = list(iter_parquet_rows(output)) if Path(output).exists() else []
        existing.append(rejected_page_to_row(url=url, offset=offset, retrieved_at=retrieved_at, response=response))
        write_parquet_table(output, "rejected_pages", existing)
        return Path(output)
    path = Path(output).with_suffix(Path(output).suffix + '.rejected.json')
    previous = json.loads(path.read_text()) if path.exists() else []
    previous.append({'url': url, 'offset': offset,
                     'retrieved_at': retrieved_at, 'response': response})
    write_atomic_bytes(
        path,
        (json.dumps(previous, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
        temp_mode='fixed',
    )
    return path


def read_rejected_pages(
    path: Path | None = None,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
) -> list[dict]:
    """Read retained rejected pages from ``weekly_tables``, Parquet, or legacy JSON."""
    if weekly_tables is not None and (path is None or not Path(path).exists()):
        return [
            {
                "url": row["url"],
                "offset": row["offset"],
                "retrieved_at": row["retrieved_at"],
                "response": json.loads(row["response_json"]),
            }
            for row in weekly_tables.iter_rows("rejected_pages")
        ]
    if path is None or not Path(path).exists():
        return []
    if is_parquet_path(path):
        return [
            {
                "url": row["url"],
                "offset": row["offset"],
                "retrieved_at": row["retrieved_at"],
                "response": json.loads(row["response_json"]),
            }
            for row in iter_parquet_rows(path)
        ]
    return json.loads(Path(path).read_text())
