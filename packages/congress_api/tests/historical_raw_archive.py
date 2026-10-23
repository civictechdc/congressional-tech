"""Historical checkpoint fixture only; production acquisition uses Archive.

Retains old snapshot reconstruction for source-policy/reference assertions. Shared
acquisition behavior comes from the maintained owner; no production caller imports
this module. This is not an operational adoption or recurring writer API.
"""
from datetime import datetime, timezone
import gzip
import json
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.parsers.archive_links import allowed_url
from congress_api.retention.raw_archive import (
    _Acquisition, CAPTURE_SCHEMA, STATE_SCHEMA, CAPTURES_KEY, STATE_KEY,
    decode_table, encode_table, capture_rank, with_derived_body_keys,
)
from congress_api.retention.raw_values import _to_legacy_capture_table


class LegacyArchiveSeed(_Acquisition):
    def __init__(self, store, run_id, *, repair=False):
        self.store, self.run_id = store, run_id
        data = store.read(CAPTURES_KEY)
        if data is None:
            raise RuntimeError(
                "The initial mirror upload must finish before recurring capture starts."
            )
        self.captures = decode_table(data)
        if self.captures.schema.remove_metadata() != CAPTURE_SCHEMA:
            raise ValueError("Unexpected capture index schema")
        saved = store.read(STATE_KEY)
        saved_table = decode_table(saved) if saved else None
        saved_metadata = (saved_table.schema.metadata or {}) if saved_table is not None else {}
        from congress_api.retention.raw_storage import format_state_row_for_python
        saved_state = {r['url']: format_state_row_for_python(r) for r in saved_table.to_pylist()} if saved_table is not None else {}
        cursor = int(saved_metadata.get(b'capture_rows', b'0'))
        from congress_api.retention.catalog_cache import capture_digest_matches
        checkpoint = b'capture_rows' in saved_metadata or b'capture_digest' in saved_metadata
        resumed = (not repair and b'capture_rows' in saved_metadata and 0 <= cursor <= len(self.captures)
                   and capture_digest_matches(self.captures.slice(0, cursor), saved_metadata.get(b'capture_digest')))
        if checkpoint and not repair and not resumed:
            raise ValueError('Capture checkpoint digest mismatch or invalid cursor; verify legacy checkpoints '
                             'with their original PyArrow writer, or explicitly repair after investigation')
        if not resumed:
            cursor = 0
        self.additions, self.body_info, self.state = [], {}, dict(saved_state)
        self.sequence = 0
        self.pending = []
        self.metadata = None  # Attached only for the lifetime of acquisition.
        self.day = datetime.now(timezone.utc).date().isoformat()
        indexed = set()
        position = 0
        legacy_captures = _to_legacy_capture_table(self.captures)
        for batch in legacy_captures.to_batches(max_chunksize=65536):
            for row in batch.to_pylist():
                position += 1
                if row["receipt_key"]:
                    indexed.add(row["receipt_key"])
                if row["body_key"] and row["sha256"]:
                    self.body_info[row["sha256"]] = {
                        k: row[k]
                        for k in (
                            "body_key",
                            "sha256",
                            "bytes",
                            "stored_sha256",
                            "stored_bytes",
                        )
                    }
                if position <= cursor:
                    continue
                if json.loads(row.get('pointer_json') or '[]')[:1] == ['archive_members']:
                    continue  # Member bytes cannot stand in for the enclosing ZIP URL.
                url = allowed_url(row["context_url"])
                if not url or row["family"] in {
                    "external/provider-responses",
                    "youtube/api",
                    "congress/meetings",
                    "congress/committees",
                }:
                    continue
                self.seed({"url": url, "family": row["family"]})
                # A 200 header also accompanies interrupted streams and challenge
                # pages. Only a primary successful capture can seed usable bytes;
                # failed/prior responses remain immutable evidence.
                pointer = json.loads(row.get('pointer_json') or '[]')
                captured = row.get('reference_kind') == 'capture'
                if (pointer[:1] == ['prior_attempts']
                        or captured and row.get('resolution') not in {'saved', 'retained'}):
                    continue
                if row["body_key"] and row["http_status"] in (None, 200):
                    previous = self.state[url]
                    if previous.get("body_key") and capture_rank(
                        previous
                    ) >= capture_rank(row):
                        continue
                    self.state[url].update(
                        body_key=row["body_key"],
                        sha256=row["sha256"],
                        media_type=row["media_type"],
                        http_status=row["http_status"],
                        outcome="retained",
                        fidelity=row["fidelity"],
                        retrieved_at=row["retrieved_at"],
                    )
        self._seed_catalog(saved_metadata, repair=repair)
        # Persisted attempts/validation take precedence over legacy bootstrap guesses.
        if not resumed:
            self.state.update(saved_state)
        # Recover all published batches, including a run interrupted before save().
        for key in sorted(store.keys("receipts/")):
            if "/download-" not in key or key in indexed:
                continue
            for line_number, line in enumerate(
                gzip.decompress(store.read(key)).splitlines(), 1
            ):
                receipt = json.loads(line)
                self.apply(receipt)
                self.add_index(receipt, key, line_number)


    def _seed_catalog(self, saved_metadata, *, repair=False):
        store = self.store
        # Add every known document URL, including files not yet downloaded.
        # Only a changed catalog can introduce additional unqueued document URLs.
        from congress_api.retention.catalog_publication import FILENAMES, MANIFEST_KEY, read_catalog
        # The selector changes only after both immutable tables are uploaded.
        object_version = getattr(store, 'version', lambda key: None)
        version = object_version(MANIFEST_KEY)
        if version == 'missing':
            version = object_version(FILENAMES)
        self.filename_version = version
        from contextlib import ExitStack
        with ExitStack() as owners:
            source = None
            if repair or version is None or saved_metadata.get(b'filename_version') != str(version).encode():
                options = dict(native=self.storage.native) if hasattr(self, 'storage') else {}
                if hasattr(self, 'selected'):
                    selector = store.read(MANIFEST_KEY)
                    if selector is not None:
                        if json.loads(selector).get('version') != 2:
                            raise ValueError('Changed file catalog requires explicit catalog adoption')
                    else:
                        from congress_api.retention.catalog_publication import DOCUMENTS
                        if any(object_version(key) != 'missing' for key in (FILENAMES, DOCUMENTS)):
                            raise ValueError('Legacy catalog files require explicit catalog adoption')
                    options['read'] = lambda key: selector if key == MANIFEST_KEY else store.read(key)
                snapshot = owners.enter_context(read_catalog(store, **options))
                if callable(getattr(snapshot, 'changes_since', None)):
                    self.filename_version = snapshot.identity
                    if hasattr(self, 'selected'):
                        cursor = self.selected.manifest['filename_version']
                        if not isinstance(cursor, dict):
                            raise ValueError('Native catalog acquisition requires an explicit initial cursor seed')
                        if cursor != snapshot.identity:
                            self._seed_catalog_source(snapshot.changed_sources_since(cursor, max_ordered_bytes=64 << 20))
                    else:
                        # Full native enumeration belongs only to the explicit
                        # investigated LegacyArchiveSeed/adoption boundary.
                        source = snapshot.table('filenames', max_ordered_bytes=64 << 20)
                elif callable(getattr(snapshot, 'table', None)):
                    raise ValueError('Native catalog lacks retained source changes')
                elif snapshot.filenames_path:
                    source = owners.enter_context(pq.ParquetFile(snapshot.filenames_path))
                    self.filename_version = snapshot.version if snapshot.version is not None else version
                elif not snapshot.files and snapshot.manifest is None:
                    # This token proves that neither a selector nor legacy pair
                    # existed; bare None must never stand for a legacy catalog.
                    self.filename_version = snapshot.identity
            if source is not None:
                self._seed_catalog_source(source)


    @property
    def raw_selection(self):
        return None  # Historical seed/reference runs have no native selection.


    @property
    def state_counts(self):
        from collections import Counter
        return dict(url_outcomes=dict(Counter(row['outcome'] for row in self.state.values())),
                    urls_by_source_family=dict(Counter(row.get('family') or 'unknown' for row in self.state.values())),
                    excluded_media_urls=sum(row['outcome'] == 'excluded_media' for row in self.state.values()))


    @property
    def retained_body_count(self):
        import pyarrow.compute as pc
        keys = with_derived_body_keys(self.captures)['body_key']
        return pc.count_distinct(pc.filter(keys, pc.not_equal(keys, ''))).as_py()


    def save(self):
        from congress_api.retention.catalog_cache import capture_digest
        from congress_api.retention.raw_archive import prepare_capture_table, prepare_state_table
        self.flush()
        combined = self.captures
        if self.additions:
            appended = prepare_capture_table(self.additions)
            combined = pa.concat_tables([combined, appended])
        metadata = {'capture_rows': str(len(combined)), 'capture_digest': capture_digest(combined)}
        if self.filename_version is not None:
            metadata['filename_version'] = str(self.filename_version)
        self.store.put(STATE_KEY, encode_table(prepare_state_table(
            list(self.state.values()), schema=STATE_SCHEMA.with_metadata(metadata))))
        if self.additions:
            self.store.put(CAPTURES_KEY, encode_table(combined))
            self.captures = combined
            self.additions.clear()
