"""Build the compare_generations expected-change file from the raw judges' summaries.

    build_expected.py JUDGE_SUMMARY URL_SUMMARY COMPARISON_REPORT EVIDENCE_DIR OUT

Pairs come from the judges (one count per raw-explained row), never from the comparison;
the comparison report is only checked against them, and any mismatch refuses.
"""
import hashlib, json, sys
from collections import Counter
from pathlib import Path

judge, urls, report, evidence, out = sys.argv[1:6]
summary = json.loads(Path(judge).read_text())
if summary['defects']:
    raise SystemExit(f"{summary['defects']} changed rows have no raw cause; they are defects")


def text(value):
    value = json.loads(value)
    return None if value is None else ('true' if value is True else 'false' if value is False else str(value))


CAUSES = {
    'mods_descriptor_reference': 'GovInfo MODS descriptor: no body, status captured; a reference, not a failed fetch (rca-d, 0043edfe registry).',
    'inline_saved_record': 'Inline record with no body is a saved-record, not a failed fetch (rca-d).',
    'record_only_no_attempt': 'Reference and saved-record rows establish no attempt.',
    'record_only_no_fetch': 'Reference and saved-record rows establish no fetch state.',
    'raw_failure': 'The raw line or its owner states an explicit failure outcome or error (rca-d, 12,386 class).',
    'writer_stated_unchanged': 'The pipeline-data writer recorded outcome unchanged (git snapshot not modified).',
    'stated_status_read': 'The status the owning object states (`status`, ct-bxqa) is read.',
    'stated_2xx_read': 'A stated 2xx other than 202 on a complete stored body makes it a good fetch (ct-bxqa).',
    'empty_body': 'An empty body (0 bytes or SHA-256 of empty input) is not a document (ct-3l1c).',
    'non_document_status': 'A stated non-2xx or 202 status is not a document (ct-bxqa, ct-c6b0).',
    'partial_206': 'A 206 whose content_range is partial is not a document (red-e1).',
    'envelope_over_empty_origin': 'A provider envelope over an empty origin body is not a document (ct-fh62).',
    'retry_status': 'A stated 429 or 503 is retry_later.',
    'no_final_document_body': 'The item has no final document body, so its fetch is failed (§7.7).',
    'unaddressed_row_not_a_document': 'A row with no request address is its own fetch; its body is not a document.',
    'recorded_complete': 'previous_receipt.body_complete is recorded true (ct-v8y0, 0043edfe).',
    'final_url_from_record': 'captures.url is the final URL (record.final_url/resolved_url), data model §5 (d3e49b9d).',
}
pairs, causes = Counter(), []
for column, old, new, cause, rows in summary['classes']:
    if cause.startswith('follows_'):
        reason = 'Good fetch follows the explained outcome change: ' + cause[len('follows_'):]
    else:
        reason = CAUSES[cause]
    pairs[(column, text(old), text(new))] += rows
    causes.append(dict(column=column, old=text(old), new=text(new), cause=cause, rows=rows, reason=reason))
for column, cause, rows in json.loads(Path(urls).read_text())['classes']:
    if cause != 'final_url_from_record':
        raise SystemExit('Unexplained address change')
    causes.append(dict(column=column, cause=cause, rows=rows, reason=CAUSES[cause], reported_only=True))
compared = json.loads(Path(report).read_text())
observed = {(c, o, n): r for c, o, n, r in compared['pairs'] if c != 'mapping_version'}
judged = {k: v for k, v in pairs.items()}
if observed != judged:
    missing = {k: (observed.get(k), judged.get(k)) for k in set(observed) | set(judged) if observed.get(k) != judged.get(k)}
    raise SystemExit(f'Judge and comparison disagree: {missing}')


def pin(path):
    data = Path(path).read_bytes()
    return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), size=len(data))


value = dict(
    version=1,
    old='publish_v21 captures.parquet', new='candidate-r1b D1 ' + json.loads(Path(evidence, 'd1-pin.json').read_text())['metadata_location'],
    only_old=0, only_new=0, removed_columns=[], added_columns=['mapping_version', 'original_path'],
    added_columns_reason='mapping_version (field 41, publish gate 5) and relative original_path (field 42), round 1b e1.',
    pairs=[[c, o, n, r] for (c, o, n), r in sorted(pairs.items(), key=lambda i: tuple(map(str, i[0])))],
    causes=causes,
    model_effects=[
        dict(cause='m3u8 tracks', rows=2389, reason='Stated 200 Senate HLS playlists become good fetches (ct-bxqa); annex §2 track-m3u8. Recordings with any track 1,359 -> 3,743; 5 empty tracks drop.',
             evidence=pin('/Users/mikewolfd/Work/congressional-tech/.cache/rounds/r1b/e1/staged/recordings-causes.json')),
        dict(cause='segments are media', reason='format other + video/audio or the registry segment pattern is role media, never a document or track (red-e1).'),
        dict(cause='Senate WAF block page', reason='A redirect is judged by both addresses and the waf.htm page is an error_response (red-e1b, documents 2026-09-29:9230).')],
    evidence=[pin(Path(evidence, name)) for name in
              ('changes.parquet', 'address-changes.parquet', 'judged.parquet', 'summary.json', 'url-summary.json')])
Path(out).write_text(json.dumps(value, indent=1) + '\n')
print(len(value['pairs']), 'pairs;', len(causes), 'causes')
