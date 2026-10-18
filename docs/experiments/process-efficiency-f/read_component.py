"""Measure only selected-pair read/validation, retaining the snapshot until sampling ends."""
import argparse
import json
from pathlib import Path
import time

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from congress_api.cli.raw_progress import memory_usage
from scripts.benchmark_core_rebuild import MemorySampler, process_tree_resident_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mirror', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scratch-root', type=Path, required=True)
    args = parser.parse_args()
    sampler = MemorySampler(args.scratch_root)
    sampler.start()
    started = time.monotonic()
    snapshot = None
    report = {'scope': 'selected catalog pair read and verification only', 'status': 'running'}
    try:
        snapshot = read_catalog(LocalStore(args.mirror))
        report['elapsed_seconds'] = time.monotonic() - started
        report['manifest'] = snapshot.manifest
        report['resident_after_read_bytes'] = process_tree_resident_bytes()
        report['high_water_memory'] = memory_usage()
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error),
                      notes=getattr(error, '__notes__', []))
        raise
    finally:
        sampler.finish()
        report['sampled_process_tree_peak_resident_bytes'] = sampler.peak
        report['sampled_scratch_peak_bytes'] = sampler.scratch_peak_bytes
        report['sampled_scratch_peak_allocated_bytes'] = sampler.scratch_peak_allocated_bytes
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        if snapshot is not None and hasattr(snapshot, 'close'):
            snapshot.close()


if __name__ == '__main__':
    main()
