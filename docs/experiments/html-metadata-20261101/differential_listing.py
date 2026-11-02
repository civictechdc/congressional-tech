"""Baseline listing parsers against HEAD's over every retained senate/pages body.

Usage: differential_listing.py CAPTURES.parquet BASELINE_SENATE.py BASELINE_SENATE_PAGE.py OUT_DIR
The baselines are `git show 3df9bdf6:` of parsers/senate.py and parsers/senate_page.py. Also
compares parse_page, whose output feeds source IDs, at each body's captured URL. Writes
differential-listing.json: counts, every skipped body by reason, every changed body.
"""
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

import pyarrow.parquet as pq

from raw_bodies import read_body

MARKED = re.compile(r'(?<![\w-])(?:vevent|h-event)(?![\w-])')
SIZE_LIMIT = 2_000_000
base = None


def setup(path, page_path):
    """Load the baseline senate.py against the baseline senate_page.py, then restore HEAD's."""
    global base
    import congress_api.parsers.senate_page as current
    spec = importlib.util.spec_from_file_location('senate_page_baseline', page_path)
    old_page = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_page)
    sys.modules['congress_api.parsers.senate_page'] = old_page
    spec = importlib.util.spec_from_file_location('senate_baseline', path)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    sys.modules['congress_api.parsers.senate_page'] = current


def sniff(raw):
    """What a body is, read from its bytes. Non-empty markup skips are the ones that would matter."""
    if raw.startswith(b'%PDF-') or b'%PDF-' in raw[:1024]:
        return 'pdf'
    if raw.startswith(b'PK\x03\x04'):
        return 'zip_format'
    head = raw[:2048].lstrip(b'\xef\xbb\xbf\x00\t\n\r ')
    if not head:
        return 'empty'
    if head[:1] in (b'{', b'['):
        return 'json'
    return 'markup' if head[:1] == b'<' or raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'other_not_markup'


def compare(item):
    sha, url = item
    from congress_api.parsers import senate as head
    try:
        raw, source = read_body(sha)
    except Exception as error:
        return sha, 'skip:unreadable:' + type(error).__name__, 'none', {}
    kind = sniff(raw)
    if kind != 'markup':
        return sha, 'skip:' + kind, source, {}
    if len(raw) >= SIZE_LIMIT:
        return sha, 'skip:markup_at_or_over_2mb', source, {}
    try:
        page = raw.decode('utf-8')
    except UnicodeDecodeError:
        return sha, 'skip:markup_not_utf8', source, {}
    try:
        site = 'x.senate.gov'
        old_rows, old_details = base.parse_listing_page(page, site), base.parse_listing_details(page, site)
        started = time.perf_counter()
        new_rows, new_details = head.parse_listing_page(page, site), head.parse_listing_details(page, site)
        elapsed = time.perf_counter() - started
    except Exception as error:
        return sha, 'skip:raises:' + type(error).__name__, source, {}
    try:
        same_page = base.parse_page(page, url).source_dict() == head.parse_page(page, url).source_dict()
    except Exception as error:
        same_page = type(base.__name__) is str and 'both_raise:' + type(error).__name__
    if old_rows == new_rows and old_details == new_details and same_page is True:
        return sha, 'same', source, dict(seconds=elapsed)
    if old_rows == new_rows and old_details == new_details:
        return sha, 'same' if str(same_page).startswith('both_raise') else 'parse_page_changed', source, dict(seconds=elapsed)
    return sha, 'changed_marked' if MARKED.search(page) else 'changed_UNMARKED', source, dict(
        seconds=elapsed, rows_changed=old_rows != new_rows, rows=[len(old_rows), len(new_rows)], details_changed=old_details != new_details, parse_page_same=same_page is True)


def main():
    table = pq.read_table(sys.argv[1], columns=['family', 'sha256', 'context_url'], filters=[('family', '=', 'senate/pages')])
    urls = {}
    for sha, url in zip(table['sha256'].to_pylist(), table['context_url'].to_pylist()):
        if sha and (url or sha not in urls):
            urls[sha] = url or urls.get(sha) or 'https://x.senate.gov/uncaptured-url'
    shas = sorted(urls)
    urls_sorted = [(sha, urls[sha]) for sha in shas]
    counts, sources, skipped, changed = Counter(), Counter(), defaultdict(list), {}
    seconds, started = 0.0, time.perf_counter()
    with ProcessPoolExecutor(8, initializer=setup, initargs=(sys.argv[2], sys.argv[3])) as pool:
        for sha, outcome, source, info in pool.map(compare, urls_sorted, chunksize=32):
            counts[outcome] += 1
            sources[source] += 1
            seconds += info.get('seconds', 0.0)
            if outcome.startswith('skip:'):
                skipped[outcome[5:]].append(sha)
            elif outcome != 'same':
                changed[sha] = dict(outcome=outcome, **{k: v for k, v in info.items() if k != 'seconds'})
    result = dict(bodies=len(shas), raw_bodies_read=sum(v for k, v in sources.items() if k != 'none'), sources=dict(sources),
                  compared=sum(v for k, v in counts.items() if not k.startswith('skip:')), counts=dict(sorted(counts.items())),
                  head_parser_seconds=round(seconds, 1), wall_seconds=round(time.perf_counter() - started),
                  changed=changed, skipped={k: sorted(v) for k, v in sorted(skipped.items())})
    (Path(sys.argv[4]) / 'differential-listing.json').write_text(json.dumps(result, indent=0) + '\n')
    print(json.dumps({k: result[k] for k in ('bodies', 'raw_bodies_read', 'sources', 'compared', 'counts', 'head_parser_seconds', 'wall_seconds')}, indent=1))


if __name__ == '__main__':
    main()
