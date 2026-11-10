"""Gates 1 and 2 (ct-tk10) in the publish path: compare with the live release, keep every link key.

`require_release_gates` runs `release_comparison.compare` on the local candidate and the
fetched base (live) release, writes the report, then refuses unless
  - the link rule finds no missing and no dangling key (no record can override it), and
  - every non-verified group has a cause record entry with the exact count, and every
    entry names an actual group, bound to these two release IDs.
The cause record is committed after a build, so the flow is build -> refuse with report ->
write record -> resume -> pass. The record's truth is not machine-checked: only its counts,
binding and evidence custody are. See release_comparison for what the comparison cannot see.

`prior_links` builds the retired-key ledger inputs (data model §8.2) from the base release
and, when the base has no ledger, the explicitly named earlier releases.
"""
import argparse
from datetime import date
import gzip
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake.receipt_metadata import document_status, document_status_sql

from viewer_publication.release_comparison import ADDED_URL_STATE, ATTEMPTED_URLS, CHURN_GROUPS

DIGEST = re.compile('[0-9a-f]{64}')
TICKET = re.compile('(ct|cef|ss)-[a-z0-9]{4}')
LEDGER_FILES = ('manifest.json', 'links.parquet', 'detail.parquet', 'list.parquet', 'sources.parquet')
PRIOR_LINKS = pa.schema([('link_key', pa.binary(8)), ('release_rank', pa.int16()), ('release_id', pa.string()),
                         ('list_row', pa.int32()), ('primary_key', pa.binary(8)), ('filename', pa.string())])
PRIOR_SOURCES = pa.schema([('release_rank', pa.int16()), ('list_row', pa.int32()), ('url', pa.string()),
                           ('member_path', pa.string())])
RETIRED = pa.schema([('link_key', pa.binary(8)), ('successor_key', pa.binary(8)),
                     ('last_release_id', pa.string()), ('last_filename', pa.string()),
                     ('address_versions', pa.list_(pa.binary(8)))])


def _sha(value, what):
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise ValueError(f'{what} must be a lowercase SHA-256')
    return value


def fetch_release(read, release_id, dest, names=None):
    """Copy a published release's files, each checked against its manifest entry.

    `read(name)` returns a binary stream for one file of the release. The manifest must
    hash to `release_id` (data model §8.3), so a wrong release or a changed file refuses.
    Existing identical files are kept, so a resumed publish does not download them again.
    """
    from congress_api.retention.derived_files import copy_checked
    from viewer_publication.archive_format import release_identity
    _sha(release_id, 'Release ID')
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with read('manifest.json') as stream:
        raw = stream.read(4 << 20)
    manifest = json.loads(raw)
    if manifest.get('release_id') != release_id or release_identity(manifest['schema_version'], manifest['files']) != release_id:
        raise ValueError(f'Fetched manifest does not identify release {release_id}')
    entries = {item['name']: item for item in manifest['files']}
    wanted = list(entries) if names is None else [n for n in names if n != 'manifest.json']
    for name in wanted:
        if name not in entries:
            if names is not None and name in LEDGER_FILES:
                raise ValueError(f'Release {release_id[:12]} has no {name}')
            continue
        item = entries[name]
        if (dest / name).is_file():
            from congress_api.retention.provenance import file_pin
            if file_pin(dest / name) == dict(sha256=item['sha256'], size=item['size']):
                continue  # already held with the manifest's identity: no second download
            raise ValueError(f'Retained {release_id[:12]}/{name} differs from its manifest entry')
        with read(name) as stream:
            copy_checked(stream, dest / name, size=item['size'], expected=dict(sha256=item['sha256'], bytes=item['size']),
                         key=f'{release_id[:12]}/{name}', exclusive=True)
    target = dest / 'manifest.json'
    if not target.exists():
        target.write_bytes(raw)
    elif target.read_bytes() != raw:
        raise ValueError('Fetched manifest differs from the retained copy')
    return manifest


def origin_reader(origin, release_id):
    """Public HTTPS reads for the offline CLI; the publish job passes its R2 client instead."""
    from viewer_publication.receipt_pins import PREFIX
    # The public origin refuses urllib's default agent; name this tool instead.
    return lambda name: urlopen(Request(f'{origin.rstrip("/")}/{PREFIX}{release_id}/{name}',
                                        headers={'User-Agent': 'congressional-tech-release-gate/1'}), timeout=120)


def client_reader(client, bucket, release_id):
    from viewer_publication.receipt_pins import PREFIX
    return lambda name: client.get_object(Bucket=bucket, Key=f'{PREFIX}{release_id}/{name}')['Body']


def prior_links(base_dir, history_dirs, out_dir):
    """Write prior_links.parquet (one row per key per release), prior_sources.parquet (each
    prior row's addresses, for the address successor rule) and base_retired.parquet.

    O(total link rows) in pyarrow, about 1.7M rows for 448651e7 plus three earlier releases.
    A release whose detail lacks `link_key` (pre-keyed detail) gives a null primary key, so
    its keys can still redirect through a sibling key.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts, addresses = [], []
    for rank, directory in enumerate([Path(base_dir), *map(Path, history_dirs)]):
        sources = pq.read_table(directory / 'sources.parquet', columns=['list_row', 'url', 'member_path'])
        addresses.append(pa.table([pa.array([rank] * len(sources), pa.int16()), sources['list_row'].cast(pa.int32()),
                                   sources['url'].cast(pa.string()), sources['member_path'].cast(pa.string())], schema=PRIOR_SOURCES))
        release_id = json.loads((directory / 'manifest.json').read_text())['release_id']
        links = pq.read_table(directory / 'links.parquet', columns=['link_key', 'list_row'])
        rows = links['list_row']
        filenames = pq.read_table(directory / 'list.parquet', columns=['filename'])['filename'].take(rows)
        detail_fields = pq.read_schema(directory / 'detail.parquet').names
        primary = (pq.read_table(directory / 'detail.parquet', columns=['link_key'])['link_key'].take(rows)
                   if 'link_key' in detail_fields else pa.nulls(len(links), pa.binary(8)))
        parts.append(pa.table([links['link_key'].cast(pa.binary(8)), pa.array([rank] * len(links), pa.int16()),
                               pa.array([release_id] * len(links), pa.string()), rows.cast(pa.int32()),
                               primary.cast(pa.binary(8)), filenames.cast(pa.string())], schema=PRIOR_LINKS))
    prior = out_dir / 'prior_links.parquet'
    pq.write_table(pa.concat_tables(parts) if parts else PRIOR_LINKS.empty_table(), prior)
    pq.write_table(pa.concat_tables(addresses) if addresses else PRIOR_SOURCES.empty_table(), out_dir / 'prior_sources.parquet')
    retired = out_dir / 'base_retired.parquet'
    source = Path(base_dir) / 'retired_links.parquet'
    if source.exists():
        held = pq.read_table(source)
        if 'address_versions' not in held.column_names:  # ledgers written before the column
            held = held.append_column('address_versions', pa.nulls(len(held), pa.list_(pa.binary(8))))
        pq.write_table(held.select(RETIRED.names).cast(RETIRED), retired)
    else:
        pq.write_table(RETIRED.empty_table(), retired)
    return prior, retired


def ledger_inputs(directory, *, prior_links=None, base_retired=None):
    """Model inputs for retired-links.sql; absent inputs mean an empty ledger, never a guess."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    inputs = []
    # prior_sources sits beside prior_links, written by the same prior_links() call.
    prior_sources = None if prior_links is None else Path(prior_links).with_name('prior_sources.parquet')
    for name, path, schema in (('prior_links', prior_links, PRIOR_LINKS), ('prior_sources', prior_sources, PRIOR_SOURCES),
                               ('base_retired', base_retired, RETIRED)):
        if path is None:
            path = directory / f'{name}.parquet'
            pq.write_table(schema.empty_table(), path)
        elif not pq.read_schema(path).equals(schema):
            raise ValueError(f'Ledger input {name} has an unexpected schema')
        inputs.append(dict(name=name, kind='parquet', path=str(Path(path).resolve())))
    return inputs


def require_ledger_history(base_dir, link_history):
    """A base without a ledger needs the earlier releases named; a base with one needs none."""
    has_ledger = (Path(base_dir) / 'retired_links.parquet').exists()
    if has_ledger and link_history:
        raise ValueError('The base release carries retired_links; link_history must be empty')
    if not has_ledger and not link_history:
        raise ValueError('The base release has no retired_links; the publish must name link_history')


def fetch_base(read_release, release_id, work, link_history=(), *, previous_release_id=None):
    """Fetch the live release and, without its own ledger, the named history; build the ledger inputs.

    `read_release(release_id)` returns a reader for that release's files. A base without a
    ledger needs link_history to continue the pointer's chain: its first entry must be the
    pointer's previous_release_id, and every named release must be readable. Releases older
    than the previous one carry no recorded predecessor, so the rest of the list is the
    publish spec's statement, checked only by manifest identity.
    Returns (base_dir, prior_links, base_retired, history_dirs), or Nones when nothing is live.
    """
    if release_id is None:
        if link_history:
            raise ValueError('link_history names earlier releases, but nothing is live')
        return None, None, None, []
    work = Path(work)
    base = work / 'base-release'
    # Only what the ledger reads; publish_candidate completes the copy for gate 1 only when
    # a new release is actually published, so an input-unchanged skip reads no more.
    fetch_release(read_release(release_id), release_id, base, (*LEDGER_FILES, 'retired_links.parquet'))
    require_ledger_history(base, link_history)
    if link_history and previous_release_id is not None and link_history[0] != previous_release_id:
        raise ValueError(f'link_history must start with the live pointer\'s previous release {previous_release_id[:12]}')
    history = []
    for earlier in link_history:
        target = work / 'link-history' / _sha(earlier, 'link_history release')
        try:
            fetch_release(read_release(earlier), earlier, target, LEDGER_FILES)
        except Exception as error:
            raise ValueError(f'link_history release {earlier[:12]} is absent or unreadable') from error
        history.append(target)
    prior, retired = prior_links(base, history, work / 'ledger')
    return base, prior, retired, history


def load_causes(pin):
    """Read a pinned cause record and custody-check every evidence pin it names."""
    from congress_shared.custody import verify_local_file
    path = Path(pin['path'])
    verified = verify_local_file(path, pin['sha256'], pin['size'])
    record = json.loads(path.read_bytes())
    verified.require(path)
    if not isinstance(record, dict) or record.get('version') != 1 or not isinstance(record.get('groups'), list):
        raise ValueError('Cause record requires version 1 and a groups list')
    for side in ('base_release_id', 'candidate_release_id'):
        _sha(record.get(side), f'Cause record {side}')
    seen = set()
    for entry in record['groups']:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or entry['id'].count('|') < 2:
            raise ValueError('Cause entry requires an id of file|group|cause')
        if entry['id'] in seen:
            raise ValueError(f'Duplicate cause entry: {entry["id"]}')
        seen.add(entry['id'])
        if type(entry.get('count')) is not int:
            raise ValueError(f'Cause entry count must be an integer: {entry["id"]}')
        if entry.get('disposition') not in ('explained', 'accepted_defect'):
            raise ValueError(f'Cause entry disposition must be explained or accepted_defect: {entry["id"]}')
        if not isinstance(entry.get('cause'), str) or not entry['cause'].strip():
            raise ValueError(f'Cause entry requires a stated cause: {entry["id"]}')
        tickets = entry.get('tickets', [])
        if not isinstance(tickets, list) or any(not isinstance(t, str) or TICKET.fullmatch(t) is None for t in tickets):
            raise ValueError(f'Cause entry tickets must be ticket ids: {entry["id"]}')
        if entry['disposition'] == 'accepted_defect' and not tickets:
            raise ValueError(f'An accepted defect needs a ticket: {entry["id"]}')
        if entry['disposition'] == 'explained' and not entry.get('evidence'):
            # An explanation names what was read (raw lines, a query result) by pinned file.
            raise ValueError(f'An explained cause needs pinned evidence: {entry["id"]}')
        for evidence in entry.get('evidence', []):
            verify_local_file(evidence['path'], evidence['sha256'], evidence['size'])
    return record


# ct-ud0b (owner decision 2026-11-02): nightly publication without a person when every
# difference is a new row traced to receipts the live release did not read. These are the
# only groups that can receive an automatic cause; anything else still needs a record.
AUTOMATIC_GROUPS = {('list.parquet', 'added rows'), ('detail.parquet', 'added rows'), ('links.parquet', 'added keys'),
                    ('urls.parquet', 'keys new'), ('urls.parquet', 'keys with more rows'),
                    ('sources.parquet', 'new URLs'), ('sources.parquet', 'member rows added'),
                    ('sources.parquet', 'same-URL rows added')}
ATTEMPTED_URL_GROUP = ('url_state.parquet', 'added URLs', ATTEMPTED_URLS)
AUTOMATIC_CAUSE = "addition traced to receipts absent from the live release's receipt set (automatic, ct-ud0b)"


def _raw_document_proof(line):
    """Read body references and the explicit request from one raw receipt line."""
    try:
        receipt = json.loads(line)
    except ValueError:
        return set(), None
    if not isinstance(receipt, dict):
        return set(), None
    entries = receipt.get('captures') or receipt.get('file_references')
    bodies = {entry['sha256'].lower() for entry in entries
              if isinstance(entry, dict) and isinstance(entry.get('sha256'), str)} if isinstance(entries, list) else set()
    record = receipt.get('record', {})
    url = None
    if isinstance(record, dict):
        status = receipt.get('http_status', record.get('http_status'))
        if (receipt.get('mode', record.get('mode')) == 'fetch'
                and receipt.get('outcome', record.get('outcome')) in ('stored', 'unchanged')
                and type(status) is int and document_status(status)):
            url = receipt.get('requested_url', record.get('requested_url'))
    return bodies, url


def automatic_causes(report, base_dir, candidate_dir, *, engine, captures, live_receipt_keys, read_receipt, work):
    """Cause entries for an addition-only difference whose every new row comes from new receipts.

    Returns (entries, reasons); entries is empty unless every check passes. A new document is
    a candidate row none of whose link keys an earlier release published. Its body keys are
    joined to `captures` (the capture mapping, not the archive model) to find the receipt
    lines holding those bodies. Each line is then read from raw: its key must be outside the
    live release's receipt set, and the line itself must name the body's SHA-256. The set is the
    live release's own input record (every key its captures were read from), so "new" is by key,
    whatever the key's date: a backlog read oldest first is new without being recent (ct-gc99).
    Every capture line of a new document must qualify, so a body the live release also read
    is not new. Link, source and lookup additions must sit on new documents only.
    Every attempt for an added URL needs a fresh receipt line that supplied the new document.
    Cannot see: a bug that adds only wrong rows (wrong values on genuinely new receipts), or a
    new row whose receipts are new while the code that made it changed; the other gates still run.
    """
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import run_job
    from viewer_publication.release_comparison import Diff, documents
    reasons = []
    groups = report['failing']
    if not report['link_rule']['ok']:
        return [], ['automatic causes: the link rule failed']
    # Include already verified differences when deciding whether this is addition-only, except
    # the cache-refresh citations the comparison proved row by row (ct-syp1): they change no
    # content, so they neither need this proof nor stop it.
    differences = [dict(group, file=name) for name, facts in report['files'].items() for group in facts['groups']
                   if group['status'] != 'verified' or (name, group['group'], group['cause']) not in CHURN_GROUPS]
    other = [g for g in differences if g.get('value') or g['count'] <= 0 or
             ((g['file'], g['group']) not in AUTOMATIC_GROUPS and
              (g['file'], g['group'], g['cause']) != ATTEMPTED_URL_GROUP)]
    if other:
        return [], [f'automatic causes: {group_id(g)} ({g["count"]}) is not an addition that can be traced' for g in other]
    if not differences:
        return [], []
    held = set(live_receipt_keys)
    if not held:
        # With nothing to be absent from, every receipt would count as new.
        return [], ['automatic causes: the live release has no receipt set to compare with']
    d = Diff(Path(base_dir), Path(candidate_dir))
    d.documents = documents(d)
    d.table('added_documents', 'SELECT file_row_number::INT r FROM candidate_list ANTI JOIN pairs ON file_row_number=lr')
    for table, fields in (('sources', 'url,member_path'), ('urls', 'lookup_key')):
        if d.has('candidate', table) and d.has('base', table):
            stray = d.one(f"""SELECT count(*) FROM (SELECT list_row,{fields} FROM candidate_{table}
                WHERE list_row NOT IN (SELECT r FROM added_documents)
                EXCEPT SELECT x.lr,{','.join('p.' + f for f in fields.split(','))} FROM base_{table} p JOIN pairs x ON p.list_row=x.pr)""")
            if stray:
                reasons.append(f'automatic causes: {stray} {table} rows were added to existing documents')
    url_additions = {}
    if any((g['file'], g['group'], g['cause']) == ATTEMPTED_URL_GROUP for g in groups):
        url_additions = dict(d.rows(f'SELECT requested_url, attempts FROM {ADDED_URL_STATE} WHERE attempts>0'))
    keys = [r[0] for r in d.rows("SELECT DISTINCT lower(hex(link_key)) FROM candidate_links WHERE list_row IN (SELECT r FROM added_documents) ORDER BY 1")]
    # A new document has no link key in the base. Its keys must account for
    # every added link key already counted by the comparison.
    added_links = sum(g['count'] for g in differences if (g['file'], g['group']) == ('links.parquet', 'added keys'))
    if len(keys) != added_links:
        reasons.append(f'automatic causes: {added_links} added link keys, {len(keys)} attached to new documents')
    if not keys:
        reasons.append('automatic causes: no new document carries a key to trace')
    if reasons:
        return [], reasons
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({'prefix': keys}), work / 'added-keys.parquet')
    source = captures['path'] if captures.get('kind') == 'parquet' else {k: v for k, v in captures.items() if k != 'kind'}
    request_column = (f", CASE WHEN c.mode='fetch' AND c.complete AND coalesce(c.attempt,0)=0 "
                      f"AND c.outcome IN ('stored','unchanged') AND {document_status_sql('c.http_status')} "
                      "THEN c.requested_url END AS requested_url") if url_additions else ''
    lines = run_job(work / 'trace', engine, inputs=[table_input('captures', source),
        dict(name='added_keys', kind='parquet', path=str(work / 'added-keys.parquet'))], steps=[], outputs=[],
        queries=[dict(name='lines', sql=f"""SELECT DISTINCT k.prefix,c.receipt_key,c.receipt_line,lower(encode(c.sha256,'hex')) AS sha{request_column}
            FROM added_keys k JOIN captures c ON substr(lower(encode(c.sha256,'hex')),1,16)=k.prefix
            WHERE c.sha256 IS NOT NULL ORDER BY 1,2,3""")])['lines']
    traced = {}
    for row in lines:
        traced.setdefault(row['prefix'], []).append(row)
    untraced = [k for k in keys if k not in traced]
    if untraced:
        reasons.append(f'automatic causes: {len(untraced)} new document keys have no capture to trace (first {untraced[:3]})')
    raw = {}
    named = {}
    attempts = {url: set() for url in url_additions}
    for row in lines:
        key = row['receipt_key']
        if key in held:
            reasons.append(f'automatic causes: {key} is already in the live release')
        else:
            if key not in raw:
                with gzip.open(BytesIO(read_receipt(key)), 'rt') as stream:
                    raw[key] = stream.read().splitlines()
            text = raw[key]
            line = row['receipt_line']
            location = (key, line)
            if location not in named:
                named[location] = (_raw_document_proof(text[line - 1]) if
                                   isinstance(line, int) and 1 <= line <= len(text) else (set(), None))
            bodies, raw_url = named[location]
            if row['sha'] not in bodies:
                reasons.append(f'automatic causes: {key}:{line} does not name body {row["sha"][:12]} in raw')
            elif (url := row.get('requested_url')) in attempts and url == raw_url:
                attempts[url].add(location)
    for url, count in url_additions.items():
        if len(attempts[url]) != count:
            reasons.append(f'automatic causes: {url} has {count} attempts but {len(attempts[url])} fresh raw lines naming the new document and its request URL')
    if reasons:
        return [], sorted(set(reasons))
    evidence = work / 'automatic-trace.json'
    evidence.write_text(json.dumps(dict(live_receipts=len(held), new_receipts=len(raw), lines=lines, url_attempts={url: sorted(matches) for url, matches in attempts.items()}), indent=1, default=str) + '\n')
    from congress_api.retention.provenance import file_pin
    pin = dict(path=str(evidence), **file_pin(evidence))
    return [dict(id=group_id(g), count=g['count'], disposition='explained', cause=AUTOMATIC_CAUSE,
                 tickets=['ct-ud0b'], evidence=[pin], automatic=True) for g in groups], []


def group_id(group):
    return f'{group["file"]}|{group["group"]}|{group["cause"]}'


def verdict(report, causes):
    """Every reason the gates refuse, each naming the rule it broke."""
    reasons = []
    rule = report['link_rule']
    if rule['missing']:
        reasons.append(f'link rule: {rule["missing"]} base link keys vanish (first {rule["missing_keys"][:5]})')
    if rule['dangling']:
        reasons.append(f'link rule: {rule["dangling"]} successors are not published keys (first {rule["dangling_keys"][:5]})')
    actual = {group_id(g): g['count'] for g in report['failing']}
    entries = {e['id']: e for e in (causes or {}).get('groups', [])}
    if causes is not None:
        for side, key in (('base', 'base_release'), ('candidate', 'candidate_release')):
            if causes[f'{side}_release_id'] != report[key]:
                reasons.append(f'cause record: bound to {side} {causes[f"{side}_release_id"][:12]}, actual {report[key][:12]}')
    for gid, count in sorted(actual.items()):
        if gid not in entries:
            reasons.append(f'comparison: no recorded cause for {gid} ({count})')
        elif entries[gid]['count'] != count:
            reasons.append(f'comparison: recorded count {entries[gid]["count"]} differs from {count} for {gid}')
    for gid in sorted(set(entries) - set(actual)):
        reasons.append(f'cause record: stale entry with no actual group: {gid}')
    return reasons


def require_release_gates(base_dir, candidate_dir, causes, *, report_path, evidence_base=None, evidence_candidate=None, history=(),
                          automatic=None):
    """Write the comparison report, then refuse on any gate 1 or gate 2 finding.

    `automatic(report)` (ct-ud0b), when given, returns (entries, reasons) for an addition-only
    difference; its entries join the recorded causes for groups the record does not name.
    """
    from viewer_publication.release_comparison import compare
    report_path = Path(report_path)
    if base_dir is None:
        report = dict(base_release=None, gates='vacuous: no live release to compare with', reasons=[])
        report_path.write_text(json.dumps(report, indent=1) + '\n')
        return report
    report = compare(base_dir, candidate_dir, evidence_base=evidence_base, evidence_candidate=evidence_candidate, history=history)
    if automatic is not None:
        entries, report['automatic_reasons'] = automatic(report)
        if entries:
            named = {e['id'] for e in (causes or {}).get('groups', [])}
            causes = dict(causes or dict(version=1, base_release_id=report['base_release'],
                                          candidate_release_id=report['candidate_release'], groups=[]))
            causes['groups'] = [*causes['groups'], *(e for e in entries if e['id'] not in named)]
            report['automatic_causes'] = entries
    report['reasons'] = verdict(report, causes)
    if causes is None and not report['reasons']:
        # A verified comparison group can still be outside the unattended policy.
        report['reasons'] = report.get('automatic_reasons', [])
    report_path.write_text(json.dumps(report, indent=1, default=str) + '\n')
    if report['reasons']:
        raise ValueError('Release gates refused (report ' + str(report_path) + '):\n' + '\n'.join(report['reasons']))
    return report


def render_notes(causes, base_dir, candidate_dir):
    """Release notes from the accepted cause record and the candidate's ledger: one source each."""
    candidate = json.loads((Path(candidate_dir) / 'manifest.json').read_text())['release_id']
    base = json.loads((Path(base_dir) / 'manifest.json').read_text())['release_id']
    if (causes['base_release_id'], causes['candidate_release_id']) != (base, candidate):
        raise ValueError('Cause record is bound to other releases')
    ledger = Path(candidate_dir) / 'retired_links.parquet'
    retired = pq.read_table(ledger, columns=['successor_key']) if ledger.exists() else RETIRED.empty_table()
    redirected = len(retired) - retired['successor_key'].null_count
    removed = retired['successor_key'].null_count
    lines = [f'# Release {candidate[:12]}', '', f'- Release: `{candidate}`', f'- Previous release: `{base}`', '']
    identifiers = causes.get('notes', {}).get('identifiers', [])
    if identifiers:
        lines += ['## Identifiers', '']
        lines += [f'- {item["statement"]} ({item["decision"]})' for item in identifiers]
        lines.append('')
    lines += ['## Links', '', f'{redirected} link keys from earlier releases now redirect to their current document. '
              f'{removed} show a removal notice. 0 vanish.', '',
              '## Row changes', '', '| File | Group | Cause | Count | Disposition | Tickets |', '| --- | --- | --- | --- | --- | --- |']
    for entry in causes['groups']:
        file, group, _ = entry['id'].split('|', 2)
        lines.append(f'| `{file}` | {group} | {entry["cause"]} | {entry["count"]} | {entry["disposition"]} | {", ".join(entry.get("tickets", []))} |')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    fetch = commands.add_parser('fetch', help='copy a published release from the public origin')
    fetch.add_argument('--origin', required=True)
    fetch.add_argument('--release', required=True)
    fetch.add_argument('--out', type=Path, required=True)
    fetch.add_argument('--names', nargs='*')
    check = commands.add_parser('compare', help='the publish-path gates, offline, with no status write')
    check.add_argument('--base', type=Path, required=True)
    check.add_argument('--candidate', type=Path, required=True)
    check.add_argument('--causes', type=Path)
    check.add_argument('--evidence-base')
    check.add_argument('--evidence-candidate')
    check.add_argument('--output', type=Path, required=True)
    notes = commands.add_parser('notes', help='render docs/releases/<date>-<candidate12>.md')
    notes.add_argument('--causes', type=Path, required=True)
    notes.add_argument('--base', type=Path, required=True)
    notes.add_argument('--candidate', type=Path, required=True)
    notes.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parents[4] / 'docs/releases')
    args = parser.parse_args(argv)
    try:
        if args.command == 'fetch':
            fetch_release(origin_reader(args.origin, args.release), args.release, args.out, args.names)
            print(args.out)
            return 0
        if args.command == 'compare':
            causes = None
            if args.causes:
                from congress_api.retention.provenance import file_pin
                causes = load_causes(dict(path=str(args.causes), **file_pin(args.causes)))
            require_release_gates(args.base, args.candidate, causes, report_path=args.output,
                                  evidence_base=args.evidence_base, evidence_candidate=args.evidence_candidate)
            print('release gates passed')
            return 0
        from congress_api.retention.provenance import file_pin
        causes = load_causes(dict(path=str(args.causes), **file_pin(args.causes)))
        text = render_notes(causes, args.base, args.candidate)
        target = args.output_dir / f'{date.today().isoformat()}-{causes["candidate_release_id"][:12]}.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        print(target)
        return 0
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
