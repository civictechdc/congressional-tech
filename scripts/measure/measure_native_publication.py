#!/usr/bin/env python3
"""Run the maintained small native publication fixture without a remote service.

The fixture owns an in-memory native runtime and object service. Real local
publication/journal persistence runs; only SDK latency is modeled. Every trial
uses the same generated source and a fresh attempt directory. Imports and
interpreter startup are excluded; source-identity cache is cold per command.
"""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch


def run(checkout, output, *, trials=3, request_latency_ms=1):
    if type(trials) is not int or not 1 <= trials <= 5:
        raise ValueError('Native fixture trials must be between one and five')
    if not 0 <= request_latency_ms <= 10:
        raise ValueError('Modeled request latency must be between zero and ten ms')
    checkout, output = Path(checkout).resolve(), Path(output).resolve()
    sys.path[:0] = [str(checkout / relative) for relative in (
        'scripts/measure', 'packages/viewer_publication/src', 'packages/congress_api/src',
        'packages/congress_shared/src', 'packages/docspec_client/src',
        'packages/congress_api/tests', 'packages/viewer_publication/tests', 'tests')]
    import measure_publication_control as measurement
    spec = importlib.util.spec_from_file_location('native_cost_fixture', measurement.publication_fixture(checkout))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    def mktemp(_name):
        source.mkdir()
        return source
    fixture.source.__wrapped__(SimpleNamespace(mktemp=mktemp))
    native = fixture._NATIVE_FIXTURES[str(source)]
    from congress_api.retention.docspec import NativeDatasets
    pin = hashlib.sha256((source / 'indexes/catalog.json').read_bytes()).hexdigest()
    receipts = []
    with patch.dict(os.environ, {'DOCSPEC_CONFIG': 'explicit-test-native-runtime.json'}), patch.object(
            NativeDatasets, 'from_config', classmethod(lambda cls, _path: native)):
        for trial in range(trials):
            receipts.append(measurement.run(checkout, source, output / f'trial-{trial + 1}', pin,
                maximum_source_bytes=8 * 1024**2, request_latency_ms=request_latency_ms))
    return receipts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--trials', type=int, default=3)
    parser.add_argument('--request-latency-ms', type=float, default=1)
    args = parser.parse_args()
    for receipt in run(args.checkout, args.output, trials=args.trials,
                       request_latency_ms=args.request_latency_ms):
        print(receipt)
