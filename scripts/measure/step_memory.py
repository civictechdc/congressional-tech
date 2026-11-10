#!/usr/bin/env python3
"""Real memory per engine statement: join a watchdog timeline to the engine's step log.

The engine's pool figures are a ledger of charges, not memory: one build peaked at
10.28 GiB physical while exporting a 15 MiB file with 2.81 GiB in the pool. The
watchdog samples the real process tree, so this gives each sample to the statement
(step, query or output) running when it was taken, and prints the peak to pass as
--expect-gb next time.

    python3 scripts/measure/step_memory.py <step log> <report>.timeline.jsonl [--top 20] [--json]

The step log is the file DOCSPEC_STEP_LOG names, or any log holding the engine's
`[docspec-metric] {json}` stderr lines. A timeline whose samples carry `epoch` joins
exactly: both sides record the same wall clock. An older timeline has only seconds
since the watchdog started, so the caller must give --offset-seconds, the timeline
second at which the first statement starts. That is read by eye and a few tenths of a
second uncertain, so statements under a second are then not attributed.

What this cannot see. A statement with no sample inside its window is unattributed,
never given a neighbour's figure. A peak between two samples is missed; sample faster
with the watchdog's --interval. The samples cover the watchdog's whole process tree, so
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
                events.append(json.loads(text))
            except ValueError:
                unreadable += 1
    return events, unreadable


def read_timeline(path):
    """Watchdog samples, and how many were dropped: it writes zeros for a sample that failed."""
    with open(path) as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    samples = [row for row in rows if row['rss_gb'] or row['physical_gb']]
    return samples, len(rows) - len(samples)


def _gib(event, key):
    return round(event[key] / GIB, 3) if key in event else None


def measure(events, samples, offset_seconds=None):
    """Give each sample to the statements whose window holds it; refuse rather than align by guess."""
    spans = sorted((event for event in events if 'start_epoch' in event and 'end_epoch' in event),
                   key=lambda event: event['start_epoch'])
    if not spans or not samples:
        raise Refused('the timeline has no samples' if spans else 'the step log has no step or output events')
    exact = all('epoch' in sample for sample in samples)
    if exact and offset_seconds is not None:
        raise Refused('this timeline carries epoch, which joins exactly; drop --offset-seconds')
    if not exact and offset_seconds is None:
        raise Refused('this timeline has no epoch (an older watchdog wrote it), so the join needs --offset-seconds: the '
                      'timeline second at which the first statement starts. Statements under 1 s are then not attributed')
    clock = 'epoch' if exact else 'seconds'
    shift = 0.0 if exact else offset_seconds - spans[0]['start_epoch']
    samples = sorted(samples, key=lambda sample: sample[clock])
    times = [sample[clock] for sample in samples]
    highest = max(samples, key=lambda sample: sample['physical_gb'])
    rows, during = [], []
    for event in spans:
        start, end = event['start_epoch'] + shift, event['end_epoch'] + shift
        window = samples[bisect_left(times, start):bisect_right(times, end)]
        earlier = bisect_right(times, start)  # the last sample at or before the start is the starting footprint
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
            if start <= highest[clock] <= end:
                during.append(dict(kind=row['kind'], name=row['name'], pool_before_gb=row['pool_before_gb']))
    gaps = [later - sooner for sooner, later in zip(times, times[1:])]
    interval = round(median(gaps), 3) if gaps else None
    if all(row['unattributed'] for row in rows):
        raise Refused('no statement has a sample in its window: these two files are not from the same run'
                      + (f', or every statement is shorter than the {interval} s between samples' if exact
                         else ', or the offset is wrong'))
    long = [row for row in rows if row['start_physical_gb'] is not None and row['seconds'] >= LONG_SECONDS]
    peak_rss = max(sample['rss_gb'] for sample in samples)
    return dict(
        alignment=clock if exact else 'offset', offset_seconds=offset_seconds, samples=len(samples), interval_seconds=interval,
        run_peak=dict(peak_physical_gb=highest['physical_gb'], peak_rss_gb=peak_rss, during=during),
        # The watchdog admits on, and stops at, the larger of the two; its samples are in thousandths.
        expect_gb=math.ceil(round(max(highest['physical_gb'], peak_rss) * 1000) / 100) / 10,
        long_statements=dict(count=len(long),
            median_start_physical_gb=round(median(row['start_physical_gb'] for row in long), 3) if long else None,
            median_pool_before_gb=round(median(row['pool_before_gb'] for row in long), 3) if long else None),
        unattributed=dict(Counter(row['unattributed'] for row in rows if row['unattributed'])), statements=rows)


def _cell(value, spec):
    return format('-' if value is None else format(value, spec), '>7')


def render(result, top):
    """The run peak, the figure to start with next time, and the statements with the largest footprints."""
    rows, peak, long = result['statements'], result['run_peak'], result['long_statements']
    ranked = sorted((row for row in rows if not row['unattributed']), key=lambda row: -row['peak_physical_gb'])[:top]
    during = ', '.join(f'{held["kind"]} {held["name"]} (pool {held["pool_before_gb"]:.2f} GiB)' for held in peak['during'])
    reasons = '; '.join(f'{count} {reason}' for reason, count in result['unattributed'].items())
    lines = [
        'alignment: exact, on the epoch both files record' if result['alignment'] == 'epoch' else
        f'alignment: the first statement placed by hand at timeline second {result["offset_seconds"]:g}; '
        'statements under 1 s are not attributed',
        f'samples: {result["samples"]}, about every {result["interval_seconds"]} s'
        + (f'; {result["failed_samples"]} failed samples dropped' if result.get('failed_samples') else '')
        + (f'; {result["unreadable_metric_lines"]} metric lines unreadable' if result.get('unreadable_metric_lines') else ''),
        f'run peak: {peak["peak_physical_gb"]:.2f} GiB physical, {peak["peak_rss_gb"]:.2f} GiB RSS, '
        + (f'during {during}' if during else 'outside every attributed statement'),
        f'next time: --expect-gb {result["expect_gb"]} (this run\'s peak, rounded up to 0.1 GiB)',
        f'{sum(result["unattributed"].values())} of {len(rows)} statements unattributed' + (f': {reasons}' if reasons else ''),
    ]
    if long['count']:
        lines.append(f'at the start of the {long["count"]} attributed statements of 1 s or more: median physical '
                     f'{long["median_start_physical_gb"]:.2f} GiB, median pool {long["median_pool_before_gb"]:.2f} GiB')
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
    parser.add_argument('--offset-seconds', type=float,
                        help='Only for a timeline without epoch: the timeline second at which the first statement starts')
    parser.add_argument('--top', type=int, default=20, help='Statements to list, largest footprint first')
    parser.add_argument('--json', action='store_true', help='Every statement and the summary as JSON')
    args = parser.parse_args(argv)
    events, unreadable = read_events(args.step_log)
    samples, failed = read_timeline(args.timeline)
    try:
        result = dict(measure(events, samples, args.offset_seconds), failed_samples=failed, unreadable_metric_lines=unreadable)
    except Refused as error:
        parser.error(str(error))
    print(json.dumps(result, indent=1) if args.json else render(result, args.top))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
