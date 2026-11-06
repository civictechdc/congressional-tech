"""Check one measured candidate against explicit per-container disk and startup bounds."""
import argparse
import json
from pathlib import Path

from congressional_explorer_mcp.body_reader import MAX_CACHE_BYTES
from congressional_explorer_mcp.release import resolve


def capacity(manifest, *, disk_bytes, image_bytes, peak_rss_bytes, memory_bytes,
             cold_start_seconds, startup_timeout_seconds, scratch_bytes=512 << 20, reserve_bytes=128 << 20):
    assets = sum(item['size'] for item in manifest['files'])
    components = dict(release_assets=assets, image=image_bytes, body_cache=MAX_CACHE_BYTES,
                      query_scratch=scratch_bytes, reserve=reserve_bytes)
    required = sum(components.values())
    return dict(status='fits' if required <= disk_bytes and peak_rss_bytes <= memory_bytes and
                cold_start_seconds <= startup_timeout_seconds else 'exceeds_capacity',
        release_id=manifest['release_id'], bytes=components, required_disk_bytes=required,
        disk_bytes=disk_bytes, disk_headroom_bytes=disk_bytes-required,
        measured_peak_rss_bytes=peak_rss_bytes, memory_bytes=memory_bytes,
        measured_cold_start_seconds=cold_start_seconds, startup_timeout_seconds=startup_timeout_seconds,
        notes=['Per-container budget; multiply independent replicas for total resources.',
               'Image bytes and process-tree RSS must come from the actual built runtime.',
               'Cold-start measurement includes download verification, selected worker initialization and readiness.',
               'Use a fresh data directory: old immutable selections add retained bytes until retired.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('publication')
    parser.add_argument('--disk-bytes', type=int, required=True)
    parser.add_argument('--image-bytes', type=int, required=True)
    parser.add_argument('--peak-rss-bytes', type=int, required=True)
    parser.add_argument('--memory-bytes', type=int, required=True)
    parser.add_argument('--cold-start-seconds', type=float, required=True)
    parser.add_argument('--startup-timeout-seconds', type=float, default=90)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    values = {name: getattr(args, name) for name in ('disk_bytes', 'image_bytes', 'peak_rss_bytes', 'memory_bytes', 'cold_start_seconds', 'startup_timeout_seconds')}
    if any(value < 0 for value in values.values()):
        parser.error('Capacity and measured values must be nonnegative')
    _, manifest, _ = resolve(args.publication)
    report = capacity(manifest, **values)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'fits' else 1


if __name__ == '__main__':
    raise SystemExit(main())
