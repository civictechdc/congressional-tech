"""Read a pinned historical matcher CSV as package-level source observations."""

import csv
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re

from congress_api.retention.provenance import json_input


SOURCE_FIELDS = (
    'package_id', 'congress', 'chamber', 'committee_code', 'held_date', 'hearing_dates',
    'record_type', 'status', 'video_ids', 'channels', 'method', 'score', 'video_minutes',
    'flags', 'source', 'note',
)


def matcher_input(scratch, pin):
    """Preserve physical row order and all source values, including empty strings."""
    raw = Path(pin['path']).read_bytes()
    digest = sha256(raw).hexdigest()
    if len(raw) != pin['size'] or digest != pin['sha256']:
        raise ValueError('Historical recording matcher CSV differs from its pin')
    reader = csv.DictReader(StringIO(raw.decode('utf-8'), newline=''), strict=True)
    if tuple(reader.fieldnames or ()) != SOURCE_FIELDS:
        raise ValueError('Unexpected historical recording matcher CSV columns')
    rows = []
    for ordinal, row in enumerate(reader, 1):
        if None in row or None in row.values() or not row['package_id'].strip():
            raise ValueError(f'Invalid historical recording matcher CSV record {ordinal}')
        score = row['score']
        if score and not re.fullmatch(r'-?(0|[1-9][0-9]{0,4})', score):
            raise ValueError(f'Invalid historical recording matcher score at record {ordinal}')
        value = int(score) if score else None
        if value is not None and (not -32768 <= value <= 32767 or str(value) != score):
            raise ValueError(f'Invalid historical recording matcher score at record {ordinal}')
        rows.append(dict(row, score=value, source_snapshot_sha256=digest,
                         source_record_ordinal=ordinal))
    fields = {name: 'Int16' if name == 'score' else 'Utf8' for name in SOURCE_FIELDS}
    return json_input(scratch, 'historical_recording_matcher_input', rows,
                      **fields, source_snapshot_sha256='Utf8', source_record_ordinal='Int64')
