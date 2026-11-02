"""Independent raw judge for every changed capture row between two generations.

    raw_judge.py CHANGES.parquet MIRROR_ROOT EXTRA_ROOT OUT_DIR

Reads each changed row's raw receipt line in full and decides, from the raw JSON
alone, why each refused column changed: the stated HTTP status on the entry, its
owning object (`status`, `http_status`, `status_code`) and the line, the body's
recorded size and digest, the owner's `content_range`, explicit failure outcomes
and errors, and whether the line names a body at all. It imports nothing from the
capture mapping. A change no raw fact explains is reported as a defect.

Writes judged.parquet (one row per changed row with its causes) and summary.json
(count per (column, old, new, cause)). Cost: one streaming pass over the lines of
the receipts that changed, O(bytes of those receipts).
"""
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict

import duckdb

EMPTY = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
RANGE = re.compile(r'^bytes (\d+)-(\d+)/(\d+)$')
FAIL = re.compile(r'(?i)error|fail|not_found|excluded|refused|timeout|exception|not_in_package|limit|throttled')


def intval(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def stated(obj, keys=('http_status', 'status_code', 'status')):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        value = intval(obj.get(key))
        if value is not None and 100 <= value <= 599:
            return value
    return None


def walk(root, path):
    node = root
    for part in path:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            return None
    return node


def pointer(entry):
    value = entry.get('pointer')
    if value is None and entry.get('pointer_json'):
        value = json.loads(entry['pointer_json'])
    return value if isinstance(value, list) else []


def failed_text(*objs):
    for obj in objs:
        if isinstance(obj, dict):
            if obj.get('error') or obj.get('error_type'):
                return True
            outcome = obj.get('outcome')
            if isinstance(outcome, str) and FAIL.search(outcome):
                return True
    return False


def empty(entry):
    return entry is not None and (entry.get('bytes', entry.get('size')) == 0
                                  or (entry.get('sha256') or '').lower() == EMPTY)


def facts(line, index):
    """The raw facts behind one capture row, located by its primary position."""
    record = line.get('record')
    caps, refs = line.get('captures') or [], line.get('file_references') or []
    primary = caps if caps else refs
    entry = primary[index] if 0 <= index < len(primary) and isinstance(primary[index], dict) else None
    ptr = pointer(entry) if entry else []
    owner = None
    for base in (record, line):
        candidate = walk(base, ptr[:-1]) if ptr else None
        if isinstance(candidate, dict):
            owner = candidate
            break
    item = None
    if isinstance(record, list):
        if ptr and isinstance(ptr[0], int) and ptr[0] < len(record):
            item = record[ptr[0]]
        elif entry is None:
            covered = {pointer(e)[0] for e in primary if isinstance(e, dict) and pointer(e) and isinstance(pointer(e)[0], int)}
            free = [i for i in range(len(record)) if i not in covered]
            rank = index - len(primary)
            item = record[free[rank]] if 0 <= rank < len(free) else None
    elif isinstance(record, dict):
        item = record
    prior = ptr[:1] == ['prior_attempts'] or 'prior_attempts' in ptr or 'previous_receipt' in ptr
    level = len(ptr) <= 1 or (len(ptr) == 2 and isinstance(ptr[0], int))
    attempt_status = stated(entry) or stated(owner)
    final_status = stated(line) or (stated(item) if level or entry is None else None)
    content_range = (owner or {}).get('content_range') if isinstance(owner, dict) else None
    return dict(entry=entry, ptr=ptr, owner=owner, item=item, record=record, prior=prior, level=level,
                attempt_status=attempt_status if attempt_status is not None else (None if prior else final_status),
                final_status=final_status, content_range=content_range,
                failed=failed_text(line, item, owner, entry if entry else None))


def item_entries(line, ptr):
    caps, refs = line.get('captures') or [], line.get('file_references') or []
    primary = caps if caps else refs
    head = ptr[0] if ptr and isinstance(ptr[0], int) else None
    return [e for e in primary if isinstance(e, dict) and
            (head is None or (pointer(e) and pointer(e)[0] == head))]


def partial(status, content_range):
    if status != 206:
        return False
    match = RANGE.match(content_range or '')
    return not (match and int(match[1]) == 0 and int(match[2]) + 1 == int(match[3]))


def has_final_document(line, f):
    for e in item_entries(line, f['ptr']):
        p = pointer(e)
        if 'prior_attempts' in p or 'previous_receipt' in p or 'archive_members' in p:
            continue
        if not e.get('sha256') or empty(e):
            continue
        if 'provider_response' in p:
            continue
        owner = None
        for base in (line.get('record'), line):
            c = walk(base, p[:-1]) if p else None
            if isinstance(c, dict):
                owner = c
                break
        status = stated(e) or stated(owner) or f['final_status']
        if status is None or (200 <= status <= 299 and status != 202 and not partial(status, (owner or {}).get('content_range'))):
            return True
    return False


def judge(row, line):
    f = facts(line, row['capture_index'])
    e = f['entry']
    s = f['attempt_status']
    causes = {}

    def why(column, cause):
        causes[column] = cause

    record_only = e is None or not e.get('sha256')
    o, n = row['old_outcome'], row['new_outcome']
    if o != n:
        if n == 'reference' and record_only:
            rec = f['record'] if isinstance(f['record'], dict) else {}
            why('outcome', 'mods_descriptor_reference' if 'package_id' in rec and rec.get('status') == 'captured'
                else 'record_only_reference')
        elif n == 'saved-record' and record_only:
            why('outcome', 'inline_saved_record')
        elif n == 'unchanged' and 304 in (s, f['final_status']):
            why('outcome', 'not_modified_304')
        elif n == 'unchanged' and line.get('outcome') == 'unchanged':
            why('outcome', 'writer_stated_unchanged')
        elif n == 'retry_later' and (s in (429, 503) or f['final_status'] in (429, 503)):
            why('outcome', 'retry_status')
        elif n == 'failed' and o == 'stored':
            if empty(e):
                why('outcome', 'empty_body')
            elif partial(s, f['content_range']):
                why('outcome', 'partial_206')
            elif s is not None and (not 200 <= s <= 299 or s == 202):
                why('outcome', 'non_document_status')
            elif f['failed']:
                why('outcome', 'raw_failure')
            elif 'provider_response' in f['ptr'] and not any(
                    not empty(x) for x in item_entries(line, f['ptr'])
                    if 'provider_response' not in pointer(x) and x.get('sha256')):
                why('outcome', 'envelope_over_empty_origin')
    hs = (row['old_http_status'], row['new_http_status'])
    if hs[0] != hs[1]:
        if hs[0] is None and hs[1] in (s, f['final_status']):
            why('http_status', 'stated_status_read')
    if row['old_complete'] != row['new_complete']:
        chain = [e or {}, f['owner'] or {}, f['item'] or {}, (f['item'] or {}).get('previous_receipt') or {}]
        if row['new_complete'] and any(x.get('body_complete') is True or x.get('complete') is True for x in chain if isinstance(x, dict)):
            why('complete', 'recorded_complete')
    if row['old_attempt'] != row['new_attempt'] and row['new_attempt'] is None and n in ('reference', 'saved-record'):
        why('attempt', 'record_only_no_attempt')
    fs = (row['old_fetch_http_status'], row['new_fetch_http_status'])
    if fs[0] != fs[1]:
        if fs[1] is None and n in ('reference', 'saved-record'):
            why('fetch_http_status', 'record_only_no_fetch')
        elif fs[0] is None and fs[1] in (f['final_status'], s):
            why('fetch_http_status', 'stated_status_read')
    fo = (row['old_fetch_outcome'], row['new_fetch_outcome'])
    if fo[0] != fo[1]:
        if fo[1] is None and n in ('reference', 'saved-record'):
            why('fetch_outcome', 'record_only_no_fetch')
        elif fo[1] == 'unchanged' and 304 in (f['final_status'], s):
            why('fetch_outcome', 'not_modified_304')
        elif fo[1] == 'unchanged' and line.get('outcome') == 'unchanged':
            why('fetch_outcome', 'writer_stated_unchanged')
        elif fo[1] == 'retry_later' and (f['final_status'] in (429, 503) or s in (429, 503)):
            why('fetch_outcome', 'retry_status')
        elif fo[1] == 'failed':
            unaddressed = row['new_url'] is None and row['requested_url'] is None
            if f['failed'] and not record_only:
                why('fetch_outcome', 'raw_failure')
            elif unaddressed and (empty(e) or (s is not None and (not 200 <= s <= 299 or s == 202))):
                # A row with no request address is its own fetch: its body decides.
                why('fetch_outcome', 'unaddressed_row_not_a_document')
            elif not has_final_document(line, f):
                why('fetch_outcome', 'no_final_document_body')
    g = (row['old_good_fetch'], row['new_good_fetch'])
    if g[0] != g[1]:
        if g[0] and not g[1] and ('outcome' in causes or 'complete' in causes):
            why('good_fetch', 'follows_' + causes.get('outcome', causes.get('complete')))
        elif not g[0] and g[1] and causes.get('http_status') == 'stated_status_read' and (s is not None and 200 <= s <= 299 and s != 202):
            why('good_fetch', 'stated_2xx_read')
        elif not g[0] and g[1] and causes.get('complete') == 'recorded_complete':
            why('good_fetch', 'recorded_complete')
    columns = ['outcome', 'http_status', 'complete', 'attempt', 'fetch_http_status', 'fetch_outcome', 'good_fetch']
    olds = dict(http_status=hs[0], fetch_http_status=fs[0], fetch_outcome=fo[0], good_fetch=g[0], outcome=o,
                complete=row['old_complete'], attempt=row['old_attempt'])
    news = dict(http_status=hs[1], fetch_http_status=fs[1], fetch_outcome=fo[1], good_fetch=g[1], outcome=n,
                complete=row['new_complete'], attempt=row['new_attempt'])
    changed = [c for c in columns if olds[c] != news[c]]
    unexplained = [c for c in changed if c not in causes]
    return causes, changed, olds, news, unexplained, f


def main():
    changes, mirror, extra, out = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    rows = duckdb.connect().execute(f"SELECT * FROM '{changes}'").fetchdf().to_dict('records')
    for r in rows:
        for k, v in list(r.items()):
            if v != v:  # NaN from pandas
                r[k] = None
            elif hasattr(v, 'item'):
                r[k] = v.item()
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r['receipt_key']][r['receipt_line']].append(r)
    summary, defects, judged = Counter(), [], []
    for key, lines in sorted(by.items()):
        path = os.path.join(mirror, key)
        if not os.path.exists(path):
            path = os.path.join(extra, key.replace('/', '__'))
        last = max(lines)
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            for number, text in enumerate(handle, 1):
                if number > last:
                    break
                if number not in lines:
                    continue
                line = json.loads(text)
                for r in lines[number]:
                    causes, changed, olds, news, unexplained, f = judge(r, line)
                    for c in changed:
                        summary[(c, json.dumps(olds[c]), json.dumps(news[c]), causes.get(c, 'UNEXPLAINED'))] += 1
                    judged.append(dict(receipt_key=key, receipt_line=number, capture_index=r['capture_index'],
                                       family=r['family'], causes=json.dumps(causes, sort_keys=True),
                                       unexplained=','.join(unexplained)))
                    if unexplained:
                        defects.append(dict(key=key, line=number, index=r['capture_index'], family=r['family'],
                            unexplained=unexplained, old={c: olds[c] for c in changed}, new={c: news[c] for c in changed},
                            causes=causes, attempt_status=f['attempt_status'], final_status=f['final_status'],
                            pointer=f['ptr'], bytes=(f['entry'] or {}).get('bytes')))
    db = duckdb.connect()
    db.execute('CREATE TABLE j(receipt_key VARCHAR, receipt_line INT, capture_index INT, family VARCHAR, causes VARCHAR, unexplained VARCHAR)')
    db.executemany('INSERT INTO j VALUES (?,?,?,?,?,?)', [tuple(d.values()) for d in judged])
    db.execute(f"COPY j TO '{out}/judged.parquet'")
    json.dump(dict(rows=len(rows), judged=len(judged), defects=len(defects),
                   classes=[[*k, v] for k, v in sorted(summary.items())]), open(f'{out}/summary.json', 'w'), indent=1)
    with open(f'{out}/defects.jsonl', 'w') as sink:
        for d in defects:
            sink.write(json.dumps(d, default=str) + '\n')
    print(json.dumps(dict(rows=len(rows), judged=len(judged), defects=len(defects))))


if __name__ == '__main__':
    main()
