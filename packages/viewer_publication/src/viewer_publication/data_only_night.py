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

The caps are tripwires, not proof. They stop a night that moved more than its new receipts can
explain, which is how a publisher serving wrong pages, or the right code reading the wrong table,
would look. The caps scale with the receipts new to the release. An untraced group may move
at most 2% of its file, subject to the small-group floor.
An added recording without an event must trace to a new page receipt even below that cap.
These proven keys keep the receipt and whole-file limits. Measured on three capture
nights with gate reports:

    night (candidate)            new receipts   largest group     largest file total
    2026-11-13 (4b9a7bd126cc)    about 1,027    2,921 (2.8 each)   6,804 (6.6 each)
    2026-11-17 (c998ffa0766f)    1,173          2,468 (2.1 each)   4,945 (4.2 each)
    2026-11-17 (2ec7ae83a852)    1,775          6,489 (3.7 each)  18,481 (10.4 each)

The only unverified removals were the fetch queue's, at most 0.056% of it; the third night also
re-keyed six people, which the comparison verified. Outside the queue the most a column lost was
0.39% of its values. The candidate that lost every html_metadata reading (08c465599d7b,
2026-11-16) emptied whole columns of 2,561 to 12,587 values, which the column tripwire stops at
any size; its changed groups moved 3.9% to 25% of detail.parquet, above the 2% ceiling.

Cannot see: wrong but non-null content served at an ordinary volume, such as an error page's
title on a few thousand re-fetched documents (the archive records what was published); a column
of fewer values than the loss floor emptied whole; small losses that add up night after night,
since each night is measured against the release before it; parser code changed with no version
bump, or a lake table rewritten at an unchanged version, which no gate here pins; a difference
the comparison cannot see. The traced proof's per-document caps on link keys and addresses do
not apply on this path. The link rule, the model's invariants and completeness
checks, and the contract and canary gates run as on any night.
"""
from collections import Counter, defaultdict
from pathlib import Path

GROUP_SHARE, GROUP_FLOOR = 0.02, 50
GROUP_ROWS_PER_RECEIPT, FILE_ROWS_PER_RECEIPT = 5, 15
REMOVAL_SHARE = 0.0025
DOCUMENT_FILES, REMOVED_DOCUMENTS = {'detail.parquet', 'list.parquet', 'links.parquet'}, 5
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
# Pages one night may capture again with new bytes; a site-wide template change would exceed it.
RECAPTURED_PAGES = 100
REMOVED_RECORDING_MATCHES = 20
# Run 44737429192 attributed at most four unlinked videos to one committee receipt.
UNLINKED_PER_RECEIPT = 20
UNLINKED_RECORDINGS_ID = 'recordings.parquet|added keys|empty event_ids; source not traced'
RECORDING_MATCH_REMOVAL_ID = 'recording_matches.parquet|removed keys|no evidence given'
# A page: saved as HTML, with a title read from the page itself. A PDF's title is its listing's
# link text, which does not change when the file is replaced, so an equal title proves nothing.
PAGE_MEDIA, PAGE_TITLES = 'text/html', {'page_title', 'page_heading'}
LINK_FINDINGS = (('link_key', '', 'link key'), ('lookup_key', 'lookup_', 'lookup key'), ('address', 'address_', 'address'))
DATA_ONLY_CAUSE = ("data-only night: built by the live release's definition and pinned inputs from a receipt set "
                   'that only grew; not traced to individual receipts (automatic, ct-pz32)')


def _provenance_compatible(candidate_prov, live_prov):
    """Decision provenance must match; receipt-bound qualification provenance may only grow."""
    if candidate_prov == live_prov:
        return True
    if not isinstance(candidate_prov, list) or not isinstance(live_prov, list):
        return False
    from viewer_publication.archive_model_job import provenance_etag_md5, provenance_record_kind

    def split_prov(items):
        other, quals = [], {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('key'), str) or not isinstance(item.get('etag'), str):
                return None
            if provenance_record_kind(item['key']) == 'qualifications':
                try:
                    md5 = provenance_etag_md5(item['etag'])
                except ValueError:
                    return None
                if item['key'] in quals and quals[item['key']] != md5:
                    return None
                quals[item['key']] = md5
            else:
                other.append(item)
        return other, quals

    cand_split, live_split = split_prov(candidate_prov), split_prov(live_prov)
    if cand_split is None or live_split is None:
        return False
    cand_other, cand_quals = cand_split
    live_other, live_quals = live_split
    return cand_other == live_other and all(cand_quals.get(k) == v for k, v in live_quals.items())


def _same_input(name, candidate_val, live_val):
    if name == 'provenance':
        return _provenance_compatible(candidate_val, live_val)
    return candidate_val == live_val


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
    differing = lambda entry: [name for name in SAME_INPUTS if not _same_input(name, candidate[name], entry['record'].get(name))]
    record = min(live_records, key=lambda entry: len(differing(entry)))['record']  # the nearest kept input
    kept = [name for name in SAME_INPUTS if record.get(name) is None]
    if kept:
        return [f'data-only night: the live release keeps no {", ".join(kept)} to compare with']
    return ['data-only night: the candidate differs from the live release in '
            + ', '.join(_first_difference(candidate[name], record[name], name) for name in SAME_INPUTS
                        if not _same_input(name, candidate[name], record[name]))]


def _group_reasons(report, new_receipts, *, proven_groups=frozenset()):
    """Every difference a data night may not carry, then every cap it passes.

    All of the comparison's groups but the re-fetch ones are read, verified or not: a verified
    group is proven to be what it says, not to be small, and the traced proof stops on it too.
    """
    from viewer_publication.release_gate import group_id
    reasons, totals = [], {}
    for file, facts in report['files'].items():
        for group in (dict(g, file=file) for g in facts['groups'] if not g.get('refetch_only')):
            name, count, base = group_id(group), group['count'], facts['rows']['base']
            recurring = name in RECURRING_UNEXPLAINED or name in proven_groups
            if group['status'] != 'verified' and not recurring and (
                    group['status'] != 'unverified' or group.get('flag')
                    or not (group.get('value') or group['group'] in EXPLAINABLE)):
                reasons.append(f'data-only night: {name} ({count}) is not a difference new receipts alone explain; '
                               'it needs a cause record')
            elif count < 0:
                cap = REMOVED_DOCUMENTS if file in DOCUMENT_FILES else max(GROUP_FLOOR, int(base * REMOVAL_SHARE))
                if -count > cap:
                    reasons.append(f'data-only night: {name} ({count}) removes more than the {cap} rows one unattended night may')
            elif file == 'recordings.parquet' and group['group'] == 'added keys' and name in proven_groups:
                cap = GROUP_ROWS_PER_RECEIPT * new_receipts
                if count > cap:
                    reasons.append(f'data-only night: {name} ({count}) exceeds {cap} rows for {new_receipts} new receipts')
            else:
                cap = max(GROUP_FLOOR, min(int(base * GROUP_SHARE), GROUP_ROWS_PER_RECEIPT * new_receipts))
                if count > cap:
                    reasons.append(f'data-only night: {name} ({count}) is more than the {cap} rows this night may add or change '
                                   f'(the lesser of {GROUP_SHARE:.0%} of {base} and {GROUP_ROWS_PER_RECEIPT} for each of its '
                                   f'{new_receipts} new receipts)')
            totals[file] = totals.get(file, 0) + abs(count)
    # A file's groups together: the same two bounds as one group, three times as wide.
    wider = FILE_ROWS_PER_RECEIPT // GROUP_ROWS_PER_RECEIPT
    for file, total in sorted(totals.items()):
        allowed = max(GROUP_FLOOR, min(int(report['files'][file]['rows']['base'] * GROUP_SHARE) * wider,
                                       FILE_ROWS_PER_RECEIPT * new_receipts))
        if total > allowed:
            reasons.append(f'data-only night: {file} moves {total} rows across its groups, more than the {allowed} this night may '
                           f'(the lesser of {GROUP_SHARE * wider:.0%} of the file and {FILE_ROWS_PER_RECEIPT} for each of its '
                           f'{new_receipts} new receipts)')
    return reasons


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


def recaptured_pages(rule, base_dir, candidate_dir, *, new_receipts, trace, read_receipt):
    """Corrections a night proves for itself: a page captured again at its own address.

    Owner decision 2026-11-17 (ct-pz32). The link rule reports each live link key, lookup key and
    address that would open another file, and leaves it to a named correction (ct-4nax). A page
    whose publisher changed its bytes is the ordinary case: run 44087092120 stopped on one House
    event page whose only change was the site's latest-news sidebar. Its findings are proven, and
    need no person, when all of this holds:

    - the address answers exactly one candidate file, and each of the page's link and lookup keys
      moves from the same live file to that same file;
    - a raw receipt line outside the live release's receipt set stored that file for that address
      at HTTP 200 (`trace` finds the lines holding the body, `read_receipt` reads them from raw);
    - both files are HTML pages whose title is read from the page itself, and that title is the
      same, and not empty, in both releases.

    A changed title (an error page, another event), a file that is not a page (a replaced PDF keeps
    its listing's title), a body no new receipt stored, or a key that moves somewhere else leaves
    the finding to a person. Returns (proven entries for the link
    rule's `proven_corrections`, reasons, facts). O(pages) receipt reads and one capture scan.
    Cannot see: a publisher that changed the body under an unchanged title.
    """
    import gzip
    import json
    import pyarrow.parquet as pq
    reasons = [f"data-only night: {rule[prefix + 'changed'] - len(rule[prefix + 'changed_answers'])} live {what}s that answer "
               "another file are beyond the report's sample, so nothing can prove them"
               for _, prefix, what in LINK_FINDINGS if rule[prefix + 'changed'] > len(rule[prefix + 'changed_answers'])]
    pages = [a for a in rule['address_changed_answers']
             if len(a['candidate_rows']) == 1 and len(a['candidate_bodies']) == 1 and a['candidate_bodies'][0]]

    def facts_of(release, row):
        """(title, where the title came from, saved media type) of one document row."""
        title = pq.read_table(Path(release) / 'list.parquet', columns=['title']).slice(row, 1).to_pylist()
        saved = pq.read_table(Path(release) / 'detail.parquet', columns=['title_source', 'saved_media_type']).slice(row, 1).to_pylist()
        return (title[0]['title'], saved[0]['title_source'], saved[0]['saved_media_type']) if title and saved else (None, None, None)
    lines = trace({a['candidate_bodies'][0][:16] for a in pages}) if pages else []
    raw = {}

    def stored(key, line):
        """The raw receipt line as (address, HTTP status, bodies it stored); each receipt read once."""
        if key not in raw:
            raw[key] = gzip.decompress(read_receipt(key)).decode('utf-8', 'replace').splitlines()
        if not isinstance(line, int) or not 1 <= line <= len(raw[key]):
            return None, None, set()
        row = json.loads(raw[key][line - 1])
        row = row if 'captures' in row or not isinstance(row.get('record'), dict) else row['record']
        return row.get('url'), row.get('http_status'), {c.get('sha256') for c in row.get('captures') or []}

    moved, recaptures = {}, []
    for answer in pages:
        address, body = answer['key'], answer['candidate_bodies'][0]
        old, new = facts_of(base_dir, answer['live_row']), facts_of(candidate_dir, answer['candidate_rows'][0])
        page = old == new and bool(old[0]) and old[1] in PAGE_TITLES and old[2] == PAGE_MEDIA
        def stores(row):
            url, status, bodies = stored(row['receipt_key'], row['receipt_line'])
            return url == address and status == 200 and body in bodies
        receipt = next((row['receipt_key'] for row in lines
                        if row['sha'] == body and row['receipt_key'] in new_receipts and stores(row)), None)
        if receipt is not None and page:
            moved[answer['live_body']] = body
            recaptures.append(dict(address=address, live_body=answer['live_body'], candidate_body=body, receipt=receipt, title=old[0]))
    proven = []
    for kind, prefix, what in LINK_FINDINGS:
        for answer in rule[prefix + 'changed_answers']:
            shown = [answer['candidate_body']] if kind == 'link_key' else answer['candidate_bodies']
            if shown == [moved.get(answer['live_body'])]:
                proven.append(dict(kind=kind, key=answer['key'], live_body=answer['live_body'], candidate_body=shown[0]))
            else:
                reasons.append(f"data-only night: live {what} {answer['key']} would open another file, and it is not a page captured "
                               'again at its own address under its own unchanged title; it needs a named correction')
    if len(recaptures) > RECAPTURED_PAGES:
        reasons.append(f'data-only night: {len(recaptures)} pages were captured again with new bytes, more than the '
                       f'{RECAPTURED_PAGES} one unattended night may')
    return proven, reasons, dict(recaptures=recaptures)


def _link_reasons(rule, link_proof, new):
    """(reasons, proven corrections, facts) for the link rule on a data night.

    A key that vanishes, dangles, is retired while published or is demoted to an alternate, and a
    check that could not run, stop any night. A key that would open another file stops it unless
    `link_proof` proves it.
    """
    hard = [f'{rule[name]} {name}' for name in ('missing', 'dangling', 'published_and_retired', 'demoted') if rule.get(name)]
    hard += [f'unchecked: {item}' for item in rule.get('unchecked') or []]
    changed = any(rule.get(prefix + 'changed') for _, prefix, _ in LINK_FINDINGS)
    if hard or (not changed and not rule['ok']):
        return [f"data-only night: the link rule failed ({', '.join(hard) or 'not ok'})"], [], {}
    if not changed:
        return [], [], {}
    if link_proof is None:
        return ['data-only night: the link rule failed (live keys would open another file, and they were not examined)'], [], {}
    proven, reasons, facts = link_proof(rule, new)
    return reasons, proven, facts


def _recording_events(directory):
    """Map recorded video keys to their events. None means the release cannot supply the proof."""
    import pyarrow.parquet as pq
    path = Path(directory) / 'recordings.parquet'
    columns = ['video_key', 'event_ids']
    if not path.is_file() or not set(columns) <= set(pq.read_schema(path).names):
        return None
    return {row['video_key']: set(row['event_ids'] or ()) for row in pq.read_table(path, columns=columns).to_pylist()}


def _meeting_videos(directory, events):
    """The video keys the publisher lists for the meetings losing a generic page match."""
    import pyarrow.parquet as pq
    path = Path(directory) / 'meetings.parquet'
    if not events or not path.is_file() or not {'event_id', 'videos'} <= set(pq.read_schema(path).names):
        return {}
    meetings = pq.read_table(path, columns=['event_id', 'videos'], filters=[('event_id', 'in', sorted(events))])
    return {r['event_id']: {v['video_key'] for v in r['videos'] or () if v and v.get('video_key')}
            for r in meetings.to_pylist()}


def _recording_match_replacements(base_dir, candidate_dir, base_rec, cand_rec, *, expected_removed, recaptures, new_receipts):
    """Prove removed `committee_page` recording matches replaced on a data-only night (ct-618r).

    A removed `recording_matches` row is proven only when `0 < expected_removed <= REMOVED_RECORDING_MATCHES`
    and every removed row (`base_recording_matches` minus `candidate_recording_matches` on `match_id`,
    excluding `publisher_link` rows already verified by `MEETING_UPDATE`) is a `committee_page` match
    whose event still has an active linked match. Each removal must meet one of three conditions.
      1. `recaptured_page`: its cited `committee_page:<live_body>` was proven recaptured at its own
         address under an unchanged HTML title (`live_body -> candidate_body`), and `event_id` now has
         a `committee_page` match citing `candidate_body`.
      2. `event_ids_replaced`: its `video_key` changed `event_ids` in `recordings.parquet` to a non-empty
         set (never dropping the video to `[]`), and every added `event_id` on `video_key` is backed by a
         candidate `committee_page` match citing a newly added HTML body absent from `base` `detail.parquet`.
      3. `publisher_corroborated`: a generic single-day match lost its event to a video the
         publisher lists for the same meeting and a newly captured page confirms for that event.
    Return None when any removed row lacks a replacement.
    """
    import pyarrow.parquet as pq
    if not (0 < expected_removed <= REMOVED_RECORDING_MATCHES):
        return None
    base_rm_path = Path(base_dir) / 'recording_matches.parquet'
    cand_rm_path = Path(candidate_dir) / 'recording_matches.parquet'
    if not (base_rm_path.is_file() and cand_rm_path.is_file()):
        return None
    rm_cols = ['match_id', 'event_id', 'video_key', 'basis', 'decision', 'status', 'source_ref', 'note']
    for path in (base_rm_path, cand_rm_path):
        if not set(rm_cols).issubset(pq.read_schema(path).names):
            return None
    base_rows = {r['match_id']: r for r in pq.read_table(base_rm_path, columns=rm_cols).to_pylist() if r.get('match_id')}
    cand_list = pq.read_table(cand_rm_path, columns=rm_cols).to_pylist()
    cand_ids = {r['match_id'] for r in cand_list if r.get('match_id')}
    removed_ids = base_rows.keys() - cand_ids
    if len(removed_ids) > REMOVED_RECORDING_MATCHES:
        return None
    removed = [base_rows[mid] for mid in sorted(removed_ids) if base_rows[mid].get('basis') != 'publisher_link']
    if len(removed) != expected_removed:
        return None

    recapture_map = {item['live_body']: item['candidate_body'] for item in (recaptures or ())
                     if isinstance(item, dict) and item.get('live_body') and item.get('candidate_body') and item.get('receipt') in new_receipts}
    covered_events = {
        r['event_id'] for r in cand_list
        if r.get('video_key') and r.get('event_id') is not None and r.get('decision') == 'linked' and r.get('status') in ('asserted', 'decided')
    }
    official = _meeting_videos(candidate_dir, {r['event_id'] for r in removed if r['note'] == 'house_single_day_generic'
                                              and r['event_id'] is not None})
    publisher_links = {(r['event_id'], r['video_key']) for r in cand_list if r.get('video_key')
                       and r.get('basis') == 'publisher_link' and r.get('decision') == 'linked'
                       and r.get('status') == 'asserted' and r.get('source_ref') == 'meetings.videos'}
    corroborated = {}
    cand_page_by_event = defaultdict(set)
    cand_page_by_video_event = {}
    for r in cand_list:
        if (r.get('basis') == 'committee_page' and r.get('event_id') is not None
                and r.get('decision') == 'linked' and r.get('status') in ('asserted', 'decided')):
            sref = r.get('source_ref') or ''
            cites = set()
            if sref.startswith('committee_page:'):
                cites.add(sref.removeprefix('committee_page:'))
            note = r.get('note') or ''
            if (r['video_key'] in official.get(r['event_id'], ()) and (r['event_id'], r['video_key']) in publisher_links
                    and sref.startswith('committee_page:')
                    and note.split(' [via ', 1)[0] == 'house_doc_link'
                    and sref != base_rows.get(r['match_id'], {}).get('source_ref')):
                corroborated.setdefault(r['event_id'], []).append((r['video_key'], sref.removeprefix('committee_page:')))
            if '[via committee_page:' in note:
                cites.add(note.split('[via committee_page:', 1)[1].split(']', 1)[0])
            cand_page_by_event[r['event_id']].update((r['video_key'], body) for body in cites if r.get('video_key'))
            if r.get('video_key'):
                cand_page_by_video_event.setdefault((r['video_key'], r['event_id']), set()).update(cites)

    base_det_path, cand_det_path = Path(base_dir) / 'detail.parquet', Path(candidate_dir) / 'detail.parquet'
    new_html_bodies = set()
    if (base_det_path.is_file() and cand_det_path.is_file()
            and 'saved_body' in pq.read_schema(base_det_path).names
            and {'saved_body', 'saved_media_type'}.issubset(pq.read_schema(cand_det_path).names)):
        held_bodies = {b.hex() if isinstance(b, bytes) else str(b).lower()
                       for b in pq.read_table(base_det_path, columns=['saved_body'])['saved_body'].to_pylist() if b}
        for r in pq.read_table(cand_det_path, columns=['saved_body', 'saved_media_type']).to_pylist():
            b = r.get('saved_body')
            if b and r.get('saved_media_type') == PAGE_MEDIA:
                hx = b.hex() if isinstance(b, bytes) else str(b).lower()
                if hx not in held_bodies:
                    new_html_bodies.add(hx)

    proven = []
    for row in removed:
        ev, vk = row.get('event_id'), row.get('video_key')
        if row.get('basis') != 'committee_page' or ev is None or ev not in covered_events:
            return None
        sref = row.get('source_ref') or ''
        live_page = sref.removeprefix('committee_page:') if sref.startswith('committee_page:') else None
        cand_page = recapture_map.get(live_page) if live_page else None
        recaptured = [(video, body) for video, body in cand_page_by_event[ev] if body == cand_page]
        if recaptured:
            proven.append(dict(match_id=row['match_id'], event_id=ev, video_key=vk, reason='recaptured_page',
                               live_page=live_page, candidate_page=cand_page, claims={ev: recaptured}))
            continue
        if (row.get('note') == 'house_single_day_generic' and vk not in official.get(ev, ()) and row.get('decision') == 'linked'
                and row.get('status') == 'asserted' and live_page and base_rec.get(vk) == {ev} and cand_rec.get(vk) == set()):
            alternatives = [(video, page) for video, page in corroborated.get(ev, ())
                            if video != vk and ev in cand_rec.get(video, ()) and page in new_html_bodies]
            if len(alternatives) == 1:
                video, page = alternatives[0]
                proven.append(dict(match_id=row['match_id'], event_id=ev, video_key=vk, reason='publisher_corroborated',
                                   replacement_video_key=video, candidate_page=page, claims={ev: [(video, page)]}))
                continue
        if vk and vk in base_rec and vk in cand_rec:
            old_evs, new_evs = base_rec[vk], cand_rec[vk]
            added_evs = new_evs - old_evs
            if ev in old_evs and ev not in new_evs and new_evs and added_evs and all(
                bool(cand_page_by_video_event.get((vk, aev), set()) & new_html_bodies) for aev in added_evs
            ):
                proven.append(dict(match_id=row['match_id'], event_id=ev, video_key=vk, reason='event_ids_replaced',
                                   new_event_ids=sorted(added_evs), claims={event: [(vk, page) for page in
                                       cand_page_by_video_event[vk, event] & new_html_bodies] for event in added_evs}))
                continue
        return None
    return proven


def added_recording_pages(added, pages, new):
    """Attribute each unlinked addition to one admitted receipt, then count by that receipt."""
    additions = {}
    for video in sorted(added):
        sources = pages.get(video, {})
        for body, source in sorted(sources.items()):
            if source.get('receipt_key') in new:
                additions[video] = dict(page_body=body, **source)
                break
    missing = sorted(set(added) - additions.keys())
    if missing:
        return {}, [f'data-only night: {len(missing)} added recordings lack a linking page from a new receipt (first {missing[:3]})']
    counts = Counter(source['receipt_key'] for source in additions.values())
    return additions, [f'data-only night: {key} accounts for {n} added recordings, above the limit of {UNLINKED_PER_RECEIPT}'
                       for key, n in sorted(counts.items()) if n > UNLINKED_PER_RECEIPT]


def _linked_additions(base_dir, candidate_dir, linked, pages):
    """Each event must have a linked match and independent publisher or raw committee-page evidence."""
    import pyarrow.parquet as pq
    path = Path(candidate_dir) / 'recording_matches.parquet'
    columns = ['event_id', 'video_key', 'basis', 'source_ref', 'decision', 'status']
    proven = defaultdict(dict)
    if path.is_file() and set(columns) <= set(pq.read_schema(path).names):
        rows = pq.read_table(path, columns=columns, filters=[('video_key', 'in', sorted(linked))]).to_pylist()
        publisher_events = {r['event_id'] for r in rows if r['basis'] == 'publisher_link' and r['source_ref'] == 'meetings.videos'}
        listed = _meeting_videos(candidate_dir, publisher_events)
        held = _meeting_videos(base_dir, publisher_events)
        for row in rows:
            event, video = row['event_id'], row['video_key']
            if event not in linked[video] or row['decision'] != 'linked' or row['status'] not in ('asserted', 'decided'):
                continue
            for body, source in sorted(pages.get(video, {}).items()):
                page_names_event = event in source.get('event_ids', ())
                # A new listing and a new match can share the same faulty model output.
                # Confirm the event independently on the page or in the held publisher listing.
                publisher = (row['basis'] == 'publisher_link' and row['source_ref'] == 'meetings.videos'
                             and video in listed.get(event, ()) and (page_names_event or video in held.get(event, ())))
                committee = (row['basis'] == 'committee_page' and row['source_ref'] == 'committee_page:' + body
                             and page_names_event)
                if publisher or committee:
                    proven[video][event] = dict(page_body=body, corroboration='committee_page' if page_names_event else 'held_publisher',
                                               **source)
                    break
    missing = [(video, ev) for video in sorted(linked) for ev in sorted(linked[video] - proven[video].keys())]
    return proven, ([f'data-only night: {len(missing)} video/event pairs on added recordings lack publisher or '
                     f'committee-page corroboration (first {missing[:3]})'] if missing else [])


def _prove_recording_changes(base_dir, candidate_dir, *, removed, expected, expected_unlinked, recaptures, new, page_proof):
    """Select added keys from the tables and verify their pages and every replacement in one scan."""
    base, candidate = _recording_events(base_dir), _recording_events(candidate_dir)
    if base is None and candidate is None and not (removed or expected):
        return {}, []
    if base is None or candidate is None:
        return {}, ['data-only night: the recording tables cannot identify the added recordings']
    added = {video: candidate[video] for video in candidate.keys() - base.keys()}
    empty = [video for video, events in added.items() if not events]
    if len(added) != expected or len(empty) != expected_unlinked or any(not video for video in added):
        return {}, [f'data-only night: expected {expected} added recordings ({expected_unlinked} unlinked), '
                    f'found {len(added)} ({len(empty)} unlinked) in the recording tables']
    replacements = (_recording_match_replacements(base_dir, candidate_dir, base, candidate, expected_removed=removed,
                    recaptures=recaptures, new_receipts=new) if removed else [])
    # A replacement also claims a proceeding video, so its receipt must verify that scoped link.
    wanted = {video: events.copy() for video, events in added.items()}
    for row in replacements or ():
        for event, choices in row['claims'].items():
            for video, _ in choices:
                wanted.setdefault(video, set()).add(event)
    supplied = page_proof(wanted, new) if wanted and page_proof else {}
    pages = {video: {body: src for body, src in sources.items() if src.get('receipt_key') in new}
             for video, sources in supplied.items()}
    facts, reasons = {}, []
    for row in replacements or ():
        sources = []
        for event, choices in sorted(row.pop('claims').items()):
            proof = None
            for video, body in sorted(choices):
                source = pages.get(video, {}).get(body)
                if not source:
                    continue
                named = source.get('event_ids', ())
                if event in named or (row['reason'] == 'recaptured_page' and not named):
                    proof = dict(event_id=event, video_key=video, page_body=body, **source)
                    break
            if not proof:
                reasons.append(f'data-only night: removed keys match {row["match_id"]} lacks a corroborating new page receipt for event {event}')
                break
            sources.append(proof)
        row['page_receipts'] = sources
    if replacements and not reasons:
        facts['replaced_recording_matches'] = replacements
    if empty:
        facts['added_recording_pages'], missing = added_recording_pages(empty, pages, new)
        reasons.extend(missing)
    linked = {video: events for video, events in added.items() if events}
    if linked:
        facts['added_recording_events'], missing = _linked_additions(base_dir, candidate_dir, linked, pages)
        reasons.extend(missing)
    return facts, reasons


def data_only_causes(report, *, candidate_record, live_records, candidate_receipt_keys, base_dir, candidate_dir, link_proof=None,
                     qualification_files=None, recording_page_proof=None):
    """Cause entries for every failing group of a night only new receipts can explain.

    `live_records` are the live release's kept input records (`receipt_pins.kept_input_records`).
    Returns (entries, reasons, facts); entries is empty unless every check passes, and every
    refusal found is returned, so a stopped night names all of it. `link_proof(rule, new_receipts)` may prove
    link findings (`recaptured_pages`); facts then carries `proven_corrections` for the link rule.
    """
    from congress_api.lake.versions import version_digest
    from viewer_publication.release_gate import group_id
    # The same receipt set the traced proof calls live: every key any kept input of the release read.
    held = {key for entry in live_records for key in entry['receipt_keys']}
    if not held:
        return [], ['data-only night: the live release has no receipt set to compare with'], {}
    same = [entry for entry in live_records
            if all(candidate_record.get(name) is not None and _same_input(name, candidate_record[name], entry['record'].get(name))
                   for name in SAME_INPUTS)]
    candidate = set(candidate_receipt_keys)
    new, groups = candidate - held, report['failing']
    reasons = [] if same else _input_reasons(candidate_record, live_records)
    if same:
        from congress_api.retention.qualification_facts import load_qualification_facts
        from viewer_publication.archive_model_job import provenance_record_kind
        live_q_keys = {item['key'] for item in (same[-1]['record'].get('provenance') or ())
                       if isinstance(item, dict) and provenance_record_kind(item.get('key')) == 'qualifications'}
        cand_q_keys = {item['key'] for item in (candidate_record.get('provenance') or ())
                       if isinstance(item, dict) and provenance_record_kind(item.get('key')) == 'qualifications'}
        added_q_keys = cand_q_keys - live_q_keys
        if added_q_keys:
            by_key = {item['key']: item for item in (qualification_files or ()) if isinstance(item, dict) and isinstance(item.get('key'), str)}
            missing_q = sorted(added_q_keys - set(by_key))
            if missing_q:
                reasons.append(f'data-only night: added qualification provenance lacks verified files ({missing_q[:3]})')
            else:
                loaded_q = load_qualification_facts([by_key[k] for k in sorted(added_q_keys)])
                if loaded_q.get('stale', 0) > 0 or loaded_q.get('unbound_facts', 0) > 0:
                    reasons.append('data-only night: added qualification provenance contains stale or receipt-unbound records')
                outside_q = sorted((loaded_q.get('all_receipt_keys') or set()) - candidate)
                if outside_q:
                    reasons.append(f'data-only night: added qualification provenance cites unknown receipts ({outside_q[:3]})')
    if held - candidate:
        reasons.append(f'data-only night: {len(held - candidate)} receipts the live release read are absent from the '
                       f'candidate (first {sorted(held - candidate)[:3]})')
    if not new:
        reasons.append('data-only night: the candidate read no receipt the live release did not, so nothing explains a difference')
    counts = {group_id(dict(g, file=file)): g['count'] for file in ('recording_matches.parquet', 'recordings.parquet')
              for g in report['files'].get(file, {}).get('groups', ())
              if g['status'] == 'unverified' and not g.get('flag') and not g.get('refetch_only')}
    removed = -counts.get(RECORDING_MATCH_REMOVAL_ID, 0)
    tentative = set()
    if 0 < removed <= REMOVED_RECORDING_MATCHES:
        tentative.add(RECORDING_MATCH_REMOVAL_ID)
    additions = [g for g in report['files'].get('recordings.parquet', {}).get('groups', ()) if g['group'] == 'added keys']
    empty_groups = {group_id(dict(g, file='recordings.parquet')) for g in additions if g['cause'].startswith('empty event_ids;')}
    tentative.update(empty_groups)
    group_reasons = _group_reasons(report, len(new), proven_groups=tentative)
    lost, columns = _column_reasons(base_dir, candidate_dir)
    stopped, proven, link_facts = _link_reasons(report['link_rule'], link_proof if not (reasons or group_reasons or lost) else None, new)
    recording_facts = {}
    if not (stopped or reasons or group_reasons or lost):
        recording_facts, reasons = _prove_recording_changes(base_dir, candidate_dir, removed=removed, expected=sum(g['count'] for g in additions),
            expected_unlinked=sum(g['count'] for g in additions if g['cause'].startswith('empty event_ids;')),
            recaptures=link_facts.get('recaptures', ()), new=new, page_proof=recording_page_proof)
    proven_groups = set()
    if 'replaced_recording_matches' in recording_facts:
        proven_groups.add(RECORDING_MATCH_REMOVAL_ID)
    if 'added_recording_pages' in recording_facts:
        proven_groups.update(empty_groups)
    if proven_groups != tentative:
        group_reasons = _group_reasons(report, len(new), proven_groups=proven_groups)
    reasons = [*stopped, *reasons, *group_reasons, *lost]
    if reasons:
        return [], reasons, {}
    facts = dict(version=1, profile_sha256=version_digest(packages={}, files={}, values=candidate_record['profile']),
                 live_input=same[-1]['key'], live_receipts=len(held), new_receipts=len(new), new_receipt_keys=sorted(new),
                 groups=len(groups), columns_compared=columns, proven_corrections=proven, **link_facts, **recording_facts,
                 caps=dict(unlinked_recordings_per_receipt=UNLINKED_PER_RECEIPT, recaptured_pages=RECAPTURED_PAGES, removed_recording_matches=REMOVED_RECORDING_MATCHES,
                           group_share=GROUP_SHARE, group_floor=GROUP_FLOOR,
                           group_rows_per_receipt=GROUP_ROWS_PER_RECEIPT, file_rows_per_receipt=FILE_ROWS_PER_RECEIPT,
                           removal_share=REMOVAL_SHARE, removed_documents=REMOVED_DOCUMENTS,
                           column_loss_share=COLUMN_LOSS_SHARE, column_loss_floor=COLUMN_LOSS_FLOOR))
    recording_causes = {UNLINKED_RECORDINGS_ID: 'A page stored in a new receipt links to each added recording.',
                        RECORDING_MATCH_REMOVAL_ID: 'Each removed committee-page match has a verified replacement.'}
    return [dict(id=group_id(group), count=group['count'], disposition='explained', automatic=True,
                 cause=recording_causes.get(group_id(group), DATA_ONLY_CAUSE),
                 tickets=['ct-618r', 'ct-pz32'] if group_id(group) == RECORDING_MATCH_REMOVAL_ID else ['ct-pz32'])
            for group in groups], [], facts


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
