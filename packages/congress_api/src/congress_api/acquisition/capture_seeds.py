"""Read bounded weekly inventory inputs; source observations remain literal."""
import gzip
import json
from pathlib import Path

from congress_api.parsers.archive_readings import json_url_strings
from congress_api.retention.body_store import validate_record

MAX_INVENTORY_BYTES = 64 << 20
MAX_LINE_BYTES = 8 << 20


def inventories(paths):
    for path in map(Path, paths):
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8') as source:
            if '.jsonl' in path.name:
                total = 0
                while text := source.readline(MAX_LINE_BYTES + 1):
                    total += len(text.encode('utf-8'))
                    if len(text.encode('utf-8')) > MAX_LINE_BYTES or total > MAX_INVENTORY_BYTES:
                        raise ValueError('Seed inventory exceeds its byte allowance')
                    if text.strip():
                        yield from observations(json.loads(text), source=path.name)
            else:
                text = source.read(MAX_INVENTORY_BYTES + 1)
                if len(text.encode('utf-8')) > MAX_INVENTORY_BYTES:
                    raise ValueError('Seed inventory exceeds its byte allowance')
                yield from observations(json.loads(text), source=path.name)


def observations(value, *, source):
    # The shared JSON parser supplies literal URL-valued strings, including
    # older document tuples. This adapter adds inventory origin, not policy.
    for link in json_url_strings(value):
        validate_record(link['href'])
        if len(link['href'].encode('utf-8'))>16384 or len(link['tag'].encode('utf-8'))>16384:
            raise ValueError('Seed observation exceeds its metadata allowance')
        yield dict(url=link['href'], source=source, pointer=link['tag'])
