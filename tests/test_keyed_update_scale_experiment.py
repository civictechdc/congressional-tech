"""Check the measurement oracle and bounded generated input, without native calls."""
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'measure'))
import compare_raw_keyed_updates_scale as experiment


class Budget:
    def sample(self):
        pass


class Source:
    budget = Budget()

    def __init__(self, rows):
        self.rows = rows

    @contextmanager
    def source_batches(self, pin, *, schema):
        assert schema.equals(experiment.SCHEMA)
        yield pa.RecordBatchReader.from_batches(schema,
            pa.Table.from_pylist(self.rows, schema=schema).to_batches(max_chunksize=3))


@pytest.mark.parametrize('case', ['original', 'append', 'correction', 'delete', 'empty'])
def test_bounded_producer_preserves_exact_nested_values_and_oracle(tmp_path, case):
    path = tmp_path / 'generated.parquet'
    count = 2050
    experiment.producer(path, count, case, Budget())
    stored = pq.ParquetFile(path)
    assert max(stored.metadata.row_group(i).num_rows for i in range(stored.num_row_groups)) <= 1024
    restored = stored.read().cast(experiment.SCHEMA, safe=True)
    assert experiment.validate(Source(restored.to_pylist()), {}, count, case) == count + (case == 'append') - (case == 'delete')
    first = restored.to_pylist()[0]['exact']
    assert first['number'] == 2**64 - 1
    assert first['values'][:2] == [None, b'']
    assert isinstance(first['values'][2], bytes)
    assert first['values'][2] == first['values'][3]


@pytest.mark.parametrize('damage', ['corrupt', 'duplicate', 'omitted', 'out_of_range'])
def test_oracle_rejects_corrupt_duplicate_omitted_or_out_of_range_rows(damage):
    rows = [experiment.row(i) for i in range(4)]
    if damage == 'corrupt':
        rows[2]['exact']['number'] -= 1
    elif damage == 'duplicate':
        rows[-1] = experiment.row(2)
    elif damage == 'omitted':
        rows.pop()
    else:
        rows[-1] = experiment.row(4)
    with pytest.raises(AssertionError):
        experiment.validate(Source(rows), {}, 4, 'original')


def arguments(**changes):
    return Namespace(**dict(dict(rows='1000,8192,10000,100000', rounds=1,
        seconds=1800, max_bytes=4 << 30, cases='append,correction,delete,empty',
        axes='population,files,history'), **changes))


@pytest.mark.parametrize('changes', [dict(rows='1'), dict(rows='1000001'), dict(rows=''),
    dict(rounds=0), dict(rounds=4), dict(seconds=1801), dict(seconds=0),
    dict(max_bytes=(4 << 30) + 1), dict(max_bytes=0), dict(cases='unknown'), dict(axes='unknown')])
def test_input_count_and_experiment_bounds_are_enforced(changes):
    with pytest.raises(ValueError):
        experiment.checked_arguments(arguments(**changes))


def test_allowed_boundary_input_counts():
    assert experiment.checked_arguments(arguments(rows='2,1000000')) == [2, 1000000]


def test_history_preparation_chains_operations_but_preserves_exact_source_pin(tmp_path):
    source = {'objects': [{'path': 'exact-original-file', 'digest': 'original-digest'}]}
    base = dict(id='initial', dataset={'groups': {'source': source}})

    class Native:
        requests = []

        def hash_input(self, path):
            assert pq.read_table(path).num_rows == 0
            return {'digest': 'empty-input'}

        def update(self, request):
            self.requests.append(request)
            return dict(id=request['operation'], dataset={'groups': {'source': source}})

    native = Native()
    result = experiment.prepare_history(native, base, 3, tmp_path)
    assert [request['base'] for request in native.requests] == ['initial', 'history-0', 'history-1']
    assert result['id'] == 'history-2'
    assert result['dataset']['groups']['source'] == source
    native.update = lambda request: dict(id='wrong', dataset={'groups': {'source': {'objects': []}}})
    with pytest.raises(AssertionError):
        experiment.prepare_history(native, base, 1, tmp_path)
