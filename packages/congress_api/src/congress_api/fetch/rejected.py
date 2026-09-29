"""Retain received Congress.gov pages that fail source interpretation."""
from datetime import UTC, datetime
import json
from pathlib import Path


def retain_rejected_page(output: Path, response, *, url: str, offset: int) -> Path:
    path = Path(output).with_suffix(Path(output).suffix + '.rejected.json')
    previous = json.loads(path.read_text()) if path.exists() else []
    previous.append({'url': url, 'offset': offset,
                     'retrieved_at': datetime.now(UTC).isoformat(), 'response': response})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)
    return path
