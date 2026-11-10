"""A watchdog sample counts for the statement it fell inside, and for no other."""
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / 'measure/step_memory.py'
SPEC = importlib.util.spec_from_file_location('step_memory_contract', PATH)
step_memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(step_memory)

GIB = 2**30
EPOCH = 1000.0   # the engine's wall clock at timeline second WATCHDOG_LEAD
WATCHDOG_LEAD = 2.5
FIRST_START = 0.2


def statement(name, start, end, *, before, after, peak=None, event='step', storage='memory'):
    value = dict(event=event, name=name, start_epoch=EPOCH + start, end_epoch=EPOCH + end, duration_seconds=end - start,
                 pool_reserved_before=int(before * GIB), pool_reserved_after=int(after * GIB))
    if event == 'step':
        value.update(storage=storage, step_index=0, rows=1, charged_bytes=0)
    if peak is not None:
        value['pool_reserved_peak'] = int(peak * GIB)
    return value


# `blip` runs between the samples at 3.0 s and 3.25 s; the run's peak is the 3.25 s sample.
EVENTS = [
    statement('short', FIRST_START, 0.8, before=0, after=1, peak=1),
    statement('a', 1.0, 3.0, before=1, after=2, peak=3),
    dict(event='retain', name='a', epoch=EPOCH + 3.0, bytes=GIB, rows=1, storage='memory',
         pool_reserved_before=GIB, pool_reserved_after=2 * GIB),
    statement('blip', 3.05, 3.1, before=2, after=2, peak=2),
    statement('big.parquet', 3.1, 6.0, before=2, after=2, event='output'),
    statement('query:q1', 6.5, 7.6, before=0.5, after=2.5, peak=2.5, storage='query'),
]
# second: (rss_gb, physical_gb); every other quarter second reads (0.8, 1.0)
READINGS = {0.5: (0.9, 1.2), 1.0: (1.5, 2.0), 2.0: (4.0, 5.0), 3.0: (2.5, 3.0), 3.25: (7.0, 9.04), 6.0: (2.0, 2.2),
            7.0: (3.0, 3.3)}


def timeline(readings=READINGS, *, epoch=True):
    rows = []
    for quarter in range(33):
        second = quarter / 4
        rss, physical = readings.get(second, (0.8, 1.0))
        row = dict(seconds=second + WATCHDOG_LEAD, rss_gb=rss, physical_gb=physical, free_disk_gb=100.0)
        rows.append({**row, 'epoch': EPOCH + second} if epoch else row)
    return rows


def write(tmp_path, events=EVENTS, samples=None, *, prefix=''):
    log, samples_path = tmp_path / 'steps.jsonl', tmp_path / 'watchdog.timeline.jsonl'
    log.write_text(''.join(f'{prefix}{json.dumps(event)}\n' for event in events))
    samples_path.write_text(''.join(json.dumps(row) + '\n' for row in (timeline() if samples is None else samples)))
    return [str(log), str(samples_path)]


def report(capsys, *argv):
    assert step_memory.main([*argv, '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    return result, {row['name']: row for row in result['statements']}


def refusal(capsys, *argv):
    with pytest.raises(SystemExit) as stopped:
        step_memory.main(list(argv))
    printed = capsys.readouterr()
    assert stopped.value.code == 2 and printed.out == ''
    return printed.err


def test_each_statement_gets_the_samples_inside_its_window_on_the_shared_clock(tmp_path, capsys):
    result, rows = report(capsys, *write(tmp_path))
    assert result['alignment'] == 'epoch' and result['samples'] == 33 and result['interval_seconds'] == 0.25
    assert [(row['kind'], row['name']) for row in result['statements']] == [
        ('step', 'short'), ('step', 'a'), ('step', 'blip'), ('output', 'big.parquet'), ('query', 'q1')]
    assert rows['a'] == dict(kind='step', name='a', seconds=2.0, samples=9, unattributed=None,
        peak_physical_gb=5.0, peak_rss_gb=4.0, start_physical_gb=2.0, rise_gb=3.0,
        pool_before_gb=1.0, pool_after_gb=2.0, pool_peak_gb=3.0)
    big = rows['big.parquet']
    assert (big['peak_physical_gb'], big['peak_rss_gb'], big['start_physical_gb'], big['rise_gb']) == (9.04, 7.0, 3.0, 6.04)
    assert big['pool_peak_gb'] is None and (big['pool_before_gb'], big['pool_after_gb']) == (2.0, 2.0)
    assert (rows['q1']['peak_physical_gb'], rows['q1']['start_physical_gb'], rows['q1']['rise_gb']) == (3.3, 1.0, 2.3)
    assert rows['short']['peak_physical_gb'] == 1.2
    assert result['run_peak'] == dict(peak_physical_gb=9.04, peak_rss_gb=7.0, during=[dict(kind='output', name='big.parquet')])
    assert result['expect_gb'] == 9.1
    assert result['long_statements'] == dict(count=3, median_start_physical_gb=2.0, median_pool_before_gb=1.0)


def test_a_statement_between_two_samples_is_unattributed_not_given_a_neighbours_peak(tmp_path, capsys):
    result, rows = report(capsys, *write(tmp_path))
    assert rows['blip'] == dict(kind='step', name='blip', seconds=0.05, samples=0, unattributed='no sample in its window',
        peak_physical_gb=None, peak_rss_gb=None, start_physical_gb=None, rise_gb=None,
        pool_before_gb=2.0, pool_after_gb=2.0, pool_peak_gb=2.0)
    assert result['unattributed'] == {'no sample in its window': 1}


def test_a_timeline_without_epoch_is_refused_until_the_caller_gives_the_offset(tmp_path, capsys):
    paths = write(tmp_path, samples=timeline(epoch=False))
    assert '--offset-seconds' in refusal(capsys, *paths)
    result, rows = report(capsys, *paths, '--offset-seconds', str(WATCHDOG_LEAD + FIRST_START))
    assert result['alignment'] == 'offset' and result['offset_seconds'] == WATCHDOG_LEAD + FIRST_START
    assert (rows['a']['peak_physical_gb'], rows['a']['rise_gb'], rows['big.parquet']['peak_physical_gb']) == (5.0, 3.0, 9.04)
    # `short` has samples inside its window, but a hand-given offset cannot place 0.6 s.
    assert rows['short']['samples'] == 3 and rows['short']['peak_physical_gb'] is None
    assert result['unattributed'] == {'under 1 s with a hand-given offset': 2}
    assert step_memory.main([*paths, '--offset-seconds', str(WATCHDOG_LEAD + FIRST_START)]) == 0
    assert 'statements under 1 s are not attributed' in capsys.readouterr().out


def test_an_offset_beside_an_exact_clock_or_a_log_from_another_run_is_refused(tmp_path, capsys):
    paths = write(tmp_path)
    assert 'epoch' in refusal(capsys, *paths, '--offset-seconds', '2.7')
    elsewhere = [{**event, 'start_epoch': event['start_epoch'] + 3600, 'end_epoch': event['end_epoch'] + 3600}
                 for event in EVENTS if 'start_epoch' in event]
    assert 'same run' in refusal(capsys, *write(tmp_path, events=elsewhere))


def test_engine_stderr_lines_read_like_the_step_log_and_unreadable_ones_are_counted(tmp_path, capsys):
    plain, _ = report(capsys, *write(tmp_path))
    paths = write(tmp_path, prefix='2026-11-02T17:11:35.4707128Z E   [docspec-metric] ')
    with open(paths[0], 'a') as log:
        log.write('Traceback (most recent call last):\n[docspec-metric] {"event":"step","name":"cut off\n')
    logged, _ = report(capsys, *paths)
    assert logged['statements'] == plain['statements'] and logged['run_peak'] == plain['run_peak']
    assert (plain['unreadable_metric_lines'], logged['unreadable_metric_lines']) == (0, 1)


def test_a_failed_sample_is_dropped_rather_than_read_as_zero_memory(tmp_path, capsys):
    result, rows = report(capsys, *write(tmp_path, samples=timeline({**READINGS, 6.5: (0.0, 0.0)})))
    assert result['failed_samples'] == 1 and result['samples'] == 32
    assert (rows['q1']['start_physical_gb'], rows['q1']['rise_gb']) == (1.0, 2.3)


def test_the_text_report_names_the_peak_statement_and_the_figure_to_start_with(tmp_path, capsys):
    assert step_memory.main([*write(tmp_path), '--top', '2']) == 0
    text = capsys.readouterr().out
    assert 'run peak: 9.04 GiB physical, 7.00 GiB RSS, during output big.parquet (pool 2.00 GiB)' in text
    assert '--expect-gb 9.1' in text and '1 of 5 statements unattributed' in text
    table = text.split('top 2 ')[1].splitlines()[2:4]
    assert [line.split()[-2:] for line in table] == [['output', 'big.parquet'], ['step', 'a']]
    assert [line.split()[:6] for line in table] == [['9.04', '+6.04', '7.00', '2.00', '2.00', '-'],
                                                    ['5.00', '+3.00', '4.00', '1.00', '2.00', '3.00']]
