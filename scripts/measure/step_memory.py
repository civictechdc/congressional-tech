#!/usr/bin/env python3
"""Real memory per engine statement: join a watchdog timeline to the engine's step log.

The engine's pool figures are a ledger of charges, not memory: one build peaked at
10.28 GiB physical while exporting a 15 MiB file with 2.81 GiB in the pool. The
watchdog samples the real process tree, so this gives each sample to the statement
(step, query or output) running when it was taken, and prints the run's peak, the
statement its highest reading fell in, and the figure to pass as --expect-gb next time.

    python3 scripts/measure/step_memory.py <step log> <report>.timeline.jsonl [--top 20] [--json]

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
from statistics import median

METRIC = '[docspec-metric] '
GIB = 2**30
# Long enough to place with an offset read by eye, and to have a starting footprint worth summarising.
LONG_SECONDS = 1.0
NO_SAMPLE = 'no sample in its window'
EXACT = ('epoch', 'read_seconds')
SAMPLE = ('seconds', 'rss_gb', 'physical_gb')
SHORT_FOR_OFFSET = 'under 1 s with a hand-given offset'


class Refused(ValueError):
    """These inputs cannot be joined without a guess."""


def read_events(path):
    """Engine events from a step log or from `[docspec-metric] ` log lines, and how many such lines were unreadable."""
    events, unreadable = [], 0
    with open(path, errors='replace') as stream:
        for line in stream:
            before, marker, after = line.partition(METRIC)
            text = (after if marker else before).strip()
            if not (marker or text.startswith('{')):
                continue
            try:
                event = json.loads(text)
            except ValueError:
                event = None
            if isinstance(event, dict):
                events.append(event)
            else:
                unreadable += 1
    return events, unreadable


def read_timeline(path):
    """Watchdog samples; how many were dropped as failed readings, which it writes as zeros; and whether the last
    line was cut off, as it is while the watchdog is still writing. Any other unreadable line is refused."""
    with open(path, errors='replace') as stream:
        lines = [line for line in stream if line.strip()]
    rows, torn = [], False
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
            whole = all(_number(row[key]) for key in SAMPLE)
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


def measure(events, samples, offset_seconds=None):
    """Give each sample to the statements whose window holds it; refuse rather than align by guess."""
    spans = sorted((event for event in events if _number(event.get('start_epoch')) and _number(event.get('end_epoch'))),
                   key=lambda event: event['start_epoch'])
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
    clock = 'epoch' if exact else 'seconds'
    shift = 0.0 if exact else offset_seconds - spans[0]['start_epoch']
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
        row = dict(kind='query' if query else event['event'], name=event['name'].removeprefix('query:') if query else event['name'],
                   seconds=round(event['end_epoch'] - event['start_epoch'], 3), samples=len(window), unattributed=None,
                   peak_physical_gb=None, peak_rss_gb=None, start_physical_gb=None, rise_gb=None,
                   pool_before_gb=_gib(event, 'pool_reserved_before'), pool_after_gb=_gib(event, 'pool_reserved_after'),
                   pool_peak_gb=_gib(event, 'pool_reserved_peak'))
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
    parser.add_argument('step_log', help='DOCSPEC_STEP_LOG file, or a log with [docspec-metric] lines')
    parser.add_argument('timeline', help='The <report>.timeline.jsonl the watchdog wrote with --timeline')
    # Transitional: delete this option, the offset path in measure() and SHORT_FOR_OFFSET once timelines with
    # epoch exist for the builds people measure. Until then older timelines are the only evidence there is.
    parser.add_argument('--offset-seconds', type=float,
                        help='Only for a timeline without epoch (transitional, until every measured build has one): '
                             'the timeline second at which the first statement starts')
    parser.add_argument('--top', type=int, default=20, help='Statements to list, largest footprint first')
    parser.add_argument('--json', action='store_true', help='Every statement and the summary as JSON')
    args = parser.parse_args(argv)
    try:
        events, unreadable = read_events(args.step_log)
        samples, failed, torn = read_timeline(args.timeline)
        result = dict(measure(events, samples, args.offset_seconds), failed_samples=failed, torn_last_line=torn,
                      unreadable_metric_lines=unreadable)
    except (Refused, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=1) if args.json else render(result, args.top))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
