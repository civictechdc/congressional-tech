"""Oracle comparison retains evidence while releasing consumed native tables."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake.capture_comparison import compare_old
from docspec_client.client import NativeDatasets
from docspec_client.models import DocSpecFailure

# Measured 2026-11-12 on pinned engine ae12bbd404902bc8fe22a4bdfa357a23fef9e319 (ct-68e1)
# for the 8,192-row full comparison (batch_rows=32, max_batch_bytes=1 MiB,
# max_metadata_bytes=1 MiB, scratch_bytes=256 MiB), 5 repeats per candidate limit:
#   - 2 threads: 176 MiB 2/5, 178 MiB 4/5, 180 MiB 3/5, 184 MiB 5/5 (smallest reliable pass)
#   - 4 threads: 192 MiB 1/5, 220 MiB 4/5, 224 MiB 3/5, 228 MiB 5/5 (each sort/aggregate
#     partition reserves spill memory independently)
# Do not raise these bounds to make an engine change pass without measuring and recording
# before/after memory needs.
MEASURED_ON = '2026-11-12'
MEASURED_ENGINE_REVISION = 'ae12bbd404902bc8fe22a4bdfa357a23fef9e319'
MEASURED_MIN_8192_MIB = {2: 184, 4: 228}
HEADROOM_8192_MIB = {2: 8, 4: 28}
BOUND_8192_MIB = {threads: MEASURED_MIN_8192_MIB[threads] + HEADROOM_8192_MIB[threads]
                  for threads in MEASURED_MIN_8192_MIB}

EXPECTED_SPILL_MESSAGES = (
    'Not enough memory to continue external sort',
    'Failed to reserve memory for sort during spill',
    'shared memory budget exhausted',
    'The used disk space during the spilling process has exceeded the allowable limit of 256.0 MB',
)


def limited_engine(tmp_path, *, threads=2, memory_mib=192):
    run_dir = tmp_path / f'engine-t{threads}-m{memory_mib}'
    run_dir.mkdir(parents=True, exist_ok=True)
    source = Path(os.environ['DOCSPEC_JOB_CONFIG']).resolve()
    config = json.loads(source.read_text())
    limits = json.loads((source.parent / config['limits']).read_text())
    # Fix the partition count: every sort partition reserves memory independently,
    # so inheriting a host/runtime CPU count changes this bounded-memory regression.
    limits.update(compute_threads=threads, memory_bytes=memory_mib << 20, scratch_bytes=256 << 20,
                  batch_rows=32, max_batch_bytes=1 << 20, max_metadata_bytes=1 << 20)
    limit_path = run_dir / 'limits.json'
    limit_path.write_text(json.dumps(limits))
    config.update(binary=str((source.parent / config['binary']).resolve()),
                  limits=str(limit_path), workspace=str(run_dir / 'workspace'), timeout_seconds=120)
    config_path = run_dir / 'runtime.json'
    config_path.write_text(json.dumps(config))
    return NativeDatasets.from_config(config_path)


def _is_spill_exhaustion(error: DocSpecFailure) -> bool:
    text = str(error)
    return 'Resources exhausted:' in text and any(msg in text for msg in EXPECTED_SPILL_MESSAGES)


def assert_within_memory_bound(run_at_mib, *, threads=2, count=8192):
    """Run once at the recorded bound; on spill failure, search and report 'needs N MiB, bound M MiB'."""
    bound_mib = BOUND_8192_MIB[threads] if count == 8192 else 192
    try:
        return run_at_mib(bound_mib)
    except DocSpecFailure as error:
        if not _is_spill_exhaustion(error):
            raise
        lo = bound_mib
        hi = None
        for delta in (32, 64, 128, 256, 384):
            candidate = bound_mib + delta
            try:
                run_at_mib(candidate)
                hi = candidate
                break
            except DocSpecFailure as probe_error:
                if not _is_spill_exhaustion(probe_error):
                    raise
                lo = candidate
        min_note = (
            f'measured min {MEASURED_MIN_8192_MIB[threads]} MiB + {HEADROOM_8192_MIB[threads]} MiB headroom '
            f'on {MEASURED_ENGINE_REVISION[:7]} ({MEASURED_ON})'
            if count == 8192 and threads in MEASURED_MIN_8192_MIB
            else f'pinned {MEASURED_ENGINE_REVISION[:7]} ({MEASURED_ON})'
        )
        if hi is None:
            raise AssertionError(
                f'{count}-row comparison at {threads} threads needs >{lo} MiB, bound {bound_mib} MiB ({min_note})'
            ) from error
        while hi - lo > 1:
            mid = (lo + hi) // 2
            try:
                run_at_mib(mid)
                hi = mid
            except DocSpecFailure as probe_error:
                if not _is_spill_exhaustion(probe_error):
                    raise
                lo = mid
        raise AssertionError(
            f'{count}-row comparison at {threads} threads needs {hi} MiB, bound {bound_mib} MiB ({min_note})'
        ) from error


@pytest.mark.parametrize('threads', [2, 4])
def test_comparison_completes_with_bounded_native_memory(tmp_path, threads):
    engine = limited_engine(tmp_path, threads=threads)
    count = 2048
    rows = [dict(receipt_key='receipts/documents/2026-10-20/large-contexts.gz',
                 receipt_line=index + 1, pointer_json='["body"]',
                 context_url='https://example.org/' + str(index) + '/' + 'x'*8192,
                 bytes=100, stored_bytes=42, media_type='application/pdf',
                 fidelity='exact-bytes', http_status=200,
                 retrieved_at='2026-10-20T00:00:00Z') for index in range(count)]
    old = tmp_path/'old.parquet'
    new = tmp_path/'new.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(row, sha256='a'*64, reference_kind='capture') for row in rows]), old,
        row_group_size=64)
    pq.write_table(pa.Table.from_pylist([
        dict(row, sha256=bytes.fromhex('a'*64), capture_index=0,
             reference_kind='capture') for row in rows]), new, row_group_size=64)
    result = compare_old(new, old, engine=engine, work=tmp_path/'comparison')
    assert result['old_rows'] == result['new_rows'] == result['matched'] == count
    assert result['old_only'] == result['new_only'] == result['secondary_duplicates'] == 0
    assert result['unexplained'] == result['expected_changes'] == 0
    assert result['owner_gate'] is False
    for name in ('old-only', 'new-only', 'expected-new-only',
                 'unexplained-new-only', 'changed-fields'):
        assert pq.read_metadata(tmp_path/'comparison'/(name + '.parquet')).num_rows == 0


@pytest.mark.parametrize(('count', 'threads'), [(2048, 2), (8192, 2), (8192, 4)])
def test_full_comparison_preserves_file_references_and_restorations_at_four_times_rows(tmp_path, count, threads):
    """The signed pivot must preserve counts and old evidence under explicit per-thread bounds."""
    key = 'receipts/documents/2026-10-20/scaled.gz'
    sha = 'a'*64
    body_key = 'bodies/sha256/aa/' + sha + '.gz'
    old_rows = [dict(receipt_key=key, receipt_line=i+1, sha256=sha, pointer_json='["body"]',
        reference_kind='capture', context_url='https://fixture.test/'+str(i)+'/'+'x'*8192,
        bytes=100, stored_bytes=42, body_key=body_key, media_type='application/pdf',
        fidelity='exact-bytes', http_status=None if i == 0 else 200,
        retrieved_at='2026-10-20T00:00:00Z', original_note='preserved') for i in range(count)]
    old_rows += [dict(old_rows[0], reference_kind='file', pointer_json='["old-file"]'),
        dict(old_rows[0], reference_kind='retained-file', pointer_json='["contradiction"]',
             stored_bytes=43, original_note='must survive unchanged'),
        dict(old_rows[0], receipt_line=count+1, sha256=None, pointer_json='[]', reference_kind='metadata',
             context_url=None, body_key=None, bytes=None, stored_bytes=None, media_type=None,
             fidelity=None, http_status=None)]
    new_rows = []
    for row in old_rows[:count]:
        new = {k: v for k, v in row.items() if k not in {'body_key', 'original_note'}}
        new.update(sha256=bytes.fromhex(sha), capture_index=0, http_status=200,
            stored_suffix='.gz', record_is_list=False, source_record_count=0, source_record_index=None)
        new_rows.append(new)
    for index in (0, 1):
        new_rows.append(dict(new_rows[0], receipt_line=count+1, sha256=None, pointer_json=None,
            reference_kind='line', context_url=None, bytes=None, stored_bytes=None, media_type=None,
            fidelity=None, http_status=None, capture_index=index, record_is_list=True,
            source_record_count=2, source_record_index=index))
    new_rows.append(dict(new_rows[1], receipt_line=count+2, sha256=bytes.fromhex('b'*64)))
    integers = {'receipt_line', 'capture_index', 'bytes', 'stored_bytes', 'http_status',
                'source_record_count', 'source_record_index'}

    def write(path, rows, binary=False):
        fields = [pa.field(name, pa.binary(32) if name == 'sha256' and binary else
            pa.int64() if name in integers else pa.bool_() if name == 'record_is_list' else pa.string())
            for name in rows[0]]
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(fields)), path, row_group_size=64)

    old = tmp_path/'old.parquet'
    new = tmp_path/'new.parquet'
    write(old, old_rows)
    write(new, new_rows, True)
    attempt = 0

    def run_comparison(mib):
        nonlocal attempt
        attempt += 1
        work_dir = tmp_path / f'comparison-{attempt}-m{mib}'
        engine = limited_engine(tmp_path / f'run-{attempt}', threads=threads, memory_mib=mib)
        return work_dir, compare_old(new, old, engine=engine, work=work_dir)

    work_dir, result = assert_within_memory_bound(run_comparison, threads=threads, count=count)
    expected = dict(old_rows=count+3, new_rows=count+3, secondary_duplicates=1, old_only=1,
        new_only=2, expected_new_only=1, unexplained_new_only=1, unexplained=0,
        expected_changes=1, matched=count+1, owner_gate=True)
    assert {name: result[name] for name in expected} == expected
    [kept] = pq.read_table(work_dir/'old-only.parquet').to_pylist()
    assert kept['original_note'] == 'must survive unchanged' and kept['stored_bytes'] == 43
    [restored] = pq.read_table(work_dir/'expected-new-only.parquet').to_pylist()
    assert restored['reason'] == 'source_list_item_restored'
    assert (restored['receipt_line'], restored['source_record_index']) == (count+1, 1)


def test_spill_bound_failure_reports_measured_need_vs_bound():
    import subprocess
    calls = []

    def fake_probe(mib):
        calls.append(mib)
        if mib < 212:
            result = subprocess.CompletedProcess(
                ['docspec'], 1, '', 'Resources exhausted: Failed to reserve memory for sort during spill')
            raise DocSpecFailure(['docspec'], result)

    with pytest.raises(AssertionError, match=r'needs 212 MiB, bound 192 MiB'):
        assert_within_memory_bound(fake_probe, threads=2, count=8192)
    assert calls[0] == 192
    assert BOUND_8192_MIB == {2: 192, 4: 256}
