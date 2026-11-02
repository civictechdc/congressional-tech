"""Marker differential, per-format cost and peak RSS for read_html_metadata.

Usage: measure_reader.py MANIFEST --mode gated|differential  (bodies via raw_bodies)
Run each mode in its own process: gated's peak RSS is the
shipped path's own, and differential deliberately runs what the marker bypasses.
"""
import argparse
import hashlib
import json
import math
import resource
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from w3lib.encoding import html_to_unicode

from raw_bodies import read_body
from congress_api.parsers.html_metadata import _MARKERS, _read_format, is_html, read_html_metadata


def load(manifest, root):
    for row in json.loads(Path(manifest).read_text())['bodies']:
        yield row, read_body(row['sha'])[0]


def gated(manifest, root):
    statuses, digest, count = Counter(), hashlib.sha256(), 0
    by_stratum, sizes = defaultdict(list), []
    start = time.perf_counter()
    for row, body in load(manifest, root):
        began = time.perf_counter()
        metadata = read_html_metadata(body)
        elapsed = time.perf_counter() - began
        by_stratum[row['why']].append(elapsed)
        sizes.append((elapsed, len(body), row['sha']))
        statuses['wall_clock_dependent'] += metadata.wall_clock_dependent
        count += 1
        digest.update(json.dumps(metadata.source_dict(), sort_keys=True).encode())
        for name, result in metadata.formats.items():
            statuses[f'{name}:{result.status}:{result.basis}:{result.error_type or ""}'] += 1
    wall = time.perf_counter() - start
    random = [value for name, values in by_stratum.items() if name.startswith('random') for value in values]
    ordered = sorted(sizes)
    large = [(math.log(n), math.log(t)) for t, n, _ in sizes if n > 20_000 and t > 0]
    return dict(bodies=count, wall_seconds=round(wall, 1), mean_ms=round(sum(t for t, _, _ in sizes) / count * 1000, 1), read_and_reader_wall_mean_ms=round(wall / count * 1000, 1),
                peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1),
                random_strata=dict(bodies=len(random), mean_ms=round(statistics.mean(random) * 1000, 1)),
                percentile_ms={str(q): round(ordered[int(count * q / 100)][0] * 1000, 1) for q in (50, 90, 99)},
                worst=[dict(sha=sha, bytes=n, ms=round(t * 1000, 1)) for t, n, sha in ordered[-5:]],
                log_log_time_slope_over_20kb=round(statistics.linear_regression(*zip(*large)).slope, 2),
                statuses=dict(sorted(statuses.items())), all_results_sha256=digest.hexdigest())


def differential(manifest, root):
    """Run the gated formats regardless of the marker. A miss is marker absent, extractor ok."""
    counts = {name: Counter() for name in _MARKERS}
    misses, seconds = [], Counter()
    for row, body in load(manifest, root):
        if not is_html(body):
            continue
        _, decoded = html_to_unicode(None, body, default_encoding='utf-8')
        for name, marker in _MARKERS.items():
            start = time.perf_counter()
            result = _read_format(decoded.encode('utf-8', errors='replace'), name, 45.0)
            elapsed = time.perf_counter() - start
            seconds[name] += elapsed
            present = bool(marker.search(decoded))
            counts[name][f"marker_{'present' if present else 'absent'}:{result.status}:{result.error_type or ''}"] += 1
            if not present:
                seconds[name + ':bypassed'] += elapsed
                if result.status == 'ok':
                    misses.append([row['sha'], name])
    return dict(counts={name: dict(sorted(value.items())) for name, value in counts.items()}, misses=misses,
                seconds={name: round(value, 1) for name, value in sorted(seconds.items())})


parser = argparse.ArgumentParser()
parser.add_argument('manifest')
parser.add_argument('--mode', choices=('gated', 'differential'), required=True)
args = parser.parse_args()
print(json.dumps((gated if args.mode == 'gated' else differential)(args.manifest, None), indent=1))
