"""Marker differential, per-format cost and peak RSS for read_html_metadata.

Usage: measure_reader.py MANIFEST BODIES_DIR --mode gated|differential
Bodies are <sha>.gz. Run each mode in its own process: gated's peak RSS is the
shipped path's own, and differential deliberately runs what the marker bypasses.
"""
import argparse
import gzip
import hashlib
import json
import resource
import time
from collections import Counter
from pathlib import Path

from w3lib.encoding import html_to_unicode

from congress_api.parsers.html_metadata import _MARKERS, _read_format, is_html, read_html_metadata


def load(manifest, root):
    for row in json.loads(Path(manifest).read_text()):
        yield row, gzip.decompress((Path(root) / f"{row['sha']}.gz").read_bytes())


def gated(manifest, root):
    statuses, digest, count = Counter(), hashlib.sha256(), 0
    start = time.perf_counter()
    for _, body in load(manifest, root):
        metadata = read_html_metadata(body)
        count += 1
        digest.update(json.dumps(metadata.source_dict(), sort_keys=True).encode())
        for name, result in metadata.formats.items():
            statuses[f'{name}:{result.status}:{result.basis}:{result.error_type or ""}'] += 1
    wall = time.perf_counter() - start
    return dict(bodies=count, wall_seconds=round(wall, 1), mean_ms=round(wall / count * 1000, 1),
                peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1),
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
parser.add_argument('bodies')
parser.add_argument('--mode', choices=('gated', 'differential'), required=True)
args = parser.parse_args()
print(json.dumps((gated if args.mode == 'gated' else differential)(args.manifest, args.bodies), indent=1))
