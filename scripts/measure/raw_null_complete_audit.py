"""Read the raw receipt line behind every top-level stored fetch with no recorded completeness.

    raw_null_complete_audit.py --mirror R2 --captures captures.parquet --output OUT.json

A row is judged by what its own line states, not by the lake row. Receipts absent from the
mirror are listed rather than inferred.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

import duckdb

STATUS_KEYS = ('http_status', 'status_code', 'status', 'final_status', 'response_status')
FAILURE_KEYS = ('error', 'error_type', 'exception', 'failure')


def verdict(line, sha):
    """(class, stated status): the raw entry naming this body, wherever the line holds it."""
    sha = sha.lower()
    for entry in [*(line.get('file_references') or []), *(line.get('captures') or [])]:
        if isinstance(entry, dict) and str(entry.get('sha256') or '').lower() == sha:
            status = entry.get('http_status') or entry.get('fetch_http_status')
            if entry.get('complete') is False or entry.get('error'):
                return 'entry_states_failure', status
            if isinstance(status, int) and not 200 <= status <= 299:
                return 'entry_states_non_2xx', status
            if entry.get('resolution') == 'digest_verified':
                return ('digest_verified_with_2xx' if status else 'digest_verified_no_response'), status
            return f"{entry.get('reference_kind') or 'entry'}_{entry.get('resolution') or 'unresolved'}", status
    return 'body_not_named_on_line', None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('mirror', 'captures', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    db = duckdb.connect(config=dict(memory_limit='3GB', threads=4))
    source = f"read_parquet('{args.captures}')"
    affected = db.execute(f"""SELECT receipt_key,receipt_line,lower(hex(sha256)),family,url IS NOT NULL,
        EXISTS (SELECT 1 FROM {source} g WHERE g.sha256=c.sha256 AND g.complete AND g.mode='fetch' AND g.outcome IN ('stored','unchanged') AND g.http_status BETWEEN 200 AND 299) AS good_elsewhere
        FROM {source} c WHERE member_path IS NULL AND complete IS NULL AND mode='fetch' AND outcome IN ('stored','unchanged') AND sha256 IS NOT NULL""").fetchall()
    by_key = defaultdict(list)
    for key, line, sha, family, has_url, elsewhere in affected:
        by_key[key].append((line, sha, family, elsewhere, has_url))
    classes, families, unread_keys, unread_rows, keys_seen, examples = Counter(), Counter(), [], 0, Counter(), defaultdict(list)
    orphan = Counter()
    for key, rows in sorted(by_key.items()):
        path = Path(args.mirror) / key
        if not path.is_file():
            unread_keys.append(key)
            unread_rows += len(rows)
            continue
        wanted = defaultdict(list)
        for row in rows:
            wanted[row[0]].append(row)
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8', errors='replace') as handle:
            for number, text in enumerate(handle, 1):
                if number not in wanted:
                    continue
                line = json.loads(text)
                keys_seen.update(line.keys())
                for _, sha, family, elsewhere, has_url in wanted[number]:
                    kind, status = verdict(line, sha)
                    classes[kind] += 1
                    families[family, kind] += 1
                    if not elsewhere:
                        orphan[f"{kind}|{'url' if has_url else 'no_url'}|{family}"] += 1
                    if len(examples[kind]) < 5:
                        examples[kind].append([key, number, family, status])
    result = dict(affected=len(affected), rows_read=sum(classes.values()), rows_unread=unread_rows, receipts_unread=unread_keys[:50], receipts_unread_count=len(unread_keys),
        classes=classes, classes_with_no_good_row_for_the_body=dict(orphan.most_common()), by_family={f'{a}|{b}': n for (a, b), n in families.most_common(40)}, line_keys=keys_seen.most_common(40), examples=examples)
    Path(args.output).write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('by_family', 'examples', 'receipts_unread')}, indent=0)[:2600])


if __name__ == '__main__':
    main()
