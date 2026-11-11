"""A watchdog sample counts for the statement it fell inside, and for no other."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

PATH = Path(__file__).resolve().parents[1] / 'measure/step_memory.py'
SPEC = importlib.util.spec_from_file_location('step_memory_contract', PATH)
step_memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(step_memory)

GIB = 2**30
EPOCH = 1000.0   # the engine's wall clock at timeline second WATCHDOG_LEAD
WATCHDOG_LEAD = 2.5
FIRST_START = 0.2
READ = 0.04   # each sample is stamped when its reading ends


def statement(name, start, end, *, before, after, peak=None, event='step', storage='memory', copied=None, refused=None):
    value = dict(event=event, name=name, start_epoch=EPOCH + start, end_epoch=EPOCH + end, duration_seconds=end - start,
                 pool_reserved_before=int(before * GIB), pool_reserved_after=int(after * GIB))
    if event == 'step':
        value.update(storage=storage, step_index=0, rows=1, charged_bytes=0)
    if peak is not None:
        value['pool_reserved_peak'] = int(peak * GIB)
    if copied is not None:  # the memory fix's binary writes both counts on every step event; the pin writes neither
        value.update(compaction_copied_batches=copied, compaction_refused_copies=refused)
    return value


# What a statement shows when its binary logs no compaction counts and no debug log was read.
UNLOGGED = dict(copied_batches=None, refused_copies=None, shared_requests=None, shared_floor_gb=None, view_copies=None,
                refusal_lines=None)


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
        rows.append({**row, 'epoch': EPOCH + second, 'read_seconds': READ} if epoch else row)
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
    assert rows['a'] == dict(kind='step', name='a', storage='memory', seconds=2.0, samples=8, unattributed=None,
        peak_physical_gb=5.0, peak_rss_gb=4.0, start_physical_gb=2.0, rise_gb=3.0,
        pool_before_gb=1.0, pool_after_gb=2.0, pool_peak_gb=3.0, **UNLOGGED)
    big = rows['big.parquet']
    assert (big['peak_physical_gb'], big['peak_rss_gb'], big['start_physical_gb'], big['rise_gb']) == (9.04, 7.0, 3.0, 6.04)
    assert big['pool_peak_gb'] is None and (big['pool_before_gb'], big['pool_after_gb']) == (2.0, 2.0)
    assert (rows['q1']['peak_physical_gb'], rows['q1']['start_physical_gb'], rows['q1']['rise_gb']) == (3.3, 1.0, 2.3)
    assert rows['short']['peak_physical_gb'] == 1.2
    assert result['run_peak'] == dict(peak_physical_gb=9.04, peak_rss_gb=7.0, seconds=WATCHDOG_LEAD + 3.25,
        during=[dict(kind='output', name='big.parquet', pool_before_gb=2.0)], overlaps=[])
    assert result['expect_gb'] == 9.1
    assert result['long_statements'] == dict(count=3, median_start_physical_gb=2.0, median_pool_before_gb=1.0)


def test_a_statement_between_two_samples_is_unattributed_not_given_a_neighbours_peak(tmp_path, capsys):
    result, rows = report(capsys, *write(tmp_path))
    assert rows['blip'] == dict(kind='step', name='blip', storage='memory', seconds=0.05, samples=0,
        unattributed='no sample in its window', peak_physical_gb=None, peak_rss_gb=None, start_physical_gb=None,
        rise_gb=None, pool_before_gb=2.0, pool_after_gb=2.0, pool_peak_gb=2.0, **UNLOGGED)
    assert result['unattributed'] == {'no sample in its window': 1}


def test_a_sample_whose_reading_began_before_the_statement_is_not_that_statements(tmp_path, capsys):
    """The 3.25 s sample, the run's peak, was read from 3.21 s; a statement that starts at 3.22 s did not make all
    of it, so the peak fell in no statement. The report still says which statements that reading overlaps."""
    events = [statement('a', 1.0, 3.0, before=1, after=2), statement('late.parquet', 3.22, 6.0, before=2, after=2, event='output')]
    result, rows = report(capsys, *write(tmp_path, events=events))
    late = rows['late.parquet']
    assert (late['samples'], late['peak_physical_gb'], late['start_physical_gb'], late['rise_gb']) == (11, 2.2, 3.0, -0.8)
    assert result['run_peak'] == dict(peak_physical_gb=9.04, peak_rss_gb=7.0, seconds=WATCHDOG_LEAD + 3.25, during=[],
        overlaps=[dict(kind='output', name='late.parquet', pool_before_gb=2.0)])
    assert step_memory.main(write(tmp_path, events=events)) == 0
    assert ('the highest reading, at timeline second 5.75, fell in no statement; it overlaps output late.parquet (pool 2.00 GiB)'
            in capsys.readouterr().out)
    assert step_memory.main(write(tmp_path, events=events[:1])) == 0
    assert 'fell in no statement; it overlaps none' in capsys.readouterr().out


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
    text = capsys.readouterr().out
    assert 'statements under 1 s are not attributed' in text
    assert 'per-statement figures move with that offset; the run peak and --expect-gb do not' in text
    # A peak inside a statement the offset cannot place fell in no statement; that statement is only overlapped.
    early, _ = report(capsys, *write(tmp_path, samples=timeline({0.5: (10.0, 12.0)}, epoch=False)), '--offset-seconds', '2.7')
    assert (early['run_peak']['during'], early['run_peak']['overlaps']) == ([], [dict(kind='step', name='short', pool_before_gb=0.0)])


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
        log.write('Traceback (most recent call last):\n[docspec-metric] {"event":"step","name":"cut off\n[docspec-metric] 5\n')
    logged, _ = report(capsys, *paths)
    assert logged['statements'] == plain['statements'] and logged['run_peak'] == plain['run_peak']
    assert (plain['unreadable_metric_lines'], logged['unreadable_metric_lines']) == (0, 2)


def test_a_failed_sample_is_dropped_rather_than_read_as_zero_memory(tmp_path, capsys):
    result, rows = report(capsys, *write(tmp_path, samples=timeline({**READINGS, 6.5: (0.0, 0.0)})))
    assert result['failed_samples'] == 1 and result['samples'] == 32
    assert (rows['q1']['start_physical_gb'], rows['q1']['rise_gb']) == (1.0, 2.3)


def test_a_step_log_without_pool_figures_still_reports_memory(tmp_path, capsys):
    bare = [{key: value for key, value in event.items() if not key.startswith('pool_')} for event in EVENTS]
    result, rows = report(capsys, *write(tmp_path, events=bare))
    assert (rows['a']['peak_physical_gb'], rows['a']['pool_before_gb'], rows['a']['pool_after_gb'], rows['a']['pool_peak_gb']) == (
        5.0, None, None, None)
    assert result['long_statements'] == dict(count=3, median_start_physical_gb=2.0, median_pool_before_gb=None)
    assert step_memory.main([*write(tmp_path, events=bare), '--top', '1']) == 0
    text = capsys.readouterr().out
    assert 'the highest reading fell in output big.parquet\n' in text and 'median physical 2.00 GiB, no pool figures' in text
    assert text.splitlines()[-1].split() == ['9.04', '+6.04', '7.00', '-', '-', '-', '2.9', 'output', 'big.parquet']


def test_a_timeline_cut_off_at_its_last_line_is_used_and_said_so_and_other_bad_input_is_refused(tmp_path, capsys):
    """A timeline read while its job still runs ends in a part-written line; anything else unreadable is not guessed at."""
    plain, _ = report(capsys, *write(tmp_path))
    paths = write(tmp_path)
    with open(paths[1], 'a') as samples:
        samples.write('{"seconds": 10.75, "epo')
    running, _ = report(capsys, *paths)
    assert (plain['torn_last_line'], running['torn_last_line'], running['samples']) == (False, True, 33)
    assert running['statements'] == plain['statements'] and running['run_peak'] == plain['run_peak']
    assert step_memory.main(paths) == 0
    assert 'the last timeline line was cut off' in capsys.readouterr().out
    with open(paths[1], 'a') as samples:
        samples.write('\n' + json.dumps(timeline()[-1]) + '\n')
    assert 'timeline line 34' in refusal(capsys, *paths)
    nameless = [{key: value for key, value in EVENTS[0].items() if key != 'name'}, *EVENTS[1:]]
    assert 'name' in refusal(capsys, *write(tmp_path, events=nameless))
    assert 'missing.jsonl' in refusal(capsys, str(tmp_path / 'missing.jsonl'), write(tmp_path)[1])


def test_the_text_report_names_the_statement_the_peak_fell_in_and_the_figure_to_start_with(tmp_path, capsys):
    assert step_memory.main([*write(tmp_path), '--top', '2']) == 0
    text = capsys.readouterr().out
    assert 'run peak: 9.04 GiB physical, 7.00 GiB RSS; the highest reading fell in output big.parquet (pool 2.00 GiB)' in text
    assert '--expect-gb 9.1' in text and '1 of 5 statements unattributed' in text
    table = text.split('top 2 ')[1].splitlines()[2:4]
    assert [line.split()[-2:] for line in table] == [['output', 'big.parquet'], ['step', 'a']]
    assert [line.split()[:6] for line in table] == [['9.04', '+6.04', '7.00', '2.00', '2.00', '-'],
                                                    ['5.00', '+3.00', '4.00', '1.00', '2.00', '3.00']]


def test_a_timeline_with_a_null_clock_or_two_runs_in_it_is_refused(tmp_path, capsys):
    broken = timeline()
    broken[5]['epoch'] = None
    assert 'timeline line 6' in refusal(capsys, *write(tmp_path, samples=broken))
    # epoch minus seconds is the watchdog's start: constant within one run, so a second run appended moves it.
    later = [{**row, 'epoch': row['epoch'] + 600} for row in timeline()]
    assert 'more than one run' in refusal(capsys, *write(tmp_path, samples=timeline() + later))


def measured(tmp_path, capsys, label, events, samples=None, *options):
    """One run measured to the JSON that --compare reads."""
    folder = tmp_path / label
    folder.mkdir()
    assert step_memory.main([*write(folder, events, samples), *options, '--json']) == 0
    path = folder / 'result.json'
    path.write_text(capsys.readouterr().out)
    return str(path)


def compared(capsys, *argv):
    assert step_memory.main(['--compare', *argv, '--json']) == 0
    return json.loads(capsys.readouterr().out)


# Run A as the pinned binary logs it: no pool peak, no compaction counts. Run B as the memory fix logs it, changed:
# `a` moved to scratch with a higher footprint, `big.parquet` ran 2 s faster, `short` was refused two view copies,
# `q1` peaked above what A shows for it; `blip` ran only in A and `captures` only in B.
PIN = [{key: value for key, value in event.items() if key != 'pool_reserved_peak'} for event in EVENTS]
FIX = [
    statement('short', FIRST_START, 0.8, before=0, after=1, peak=1, copied=0, refused=2),
    statement('a', 1.0, 3.0, before=1, after=2, peak=2, storage='scratch', copied=3, refused=0),
    statement('big.parquet', 3.1, 4.0, before=2, after=2, event='output'),
    statement('query:q1', 6.5, 7.6, before=0.5, after=2.5, peak=3.5, storage='query', copied=0, refused=0),
    statement('captures', 7.7, 8.0, before=2.5, after=2.5, peak=2.5, copied=0, refused=0),
]


def test_two_runs_compare_statement_by_statement_and_one_run_statements_are_listed(tmp_path, capsys):
    pin = measured(tmp_path, capsys, 'pin', PIN)
    fix = measured(tmp_path, capsys, 'fix', FIX, timeline({**READINGS, 2.0: (4.0, 6.0)}))
    result = compared(capsys, pin, fix)
    assert result['thresholds'] == dict(seconds=1.0, gib=0.5)
    assert result['only_in'] == dict(a=['step blip'], b=['step captures'])
    assert result['moved'] == {'step a': dict(peak_physical_gb=[5.0, 6.0], rise_gb=[3.0, 4.0], storage=['memory', 'scratch']),
                               'output big.parquet': dict(seconds=[2.9, 0.9])}
    assert [(row['statement'], row['a'] is None, row['b'] is None) for row in result['statements']] == [
        ('step short', False, False), ('step a', False, False), ('step blip', False, True),
        ('output big.parquet', False, False), ('query q1', False, False), ('step captures', True, False)]
    # The pinned binary writes neither count: that is "not logged" (None), never zero.
    assert result['counts']['refused_copies'] == dict(a=None, b=dict(logged=4, statements={'step short': 2}))
    assert result['counts']['copied_batches'] == dict(a=None, b=dict(logged=4, statements={'step a': 3}))
    assert result['counts']['refusal_lines'] == dict(a=None, b=None)
    # A logs no pool peak, but its peak is at least the larger of its pool before and after: B at or below that
    # passes; above it is undetermined, not a failure.
    assert result['pool_peak'] == dict(judged=3, against_a_bound=3, above={}, above_a_bound={'query q1': [2.5, 3.5]})
    assert step_memory.main(['--compare', pin, fix]) == 0
    text = capsys.readouterr().out
    assert 'refused copies (pass: 0 on every statement): A not logged by this binary; B 2 in step short (logged on 4 of 5)' in text
    assert 'copied batches: A not logged by this binary; B 3 in step a (logged on 4 of 5)' in text
    assert 'B above that bound, undetermined: query q1 (2.50 -> 3.50 GiB)' in text
    assert 'in A only: step blip\nin B only: step captures\n' in text
    assert text.endswith('moved: 2 of 4 statements in both\n  step a: peak physical 5.00 -> 6.00 GiB; rise +3.00 -> +4.00 GiB; '
                         'storage memory -> scratch\n  output big.parquet: seconds 2.9 -> 0.9\n')


def test_a_pool_peak_above_the_other_runs_is_named_whatever_the_thresholds(tmp_path, capsys):
    raised = [statement('a', 1.0, 3.0, before=1, after=2, peak=3.5) if event.get('name') == 'a' and 'start_epoch' in event
              else statement('query:q1', 6.5, 7.9, before=0.5, after=2.5, peak=2.5, storage='query')
              if event.get('name') == 'query:q1' else event for event in EVENTS]
    base, high = measured(tmp_path, capsys, 'base', EVENTS), measured(tmp_path, capsys, 'high', raised)
    result = compared(capsys, base, high)
    assert result['moved'] == {} and result['only_in'] == dict(a=[], b=[])
    assert result['pool_peak'] == dict(judged=4, against_a_bound=0, above={'step a': [3.0, 3.5]}, above_a_bound={})
    tight = compared(capsys, base, high, '--seconds', '0.25', '--gib', '0.25')
    assert tight['thresholds'] == dict(seconds=0.25, gib=0.25)
    assert tight['moved'] == {'step a': dict(pool_peak_gb=[3.0, 3.5]), 'query q1': dict(seconds=[1.1, 1.4])}
    assert step_memory.main(['--compare', base, high]) == 0
    assert "pool peak (pass: none in B above A's): B above A on step a (3.00 -> 3.50 GiB)" in capsys.readouterr().out
    # A statement run twice is two statements, so the second is not folded into the first.
    twice = measured(tmp_path, capsys, 'twice', [*EVENTS, statement('a', 7.7, 8.0, before=2, after=2)])
    assert compared(capsys, base, twice)['only_in'] == dict(a=[], b=['step a #2'])


def test_compare_refuses_what_is_not_a_result_of_this_script(tmp_path, capsys):
    good = measured(tmp_path, capsys, 'good', EVENTS)
    older = tmp_path / 'older.json'
    value = json.loads(Path(good).read_text())
    for row in value['statements']:
        del row['storage']  # a result written before the comparison existed
    older.write_text(json.dumps(value))
    (tmp_path / 'text.json').write_text('alignment: exact\n')
    (tmp_path / 'list.json').write_text('[1, 2]\n')
    assert 'older.json' in refusal(capsys, '--compare', good, str(older))
    assert 'text.json' in refusal(capsys, '--compare', str(tmp_path / 'text.json'), good)
    assert 'list.json' in refusal(capsys, '--compare', good, str(tmp_path / 'list.json'))
    assert 'missing.json' in refusal(capsys, '--compare', good, str(tmp_path / 'missing.json'))
    assert '--compare' in refusal(capsys, *write(tmp_path), '--compare', good, good)
    assert 'step log' in refusal(capsys)


COPY, DEDUP = ('src/storage/batch/views.rs', 148), ('src/storage/batch/views.rs', 104)


def admission(available, size=1 << 20, site=('src/job/export.rs', 234)):
    """A shared admission request as tracing_subscriber::fmt writes it to a file, ANSI colours and all."""
    fields = ' '.join(f'\x1b[3m{key}\x1b[0m\x1b[2m=\x1b[0m{value}' for key, value in (
        ('bytes', size), ('available', int(available * GIB)), ('native_reserved', 0), ('file', f'"{site[0]}"'),
        ('line', site[1])))
    return (f'\x1b[2m2026-11-11T00:00:00.000001Z\x1b[0m \x1b[34mDEBUG\x1b[0m \x1b[2mdocspec::budget\x1b[0m\x1b[2m:\x1b[0m '
            f'shared admission request {fields}\n')


REFUSAL = ('2026-11-11T00:00:00.000002Z DEBUG docspec::budget::view_compaction: retained compaction refused; views passed '
           'on uncompacted rows=8192 error=capacity: shared memory budget exhausted: requested 9 bytes, available 1\n')


def metric(event):
    return f'[docspec-metric] {json.dumps(event)}\n'


SHORT, A, RETAIN, BLIP, BIG, Q1 = EVENTS
DEBUG = ''.join([
    admission(10),  # before the first statement (input registration): the first statement's
    metric(SHORT),
    # The same request as admission(8, size=GIB), message last and inside a span with a field named like one of its own.
    '2026-11-11T00:00:00Z DEBUG reserve{line=1}: docspec::budget: bytes=1073741824 available=8589934592 native_reserved=0 '
    'file="src/job/export.rs" line=234 shared admission request\n',
    admission(6, size=5 * GIB), admission(3, size=0),  # left after the second: 1 GiB
    admission(5, site=DEDUP), admission(4, site=COPY), admission(4.5, site=COPY),
    metric(A), metric(RETAIN),
    admission(2), REFUSAL,  # after a's event: the next statement's, blip
    metric(BLIP),
    REFUSAL, 'archive_watchdog: a line from another process\n',
    '2026-11-11T00:00:00Z DEBUG docspec::budget: shared admission request bytes=5 file="src/job/export.rs" line=234\n',
    metric(BIG), metric(Q1),  # q1 has no debug line at all
    admission(1), REFUSAL, admission(7, site=('src/storage/batch/views.rs', 999)),  # after the last statement
])


def test_a_debug_line_counts_for_the_next_statement_in_its_stream(tmp_path, capsys):
    paths = write(tmp_path)
    (tmp_path / 'engine.log').write_text(DEBUG)
    result, rows = report(capsys, *paths, '--debug-log', str(tmp_path / 'engine.log'))
    figures = {name: (row['shared_requests'], row['shared_floor_gb'], row['view_copies'], row['refusal_lines'])
               for name, row in rows.items()}
    # The floor is the lowest `available` a request saw before its own acquisition: 3 GiB in `a`, never 6 - 5.
    assert figures == {'short': (1, 10.0, 0, 0), 'a': (6, 3.0, 2, 0), 'blip': (1, 2.0, 0, 1), 'big.parquet': (0, None, 0, 1),
                       'q1': (0, None, 0, 0)}
    assert result['debug'] == dict(log=str(tmp_path / 'engine.log'), statements=5, requests=8, unreadable_lines=1,
        unknown_view_lines=[999], after_last=dict(shared_requests=2, shared_floor_gb=1.0, view_copies=0, refusal_lines=1))
    assert step_memory.main([*paths, '--debug-log', str(tmp_path / 'engine.log'), '--top', '2']) == 0
    text = capsys.readouterr().out
    assert 'lowest available before its own acquisition: 2.00 GiB, in step blip' in text
    assert 'a debug line counts for the next statement event after it in the same file' in text
    assert 'after the last statement: 2 requests (lowest 1.00 GiB), 0 view copies, 1 refusal lines' in text
    assert 'src/storage/batch/views.rs lines this script does not know: 999' in text
    assert 'compaction counts: not logged by this binary' in text
    floors = text.split('lowest shared floor')[1].splitlines()[2:4]
    assert [line.split() for line in floors] == [['2.00', '1', '0', '1', 'step', 'blip'], ['3.00', '6', '2', '0', 'step', 'a']]


def test_a_debug_log_from_another_run_or_none_at_all_is_refused(tmp_path, capsys):
    paths = write(tmp_path)
    moved = ''.join(metric({**event, 'start_epoch': event['start_epoch'] + 1}) if 'start_epoch' in event else metric(event)
                    for event in EVENTS)
    (tmp_path / 'other.log').write_text(moved)
    assert 'not from this run' in refusal(capsys, *paths, '--debug-log', str(tmp_path / 'other.log'))
    assert 'absent.log' in refusal(capsys, *paths, '--debug-log', str(tmp_path / 'absent.log'))


def test_two_runs_compare_their_shared_floors_when_both_read_a_debug_log(tmp_path, capsys):
    (tmp_path / 'one.log').write_text(DEBUG)
    (tmp_path / 'two.log').write_text(DEBUG.replace(admission(3, size=0), admission(0.25, size=0)))
    one = measured(tmp_path, capsys, 'one', EVENTS, None, '--debug-log', str(tmp_path / 'one.log'))
    two = measured(tmp_path, capsys, 'two', EVENTS, None, '--debug-log', str(tmp_path / 'two.log'))
    result = compared(capsys, one, two)
    assert result['moved'] == {'step a': dict(shared_floor_gb=[3.0, 0.25])}
    assert result['counts']['refusal_lines'] == dict(a=dict(logged=5, statements={'step blip': 1, 'output big.parquet': 1}),
                                                     b=dict(logged=5, statements={'step blip': 1, 'output big.parquet': 1}))


JOB = """import json, sys, time
def statement(name, megabytes):
    start = time.time()
    held = bytearray(megabytes * 1024 * 1024)
    for index in range(0, len(held), 4096):
        held[index] = 1
    time.sleep(1)
    del held
    print('[docspec-metric] ' + json.dumps(dict(event='step', name=name, storage='memory', start_epoch=start,
        end_epoch=time.time(), pool_reserved_before=0, pool_reserved_after=0)), file=sys.stderr, flush=True)
time.sleep(0.5)
for name, megabytes in (('small', 20), ('medium', 150), ('large', 400)):
    statement(name, megabytes)
time.sleep(0.3)
"""


def test_a_real_jobs_allocation_lands_in_the_statement_that_made_it(tmp_path, capsys, monkeypatch):
    """The whole seam: the watchdog's clock against epochs a job stamps on its own stderr, with no offset given."""
    monkeypatch.setenv('ARCHIVE_WATCHDOG_STATE', str(tmp_path / 'state'))
    ran = subprocess.run([sys.executable, str(PATH.parents[1] / 'archive_watchdog.py'), '--rss-gb', '4', '--min-disk-gb', '0',
        '--min-available-gb', '0', '--interval', '0.1', '--report', str(tmp_path / 'report.json'), '--timeline', '--',
        sys.executable, '-c', JOB], capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0, ran.stderr
    (tmp_path / 'engine.log').write_text(ran.stderr)
    result, rows = report(capsys, str(tmp_path / 'engine.log'), str(tmp_path / 'report.timeline.jsonl'))
    assert result['alignment'] == 'epoch' and not result['unattributed']
    # No claim about which statement holds the run's single highest reading: the last reading of `large` can
    # straddle its end, and freed memory stays in the footprint.
    assert rows['small']['peak_physical_gb'] < 0.12 < rows['medium']['peak_physical_gb'] < rows['large']['peak_physical_gb'] - 0.2
    assert rows['medium']['rise_gb'] > 0.1 and rows['large']['rise_gb'] > 0.15
    assert result['run_peak']['peak_physical_gb'] == json.loads((tmp_path / 'report.json').read_text())['peak_physical_gb']
