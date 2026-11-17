"""Gate 1 for a night on which only the data moved (ct-pz32, owner decision 2026-11-17).

A release is a function of its definition and its inputs. Every release keeps both in its input
record: the semantic profile (SQL, registries, parser, engine and writer pins, model code hashes),
the reference-entity digests, the decision records' ETags, and the inputs no profile names
(`unprofiled_inputs`: every producer's current version, the committed job specs' pins). When the
candidate's are all equal to the live release's and its receipt set only grew, nothing but the new
receipts can explain a difference. Such a night needs no cause record. A night that changed code,
a parser, a pin or a decision is not this night: it needs the traced proof or a record.

This rule decides only a night the traced addition proof (`release_gate.automatic_causes`) cannot
read, one with a changed or removed row. That proof stops on such a night before any check, so
nothing here stands in for a check that ran and refused. An additions-only night stays with it.

The caps are tripwires, not proof. They stop a night that moved more than a capture night moves,
which is how a publisher serving wrong pages, or the right code reading the wrong table, would
look. Measured on the two capture nights with gate reports (2026-11-13 into 4b9a7bd126cc and
2026-11-17 into c998ffa0766f; 2,000 requests each): the largest group added or changed 2,921 rows
and 0.60% of its file; one file's groups summed to 6,792 rows; the only removals were url_state's
queue at 0.056%; and outside that queue the most a column lost was 0.39% of its values. The
candidate that lost every html_metadata reading (08c465599d7b, 2026-11-16) emptied whole columns
of 2,561 to 12,587 values, which the column tripwire stops at any size.

Cannot see: wrong but non-null content served at an ordinary volume, such as an error page's
title on a few thousand re-fetched documents (the archive records what was published); a column
of fewer values than the loss floor emptied whole; small losses that add up night after night,
since each night is measured against the release before it; parser code changed with no version
bump, or a lake table rewritten at an unchanged version, which no gate here pins; a difference
the comparison cannot see. The traced proof's per-document caps on link keys and addresses do
not apply on this path. The link rule, the model's invariants and completeness
checks, and the contract and canary gates run as on any night.
"""
from pathlib import Path

GROUP_SHARE, GROUP_FLOOR, GROUP_ROWS = 0.02, 50, 5_000
FILE_ROWS = 10_000
REMOVED_ROWS = 5
QUEUE_REMOVAL_SHARE = 0.0025
COLUMN_LOSS_SHARE, COLUMN_LOSS_FLOOR = 0.05, 50
# The fetch queue's own columns turn over by design: a queued address that is fetched leaves
# with its whole linked_from list (5.8% of that column's values on 2026-11-17 in run 44065807228,
# 1.3% on 2026-11-13). The queue is bounded by its row caps above, not by the column tripwire.
QUEUE_FILE = 'url_state.parquet'
# The shapes a capture night's own receipts produce, from both measured nights and the 2026-11-13
# record: rows, keys and addresses added, and a value changed on a matched key. Anything else the
# comparison leaves unverified is for a person: a removal, a link whose file became an alternate
# (ct-4qld), a defect, a flag, a whole file.
EXPLAINABLE = {'added rows', 'added keys', 'added URLs', 'keys new', 'new URLs'}
# By id, the two groups no proof covers that the three latest capture-night records (750a2a24d00a
# into 6c46b8f7a606, 55c14dcda87a into 4b9a7bd126cc, 4b9a7bd126cc into 6ac86c21b373) and both
# measured nights all carry: a rewritten recoveries file with no differing row, and queued URLs
# replaced by their fetches.
RECURRING_UNEXPLAINED = {'recoveries.parquet|changed bytes, no key or value difference found|unexplained',
                         'url_state.parquet|removed URLs|unexplained'}
SAME_INPUTS = ('profile', 'entity_digests', 'provenance', 'unprofiled_inputs')
DATA_ONLY_CAUSE = ("data-only night: built by the live release's definition and pinned inputs from a receipt set "
                   'that only grew; not traced to individual receipts (automatic, ct-pz32)')


def _first_difference(candidate, live, path=''):
    """Where two input values first differ, by sorted key."""
    if isinstance(candidate, dict) and isinstance(live, dict):
        for key in sorted(set(candidate) | set(live)):
            if candidate.get(key) != live.get(key):
                return _first_difference(candidate.get(key), live.get(key), f'{path}.{key}' if path else str(key))
    return path


def _input_reasons(candidate, live_records):
    """Why no kept input of the live release has the candidate's definition and pinned inputs."""
    missing = [name for name in SAME_INPUTS if candidate.get(name) is None]
    if missing:
        return [f'data-only night: the candidate names no {", ".join(missing)}']
    differing = lambda entry: [name for name in SAME_INPUTS if entry['record'].get(name) != candidate[name]]
    record = min(live_records, key=lambda entry: len(differing(entry)))['record']  # the nearest kept input
    kept = [name for name in SAME_INPUTS if record.get(name) is None]
    if kept:
        return [f'data-only night: the live release keeps no {", ".join(kept)} to compare with']
    return ['data-only night: the candidate differs from the live release in '
            + ', '.join(_first_difference(candidate[name], record[name], name) for name in SAME_INPUTS
                        if candidate[name] != record[name])]


def _group_reasons(report):
    """Every difference a data night may not carry, then every cap it passes.

    All of the comparison's groups but the re-fetch ones are read, verified or not: a verified
    group is proven to be what it says, not to be small, and the traced proof stops on it too.
    """
    from viewer_publication.release_gate import group_id
    reasons, totals = [], {}
    for file, facts in report['files'].items():
        for group in (dict(g, file=file) for g in facts['groups'] if not g.get('refetch_only')):
            name, count, base = group_id(group), group['count'], facts['rows']['base']
            recurring = name in RECURRING_UNEXPLAINED
            if group['status'] != 'verified' and not recurring and (
                    group['status'] != 'unverified' or group.get('flag')
                    or not (group.get('value') or group['group'] in EXPLAINABLE)):
                reasons.append(f'data-only night: {name} ({count}) is not a difference new receipts alone explain; '
                               'it needs a cause record')
            elif count < 0:
                cap = int(base * QUEUE_REMOVAL_SHARE) if file == QUEUE_FILE else REMOVED_ROWS
                if -count > cap:
                    reasons.append(f'data-only night: {name} ({count}) removes more than the {cap} rows one unattended night may')
            else:
                cap = min(GROUP_ROWS, max(GROUP_FLOOR, int(base * GROUP_SHARE)))
                if count > cap:
                    reasons.append(f'data-only night: {name} ({count}) is more than the {cap} rows one unattended night '
                                   f'may add or change (the lesser of {GROUP_ROWS} and {GROUP_SHARE:.0%} of {base})')
            totals[file] = totals.get(file, 0) + abs(count)
    return reasons + [f'data-only night: {file} moves {total} rows across its groups, more than the {FILE_ROWS} one '
                      'unattended night may' for file, total in sorted(totals.items()) if total > FILE_ROWS]


def column_values(release):
    """Non-null leaf values per (file, column path), from Parquet footers alone.

    A null field, an empty list and a null parent all leave a leaf null, so a column emptied in
    any of those ways shows here. None where a footer keeps no null count.
    """
    import pyarrow.parquet as pq
    values = {}
    for path in sorted(Path(release).glob('*.parquet')):
        metadata = pq.ParquetFile(path).metadata
        for index in range(metadata.num_columns):
            chunks = [chunk for chunk in (metadata.row_group(group).column(index) for group in range(metadata.num_row_groups))
                      if chunk.num_values]  # an empty chunk holds no value and keeps no statistics
            counted = all(chunk.statistics is not None and chunk.statistics.has_null_count for chunk in chunks)
            values[path.name, metadata.schema.column(index).path] = (
                sum(chunk.num_values - chunk.statistics.null_count for chunk in chunks) if counted else None)
    return values


def _column_reasons(base_dir, candidate_dir):
    """A column that lost more of its values than a capture night loses, or that cannot be counted."""
    base, candidate = column_values(base_dir), column_values(candidate_dir)
    reasons = []
    for (file, column), held in sorted(base.items()):
        if file == QUEUE_FILE:
            continue
        now = candidate.get((file, column), 0)
        if held is None or now is None:
            reasons.append(f'data-only night: {file}:{column} keeps no null count, so its values cannot be compared')
        elif held - now > max(COLUMN_LOSS_FLOOR, int(held * COLUMN_LOSS_SHARE)):
            reasons.append(f'data-only night: {file}:{column} lost {held - now} of its {held} values, more than the '
                           f'{COLUMN_LOSS_SHARE:.0%} one unattended night may')
    return reasons, sum(file != QUEUE_FILE for file, _ in base)


def data_only_causes(report, *, candidate_record, live_records, candidate_receipt_keys, base_dir, candidate_dir):
    """Cause entries for every failing group of a night only new receipts can explain.

    `live_records` are the live release's kept input records (`receipt_pins.kept_input_records`).
    Returns (entries, reasons, facts); entries is empty unless every check passes, and every
    refusal found is returned, so a stopped night names all of it.
    """
    from congress_api.lake.versions import version_digest
    from viewer_publication.release_gate import group_id
    if not report['link_rule']['ok']:
        return [], ['data-only night: the link rule failed'], {}
    # The same receipt set the traced proof calls live: every key any kept input of the release read.
    held = {key for entry in live_records for key in entry['receipt_keys']}
    if not held:
        return [], ['data-only night: the live release has no receipt set to compare with'], {}
    same = [entry for entry in live_records
            if all(candidate_record.get(name) is not None and entry['record'].get(name) == candidate_record[name]
                   for name in SAME_INPUTS)]
    candidate = set(candidate_receipt_keys)
    new, groups = candidate - held, report['failing']
    reasons = [] if same else _input_reasons(candidate_record, live_records)
    if held - candidate:
        reasons.append(f'data-only night: {len(held - candidate)} receipts the live release read are absent from the '
                       f'candidate (first {sorted(held - candidate)[:3]})')
    if not new:
        reasons.append('data-only night: the candidate read no receipt the live release did not, so nothing explains a difference')
    reasons += _group_reasons(report)
    lost, columns = _column_reasons(base_dir, candidate_dir)
    reasons += lost
    if reasons:
        return [], reasons, {}
    facts = dict(version=1, profile_sha256=version_digest(packages={}, files={}, values=candidate_record['profile']),
                 live_input=same[-1]['key'], live_receipts=len(held), new_receipts=len(new), new_receipt_keys=sorted(new),
                 groups=len(groups), columns_compared=columns,
                 caps=dict(group_share=GROUP_SHARE, group_floor=GROUP_FLOOR, group_rows=GROUP_ROWS, file_rows=FILE_ROWS,
                           removed_rows=REMOVED_ROWS, queue_removal_share=QUEUE_REMOVAL_SHARE,
                           column_loss_share=COLUMN_LOSS_SHARE, column_loss_floor=COLUMN_LOSS_FLOOR))
    return [dict(id=group_id(group), count=group['count'], disposition='explained', automatic=True,
                 cause=DATA_ONLY_CAUSE, tickets=['ct-pz32']) for group in groups], [], facts


def unattended_causes(report, *, traced, data_only):
    """Decide a night that has no cause record: (entries, reasons, data-only facts or None).

    The traced proof decides every night it can read, pass or refuse. Only a night with a
    difference outside its scope goes to the data-only rule.
    """
    from viewer_publication.release_gate import untraceable_groups
    outside = untraceable_groups(report)
    if not outside:
        return (*traced(report), None)
    entries, reasons, facts = data_only(report)
    if reasons:
        # What a person reads first is why this night is not a data-only night; the traced proof
        # ran no check, so one line says so in place of one per group.
        return [], [*reasons, f'automatic causes: {len(outside)} differences are not additions the traced proof reads, '
                              'so it ran no check'], None
    return entries, [], facts
