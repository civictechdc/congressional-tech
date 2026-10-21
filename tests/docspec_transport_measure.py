"""Bounded real-native comparison; run before and after the transport change."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import types

import pyarrow as pa

from congress_api.retention.docspec import NativeDatasets
from native_test_helpers import native_test_client


def measure():
    global NativeDatasets
    if len(sys.argv) > 2:
        # Reproduce the pre-change adapter without creating another worktree.
        import native_test_helpers
        source = subprocess.check_output(['git', 'show',
            sys.argv[2] + ':packages/docspec_client/src/docspec_client/docspec.py'], text=True)
        module = types.ModuleType('docspec_client.docspec_baseline')
        exec(compile(source, 'docspec-baseline.py', 'exec'), module.__dict__)
        NativeDatasets = native_test_helpers.NativeDatasets = module.NativeDatasets
    counts = dict(native_process_launches=0, scratch_read_bytes=0,
                  exact_release_lookups=0, exact_release_seconds=0)
    popen = subprocess.Popen
    call = NativeDatasets._call
    release = NativeDatasets.release

    def counted_popen(*args, **kwargs):
        counts['native_process_launches'] += 1
        return popen(*args, **kwargs)

    def counted_call(self, *args, **kwargs):
        result = call(self, *args, **kwargs)
        if args[0] == 'read':
            counts['scratch_read_bytes'] += Path(args[2]).stat().st_size
        return result

    def counted_lookup(operation, *args, **kwargs):
        counts['exact_release_lookups'] += 1
        started = time.perf_counter()
        try:
            return operation(*args, **kwargs)
        finally:
            counts['exact_release_seconds'] += time.perf_counter() - started

    def counted_release(self, *args):
        return counted_lookup(release, self, *args)

    subprocess.Popen = counted_popen
    NativeDatasets._call = counted_call
    if hasattr(NativeDatasets, '_execution_host'):
        from congress_api.retention.docspec_host import Host
        request = Host.request
        def counted_request(self, method, path, **kwargs):
            if method == 'GET' and '/versions/' in path and not path.endswith('/arrow/source'):
                return counted_lookup(request, self, method, path, **kwargs)
            return request(self, method, path, **kwargs)
        Host.request = counted_request
    else:
        NativeDatasets.release = counted_release
    schema = pa.schema([('row', pa.int64()), ('unsigned', pa.uint64()),
        ('nested', pa.list_(pa.struct([('name', pa.string()),
                                      ('values', pa.list_(pa.binary()))])))],
        metadata={b'application': b'exact'})
    rows = [dict(row=0, unsigned=2**64-1,
                 nested=[dict(name='', values=[b'x', None, b'x'])] ),
            dict(row=1, unsigned=None, nested=None),
            dict(row=2, unsigned=0, nested=[])]
    rows += rows
    table = pa.Table.from_pylist(rows, schema=schema)
    with TemporaryDirectory(prefix='docspec-transport-measure-') as directory:
        native = native_test_client(os.environ['DOCSPEC_BINARY'], Path(directory) / 'workspace')
        start = time.perf_counter()
        try:
            pin = native.run_table(table, dataset='transport-measure',
                                   operation='initial', definition='nested-v1')
            for _ in range(3):
                with native.source_batches(pin, schema=schema) as reader:
                    actual = reader.read_all().sort_by([('row', 'ascending')])
                    assert actual.equals(table.sort_by([('row', 'ascending')]), check_metadata=True)
            assert native.latest('transport-measure') == pin
            assert native.release('transport-measure', 'initial') == pin
        finally:
            if hasattr(native, 'close'):
                native.close()
        counts['elapsed_seconds'] = time.perf_counter() - start
    counts['rows'] = len(rows)
    counts['reads'] = 3
    counts['native_binary'] = os.environ['DOCSPEC_BINARY']
    counts['implementation'] = sys.argv[2] if len(sys.argv) > 2 else 'current-host'
    print(json.dumps(counts, indent=2))
    Path(sys.argv[1]).write_text(json.dumps(counts, indent=2) + '\n')


if __name__ == '__main__':
    measure()
