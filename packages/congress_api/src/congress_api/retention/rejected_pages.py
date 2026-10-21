"""Retain received Congress.gov pages that fail source interpretation."""

import json
from datetime import UTC, datetime
from pathlib import Path

from congress_shared.custody import write_atomic_bytes


def retain_rejected_page(output: Path, response, *, url: str, offset: int) -> Path:
    path = Path(output).with_suffix(Path(output).suffix + '.rejected.json')
    previous = json.loads(path.read_text()) if path.exists() else []
    previous.append({'url': url, 'offset': offset,
                     'retrieved_at': datetime.now(UTC).isoformat(), 'response': response})
    write_atomic_bytes(
        path,
        (json.dumps(previous, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
        temp_mode='fixed',
    )
    return path
