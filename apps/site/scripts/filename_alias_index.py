"""Disposable SQLite index for exact alias and source/group mapping preparation."""
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded, bounded_batches, failure_receipt, open_parquet
from filename_aliases import content_kind, valid_body, wrapped_target
from congress_api.parsers.archive_links import allowed_url
from congress_api.retention.saved_responses import FIELDS, saved_response

OUTPUT_BYTES = 32 * 1024**2


class AliasIndex:
    def __init__(self, path, accepted=(), *, group_for=None, metrics=None, policy=DEFAULT_DECODED_POLICY):
        self.path, self.accepted, self.group_for = Path(path), accepted, group_for
        self.metrics = metrics if metrics is not None else {}
        self.policy = policy
        self.folder = Path(tempfile.mkdtemp(prefix='viewer-alias-index-'))
        self.db = sqlite3.connect(self.folder / 'index.sqlite')
        self.output_bytes = 0
        try:
            self.db.executescript(f'''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
                PRAGMA temp_store=FILE; PRAGMA cache_size=-{self.policy.sqlite_cache_kib};
                CREATE TABLE sources(position INTEGER PRIMARY KEY,url TEXT,body TEXT,kind TEXT,saved INTEGER,groupid INTEGER);
                CREATE INDEX source_urls ON sources(url);
                CREATE TABLE candidates(original TEXT,target TEXT,PRIMARY KEY(original,target));
                CREATE TABLE saved(original TEXT PRIMARY KEY);
                CREATE TABLE accepted(original TEXT PRIMARY KEY);
                CREATE TABLE targets(original TEXT PRIMARY KEY,target TEXT);
                CREATE INDEX target_urls ON targets(target);
                CREATE TABLE bodies(url TEXT,body TEXT,kind TEXT,PRIMARY KEY(url,body));
                CREATE TABLE recoveries(i INTEGER PRIMARY KEY,original TEXT UNIQUE,target TEXT,body TEXT,kind TEXT);
                CREATE TABLE accepted_saved(target TEXT,body TEXT,i INTEGER,PRIMARY KEY(target,body));
                CREATE TABLE group_matches(groupid INTEGER,i INTEGER,PRIMARY KEY(groupid,i));''')
        except BaseException as error:
            try:
                self.db.close()
            except BaseException as cleanup:
                error.add_note('Alias initialization close also failed: ' + str(cleanup))
            error.add_note('Owned alias index evidence retained: ' + str(self.folder))
            raise


    def __enter__(self):
        try:
            self.build()
            return self
        except BaseException as error:
            if isinstance(error, DecodedBudgetExceeded):
                failure_receipt(self.folder, error, self.policy, self.metrics)
            self.__exit__(type(error), error, error.__traceback__)
            raise

    def __exit__(self, kind, error, traceback):
        cleanup_error = None
        try:
            self.metrics['scratch_bytes'] = sum(path.stat().st_size for path in self.folder.rglob('*') if path.is_file())
            self.metrics['sqlite_cache_kib'] = self.policy.sqlite_cache_kib
        except BaseException as failure:
            cleanup_error = failure
        try:
            self.db.close()
        except BaseException as failure:
            if cleanup_error is None:
                cleanup_error = failure
            else:
                cleanup_error.add_note('Alias index close also failed: ' + str(failure))
        if error is not None:
            if cleanup_error is not None:
                error.add_note('Alias index cleanup also failed: ' + str(cleanup_error))
            error.add_note('Owned alias index evidence retained: ' + str(self.folder))
        elif cleanup_error is not None:
            cleanup_error.add_note('Owned alias index evidence retained: ' + str(self.folder))
            raise cleanup_error
        else:
            shutil.rmtree(self.folder)

    def account(self, value):
        self.output_bytes += len(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()) + 1
        if self.output_bytes > OUTPUT_BYTES:
            raise ValueError(f'Recovery status exceeds {OUTPUT_BYTES} byte output budget')
        self.metrics['output_budget_bytes_used'] = self.output_bytes

    def build(self):
        db = self.db
        db.executemany('INSERT INTO accepted VALUES (?)', ((row['original_url'],) for row in self.accepted))
        position = 0
        self.metrics.update(source_scans=1, max_batch_rows=0, max_batch_arrow_bytes=0)
        with open_parquet(self.path) as source:
            columns = [name for name in (*FIELDS, 'source_resolved_url') if name in source.schema_arrow.names]
            for batch in bounded_batches(source, batch_rows=128, columns=columns, policy=self.policy,
                                         stage='alias index', metrics=self.metrics):
                self.metrics['max_batch_rows'] = max(self.metrics['max_batch_rows'], len(batch))
                self.metrics['max_batch_arrow_bytes'] = max(self.metrics['max_batch_arrow_bytes'], batch.nbytes)
                for row in batch.to_pylist():
                    original = row.get('source_url')
                    usable = saved_response(row)
                    db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?)',
                        (position, original, row.get('body_key'), content_kind(row), int(usable),
                         self.group_for(position) if self.group_for else None))
                    position += 1
                    if not original or db.execute('SELECT 1 FROM accepted WHERE original=?', (original,)).fetchone():
                        continue
                    if usable:
                        db.execute('INSERT OR IGNORE INTO saved VALUES (?)', (original,))
                    resolved = row.get('source_resolved_url') or []
                    if not resolved:
                        target = wrapped_target(original)
                        resolved = [target] if target else []
                    # JSON preserves None and invalid/self values as distinct
                    # conflict evidence; validity is checked only after grouping.
                    db.executemany('INSERT OR IGNORE INTO candidates VALUES (?,?)',
                        ((original, json.dumps(target, ensure_ascii=False)) for target in resolved))
        self.rows = position
        for original, encoded in db.execute('''SELECT original,MIN(target) FROM candidates
                WHERE original NOT IN (SELECT original FROM saved) GROUP BY original HAVING COUNT(*)=1'''):
            target = json.loads(encoded)
            if isinstance(target, str) and target != original and allowed_url(target) == target:
                db.execute('INSERT INTO targets VALUES (?,?)', (original, target))
        for url, body, kind in db.execute('''SELECT s.url,s.body,s.kind FROM sources s
                WHERE s.saved=1 AND EXISTS(SELECT 1 FROM targets t WHERE t.target=s.url) ORDER BY s.position'''):
            if valid_body(body):
                db.execute('INSERT OR REPLACE INTO bodies VALUES (?,?,?)', (url, body, kind))
        for row in self.accepted:
            if row['kind'] == 'video' or not valid_body(row['body_key']):
                continue
            for url in (row['original_url'], row['recovered_url']):
                if db.execute('SELECT 1 FROM targets WHERE target=? LIMIT 1', (url,)).fetchone():
                    db.execute('INSERT OR REPLACE INTO bodies VALUES (?,?,?)', (url, row['body_key'], row['kind']))
        self.metrics.update(source_rows=position,
            candidate_pairs=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],
            body_versions=db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0])

    def aliases(self):
        result = []
        for original, target, body, kind in self.db.execute('''SELECT t.original,t.target,MIN(b.body),MIN(b.kind)
                FROM targets t JOIN bodies b ON b.url=t.target GROUP BY t.original,t.target
                HAVING COUNT(*)=1 ORDER BY t.original'''):
            row = dict(original_url=original, recovered_url=target, body_key=body, kind=kind,
                       recovery_status='recovered', recovery_basis='resolved_source_url')
            self.account(row); result.append(row)
        return result

    def mappings(self, rows):
        for row in self.accepted:
            self.account(row)
        for index, row in enumerate(rows):
            self.db.execute('INSERT INTO recoveries VALUES (?,?,?,?,?)',
                (index, row['original_url'], row['recovered_url'], row['body_key'], row['kind']))
        for index, row in enumerate(self.accepted):
            self.db.execute('INSERT OR REPLACE INTO accepted_saved VALUES (?,?,?)',
                            (row['recovered_url'], row['body_key'], index))
        sources = []
        for position, match, group in self.db.execute('''SELECT s.position,COALESCE(r.i,a.i),s.groupid FROM sources s
                LEFT JOIN recoveries r ON r.original=s.url
                LEFT JOIN accepted_saved a ON a.target=s.url AND a.body=s.body
                WHERE COALESCE(r.i,a.i) IS NOT NULL ORDER BY s.position'''):
            row = [position, match]; self.account(row); sources.append(row)
            self.db.execute('INSERT OR IGNORE INTO group_matches VALUES (?,?)', (group, match))
        groups, current, values = [], None, []
        for group, match in self.db.execute('SELECT groupid,i FROM group_matches ORDER BY groupid,i'):
            if group != current:
                if current is not None:
                    row = [current, values]; self.account(row); groups.append(row)
                current, values = group, []
            values.append(match)
        if current is not None:
            row = [current, values]; self.account(row); groups.append(row)
        return sources, groups
