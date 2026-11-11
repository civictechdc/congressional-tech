#!/usr/bin/env python3
"""Real memory per engine statement: join a watchdog timeline to the engine's step log, and compare two runs.

The engine's pool figures are a ledger of charges, not memory: one build peaked at
10.28 GiB physical while exporting a 15 MiB file with 2.81 GiB in the pool. The
watchdog samples the real process tree, so this gives each sample to the statement
(step, query or output) running when it was taken, and prints the run's peak, the
statement its highest reading fell in, and the figure to pass as --expect-gb next time.

    python3 scripts/measure/step_memory.py <step log> <report>.timeline.jsonl [--debug-log <stderr>] [--top 20] [--json]
    python3 scripts/measure/step_memory.py --compare <run A>.json <run B>.json [--seconds 1] [--gib 0.5] [--json]

The step log is the file DOCSPEC_STEP_LOG names, or any log holding the engine's
`[docspec-metric] {json}` stderr lines. A timeline whose samples carry `epoch` and
`read_seconds` joins exactly: both sides record the same wall clock, and a sample
counts for a statement only when the statement spans the whole reading (one takes about
0.07 s, longer than many statements). An older timeline has only seconds since the
watchdog started, so the caller must give --offset-seconds, the timeline second at
which the first statement starts. That is read by eye and a few tenths of a second
uncertain, so statements under a second are then not attributed and every
per-statement figure moves with the offset: on build c03c43da, offsets from 5.3 to
6.5 s gave 4 to 6 statements over 8 GiB lasting 32.9 to 39.2 s. The run peak and the
--expect-gb come from the timeline alone and do not move.

Each statement also carries what its event logs: storage, `pool_reserved_peak`, and the
memory fix's `compaction_copied_batches` and `compaction_refused_copies`. The pinned
binary (b0342a7) writes none of those three, and no output event carries them, so they
are None there: "not logged", never 0.

--compare reads two results written with --json and lists, statement by statement, what
moved: seconds by more than --seconds, peak physical footprint, its rise, pool peak and
shared floor by more than --gib, storage and the counts on any change. A figure one run lacks
is not compared; statements in one run only are listed. Its pass lines are the next
pin's qualification (ct-x00f): refused copies 0 on every statement, and no statement's
pool peak in B above A's. Where A logs no pool peak, B is judged against the larger of
A's pool before and after, which A's peak is at least: above it is undetermined.

--debug-log reads the engine's stderr from a run with
RUST_LOG=docspec=info,docspec::budget=debug and gives each statement its shared-budget
admission requests, the lowest `available` they saw, the view copies among them, and
its "retained compaction refused" lines. The value logged is what was available BEFORE
that request's own acquisition, so nothing "after" is computed from it. A view copy is
one column copied, not comparable to the engine's copied batches. A debug line counts
for the next statement event after it in the same file, so no clock is needed. That
cannot see work outside statements (input registration before the first, releases after
an event: it lands on the next statement), memory a statement uses after its last
request, or lines another process wrote to the file; lines after the last statement
event are counted apart.

What this cannot see. A statement that spans no whole reading is unattributed, never
given a neighbour's figure. A peak between two readings is missed; sample faster with
the watchdog's --interval. The statement the highest reading fell in need not have set
it: a footprint the allocator has not returned still counts in later statements, so
read the rise beside the peak. The samples cover the watchdog's whole process tree, so
a Python parent's memory is in every figure. Standard library only, like the watchdog.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import json
import math
import re
from statistics import median

METRIC = '[docspec-metric] '
GIB = 2**30
# Long enough to place with an offset read by eye, and to have a starting footprint worth summarising.
LONG_SECONDS = 1.0
NO_SAMPLE = 'no sample in its window'
EXACT = ('epoch', 'read_seconds')
SAMPLE = ('seconds', 'rss_gb', 'physical_gb')
SHORT_FOR_OFFSET = 'under 1 s with a hand-given offset'
# epoch minus seconds is the watchdog's start: within one run it moves only by rounding (4 ms over the 778 s of
# build3-control), so more than this means two runs in one file.
ONE_RUN_SECONDS = 1.0
# The engine's debug lines as tracing_subscriber::fmt() writes them to stderr (src/main.rs:537), ANSI colours included.
# The format is the engine's and can move; read it with `git show <commit>:<file>` in docspec-rs:
#   b0342a7 (the pin) src/budget.rs:236-242 and ec24d1f src/budget.rs:256-262, in Budget::reserve:
#     tracing::debug!(bytes, available, native_reserved, file, line, "shared admission request"), with `available`
#     read before try_acquire_many_owned, and `file` and `line` the caller's (#[track_caller]).
#   ec24d1f src/budget/view_compaction.rs:258-261: "retained compaction refused; views passed on uncompacted". The pin
#     has no such line: there a refused view copy fails the statement.
ADMISSION = 'shared admission request'
REFUSED = 'retained compaction refused'
ANSI = re.compile(r'\x1b\[[0-9;]*m')
FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
# compact_views' two reserves by caller line: the dedup table charged before deciding whether a column is worth
# copying, then the copy. Every edit of views.rs moves them, so a views.rs line not here is reported, not guessed at.
VIEWS = 'src/storage/batch/views.rs'
VIEW_RESERVES = {104: 'dedup', 148: 'copy',  # b0342a7
                 162: 'dedup', 206: 'copy',  # ec24d1f, 1718b49
                 165: 'dedup', 209: 'copy'}  # dx/one-line 562ad6a
# Compared with a threshold (seconds, or GiB for the rest), then on any change; a statement's other figures are context.
# A peak that moved without its rise is the footprint carried in from earlier statements (on build3, start and peak
# moved on the same 94 statements, the rise on 30).
MOVED = {'seconds': ('seconds', '.1f', ''), 'peak_physical_gb': ('peak physical', '.2f', ' GiB'),
         'rise_gb': ('rise', '+.2f', ' GiB'), 'pool_peak_gb': ('pool peak', '.2f', ' GiB'),
         'shared_floor_gb': ('shared floor', '.2f', ' GiB'),
         'storage': ('storage', '', ''), 'copied_batches': ('copied batches', 'd', ''),
         'refused_copies': ('refused copies', 'd', ''), 'view_copies': ('view copies', 'd', ''),
         'refusal_lines': ('refusal lines', 'd', '')}
THRESHOLD = {'seconds': 'seconds', 'peak_physical_gb': 'gib', 'rise_gb': 'gib', 'pool_peak_gb': 'gib', 'shared_floor_gb': 'gib'}
COUNTS = ('copied_batches', 'refused_copies', 'view_copies', 'refusal_lines')
FROM_DEBUG = ('shared_requests', 'shared_floor_gb', 'view_copies', 'refusal_lines')
COMPARED = {'kind', 'name', 'pool_before_gb', 'pool_after_gb', *MOVED}  # the row fields --compare reads


class Refused(ValueError):
    """These inputs cannot be joined without a guess."""


def _event(line):
    """The engine event a step-log or `[docspec-metric] ` line holds, False if it does not parse, None for other lines."""
    before, marker, after = line.partition(METRIC)
    text = (after if marker else before).strip()
    if not (marker or text.startswith('{')):
        return None
    try:
        event = json.loads(text)
    except ValueError:
        return False
    return event if isinstance(event, dict) else False


def _statement(event):
    """A step, query or output: the events with a start and an end."""
    return _number(event.get('start_epoch')) and _number(event.get('end_epoch'))


def _identity(event):
    return event.get('event'), event.get('name'), event['start_epoch']


def read_events(path):
    """Engine events from a step log or from `[docspec-metric] ` log lines, and how many such lines were unreadable."""
    events, unreadable = [], 0
    with open(path, errors='replace') as stream:
        for line in stream:
            event = _event(line)
            if event is False:
                unreadable += 1
            elif event is not None:
                events.append(event)
    return events, unreadable


def _tally():
    return dict(requests=0, floor=None, view_copies=0, refusal_lines=0)


def read_debug_log(path):
    """Shared-budget figures per statement from the engine's stderr, each debug line counted for the next statement
    event after it in the same stream; the figures after the last one; unreadable lines; unknown views.rs lines."""
    statements, tally, unreadable, unknown = {}, _tally(), 0, set()
    with open(path, errors='replace') as stream:
        for line in stream:
            event = _event(line)
            if event is False:
                unreadable += 1
            elif event is not None:
                if _statement(event):
                    statements[_identity(event)], tally = tally, _tally()
                continue
            text = ANSI.sub('', line)
            if REFUSED in text:
                tally['refusal_lines'] += 1
            elif ADMISSION in text:
                fields = dict(FIELD.findall(text))  # the event's own fields come last, after any span's
                try:
                    available, site, number = int(fields['available']), fields['file'].strip('"'), int(fields['line'])
                except (KeyError, ValueError):
                    unreadable += 1
                    continue
                tally['requests'] += 1
                # What was available BEFORE this request's acquisition: the lowest of these is the floor, as logged.
                tally['floor'] = available if tally['floor'] is None else min(tally['floor'], available)
                if site.endswith(VIEWS):
                    role = VIEW_RESERVES.get(number)
                    tally['view_copies'] += role == 'copy'
                    if role is None:
                        unknown.add(number)
    return dict(statements=statements, after_last=tally, unreadable_lines=unreadable, unknown_view_lines=sorted(unknown))


def _shared(tally):
    """A statement's debug-log figures; all None when no debug log was read."""
    if tally is None:
        return dict.fromkeys(FROM_DEBUG)
    return dict(shared_requests=tally['requests'], shared_floor_gb=_gib(tally, 'floor'), view_copies=tally['view_copies'],
                refusal_lines=tally['refusal_lines'])


def read_result(path):
    """A result this script wrote with --json, refused if it lacks what a comparison reads."""
    with open(path, errors='replace') as stream:
        try:
            value = json.load(stream)
        except ValueError:
            raise Refused(f'{path} is not JSON: give a result step_memory.py wrote with --json') from None
    rows = value.get('statements') if isinstance(value, dict) else None
    if not (isinstance(rows, list) and isinstance(value.get('run_peak'), dict)
            and all(isinstance(row, dict) and COMPARED <= row.keys() for row in rows)):
        raise Refused(f'{path} is not a result of this step_memory.py --json (an older one lacks storage and the '
                      'compaction counts): measure that run again')
    return value


def read_timeline(path):
    """Watchdog samples; how many were dropped as failed readings, which it writes as zeros; and whether the last
    line was cut off, as it is while the watchdog is still writing. Any other unreadable line is refused."""
    with open(path, errors='replace') as stream:
        lines = [line for line in stream if line.strip()]
    rows, torn = [], False
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
            whole = all(_number(row[key]) for key in SAMPLE) and all(_number(row[key]) for key in EXACT if key in row)
        except (ValueError, KeyError, TypeError):
            whole = False
        if whole:
            rows.append(row)
        elif number == len(lines):
            torn = True
        else:
            raise Refused(f'timeline line {number} of {len(lines)} is not a watchdog sample')
    samples = [row for row in rows if row['rss_gb'] or row['physical_gb']]
    return samples, len(rows) - len(samples), torn


def _number(value):
    return isinstance(value, (int, float))


def _gib(event, key):
    return round(event[key] / GIB, 3) if _number(event.get(key)) else None


def _median(values):
    present = [value for value in values if value is not None]
    return round(median(present), 3) if present else None


def _count(event, key):
    return event[key] if _number(event.get(key)) else None


def measure(events, samples, offset_seconds=None, debug=None):
    """Give each sample to the statements whose window holds it; refuse rather than align by guess. `debug` is
    read_debug_log's statements, which must be this step log's."""
    spans = sorted((event for event in events if _statement(event)), key=lambda event: event['start_epoch'])
    for event in spans:
        if not (isinstance(event.get('name'), str) and isinstance(event.get('event'), str)):
            raise Refused(f'a statement in the step log has no name or no event kind: {json.dumps(event)[:160]}')
    if not spans or not samples:
        raise Refused('the timeline has no samples' if spans else 'the step log has no step or output events')
    exact = all(key in sample for sample in samples for key in EXACT)
    if exact and offset_seconds is not None:
        raise Refused('this timeline carries epoch, which joins exactly; drop --offset-seconds')
    if not exact and offset_seconds is None:
        raise Refused('this timeline has no epoch and read_seconds (an older watchdog wrote it), so the join needs '
                      '--offset-seconds: the timeline second at which the first statement starts. Statements under 1 s '
                      'are then not attributed')
    if exact:
        starts = [sample['epoch'] - sample['seconds'] for sample in samples]
        if max(starts) - min(starts) > ONE_RUN_SECONDS:
            raise Refused(f'the timeline holds more than one run: its watchdog start (epoch minus seconds) moves by '
                          f'{max(starts) - min(starts):.1f} s; give one run\'s timeline')
    clock = 'epoch' if exact else 'seconds'
    shift = 0.0 if exact else offset_seconds - spans[0]['start_epoch']
    unmatched, missing = dict(debug or {}), 0
    samples = sorted(samples, key=lambda sample: sample[clock])
    # A reading ends at its stamp. Readings never overlap, so their starts are in the same order as their ends.
    ends = [sample[clock] for sample in samples]
    begins = [sample['epoch'] - sample['read_seconds'] for sample in samples] if exact else ends
    highest = max(range(len(samples)), key=lambda index: samples[index]['physical_gb'])
    rows, during, overlaps = [], [], []
    for event in spans:
        start, end = event['start_epoch'] + shift, event['end_epoch'] + shift
        first, last = bisect_left(begins, start), bisect_right(ends, end)
        window = samples[first:last]
        earlier = bisect_right(ends, start)  # the last reading that finished by the start is the starting footprint
        query = event.get('storage') == 'query'  # the engine logs a query as a step named query:<name>
        tally = unmatched.pop(_identity(event), None)
        missing += debug is not None and tally is None
        row = dict(kind='query' if query else event['event'], name=event['name'].removeprefix('query:') if query else event['name'],
                   storage=event.get('storage'), seconds=round(event['end_epoch'] - event['start_epoch'], 3),
                   samples=len(window), unattributed=None,
                   peak_physical_gb=None, peak_rss_gb=None, start_physical_gb=None, rise_gb=None,
                   pool_before_gb=_gib(event, 'pool_reserved_before'), pool_after_gb=_gib(event, 'pool_reserved_after'),
                   pool_peak_gb=_gib(event, 'pool_reserved_peak'), copied_batches=_count(event, 'compaction_copied_batches'),
                   refused_copies=_count(event, 'compaction_refused_copies'), **_shared(tally))
        rows.append(row)
        if not exact and row['seconds'] < LONG_SECONDS:
            row['unattributed'] = SHORT_FOR_OFFSET
        elif not window:
            row['unattributed'] = NO_SAMPLE
        else:
            row.update(peak_physical_gb=max(sample['physical_gb'] for sample in window),
                       peak_rss_gb=max(sample['rss_gb'] for sample in window))
            if earlier:
                row['start_physical_gb'] = samples[earlier - 1]['physical_gb']
                row['rise_gb'] = round(row['peak_physical_gb'] - row['start_physical_gb'], 3)
        # The highest reading fell in a statement that spans all of it; one that only touches it is named apart.
        held = dict(kind=row['kind'], name=row['name'], pool_before_gb=row['pool_before_gb'])
        if first <= highest < last and not row['unattributed']:
            during.append(held)
        elif start <= ends[highest] and begins[highest] <= end:
            overlaps.append(held)
    if missing or unmatched:
        raise Refused(f'the debug log is not from this run: {missing} statements of the step log are not in it, and '
                      f'{len(unmatched)} of its statements are not in the step log')
    interval = _median(later - sooner for sooner, later in zip(ends, ends[1:]))
    if all(row['unattributed'] for row in rows):
        raise Refused('no statement has a sample in its window: these two files are not from the same run'
                      + (f', or every statement is shorter than the {interval} s between samples' if exact
                         else ', or the offset is wrong'))
    long = [row for row in rows if row['start_physical_gb'] is not None and row['seconds'] >= LONG_SECONDS]
    peak_physical, peak_rss = samples[highest]['physical_gb'], max(sample['rss_gb'] for sample in samples)
    return dict(
        alignment=clock if exact else 'offset', offset_seconds=offset_seconds, samples=len(samples), interval_seconds=interval,
        run_peak=dict(peak_physical_gb=peak_physical, peak_rss_gb=peak_rss, seconds=samples[highest]['seconds'],
                      during=during, overlaps=overlaps),
        # The watchdog admits on, and stops at, the larger of the two; its samples are in thousandths.
        expect_gb=math.ceil(round(max(peak_physical, peak_rss) * 1000) / 100) / 10,
        long_statements=dict(count=len(long), median_start_physical_gb=_median(row['start_physical_gb'] for row in long),
                             median_pool_before_gb=_median(row['pool_before_gb'] for row in long)),
        unattributed=dict(Counter(row['unattributed'] for row in rows if row['unattributed'])), statements=rows)


def _keyed(result):
    """Statements by label in run order; a name run twice is `<label> #2`, so no statement is folded into another."""
    seen, keyed = Counter(), {}
    for row in result['statements']:
        label = f'{row["kind"]} {row["name"]}'
        seen[label] += 1
        keyed[label if seen[label] == 1 else f'{label} #{seen[label]}'] = row
    return keyed


def _logged(rows, field):
    """How many statements log a count, and those where it is not 0; None when none logs it."""
    logged = {label: row[field] for label, row in rows.items() if row[field] is not None}
    return dict(logged=len(logged), statements={label: count for label, count in logged.items() if count}) if logged else None


def compare(run_a, run_b, *, seconds, gib):
    """Two (path, result) runs statement by statement: what moved past a threshold, what one run lacks, the pass lines."""
    (path_a, a), (path_b, b) = run_a, run_b
    rows_a, rows_b = _keyed(a), _keyed(b)
    both = [label for label in rows_a if label in rows_b]
    limit = dict(seconds=seconds, gib=gib)
    moved, pool, compared_memory = {}, dict(judged=0, against_a_bound=0, above={}, above_a_bound={}), 0
    for label in both:
        x, y = rows_a[label], rows_b[label]
        changes = {}
        for field in MOVED:
            before, after = x[field], y[field]
            if before is None or after is None:
                continue  # a figure one run lacks is not compared
            if abs(after - before) > limit[THRESHOLD[field]] if field in THRESHOLD else before != after:
                changes[field] = [before, after]
        if changes:
            moved[label] = changes
        compared_memory += x['peak_physical_gb'] is not None and y['peak_physical_gb'] is not None
        if y['pool_peak_gb'] is None:
            continue
        if x['pool_peak_gb'] is not None:
            pool['judged'] += 1
            if y['pool_peak_gb'] > x['pool_peak_gb']:
                pool['above'][label] = [x['pool_peak_gb'], y['pool_peak_gb']]
        elif x['pool_before_gb'] is not None and x['pool_after_gb'] is not None:
            # A logs no peak, but its peak is at least its pool at the start and at the end.
            pool['judged'] += 1
            pool['against_a_bound'] += 1
            bound = max(x['pool_before_gb'], x['pool_after_gb'])
            if y['pool_peak_gb'] > bound:
                pool['above_a_bound'][label] = [bound, y['pool_peak_gb']]

    def run(path, result, rows):
        return dict(result=path, statements=len(rows), seconds=round(sum(row['seconds'] for row in rows.values()), 3),
                    peak_physical_gb=result['run_peak']['peak_physical_gb'], peak_rss_gb=result['run_peak']['peak_rss_gb'],
                    debug_log=(result.get('debug') or {}).get('log'))
    only_b = [label for label in rows_b if label not in rows_a]
    return dict(
        runs=dict(a=run(path_a, a, rows_a), b=run(path_b, b, rows_b)), thresholds=limit,
        counts={field: dict(a=_logged(rows_a, field), b=_logged(rows_b, field)) for field in COUNTS}, pool_peak=pool,
        memory_compared=compared_memory, only_in=dict(a=[label for label in rows_a if label not in rows_b], b=only_b),
        moved=moved,
        statements=[dict(statement=label, a=rows_a.get(label), b=rows_b.get(label)) for label in [*rows_a, *only_b]])


def _pairs(values):
    return ', '.join(f'{label} ({before:.2f} -> {after:.2f} GiB)' for label, (before, after) in values.items())


def render_compare(result):
    """The two runs, the pass lines, what one run lacks, and what moved."""
    runs, counts, pool, limit = result['runs'], result['counts'], result['pool_peak'], result['thresholds']

    def logged(title, field):
        def side(run):
            count = counts[field][run]
            if count is None:
                return 'no debug log read' if field in FROM_DEBUG else 'not logged by this binary'
            found = ', '.join(f'{number} in {label}' for label, number in count['statements'].items()) or '0'
            return f'{found} (logged on {count["logged"]} of {runs[run]["statements"]})'
        return f'{title}: A {side("a")}; B {side("b")}'

    by_a = pool['judged'] - pool['against_a_bound']
    verdict = ([f'B above A on {_pairs(pool["above"])}' if pool['above'] else f'none above A on the {by_a} statements both log']
               if by_a else [])
    if pool['against_a_bound']:
        verdict.append(f'on {pool["against_a_bound"]} statements A logs no pool peak, but its peak is at least the larger of '
                       f'its pool before and after: B at or below that on {pool["against_a_bound"] - len(pool["above_a_bound"])}'
                       + (f'; B above that bound, undetermined: {_pairs(pool["above_a_bound"])}' if pool['above_a_bound'] else ''))
    lines = [f'{run.upper()}: {value["result"]}: {value["statements"]} statements, {value["seconds"]:.1f} s in statements; '
             f'run peak {value["peak_physical_gb"]:.2f} GiB physical, {value["peak_rss_gb"]:.2f} GiB RSS'
             + (f'; debug log {value["debug_log"]}' if value['debug_log'] else '') for run, value in runs.items()]
    lines += [
        f'thresholds: seconds moved by more than {limit["seconds"]:g} s; peak physical, rise, pool peak and shared floor by more '
        f'than {limit["gib"]:g} GiB; storage and counts on any change; a figure one run lacks is not compared',
        logged('refused copies (pass: 0 on every statement)', 'refused_copies'),
        "pool peak (pass: none in B above A's): " + ('; '.join(verdict) or 'not judged: B logs no pool peak on a statement in both'),
        logged('copied batches', 'copied_batches'),
    ]
    if runs['a']['debug_log'] or runs['b']['debug_log']:
        lines += [logged('refusal lines (debug log)', 'refusal_lines'), logged('view copies (debug log)', 'view_copies')]
    both = len(result['statements']) - len(result['only_in']['a']) - len(result['only_in']['b'])
    lines += [f'real memory: peak physical compared on the {result["memory_compared"]} statements attributed in both',
              'in A only: ' + (', '.join(result['only_in']['a']) or 'none'),
              'in B only: ' + (', '.join(result['only_in']['b']) or 'none'),
              '', f'moved: {len(result["moved"])} of {both} statements in both']
    for label, changes in result['moved'].items():
        lines.append(f'  {label}: ' + '; '.join(
            f'{MOVED[field][0]} {before:{MOVED[field][1]}} -> {after:{MOVED[field][1]}}{MOVED[field][2]}'
            for field, (before, after) in changes.items()))
    return '\n'.join(lines)


def _cell(value, spec):
    return format('-' if value is None else format(value, spec), '>7')


def _named(statements):
    return ', '.join(f'{held["kind"]} {held["name"]}'
                     + ('' if held['pool_before_gb'] is None else f' (pool {held["pool_before_gb"]:.2f} GiB)')
                     for held in statements) or 'none'


def render(result, top):
    """The run peak, the figure to start with next time, and the statements with the largest footprints."""
    rows, peak, long = result['statements'], result['run_peak'], result['long_statements']
    ranked = sorted((row for row in rows if not row['unattributed']), key=lambda row: -row['peak_physical_gb'])[:top]
    reasons = '; '.join(f'{count} {reason}' for reason, count in result['unattributed'].items())
    lines = [
        'alignment: exact, on the epoch both files record' if result['alignment'] == 'epoch' else
        f'alignment: the first statement placed by hand at timeline second {result["offset_seconds"]:g}; '
        'statements under 1 s are not attributed; per-statement figures move with that offset; '
        'the run peak and --expect-gb do not',
        f'samples: {result["samples"]}, about every {result["interval_seconds"]} s'
        + (f'; {result["failed_samples"]} failed samples dropped' if result.get('failed_samples') else '')
        + (f'; {result["unreadable_metric_lines"]} metric lines unreadable' if result.get('unreadable_metric_lines') else '')
        + ('; the last timeline line was cut off and skipped, as when the job is still running: figures so far'
           if result.get('torn_last_line') else ''),
        f'run peak: {peak["peak_physical_gb"]:.2f} GiB physical, {peak["peak_rss_gb"]:.2f} GiB RSS; the highest reading'
        + (f' fell in {_named(peak["during"])}' if peak['during'] else
           f', at timeline second {peak["seconds"]:g}, fell in no statement; it overlaps {_named(peak["overlaps"])}'),
        f'next time: --expect-gb {result["expect_gb"]} (this run\'s peak, rounded up to 0.1 GiB)',
        f'{sum(result["unattributed"].values())} of {len(rows)} statements unattributed' + (f': {reasons}' if reasons else ''),
    ]
    if long['count']:
        pool = long['median_pool_before_gb']
        lines.append(f'at the start of the {long["count"]} attributed statements of 1 s or more: median physical '
                     f'{long["median_start_physical_gb"]:.2f} GiB, '
                     + ('no pool figures in the step log' if pool is None else f'median pool {pool:.2f} GiB'))
    counted = [row for row in rows if row['refused_copies'] is not None]
    refused = ', '.join(f'{row["kind"]} {row["name"]} ({row["refused_copies"]})' for row in counted if row['refused_copies'])
    lines.append('compaction counts: not logged by this binary' if not counted else
                 f'compaction counts on {len(counted)} of {len(rows)} statements: '
                 f'{sum(row["copied_batches"] or 0 for row in counted)} copied batches, refused copies in {refused or "none"}')
    debug = result.get('debug')
    if debug:
        floored = sorted((row for row in rows if row['shared_floor_gb'] is not None), key=lambda row: row['shared_floor_gb'])
        after = debug['after_last']
        lines += [
            f'shared budget, from the debug log: {debug["requests"]} admission requests in {debug["statements"]} statements; '
            + (f'lowest available before its own acquisition: {floored[0]["shared_floor_gb"]:.2f} GiB, in '
               f'{floored[0]["kind"]} {floored[0]["name"]}' if floored else 'no statement made one')
            + f'; {sum(row["view_copies"] for row in rows)} view copies; {sum(row["refusal_lines"] for row in rows)} refusal lines',
            f'after the last statement: {after["shared_requests"]} requests'
            + ('' if after['shared_floor_gb'] is None else f' (lowest {after["shared_floor_gb"]:.2f} GiB)')
            + f', {after["view_copies"]} view copies, {after["refusal_lines"]} refusal lines',
            'a debug line counts for the next statement event after it in the same file: work outside statements '
            '(input registration, releases after an event) lands on the next statement; memory used after a '
            "statement's last request, and lines another process wrote, are not seen",
        ]
        if debug['unknown_view_lines']:
            lines.append(f'{VIEWS} lines this script does not know: {", ".join(map(str, debug["unknown_view_lines"]))} '
                         '(another engine revision: add its reserve lines to VIEW_RESERVES; copies there are not counted)')
        if debug['unreadable_lines']:
            lines.append(f'{debug["unreadable_lines"]} debug or metric lines in the debug log unreadable')
        lines += ['', f'lowest shared floor first, top {min(top, len(floored))}, GiB:',
                  ' '.join(format(title, '>7') for title in ('floor', 'requests', 'copies', 'refused')) + '  statement']
        lines += [' '.join(_cell(row[key], spec) for key, spec in (
            ('shared_floor_gb', '.2f'), ('shared_requests', 'd'), ('view_copies', 'd'), ('refusal_lines', 'd')))
            + f'  {row["kind"]} {row["name"]}' for row in floored[:top]]
    lines += ['', f'top {len(ranked)} by peak physical footprint, GiB:',
              ' '.join(format(title, '>7') for title in ('peak', 'rise', 'rss', 'pool', 'after', 'poolmax', 'seconds'))
              + '  statement']
    for row in ranked:
        lines.append(' '.join(_cell(row[key], spec) for key, spec in (
            ('peak_physical_gb', '.2f'), ('rise_gb', '+.2f'), ('peak_rss_gb', '.2f'), ('pool_before_gb', '.2f'),
            ('pool_after_gb', '.2f'), ('pool_peak_gb', '.2f'), ('seconds', '.1f'))) + f'  {row["kind"]} {row["name"]}')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step_log', nargs='?', help='DOCSPEC_STEP_LOG file, or a log with [docspec-metric] lines')
    parser.add_argument('timeline', nargs='?', help='The <report>.timeline.jsonl the watchdog wrote with --timeline')
    parser.add_argument('--debug-log', help='The engine stderr of the same run, with RUST_LOG=docspec=info,docspec::budget=debug')
    parser.add_argument('--compare', nargs=2, metavar=('A', 'B'),
                        help='Instead: two results written with --json, compared statement by statement, B against A')
    parser.add_argument('--seconds', type=float, default=1.0, help='--compare: seconds moved by more than this (default 1)')
    parser.add_argument('--gib', type=float, default=0.5,
                        help='--compare: peak physical, rise, pool peak and shared floor moved by more than this (default 0.5)')
    # Transitional: delete this option, the offset path in measure() and SHORT_FOR_OFFSET once timelines with
    # epoch exist for the builds people measure. Until then older timelines are the only evidence there is.
    parser.add_argument('--offset-seconds', type=float,
                        help='Only for a timeline without epoch (transitional, until every measured build has one): '
                             'the timeline second at which the first statement starts')
    parser.add_argument('--top', type=int, default=20, help='Statements to list, largest footprint first')
    parser.add_argument('--json', action='store_true', help='Every statement and the summary as JSON')
    args = parser.parse_args(argv)
    if args.compare and (args.step_log or args.debug_log or args.offset_seconds is not None):
        parser.error('--compare takes two results and no step log, timeline, --debug-log or --offset-seconds')
    if not (args.compare or args.timeline):
        parser.error('give a step log and a timeline, or --compare and two results')
    try:
        if args.compare:
            result = compare(*((path, read_result(path)) for path in args.compare), seconds=args.seconds, gib=args.gib)
        else:
            events, unreadable = read_events(args.step_log)
            samples, failed, torn = read_timeline(args.timeline)
            debug = read_debug_log(args.debug_log) if args.debug_log else None
            result = dict(measure(events, samples, args.offset_seconds, debug and debug['statements']),
                          failed_samples=failed, torn_last_line=torn, unreadable_metric_lines=unreadable,
                          debug=debug and dict(log=args.debug_log, statements=len(debug['statements']),
                                               requests=sum(tally['requests'] for tally in debug['statements'].values()),
                                               unreadable_lines=debug['unreadable_lines'],
                                               unknown_view_lines=debug['unknown_view_lines'],
                                               after_last=_shared(debug['after_last'])))
    except (Refused, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=1) if args.json else
          render_compare(result) if args.compare else render(result, args.top))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
