"""Shared production seams: fresh-id source, clock, canonical instants, runs.

Adapters, identity, and analysis consume this module so tests can inject a
deterministic id source and clock. It imports nothing from the package: the
contract stays the only owner of record rules, and no module here reaches into
storage internals. It is the single owner of instant rendering and parsing
(storage.mapping imports from here rather than keeping a twin).
"""
import copy
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

INSTANT_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d(?:\.\d{1,6})?Z$')
INSTANT_KEYS = frozenset({
    'recorded_at',
    'observed_at',
    'retain_until',
    'first_seen_at',
    'started_at',
    'finished_at',
    'at',
    'completed_until',
})


def format_instant(moment):
    """Canonical UTC rendering accepted by the schema instant pattern.

    Never invents precision: fractional seconds appear only when present.
    """
    moment = moment.astimezone(timezone.utc)
    if moment.microsecond:
        fraction = f'{moment.microsecond:06d}'.rstrip('0')
        return f'{moment:%Y-%m-%dT%H:%M:%S}.{fraction}Z'
    return f'{moment:%Y-%m-%dT%H:%M:%S}Z'


def parse_instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _canonicalize_in_place(node):
    if not isinstance(node, dict):
        return node
    for key, value in list(node.items()):
        if key in INSTANT_KEYS and isinstance(value, str) and INSTANT_PATTERN.fullmatch(value):
            node[key] = format_instant(parse_instant(value))
        elif isinstance(value, list):
            for element in value:
                if isinstance(element, dict):
                    _canonicalize_in_place(element)
        elif isinstance(value, dict):
            _canonicalize_in_place(value)
    return node


def canonicalize_record_instants(record):
    """Return a copy with instant strings re-rendered in canonical form.

    Replay dedup compares incoming records against the round-tripped stored
    form, and the export path trims trailing-zero fractions; a schema-valid
    input like '…00.123000Z' must therefore be normalized before comparison
    or a legitimate replay would look like a value change (I2). Only strings
    matching the schema's instant pattern are touched; the caller's record is
    not mutated.
    """
    return _canonicalize_in_place(copy.deepcopy(record))


def named_id(namespace, name):
    """Deterministic lowercase uuid5 under a documented namespace."""
    return str(uuid5(namespace, name))


def uuid7(moment=None, *, timestamp_ms=None, counter=None):
    """Mint a lowercase RFC 9562 UUIDv7 string ordered by UTC millisecond timestamp."""
    if timestamp_ms is None:
        if moment is None:
            moment = datetime.now(timezone.utc)
        timestamp_ms = int(moment.timestamp() * 1000)
    ts_ms = max(0, int(timestamp_ms)) & ((1 << 48) - 1)
    rand_bytes = int.from_bytes(os.urandom(10), 'big')
    rand_a = (counter if counter is not None else (rand_bytes >> 62)) & 0xFFF
    rand_b = rand_bytes & ((1 << 62) - 1)
    value = (
        (ts_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=value))


class AdapterContext:
    """Fresh ids (captures are minted per fetch attempt) and a clock.

    Storage owns journaling capture ids across crash retries; the default id
    source is RFC 9562 UUIDv7 (time-ordered by the context clock so chronological
    polls cluster keys into disjoint Parquet file min/max intervals) and callers
    that need cross-crash stability pass their own ids (or replay through the
    publish journal, which pins record ids).
    """

    def __init__(self, id_source=None, clock=None):
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))
        self._last_ms = -1
        self._seq = 0
        self._id_source = id_source if id_source is not None else self._next_uuid7

    def _next_uuid7(self):
        ms = max(0, int(self.now().timestamp() * 1000))
        if ms <= self._last_ms:
            self._seq += 1
            if self._seq > 0xFFF:
                self._last_ms += 1
                self._seq = 0
            ms = self._last_ms
        else:
            self._last_ms = ms
            self._seq = 0
        return uuid7(timestamp_ms=ms, counter=self._seq)

    def new_id(self):
        return str(self._id_source()).lower()

    def now(self):
        return self._clock()

    def now_string(self):
        return format_instant(self.now())


def inputs_hash(inputs):
    """C4: hash over actual ordered inputs under a documented normalization.

    One '<kind>:<id>' line per input reference, in the given order, LF-joined,
    UTF-8, SHA-256. Captures are immutable append-only records, so hashing the
    ordered references covers the actual inputs.
    """
    joined = '\n'.join(f"{ref['kind']}:{ref['id']}" for ref in inputs)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()


def config_hash(config):
    """C4: configuration hash including settings and model version.

    Canonical JSON (sorted keys, compact separators) of the full config
    dictionary; callers put model_version inside the config they pass.
    """
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def build_run(namespace, context, *, processor, processor_version, config, inputs,
              mode='live', status='succeeded', started_at=None, finished_at=None,
              reason=None, model_version=None):
    """Build one run record with deterministic id, config hash, input hash.

    The id is derived from (processor, config hash, input hash): replaying the
    same extraction reuses the run id (append replay no-op), while changed
    configuration or inputs produce a new run (C4). started/finished default
    to the context clock, keeping started <= finished.
    """
    full = {'processor': processor, 'processor_version': processor_version, 'config': config}
    if model_version is not None:
        full['model_version'] = model_version
    run_config_hash = config_hash(full)
    run_input_hash = inputs_hash(inputs)
    now = context.now_string()
    record = {
        'kind': 'run',
        'id': named_id(namespace, f'run:{processor}:{run_config_hash}:{run_input_hash}'),
        'recorded_at': now,
        'processor': processor,
        'processor_version': processor_version,
        'config_hash': run_config_hash,
        'input_hash': run_input_hash,
        'inputs': [dict(ref) for ref in inputs],
        'mode': mode,
        'status': status,
        'started_at': started_at if started_at is not None else now,
        'finished_at': finished_at if finished_at is not None else now,
    }
    if model_version is not None:
        record['model_version'] = model_version
    if reason is not None:
        record['reason'] = reason
    return record


def adapter_namespace(name):
    """A documented deterministic namespace uuid for a producer module."""
    return uuid5(NAMESPACE_URL, f'urn:political-news-lake:{name}')
