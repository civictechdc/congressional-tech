"""Gates 1 and 2 (ct-tk10) in the publish path: compare with the live release, keep every link key.

`require_release_gates` runs `release_comparison.compare` on the local candidate and the
fetched base (live) release, writes the report, then refuses unless
  - the link rule finds no missing key, no dangling key and no check it could not run (no record
    can override these), and no live link key, lookup key or address answering another file
    unless the record names it, with its live and candidate body, as a correction (ct-4nax), and
  - every non-verified group has a cause record entry with the exact count, every entry names
    an actual group and every correction an actual finding, bound to these two release IDs.
The cause record is committed after a build, so the flow is build -> refuse with report ->
write record -> resume -> pass. The record's truth is not machine-checked: only its counts,
named bodies, binding and evidence custody are. See release_comparison for what the
comparison cannot see.

`prior_links` builds the retired-key ledger inputs (data model §8.2) from the base release
and, when the base has no ledger, the explicitly named earlier releases.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import gzip
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

import pyarrow as pa
import pyarrow.parquet as pq

from viewer_publication.release_comparison import ATTEMPTED_URLS, QUEUED_URLS

DIGEST = re.compile('[0-9a-f]{64}')
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
TICKET = re.compile('(ct|cef|ss)-[a-z0-9]{4}')
ROOT = Path(__file__).resolve().parents[4]  # the checkout running the gate
TICKETS = ROOT / '.tickets'
# ct-4nax: what a cause record's correction may name, as {kind: (field prefix in link_rule, plural)}.
CORRECTED = {'link_key': ('', 'link keys'), 'lookup_key': ('lookup_', 'lookup keys'), 'address': ('address_', 'addresses')}
CORRECTION_FIELDS = {'kind', 'key', 'live_body', 'candidate_body', 'decision', 'tickets'}
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


def _tickets(entry, name, *, needed_by=None):
    """An entry's ticket ids; `needed_by` names the kind of entry that must have at least one."""
    tickets = entry.get('tickets', [])
    if not isinstance(tickets, list) or any(not isinstance(t, str) or TICKET.fullmatch(t) is None for t in tickets):
        raise ValueError(f'Cause entry tickets must be ticket ids: {name}')
    if needed_by and not tickets:
        raise ValueError(f'{needed_by} needs a ticket: {name}')
    return tickets


def _corrections(record):
    """Validate the record's `corrections` (ct-4nax): each names one link-rule finding exactly.

    An entry is {kind, key, live_body, candidate_body, decision, tickets} and nothing else: kind is
    one of CORRECTED, key is printed as the report prints it (16 hex for a link or lookup key, the
    address otherwise), both bodies are SHA-256s, the decision says what was corrected and by which
    permanent record, and every ticket is a file in this checkout's .tickets. One entry per
    (kind, key, live body).
    """
    corrections = record.get('corrections', [])
    if not isinstance(corrections, list):
        raise ValueError('Cause record corrections must be a list')
    seen = set()
    for entry in corrections:
        if not isinstance(entry, dict) or set(entry) != CORRECTION_FIELDS:
            raise ValueError(f'A correction has exactly the fields {", ".join(sorted(CORRECTION_FIELDS))}: {entry}')
        kind, key = entry['kind'], entry['key']
        name = f'{kind} {key}'
        if kind not in CORRECTED:
            raise ValueError(f'Correction kind must be one of {", ".join(CORRECTED)}: {name}')
        if not isinstance(key, str) or (re.fullmatch('[0-9a-f]{16}', key) is None if kind != 'address' else not key.strip()):
            raise ValueError(f'Correction key must be printed as the report prints it: {name}')
        for side in ('live_body', 'candidate_body'):
            _sha(entry[side], f'Correction {side} of {name}')
        if not isinstance(entry['decision'], str) or not entry['decision'].strip():
            raise ValueError(f'A correction needs its decision: {name}')
        missing = [t for t in _tickets(entry, name, needed_by='A correction') if not (TICKETS / f'{t}.md').is_file()]
        if missing:
            raise ValueError(f'Correction tickets have no file in {TICKETS}: {", ".join(missing)} ({name})')
        if (kind, key, entry['live_body']) in seen:
            raise ValueError(f'Duplicate correction: {name} from {entry["live_body"]}')
        seen.add((kind, key, entry['live_body']))


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
    _corrections(record)
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
        _tickets(entry, entry['id'], needed_by='An accepted defect' if entry['disposition'] == 'accepted_defect' else None)
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
# ct-9j3z: the url_state groups a capture night makes. url_state_proof checks each of their rows
# against the lines of receipts new to the release; any other url_state group still needs a record.
URL_STATE_COLUMNS = ('attempts', 'last_attempt', 'last_status', 'last_outcome', 'last_good_at', 'next_attempt_at',
                     'recheck_meeting_date', 'linked_from')
URL_STATE_GROUPS = {*(('changed ' + column, 'value differs on matched key') for column in URL_STATE_COLUMNS),
                    ('added URLs', ATTEMPTED_URLS), ('added URLs', QUEUED_URLS)}
AUTOMATIC_CAUSE = "addition traced to receipts absent from the live release's receipt set (automatic, ct-ud0b)"
URL_STATE_CAUSE = ("every row is what the lines of receipts absent from the live release's receipt set imply "
                   "(automatic, ct-9j3z)")
# Unattended caps: where the proof shows where a value came from but not that it is right, one
# night may take at most so many such values; more waits for a person. Checked by `over_cap`.
# Documents: values of added rows have no live partner to compare with. Chosen from the two nights
# measured (ct-gc99): the one capture day in release 619db5f9e08e added 151, its week-old backlog
# 567 more (731 with recoveries). 250 passes the first with room and stops the second.
AUTOMATIC_ADDITION_CAP = 250
# First schedules with a meeting date (ct-9j3z): an address fetched for the first time has no live
# meeting date to keep, so the band's date is taken as published. The scheduled capture is budgeted
# at 2,000 requests a night (repository variable ARCHIVE_CAPTURE_REQUEST_BUDGET, read by
# capture-archive.yml; 2,000 on 2026-11-10), so an ordinary night cannot make more than 2,000 first
# fetches, dated or not; a night above that is a catch-up or a hand run with a larger budget, and
# those get a person. Measured on the 2026-11-10 pair: at least 663 first schedules carried a date,
# 630 of them among the 1,132 first fetches of the one 2026-11-08 capture day. The two numbers are
# coupled by hand: if the capture budget is raised, this cap must be looked at again.
AUTOMATIC_FIRST_SCHEDULE_CAP = 2000


def over_cap(count, what, cap):
    """The one refusal for an unattended cap: empty while `count` is within `cap`."""
    return [f'automatic causes: {count} {what}, more than the {cap} one unattended night may add'] if count > cap else []


def _raw_line_facts(line):
    """Body references and the request URL of one raw receipt line.

    The request is the line's own `requested_url`, at the top or in its `record`, as the capture
    mapping reads it first. A line whose only other URL is its redirect target therefore cannot
    stand for that target (review W2b). A line with no `requested_url` names no request: older
    shapes that carry the address elsewhere refuse rather than being matched loosely.
    """
    try:
        receipt = json.loads(line)
    except ValueError:
        return set(), None
    if not isinstance(receipt, dict):
        return set(), None
    entries = receipt.get('captures') or receipt.get('file_references')
    bodies = {entry['sha256'].lower() for entry in entries
              if isinstance(entry, dict) and isinstance(entry.get('sha256'), str)} if isinstance(entries, list) else set()
    record = receipt.get('record')
    request = receipt.get('requested_url')
    if not isinstance(request, str) and isinstance(record, dict):
        request = record.get('requested_url')
    return bodies, request if isinstance(request, str) else None


def _captures_source(captures):
    return captures['path'] if captures.get('kind') == 'parquet' else {k: v for k, v in captures.items() if k != 'kind'}


def _epoch_us(moment):
    """Microseconds since the epoch, as the engine's `arrow_cast(<timestamp>,'Int64')` gives a lake time."""
    return ((moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)) - EPOCH) // timedelta(microseconds=1)


_HOUSE_XML_EVENT_PATTERNS = (
    re.compile(r'(?i)^https?://docs[.]house[.]gov/meetings/[^/?#]+/[^/?#]+/[0-9]{8}/(?:hhrg|hmkp|hmtg)?([0-9]+)(?:/|$|[?#])'),
    re.compile(r'(?i)[?&]eventid=([0-9]+)(?=$|[^0-9])'),
)


def cited_files_are_new(base_dir, candidate_dir, *, engine, captures, held, work, updated_events=(),
                        candidate_receipt_keys=None):
    """Reasons a re-fetch-only change cannot pass without a person (ct-syp1, ct-uywf, ct-rhqw); empty when it can.

    The comparison shows only that the candidate is consistent with itself. Here every body the
    candidate cites for the first time (`release_comparison.new_citations`: cache files, witness
    records, meeting detail bodies) is looked up in `captures`, which the candidate does not
    control: it must be the SHA-256 of a captured body, and every receipt holding that body must
    be absent from the live release's receipt set. So a made-up hash, and a body the live release
    could already have cited, both refuse. Every detail read a meeting names for the first time
    (`release_comparison.new_reads`) must be a capture line at that receipt, line and capture
    index, in a receipt outside the live set, requesting the read's address, holding its body (a
    byte-identical re-fetch names an old body in a new line) and fetched at the read's time. The
    comparison requires that time later than the live read's, so the capture line is too. So a
    made-up read, a read the live release already held and a read dated other than its line refuse.
    When `updated_events` names Congress.gov meeting updates, the same job checks that no new
    receipt delivered a new House meeting XML body for an updated meeting (a null-status,
    unchanged-stamp House XML leaves no trace in `meetings.parquet`, yet leads title, date and
    videos). One engine job; the evidence file lists each hash's receipts and each read's line.
    Cannot see: whether the body holds the published values, or the raw receipt line (the capture
    mapping is trusted for hash and address; documents are checked against raw).
    """
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import run_job
    from viewer_publication.release_comparison import new_citations, new_reads
    cited, reads = new_citations(base_dir, candidate_dir), new_reads(base_dir, candidate_dir)
    if not cited and not reads:
        return ['automatic causes: citations moved, but the candidate cites no file or read the live release does not']
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    cited_hex = [s for s in cited if re.fullmatch('[0-9a-f]{64}', s)]
    pq.write_table(pa.table({'sha': pa.array(cited_hex, pa.string()),
                             'sha_bin': pa.array([bytes.fromhex(s) for s in cited_hex], pa.binary(32))}),
                   work / 'cited-files.parquet')
    pq.write_table(pa.table({f: pa.array([r[f] for r in reads], t) for f, t in
                             (('receipt_key', pa.string()), ('receipt_line', pa.int32()), ('capture_index', pa.int32()))}),
                   work / 'cited-reads.parquet')
    inputs = [table_input('captures', _captures_source(captures)),
              dict(name='cited_files', kind='parquet', path=str(work / 'cited-files.parquet')),
              dict(name='cited_reads', kind='parquet', path=str(work / 'cited-reads.parquet'))]
    steps = []
    queries = [dict(name='files', sql="""SELECT DISTINCT k.sha,c.receipt_key FROM cited_files k
            JOIN captures c ON c.sha256=k.sha_bin ORDER BY 1,2"""),
               dict(name='reads', sql="""SELECT k.receipt_key,k.receipt_line,k.capture_index,lower(encode(c.sha256,'hex')) AS sha,
            c.requested_url,arrow_cast(c.retrieved_at,'Int64') AS t FROM cited_reads k JOIN captures c ON c.receipt_key=k.receipt_key AND c.receipt_line=k.receipt_line
            AND c.capture_index=k.capture_index ORDER BY 1,2,3""")]
    if updated_events:
        pq.write_table(pa.table({'receipt_key': pa.array(sorted(held), pa.string())}), work / 'held-receipts.parquet')
        inputs.append(dict(name='held_receipts', kind='parquet', path=str(work / 'held-receipts.parquet')))
        addr = "lower(coalesce(c.url,c.requested_url,c.context_url,''))"
        has_sniffed = captures.get('kind') != 'parquet' or 'sniffed_format' in pq.read_schema(captures['path']).names
        xml_fmt = f"({addr} LIKE '%.xml%' OR c.sniffed_format='xml')" if has_sniffed else f"{addr} LIKE '%.xml%'"
        hx_pred = f"""c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged')
              AND c.http_status BETWEEN 200 AND 299 AND c.sha256 IS NOT NULL
              AND coalesce(c.family,'')<>'house/witness-xml' AND {addr} NOT LIKE '%wlist%'
              AND (c.family IN ('house/meeting-xml','house/Committees')
                   OR ({addr} LIKE '%docs.house.gov%' AND {xml_fmt}))"""
        if candidate_receipt_keys is not None:
            pq.write_table(pa.table({'receipt_key': pa.array(sorted(set(candidate_receipt_keys) - held), pa.string())}),
                           work / 'new-receipts.parquet')
            inputs.append(dict(name='new_receipts', kind='parquet', path=str(work / 'new-receipts.parquet')))
            new_from = 'FROM new_receipts nr JOIN captures c ON c.receipt_key=nr.receipt_key WHERE'
        else:
            new_from = 'FROM held_receipts hr RIGHT JOIN captures c ON c.receipt_key=hr.receipt_key WHERE hr.receipt_key IS NULL AND'
        steps += [
            dict(name='new_hx', materialize=True,
                 sql=f'SELECT DISTINCT c.sha256,c.receipt_key,{addr} AS addr {new_from} {hx_pred}'),
            dict(name='new_hx_shas', materialize=True, sql='SELECT DISTINCT sha256 FROM new_hx'),
            dict(name='live_hx', materialize=True,
                 sql=f'SELECT DISTINCT s.sha256 FROM new_hx_shas s JOIN captures c ON c.sha256=s.sha256 '
                     f'JOIN held_receipts hr ON hr.receipt_key=c.receipt_key WHERE {hx_pred}')]
        queries.append(dict(name='house_xml', sql="""SELECT lower(encode(n.sha256,'hex')) AS sha,n.receipt_key,n.addr
            FROM new_hx n LEFT JOIN live_hx l ON l.sha256=n.sha256 WHERE l.sha256 IS NULL ORDER BY 1,2,3"""))
    found = run_job(work / 'citations', engine, inputs=inputs, steps=steps, outputs=[], queries=queries)
    receipts = {}
    for row in found['files']:
        receipts.setdefault(row['sha'], []).append(row['receipt_key'])
    reasons = []
    for sha in cited:
        if sha not in receipts:
            reasons.append(f'automatic causes: cited file {sha[:16]} is not a body in the capture table')
        for key in receipts.get(sha, []):
            if key in held:
                reasons.append(f'automatic causes: cited file {sha[:16]} was already read by the live release ({key})')
    lines = {(r['receipt_key'], r['receipt_line'], r['capture_index']): r for r in found['reads']}
    for read in reads:
        where = f"{read['receipt_key']}:{read['receipt_line']}:{read['capture_index']}"
        line = lines.get((read['receipt_key'], read['receipt_line'], read['capture_index']))
        body = (read['body_sha256'] or '').lower() or None
        if read['receipt_key'] in held:
            reasons.append(f'automatic causes: read {where} is in a receipt the live release read')
        if line is None:
            reasons.append(f'automatic causes: read {where} is not a line in the capture table')
        elif line['sha'] != body:
            reasons.append(f"automatic causes: read {where} holds body {str(line['sha'])[:16]}, not {str(body)[:16]}")
        elif line['requested_url'] != read['source_url']:
            reasons.append(f"automatic causes: read {where} requested {line['requested_url']}, not {read['source_url']}")
        elif read['retrieved_at'] is None or line['t'] != _epoch_us(read['retrieved_at']):
            reasons.append(f"automatic causes: read {where} is dated {read['retrieved_at']}, not its capture line's time")
    if found.get('house_xml'):
        updated_set = {int(e) for e in updated_events}
        meetings_path = Path(candidate_dir) / 'meetings.parquet'
        non_senate_update = True
        if meetings_path.exists():
            schema_names = set(pq.read_schema(meetings_path).names)
            cols = [c for c in ('event_id', 'chamber', 'congress_gov_detail_observation') if c in schema_names]
            mrows = [r for r in pq.read_table(meetings_path, columns=cols).to_pylist() if r.get('event_id') in updated_set]
            non_senate_update = any(
                (r.get('chamber') or '').lower() != 'senate' if 'chamber' in schema_names
                else '/senate/' not in (((r.get('congress_gov_detail_observation') or {}).get('successful_read') or {}).get('source_url') or '').lower()
                for r in mrows)
        for row in found['house_xml']:
            addr_val = row['addr'] or ''
            ids_in_url = {int(m) for pat in _HOUSE_XML_EVENT_PATTERNS for m in pat.findall(addr_val)}
            if (ids_in_url & updated_set) or (not ids_in_url and non_senate_update):
                reasons.append(
                    f"automatic causes: new House XML body {row['sha'][:16]} ({row['receipt_key']}) accompanies an updated meeting")
    (work / 'citation-trace.json').write_text(json.dumps(dict(live_receipts=len(held), files=receipts, reads=found['reads']),
                                                          indent=1, default=str) + '\n')
    return reasons


def _url_state_rules():
    """SQL giving one reason for a url_state row the new lines do not imply, NULL when they do.

    Aliases: b (live row), c (candidate row), u (`url_pairs`, carrying `date_moved` for addresses
    whose meeting date a Congress.gov update moved), p (the address's new lines: n, and `good`, the
    time of its newest line the model's own good-fetch steps call good), x (its newest new line,
    and the interval the model's own band steps give it with the candidate's published meeting
    date), r (its newest live line and interval under the candidate's published meeting date, for
    `date_moved` rows with no later new line). Times compare as epoch microseconds. Every
    condition is written to be true or false, never NULL, so a missing value cannot pass a rule.
    """
    n = 'coalesce(p.n,0)'
    # Not here: a change to any other column, or a removed address. Each makes a comparison group
    # that automatic_causes refuses before this proof runs, so a rule for them could never fire.
    schedule = ('last_attempt', 'last_status', 'last_outcome', 'last_good_at', 'next_attempt_at', 'recheck_meeting_date')
    later = '(x.t IS NOT NULL AND (b.last_attempt IS NULL OR x.t>epoch_us(b.last_attempt)))'
    newest = ('epoch_us(c.last_attempt) IS NOT DISTINCT FROM x.t AND c.last_status IS NOT DISTINCT FROM x.s '
              'AND c.last_outcome IS NOT DISTINCT FROM x.o')
    band = ('x.interval_seconds IS NOT NULL AND epoch_us(c.next_attempt_at) IS NOT DISTINCT FROM '
            'x.t+x.interval_seconds*1000000')
    recheck_band = ('r.interval_seconds IS NOT NULL AND r.t IS NOT DISTINCT FROM epoch_us(b.last_attempt) '
                    'AND epoch_us(c.next_attempt_at) IS NOT DISTINCT FROM r.t+r.interval_seconds*1000000')
    # last_good_at as url-state.sql folds it: the later of the live value and the newest good line.
    good = ('epoch_us(c.last_good_at) IS NOT DISTINCT FROM CASE WHEN p.good IS NULL THEN epoch_us(b.last_good_at) '
            'ELSE greatest(p.good,coalesce(epoch_us(b.last_good_at),p.good)) END')
    has_pages = 'coalesce(len(c.linked_from),0)>0'
    wrong_band = 'next_attempt_at is not last_attempt plus the band of its published meeting date'
    # The band's date is anchored to the live release only where the live release had scheduled the
    # address (unless a Congress.gov meeting update moved that meeting's date); a first schedule has
    # no live value to keep.
    date = ('recheck_meeting_date changed on an address the live release had scheduled',
            'b.attempts>0 AND c.recheck_meeting_date IS DISTINCT FROM b.recheck_meeting_date AND NOT u.date_moved')
    pages = ('a page that linked a queued address is gone', 'NOT coalesce(list_has_all(c.linked_from,b.linked_from),false)')
    fetched = [
        ('changed with no new line', f'{n}=0 AND NOT u.date_moved'),
        ('attempts are not the live count plus the new lines', f'c.attempts IS DISTINCT FROM b.attempts+{n}'),
        ('the newest new line has no time', f'{n}>0 AND x.t IS NULL'),
        ('the newest new line ties the live last_attempt', f'{n}>0 AND b.last_attempt IS NOT NULL AND x.t=epoch_us(b.last_attempt)'),
        ('last_attempt, last_status or last_outcome is not the newest new line', f'{n}>0 AND {later} AND NOT ({newest})'),
        ('the latest attempt moved without a later new line', f"""{n}>0 AND NOT {later} AND (c.last_attempt IS DISTINCT FROM b.last_attempt
            OR c.last_status IS DISTINCT FROM b.last_status OR c.last_outcome IS DISTINCT FROM b.last_outcome
            OR (NOT u.date_moved AND c.next_attempt_at IS DISTINCT FROM b.next_attempt_at))"""),
        ('the latest attempt moved without a new line', f"""{n}=0 AND (c.last_attempt IS DISTINCT FROM b.last_attempt
            OR c.last_status IS DISTINCT FROM b.last_status OR c.last_outcome IS DISTINCT FROM b.last_outcome)"""),
        ('last_good_at is not the later of the live value and the newest good new line', f'NOT ({good})'),
        date,
        ('an address with attempts names linking pages', has_pages),
        (wrong_band, f'({n}>0 AND {later} AND NOT ({band})) OR (u.date_moved AND NOT ({n}>0 AND {later}) AND NOT ({recheck_band}))')]
    added = [
        ('attempts are not its new lines', f'c.attempts IS DISTINCT FROM {n}'),
        ('the newest new line has no time', 'x.t IS NULL'),
        ('last_attempt, last_status or last_outcome is not the newest new line', f'NOT ({newest})'),
        ('last_good_at is not the newest good new line', 'epoch_us(c.last_good_at) IS DISTINCT FROM p.good'),
        ('an address with attempts names linking pages', has_pages),
        (wrong_band, f'NOT ({band})')]
    queued = [('a queued address has new lines', f'{n}>0'),
              ('a queued address carries a schedule', ' OR '.join(f'c.{column} IS NOT NULL' for column in schedule))]

    def first(rules):
        return 'CASE ' + ' '.join(f"WHEN {condition} THEN '{reason}'" for reason, condition in rules) + ' END'
    return f"""CASE WHEN c.attempts IS NULL OR c.attempts<0 THEN 'invalid attempt count'
        WHEN b.requested_url IS NULL AND c.attempts>0 THEN {first(added)}
        WHEN b.requested_url IS NULL THEN {first([*queued, ('a queued address names no linking page', f'NOT {has_pages}')])}
        WHEN b.attempts=0 AND c.attempts=0 THEN {first([*queued, pages])}
        ELSE {first(fetched)} END"""


# The capture columns the gate's one engine job reads: the model's fold, good-fetch and band steps
# (url_state_lines, good-archive-containers.sql, good-fetches.sql, url_state_good_lines) and the
# body trace. The capture input is scanned once, for these only (17 of its 42 columns); a night
# with no url_state proof reads the trace's three.
CAPTURE_COLUMNS = ('receipt_key', 'receipt_line', 'capture_index', 'mode', 'outcome', 'family', 'requested_url',
                   'context_url', 'member_path', 'attempt', 'http_status', 'complete', 'fetch_http_status',
                   'fetch_outcome', 'retrieved_at', 'sha256', 'expansion')
TRACE_COLUMNS = ('receipt_key', 'receipt_line', 'sha256')


def _recheck_step(step):
    sql = step['sql']
    for old in ('captures', 'url_state_lines', 'url_state_latest', 'url_state_ages', 'url_state_interval_candidates'):
        sql = re.sub(rf'\b{old}\b', f'recheck_{old}', sql)
    return dict(step, name=f"recheck_{step['name']}", sql=sql)


def capture_job(work, engine, captures, *, keys, new_receipts=(), held_receipts=(), recheck_urls=(), candidate_state=None):
    """One engine job and one scan of the capture input, for the trace and the url_state proof.

    The scan keeps only CAPTURE_COLUMNS (TRACE_COLUMNS with no url_state part) of the rows in `new_receipts` or holding a body whose first
    16 hex digits are in `keys` (plus live captures of `recheck_urls` when a Congress.gov update
    moved their meeting date); the small sides are hash-built and the capture input is probed
    once. Returns `trace`: the receipt lines of every traced body, in every receipt (a body the
    live release also read must show), and, given `candidate_state` (the candidate's url_state
    file), `lines` and `newest` from the model's own steps over the new receipts' captures (and
    `rechecked` over live captures of `recheck_urls`).
    """
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import run_job
    from viewer_publication.archive_model import evidence_steps, registry_inputs, source_steps
    from viewer_publication.archive_url_state import url_state_steps
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({'new_key': pa.array(sorted(set(new_receipts)), pa.string())}), work / 'new-receipts.parquet')
    pq.write_table(pa.table({'prefix': pa.array(sorted(set(keys)), pa.string())}), work / 'traced-keys.parquet')
    inputs = [table_input('lake_captures', _captures_source(captures)),
              dict(name='new_receipts', kind='parquet', path=str(work / 'new-receipts.parquet')),
              dict(name='traced_keys', kind='parquet', path=str(work / 'traced-keys.parquet'))]
    columns = CAPTURE_COLUMNS if candidate_state is not None else TRACE_COLUMNS
    live_recheck = bool(candidate_state is not None and recheck_urls)
    if live_recheck:
        pq.write_table(pa.table({'held_key': pa.array(sorted(set(held_receipts)), pa.string())}), work / 'held-receipts.parquet')
        pq.write_table(pa.table({'recheck_url': pa.array(sorted(set(recheck_urls)), pa.string())}), work / 'recheck-urls.parquet')
        inputs += [dict(name='held_receipts', kind='parquet', path=str(work / 'held-receipts.parquet')),
                   dict(name='recheck_urls', kind='parquet', path=str(work / 'recheck-urls.parquet'))]
        scan_sql = f"""SELECT {','.join('c.' + c for c in columns)},
            n.new_key IS NOT NULL AS new_line,
            (h.held_key IS NOT NULL AND r.recheck_url IS NOT NULL) AS live_recheck,k.prefix
            FROM held_receipts h RIGHT JOIN (recheck_urls r RIGHT JOIN (traced_keys k RIGHT JOIN
              (new_receipts n RIGHT JOIN lake_captures c ON c.receipt_key=n.new_key)
              ON k.prefix=substr(lower(encode(c.sha256,'hex')),1,16))
              ON c.requested_url=r.recheck_url) ON c.receipt_key=h.held_key
            WHERE n.new_key IS NOT NULL OR k.prefix IS NOT NULL
              OR (h.held_key IS NOT NULL AND r.recheck_url IS NOT NULL)"""
    else:
        scan_sql = f"""SELECT {','.join('c.' + c for c in columns)},
            n.new_key IS NOT NULL AS new_line,k.prefix
            FROM traced_keys k RIGHT JOIN (new_receipts n RIGHT JOIN lake_captures c ON c.receipt_key=n.new_key)
              ON k.prefix=substr(lower(encode(c.sha256,'hex')),1,16)
            WHERE n.new_key IS NOT NULL OR k.prefix IS NOT NULL"""
    steps = [dict(name='capture_rows', materialize=True, sql=scan_sql)]
    queries = [dict(name='trace', sql="""SELECT DISTINCT prefix,receipt_key,receipt_line,lower(encode(sha256,'hex')) AS sha
        FROM capture_rows WHERE prefix IS NOT NULL ORDER BY 1,2,3""")]
    if candidate_state is not None:
        # The model's own steps, by name: the fold, the good-fetch predicate and the band.
        model = {step['name']: step for step in [*evidence_steps(), *source_steps(), *url_state_steps()]}
        inputs += [dict(name='candidate_url_state', kind='parquet', path=str(Path(candidate_state).resolve())),
                   next(item for item in registry_inputs(work / 'registries') if item['name'] == 'recheck_intervals')]
        steps += [dict(name='captures', materialize=True, sql=f"SELECT {','.join(CAPTURE_COLUMNS)} FROM capture_rows WHERE new_line"),
                  dict(name='capture_evidence', sql='SELECT * FROM captures'),
                  *(model[name] for name in ('good_archive_containers', 'good_fetches', 'good_fetch_contexts',
                                             'url_state_lines', 'url_state_good_lines', 'url_state_latest')),
                  dict(name='url_state_meeting_dates', sql="""SELECT requested_url,recheck_meeting_date AS meeting_date
                      FROM candidate_url_state WHERE recheck_meeting_date IS NOT NULL""", materialize=True),
                  model['url_state_ages'], model['url_state_interval_candidates'], model['url_state_intervals']]
        queries += [
            dict(name='lines', sql="""SELECT l.receipt_key,l.receipt_line,l.requested_url,arrow_cast(l.retrieved_at,'Int64') AS t,
                g.receipt_key IS NOT NULL AS good FROM url_state_lines l LEFT JOIN url_state_good_lines g
                ON g.receipt_key=l.receipt_key AND g.receipt_line=l.receipt_line AND g.requested_url=l.requested_url ORDER BY 1,2,3"""),
            dict(name='newest', sql="""SELECT x.requested_url,arrow_cast(x.retrieved_at,'Int64') AS t,
                cast(x.http_status AS INT) AS s,x.outcome AS o,i.interval_seconds
                FROM url_state_latest x LEFT JOIN url_state_intervals i ON i.requested_url=x.requested_url""")]
        if live_recheck:
            steps += [dict(name='recheck_captures', materialize=True,
                           sql=f"SELECT {','.join(CAPTURE_COLUMNS)} FROM capture_rows WHERE live_recheck"),
                      *(_recheck_step(model[name]) for name in (
                          'url_state_lines', 'url_state_latest', 'url_state_ages',
                          'url_state_interval_candidates', 'url_state_intervals'))]
            queries.append(dict(name='rechecked', sql="""SELECT x.requested_url,arrow_cast(x.retrieved_at,'Int64') AS t,
                i.interval_seconds FROM recheck_url_state_latest x
                LEFT JOIN recheck_url_state_intervals i ON i.requested_url=x.requested_url"""))
    return run_job(work / 'job', engine, inputs=inputs, steps=steps, outputs=[], queries=queries)


def _side_url_meetings(d, side):
    """`(url, event_id, meeting_date)` pairs for `moved_url_candidates` on `side` (`base` or `candidate`),
    mirroring `url_state_meeting_dates` (`archive_model.py`, `source-annotations-addresses.sql`)."""
    parts = [f"""SELECT u.url,m.event_id,m.meeting_date
        FROM moved_url_candidates u JOIN {side}_meetings m ON m.event_id=coalesce(
            try_cast(nullif(regexp_extract(u.url,'(?i)/committee-meeting/[0-9]+/[a-z]+/([0-9]+)',1),'') AS BIGINT),
            try_cast(nullif(regexp_extract(u.url,'(?i)[?&]eventid=([0-9]+)',1),'') AS BIGINT),
            try_cast(nullif(regexp_extract(u.url,'(?i)^https?://docs[.]house[.]gov/meetings/[^/]+/[^/]+/[0-9]{{8}}/(?:HHRG|HMKP|HMTG)?([0-9]+)(?:/|$)',1),'') AS BIGINT),
            try_cast(nullif(regexp_extract(u.url,'(?i)^https?://(?:www[.])?congress[.]gov/[0-9]+/meeting/(?:house|senate|joint)/([0-9]+)(?:/|$)',1),'') AS BIGINT))
        WHERE m.meeting_date IS NOT NULL"""]
    doc_refs = d.arrow_types(side, 'meetings').get('document_references')
    if doc_refs is not None and (pa.types.is_list(doc_refs) or pa.types.is_large_list(doc_refs)):
        url_expr = ('ref.url' if pa.types.is_struct(doc_refs.value_type) and doc_refs.value_type.get_field_index('url') >= 0
                    else 'ref')
        parts.append(f"""SELECT u.url,m.event_id,m.meeting_date FROM moved_url_candidates u
            JOIN (SELECT event_id,meeting_date,{url_expr} AS doc_url
                  FROM (SELECT event_id,meeting_date,unnest(document_references) AS ref FROM {side}_meetings
                        WHERE meeting_date IS NOT NULL AND document_references IS NOT NULL)) m
              ON u.url=m.doc_url""")
    if (d.has(side, 'sources') and d.has(side, 'list')
            and {'list_row', 'url'} <= set(d.columns(side, 'sources'))
            and 'meeting_keys' in d.columns(side, 'list')):
        parts.append(f"""SELECT u.url,m.event_id,m.meeting_date FROM moved_url_candidates u
            JOIN {side}_sources s ON u.url=s.url
            JOIN (SELECT file_row_number AS list_row,try_cast(unnest(meeting_keys) AS BIGINT) AS event_id
                  FROM {side}_list WHERE meeting_keys IS NOT NULL) l ON s.list_row=l.list_row
            JOIN {side}_meetings m ON m.event_id=l.event_id
            WHERE m.meeting_date IS NOT NULL""")
    return f"SELECT DISTINCT url,event_id,meeting_date FROM ({' UNION ALL '.join(parts)})"


def _mark_moved_meeting_dates(d, updated_events):
    """Set `url_pairs.date_moved` where a Congress.gov meeting update moved the effective
    `recheck_meeting_date` from `b.recheck_meeting_date` to `c.recheck_meeting_date` (ct-rhqw).
    Returns the `url` set of `date_moved` rows so `capture_job` can verify live bands."""
    if not updated_events or not (d.has('base', 'meetings') and d.has('candidate', 'meetings')):
        return set()
    if not {'event_id', 'meeting_date'} <= set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings')):
        return set()
    d.table('moved_url_candidates',
            'SELECT url FROM url_pairs WHERE b.attempts>0 AND b.recheck_meeting_date IS DISTINCT FROM c.recheck_meeting_date')
    if not d.one('SELECT count(*) FROM moved_url_candidates'):
        return set()
    d.table('base_url_meetings', _side_url_meetings(d, 'base'))
    d.table('cand_url_meetings', _side_url_meetings(d, 'candidate'))
    ev_list = ','.join(str(int(e)) for e in updated_events)
    fallback = "try_strptime(nullif(regexp_extract(u.url,'(?i)^https?://docs[.]house[.]gov/meetings/[^/]+/[^/]+/([0-9]{8})/',1),''),'%Y%m%d')::DATE"
    d.table('moved_url_verified', f"""WITH delta AS (
          SELECT * FROM base_url_meetings EXCEPT SELECT * FROM cand_url_meetings
          UNION ALL
          SELECT * FROM cand_url_meetings EXCEPT SELECT * FROM base_url_meetings),
        eff AS (
          SELECT u.url,
            coalesce((SELECT min(meeting_date) FROM base_url_meetings b WHERE b.url=u.url),{fallback}) AS old_eff,
            coalesce((SELECT min(meeting_date) FROM cand_url_meetings c WHERE c.url=u.url),{fallback}) AS new_eff
          FROM moved_url_candidates u)
        SELECT p.url FROM url_pairs p JOIN eff e ON e.url=p.url
        WHERE p.b.attempts>0
          AND EXISTS (SELECT 1 FROM delta d WHERE d.url=p.url)
          AND NOT EXISTS (SELECT 1 FROM delta d WHERE d.url=p.url AND d.event_id NOT IN ({ev_list}))
          AND e.old_eff IS DISTINCT FROM e.new_eff
          AND p.b.recheck_meeting_date IS NOT DISTINCT FROM e.old_eff
          AND p.c.recheck_meeting_date IS NOT DISTINCT FROM e.new_eff""")
    verified = {u for (u,) in d.rows('SELECT url FROM moved_url_verified')}
    if verified:
        d.con.execute("""CREATE OR REPLACE TEMP TABLE url_pairs AS
            SELECT u.* REPLACE ((u.url IN (SELECT url FROM moved_url_verified)) AS date_moved) FROM url_pairs u""")
    return verified


def url_state_proof(d, candidate_dir, *, engine, captures, new_receipts, work, keys=(), held_receipts=(), updated_events=()):
    """Check a capture night's url_state rows against the receipts new to the release (ct-9j3z).

    Returns (reasons, summary, page_keys, lines, trace). reasons is empty when every changed or
    added row is exactly what the new lines imply. page_keys (hex) are the pages behind newly
    queued links and lines the new (receipt_key, receipt_line, requested_url) lines; the caller
    traces both to raw. trace holds the receipt lines of `keys` (the new documents' bodies) and of
    those pages, from the same job; None when the proof stops before the job. summary counts each url_state group's rows and how many are
    implied.

    New lines: the model's own url_state_lines, run by the engine over `captures` restricted to
    `new_receipts` (the candidate's receipts absent from the live set). The model's own latest and
    band steps (archive_url_state) then give each address's newest new line and its interval, fed
    the candidate's published recheck_meeting_date. So the gate keeps no second copy of the fold or
    of the band rule; what makes this a check is its inputs: lines, times, statuses and families
    come from the capture table, which the candidate does not control, every line is confirmed in
    raw by the caller, and a meeting date the live release published must be kept unless a
    Congress.gov meeting update in `updated_events` moved that meeting's date (`_mark_moved_meeting_dates`),
    in which case `capture_job` also verifies the recomputed band against `held_receipts` (ct-rhqw).
    Per address (`_url_state_rules`):
      fetched, before or now: at least one new line (unless its meeting date moved under `updated_events`);
        attempts = live + new lines; when the newest new line is later than the live last_attempt
        (a tie refuses) it sets last_attempt, last_status and last_outcome, and next_attempt_at =
        last_attempt + its band; otherwise last_attempt, last_status and last_outcome do not move
        (and next_attempt_at moves only to last_attempt + its band under the updated meeting date);
        last_good_at is the later of the live value and the newest new line the
        model's own good-fetch steps (good-fetches.sql, url_state_good_lines) call good;
        recheck_meeting_date equals the live value when the live release had scheduled the address
        (or the updated meeting date when a Congress.gov update moved it);
        linked_from is empty; every other column is unchanged.
      added with attempts: the same with no live values, so its meeting date is taken as published;
        at most AUTOMATIC_FIRST_SCHEDULE_CAP such first schedules carrying a date in one night.
      queued (added, or queued in both): no new line, no schedule, at least one linking page, every
        live page kept; each page the live row did not list must come from new receipts only.
      Every address with a new line must have a changed or added row. A removed address, or a
      change to any other column, is its own comparison group, refused before this proof runs.
    Cannot see: a wrong meeting association on a first schedule (no live value to keep; like any
    value of an added row it is taken as published); whether a page really links its queued
    address (the reading is the model's); a change to the fold or band code that touches only new
    lines (the gate runs the same code). Taken from the capture table, not raw: a line's time,
    status and outcome (raw is read for the request URL and bodies only; review W7). Unchecked on
    an added row: its other columns, such as capture_disposition (W8). A new receipt that replays
    an older line under a new key counts as one more attempt; only a replay of the newest line is
    caught, by the tie rule (W6).
    Cost: the two url_state files are joined once here (O(rows), about 1.2M), keeping only the
    changed and added rows, each side as a struct; then `capture_job`, one scan of the capture
    input. The comparison joins the same two files once more on its own connection.
    """
    columns = {side: set(d.columns(side, 'url_state')) if d.has(side, 'url_state') else set() for side in ('base', 'candidate')}
    # Both releases must publish both facts: the rules read the live and the candidate values. The first
    # candidate with the columns meets a live release without them, once; it refuses here, plainly.
    missing = [f'automatic causes: url_state cannot be traced: {name} publishes no {", ".join(absent)}'
               for side, name in (('base', 'the live release'), ('candidate', 'the candidate'))
               if (absent := [f for f in ('recheck_meeting_date', 'linked_from') if f not in columns[side]])]
    if missing:
        return missing, {}, set(), [], None
    common = sorted(columns['base'] & columns['candidate'] - {'requested_url'})
    # The one join of the two files: changed and added rows, the live row `b` and the candidate's `c`.
    d.table('url_pairs', f"""SELECT c.requested_url AS url,b,c,false AS date_moved FROM candidate_url_state c
        LEFT JOIN base_url_state b ON b.requested_url=c.requested_url
        WHERE b.requested_url IS NULL OR {' OR '.join(f'b.{column} IS DISTINCT FROM c.{column}' for column in common)}""")
    recheck_urls = _mark_moved_meeting_dates(d, updated_events)
    pages = {key.hex() for (key,) in d.rows("""SELECT DISTINCT k FROM (SELECT url,unnest(c.linked_from) AS k FROM url_pairs WHERE c.attempts=0)
        ANTI JOIN (SELECT url,unnest(b.linked_from) AS k FROM url_pairs WHERE b.requested_url IS NOT NULL) USING(url,k)""")}
    dated = d.one('SELECT count(*) FROM url_pairs WHERE c.attempts>0 AND coalesce(b.attempts,0)=0 AND c.recheck_meeting_date IS NOT NULL')
    result = capture_job(work, engine, captures, keys=set(keys) | pages, new_receipts=new_receipts,
                         held_receipts=held_receipts, recheck_urls=recheck_urls,
                         candidate_state=Path(candidate_dir) / 'url_state.parquet')
    d.con.register('url_new_lines', pa.Table.from_pylist(result['lines'], schema=pa.schema([
        ('receipt_key', pa.string()), ('receipt_line', pa.int32()), ('requested_url', pa.string()), ('t', pa.int64()), ('good', pa.bool_())])))
    d.con.register('url_newest', pa.Table.from_pylist(result['newest'], schema=pa.schema([
        ('requested_url', pa.string()), ('t', pa.int64()), ('s', pa.int32()), ('o', pa.string()), ('interval_seconds', pa.int64())])))
    d.con.register('url_rechecked', pa.Table.from_pylist(result.get('rechecked', []), schema=pa.schema([
        ('requested_url', pa.string()), ('t', pa.int64()), ('interval_seconds', pa.int64())])))
    d.table('url_rows', f"""WITH p AS (SELECT requested_url,count(*) AS n,
          max(t) FILTER (WHERE good) AS good FROM url_new_lines GROUP BY 1)
        SELECT u.url,b.requested_url IS NOT NULL AS live,c.attempts>0 AS attempted,
          {''.join(f'b.{column} IS DISTINCT FROM c.{column} AS "moved {column}",' for column in common if column in URL_STATE_COLUMNS)}
          {_url_state_rules()} AS reason
        FROM url_pairs u LEFT JOIN p ON p.requested_url=u.url
        LEFT JOIN url_newest x ON x.requested_url=u.url
        LEFT JOIN url_rechecked r ON r.requested_url=u.url""")
    reasons = [f'automatic causes: url_state: {count} rows: {reason} (first {urls})' for reason, count, urls in d.rows(
        'SELECT reason,count(*),list(url ORDER BY url)[1:3] FROM url_rows WHERE reason IS NOT NULL GROUP BY 1 ORDER BY 1')]
    reasons += over_cap(dated, 'first schedules with a meeting date', AUTOMATIC_FIRST_SCHEDULE_CAP)
    unaccounted = d.one('SELECT count(*) FROM (SELECT DISTINCT requested_url FROM url_new_lines) ANTI JOIN url_rows ON url=requested_url')
    if unaccounted:
        reasons.append(f'automatic causes: url_state: {unaccounted} addresses with new lines have no changed or added row in the candidate')
    counts = 'SELECT count(*),count(*) FILTER (WHERE reason IS NULL) FROM url_rows WHERE '
    summary = {f'changed {column}': list(d.rows(f'{counts}live AND "moved {column}"')[0])
               for column in URL_STATE_COLUMNS if column in common}
    summary[f'added URLs: {ATTEMPTED_URLS}'] = list(d.rows(f'{counts}NOT live AND attempted')[0])
    summary[f'added URLs: {QUEUED_URLS}'] = list(d.rows(f'{counts}NOT live AND NOT attempted')[0])
    summary['first schedules with a meeting date'] = [dated, AUTOMATIC_FIRST_SCHEDULE_CAP]
    lines = [(r['receipt_key'], r['receipt_line'], r['requested_url']) for r in result['lines']]
    return reasons, summary, pages, lines, result['trace']


MEETING_UPDATES = 'meeting-updates'  # the morning report's file stem, beside the gate report (ct-rhqw)
# Meeting columns every read moves; the report names them only in its count of meetings.
QUIET = ('congress_gov_detail_observation', 'congress_gov_updated', 'publisher_status_observations')
SHOWN = ('event_id', 'title', 'meeting_date', 'publisher_status', 'document_references', 'videos', 'sittings')


def _sitting(value):
    """One sitting as the report shows it: its start and the room or place."""
    if not isinstance(value, dict):
        return str(value)
    start = value.get('start')
    if hasattr(start, 'astimezone') and getattr(start, 'tzinfo', None) is not None:
        start = start.astimezone(timezone.utc)
    when = '' if start is None else start.strftime('%Y-%m-%d %H:%MZ') if hasattr(start, 'strftime') else str(start)
    where = str(value['place']) if value.get('place') else ' '.join(
        str(value[k]) for k in ('room', 'building', 'address') if value.get(k))
    return f'{when} {where}'.strip() or '(unnamed)'


def _link(value):
    """A document or video link as the report shows it: its name, or its address."""
    if isinstance(value, dict):
        return value.get('name') or value.get('description') or value.get('url') or '(unnamed)'
    return str(value)


def _multiset_moved(before, after):
    """The items of `before` not matched one for one in `after` (whole records, so a renamed link or a
    repeated entry shows)."""
    rest, out = [json.dumps(a, sort_keys=True, default=str) for a in after], []
    for item in before:
        key = json.dumps(item, sort_keys=True, default=str)
        if key in rest:
            rest.remove(key)
        else:
            out.append(item)
    return out


def meeting_updates(report, base_dir, candidate_dir):
    """The morning report's entries (ct-rhqw): for each Congress.gov meeting the comparison set apart as
    updated (`release_comparison.updated_meetings`), what changed between the live release and the
    candidate: title, date and status as they were and are; Congress.gov witnesses added and removed
    (by name and organization) and the live witness keys the candidate map does not resolve to one
    witness; document links, videos and sittings added and removed, compared as whole records; and
    any other column that moved. Reads the two releases' meetings, witnesses and map for those
    meetings only."""
    import duckdb
    ids = report['files'].get('meetings.parquet', {}).get('congress_gov_updates') or []
    if not ids:
        return []
    con = duckdb.connect()
    con.execute('SET threads=1')
    events, occasions = ','.join(str(int(i)) for i in ids), ','.join(f"'meeting:{int(i)}'" for i in ids)
    rows = lambda path, where: con.execute(f"SELECT * FROM read_parquet('{path}') WHERE {where}").to_arrow_table().to_pylist()
    def side(directory):
        directory = Path(directory)
        meetings = {r['event_id']: r for r in rows(directory / 'meetings.parquet', f'event_id IN ({events})')}
        people = {}
        if (directory / 'witnesses.parquet').exists():
            for w in rows(directory / 'witnesses.parquet', f"source='congress_gov' AND occasion IN ({occasions})"):
                name = (w.get('name') or '(unnamed)') + (f" ({w['organization']})" if w.get('organization') else '')
                people.setdefault(int(w['occasion'].split(':')[1]), []).append((w.get('display_order') or 0, w['witness_key'], name))
        return meetings, {event: sorted(found) for event, found in people.items()}
    (old, old_people), (new, new_people) = side(base_dir), side(candidate_dir)
    base_dir, candidate_dir = Path(base_dir), Path(candidate_dir)
    quote = lambda keys: ','.join("'" + str(k).replace("'", "''") + "'" for k in keys)
    lost = {}
    old_keys = {key: (event, name) for event, found in old_people.items() for _, key, name in found}
    hist_keys = {}
    if (base_dir / 'witness_key_map.parquet').exists():
        map_cols = set(pq.read_schema(base_dir / 'witness_key_map.parquet').names)
        if {'old_key', 'status', 'occasion', 'source'} <= map_cols:
            for r in rows(base_dir / 'witness_key_map.parquet', f"source='congress_gov' AND occasion IN ({occasions})"):
                if r['old_key'] not in old_keys:
                    hist_keys[r['old_key']] = (int(r['occasion'].split(':')[1]), 'historical', r['status'] == 'unambiguous')
    tracked = [(k, ev, name, True) for k, (ev, name) in old_keys.items()] + [
        (k, ev, label, ok) for k, (ev, label, ok) in hist_keys.items()]
    if tracked:
        current_by_event = {event: {key for _, key, _ in found} for event, found in new_people.items()}
        cand_map = ({r['old_key']: r for r in rows(candidate_dir / 'witness_key_map.parquet', f"old_key IN ({quote([k for k, *_ in tracked])})")}
                    if (candidate_dir / 'witness_key_map.parquet').exists() else {})
        targets = {m['witness_key'] for m in cand_map.values() if m.get('witness_key')} | {k for k, *_ in tracked}
        published = ({r['witness_key'] for r in rows(candidate_dir / 'witnesses.parquet', f'witness_key IN ({quote(targets)})')}
                     if targets and (candidate_dir / 'witnesses.parquet').exists() else set())
        collisions = set()
        check_targets = ({m['witness_key'] for m in cand_map.values() if m.get('status') == 'unambiguous' and m.get('witness_key') in published}
                         | {k for keys in current_by_event.values() for k in keys})
        if check_targets and (candidate_dir / 'witness_key_map.parquet').exists() and (candidate_dir / 'witnesses.parquet').exists():
            from viewer_publication.release_comparison import witness_collision_sql
            con.execute(f"""CREATE TEMP VIEW rc_targets AS SELECT m.old_key,m.witness_key
              FROM read_parquet('{candidate_dir / 'witness_key_map.parquet'}') m
              JOIN read_parquet('{candidate_dir / 'witnesses.parquet'}') w USING(witness_key)
              WHERE m.status='unambiguous' AND m.witness_key IN ({quote(check_targets)})""")
            bw_rel = f"read_parquet('{base_dir / 'witnesses.parquet'}')" if (base_dir / 'witnesses.parquet').exists() else None
            bm_path = base_dir / 'witness_key_map.parquet'
            bm_ok = bm_path.exists() and {'old_key', 'witness_key', 'status'} <= set(pq.read_schema(bm_path).names)
            bm_rel = f"read_parquet('{bm_path}')" if bm_ok else None
            collisions = {r[0] for r in con.execute(witness_collision_sql(
                rc_rel='rc_targets', base_witnesses_rel=bw_rel, base_map_rel=bm_rel, has_base_map_cols=bm_ok)).fetchall()}
        for key, event, label, was_unambiguous in tracked:
            on_event = current_by_event.get(event, set())
            if key in on_event:
                if key in collisions:
                    lost.setdefault(event, []).append(f'{key} ({label}): collides on {key}')
                continue
            if not was_unambiguous:
                if key not in cand_map and key not in published:
                    lost.setdefault(event, []).append(f'{key} ({label}): no map row')
                continue
            m = cand_map.get(key)
            if m is None:
                reason = f'not on meeting:{event}' if key in published else 'no map row'
                lost.setdefault(event, []).append(f'{key} ({label}): {reason}')
            elif m['status'] != 'unambiguous':
                lost.setdefault(event, []).append(f"{key} ({label}): {m['status']}")
            else:
                wk = m.get('witness_key')
                if not wk or wk not in published:
                    lost.setdefault(event, []).append(f'{key} ({label}): successor {wk} not published')
                elif wk not in on_event or (m.get('occasion') is not None and m.get('occasion') != f'meeting:{event}') or (
                        m.get('source') is not None and m.get('source') != 'congress_gov'):
                    lost.setdefault(event, []).append(f'{key} ({label}): successor {wk} not on meeting:{event}')
                elif wk in collisions:
                    lost.setdefault(event, []).append(f'{key} ({label}): collides on {wk}')
    result = []
    for event in ids:
        now, was = new[event], old.get(event)
        entry = dict(event_id=event, title=now.get('title'), meeting_date=str(now['meeting_date']) if now.get('meeting_date') else None,
                     first_stated=was is None)
        for key in ('title', 'meeting_date', 'publisher_status'):
            if was is not None and was.get(key) != now.get(key):
                entry[key + '_was'] = None if was.get(key) is None else str(was.get(key))
                entry[key + '_now'] = None if now.get(key) is None else str(now.get(key))
        for key, label, show in (('document_references', 'documents', _link), ('videos', 'videos', _link), ('sittings', 'sittings', _sitting)):
            before, after = (was or {}).get(key) or [], now.get(key) or []
            entry[label + '_added'] = [show(v) for v in _multiset_moved(after, before)]
            entry[label + '_removed'] = [show(v) for v in _multiset_moved(before, after)]
        people_before = [name for _, _, name in old_people.get(event, [])]
        people_after = [name for _, _, name in new_people.get(event, [])]
        entry['witnesses_added'] = _multiset_moved(people_after, people_before)
        entry['witnesses_removed'] = _multiset_moved(people_before, people_after)
        entry['keys_lost'] = sorted(lost.get(event, []))
        entry['also_changed'] = sorted(k for k in now if k not in (*SHOWN, *QUIET) and was is not None and was.get(k) != now.get(k))
        result.append(entry)
    return result


def _plural(n, word):
    return f'{n} {word}' + ('' if n == 1 else 'es' if word.endswith('s') else 's')


def write_meeting_updates(report, base_dir, candidate_dir, folder, refused=()):
    """Write the morning report as `meeting-updates.txt` (plain, one block per meeting) and
    `meeting-updates.json` (the entries, whether the release check cleared, and one summary `line` for
    the nightly summary) into `folder`, when the comparison names any Congress.gov meeting update. A
    night the gates `refused` says so first, with its reasons: its updates waited, none published.
    Later publication steps can still stop a cleared night; the nightly summary's status says so.
    Returns the line, or None."""
    entries = meeting_updates(report, base_dir, candidate_dir)
    if not entries:
        return None
    count = _plural(len(entries), 'Congress.gov meeting update')
    pair = f"{report['base_release'][:12]} to {report['candidate_release'][:12]}"
    if refused:
        text = [f'STOPPED at the release check, nothing published ({pair}): {count} waited, for these reasons (ct-rhqw):',
                *(f'  {reason}' for reason in list(refused)[:10]), *([f'  and {len(refused) - 10} more'] if len(refused) > 10 else []), '']
    else:
        text = [f'Cleared the release check: {count} ({pair}, ct-rhqw).', '']
    parts = []
    for e in entries:
        head = f"{e['event_id']} {e['title'] or '(no title)'} ({e['meeting_date'] or 'no date'})"
        text.append(head + (' - first stated' if e['first_stated'] else ''))
        changed = ['new'] if e['first_stated'] else []
        for key, label in (('title', 'title'), ('meeting_date', 'date'), ('publisher_status', 'status')):
            if key + '_was' in e:
                text.append(f"  {label}: {e[key + '_was']} -> {e[key + '_now']}")
                changed.append(label)
        for key, noun in (('witnesses', 'witness'), ('documents', 'document'), ('videos', 'video'), ('sittings', 'sitting')):
            for direction, sign in (('added', '+'), ('removed', '-')):
                found = e[f'{key}_{direction}']
                if found:
                    text.append(f'  {key} {direction}: ' + '; '.join(found))
                    changed.append(sign + _plural(len(found), noun))
        if e['keys_lost']:
            text.append('  witness keys lost (no single successor): ' + '; '.join(e['keys_lost']))
            changed.append(_plural(len(e['keys_lost']), 'lost key'))
        if e['also_changed']:
            text.append('  also changed: ' + ', '.join(e['also_changed']))
            changed += e['also_changed']
        if text[-1] == head and not e['first_stated']:
            text.append('  read again with new bytes; no title, date, status, witness, document, video or sitting change')
        parts.append(f"{e['event_id']} ({', '.join(changed) or 'read again'})")
        text.append('')
    shown = parts[:12] + ([f'and {len(parts) - 12} more'] if len(parts) > 12 else [])
    line = (f"STOPPED at the release check, nothing published; {count} waited: " if refused
            else f"Cleared the release check with {count}: ") + '; '.join(shown)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{MEETING_UPDATES}.txt').write_text('\n'.join(text))
    (folder / f'{MEETING_UPDATES}.json').write_text(json.dumps(dict(line=line, cleared=not refused, reasons=list(refused),
                                                                   meetings=entries), indent=1, default=str) + '\n')
    return line


def automatic_causes(report, base_dir, candidate_dir, *, engine, captures, live_receipt_keys, read_receipt, work,
                     candidate_receipt_keys=None):
    """Cause entries for a difference whose every row comes from receipts new to the release.

    Returns (entries, reasons); entries is empty unless every check passes: the proof is all or
    nothing, because a change no receipt explains is a sign that something else moved (a code or
    policy change), and while one stands no addition is attributed to receipts without a person.
    A new document is a candidate row none of whose link keys an earlier release published. Its
    body keys are joined to `captures` (the capture mapping, not the archive model) to find the
    receipt lines holding those bodies. A key the live release retired is absent from its links
    too, but a document that comes back is not new: published again, its key leaves the ledger,
    and that `retired_links` group is not an addition, so the proof stops above. Each line is then
    read from raw: its key must be outside the live release's receipt set, and the line itself must
    name the body's SHA-256. The set is the live release's own input record (every key its
    captures were read from), so "new" is by key, whatever the key's date: a backlog read oldest
    first is new without being recent (ct-gc99). Every capture line of a new document must
    qualify, so a body the live release also read is not new. Link, source and lookup additions
    must sit on new documents only. At most AUTOMATIC_ADDITION_CAP documents may be added this way
    in one night.
    url_state (ct-9j3z): every changed, added or removed row must be exactly what the lines of the
    candidate's receipts outside the live set imply (`url_state_proof`); each such line must be in
    raw with its own requested_url equal to the address, and each page behind a newly queued link is traced like a new
    document's body. This replaces ct-ud0b's rule that an added attempted address must have
    supplied a new document: a failed or repeated fetch is still a fetch.
    Cannot see: a bug that adds only wrong rows (wrong values on genuinely new receipts), or a
    new row whose receipts are new while the code that made it changed; the other gates still run.
    """
    from viewer_publication.release_comparison import Diff, documents
    reasons = []
    groups = report['failing']
    if not report['link_rule']['ok']:
        return [], ['automatic causes: the link rule failed']
    # Include already verified differences when deciding whether this is addition-only. The
    # re-fetch groups (ct-syp1 cache files, ct-uywf witness re-keys and meeting reads) change no
    # content, so they do not stop this proof; they get their own check below, against the capture
    # table. Any other verified group still stops it.
    every = [dict(group, file=name) for name, facts in report['files'].items() for group in facts['groups']]
    differences = [g for g in every if not g.get('refetch_only')]
    url_state = [g for g in differences if g['file'] == 'url_state.parquet' and (g['group'], g['cause']) in URL_STATE_GROUPS]
    other = [g for g in differences if g not in url_state and (
        g.get('value') or g['count'] <= 0 or (g['file'], g['group']) not in AUTOMATIC_GROUPS)]
    if other:
        return [], [f'automatic causes: {group_id(g)} ({g["count"]}) is not an addition that can be traced' for g in other]
    if len(every) == 0:
        return [], []
    held = set(live_receipt_keys)
    if not held:
        # With nothing to be absent from, every receipt would count as new.
        return [], ['automatic causes: the live release has no receipt set to compare with']
    updated_events = report['files'].get('meetings.parquet', {}).get('congress_gov_updates') or []
    if len(every) > len(differences):
        reasons = cited_files_are_new(base_dir, candidate_dir, engine=engine, captures=captures, held=held,
                                      work=Path(work) / 'cited', updated_events=updated_events,
                                      candidate_receipt_keys=candidate_receipt_keys)
        if reasons or not differences:
            return [], reasons
    d = Diff(Path(base_dir), Path(candidate_dir))
    d.documents = documents(d)
    d.table('added_documents', 'SELECT file_row_number::INT r FROM candidate_list ANTI JOIN pairs ON file_row_number=lr')
    added = d.one('SELECT count(*) FROM added_documents')
    reasons += over_cap(added, 'added documents', AUTOMATIC_ADDITION_CAP)
    for table, fields in (('sources', 'url,member_path'), ('urls', 'lookup_key')):
        if d.has('candidate', table) and d.has('base', table):
            stray = d.one(f"""SELECT count(*) FROM (SELECT list_row,{fields} FROM candidate_{table}
                WHERE list_row NOT IN (SELECT r FROM added_documents)
                EXCEPT SELECT x.lr,{','.join('p.' + f for f in fields.split(','))} FROM base_{table} p JOIN pairs x ON p.list_row=x.pr)""")
            if stray:
                reasons.append(f'automatic causes: {stray} {table} rows were added to existing documents')
    keys = [r[0] for r in d.rows("SELECT DISTINCT lower(hex(link_key)) FROM candidate_links WHERE list_row IN (SELECT r FROM added_documents) ORDER BY 1")]
    # A new document has no link key in the base. Its keys must account for
    # every added link key already counted by the comparison.
    added_links = sum(g['count'] for g in differences if (g['file'], g['group']) == ('links.parquet', 'added keys'))
    if len(keys) != added_links:
        reasons.append(f'automatic causes: {added_links} added link keys, {len(keys)} attached to new documents')
    if not keys and len(url_state) < len(differences):
        reasons.append('automatic causes: no new document carries a key to trace')
    if reasons:
        return [], reasons
    # From here every check runs and every reason is kept, so a refused night names all it found.
    # One engine job for the trace and the url_state proof: one scan of the capture input.
    summary, pages, url_lines, lines = {}, set(), [], None
    work = Path(work)
    if url_state and candidate_receipt_keys is None:
        reasons.append("automatic causes: url_state needs the candidate's receipt set")
    elif url_state:
        reasons, summary, pages, url_lines, lines = url_state_proof(
            d, candidate_dir, engine=engine, captures=captures, new_receipts=set(candidate_receipt_keys) - held,
            held_receipts=held, updated_events=updated_events, work=work / 'url-state', keys=keys)
    if lines is None:
        lines = capture_job(work / 'trace', engine, captures, keys=set(keys))['trace'] if keys else []
    work.mkdir(parents=True, exist_ok=True)
    traced = {row['prefix'] for row in lines}
    for kind, missing in (('new document', [k for k in keys if k not in traced]), ('queued link page', sorted(pages - traced))):
        if missing:
            reasons.append(f'automatic causes: {len(missing)} {kind} keys have no capture to trace (first {missing[:3]})')
    raw, facts = {}, {}

    def line_facts(key, line):
        """One raw receipt line's bodies and strings, each receipt read once."""
        if key not in raw:
            with gzip.open(BytesIO(read_receipt(key)), 'rt') as stream:
                raw[key] = stream.read().splitlines()
        if (key, line) not in facts:
            text = raw[key]
            facts[key, line] = _raw_line_facts(text[line - 1]) if isinstance(line, int) and 1 <= line <= len(text) else (set(), set())
        return facts[key, line]
    for row in lines:
        key = row['receipt_key']
        if key in held:
            reasons.append(f'automatic causes: {key} is already in the live release')
        elif row['sha'] not in line_facts(key, row['receipt_line'])[0]:
            reasons.append(f'automatic causes: {key}:{row["receipt_line"]} does not name body {row["sha"][:12]} in raw')
    for key, line, url in url_lines:
        request = line_facts(key, line)[1]
        if request is None:
            reasons.append(f'automatic causes: {key}:{line} names no requested_url in raw, so it cannot be matched to {url}')
        elif request != url:
            reasons.append(f'automatic causes: {key}:{line} requests {request} in raw, not {url}')
    if reasons:
        return [], sorted(set(reasons))
    evidence = work / 'automatic-trace.json'
    evidence.write_text(json.dumps(dict(live_receipts=len(held), new_receipts=len(raw), lines=lines,
                                        url_state=dict(groups=summary, lines=len(url_lines), queued_link_pages=sorted(pages))),
                                   indent=1, default=str) + '\n')
    from congress_api.retention.provenance import file_pin
    pin = dict(path=str(evidence), **file_pin(evidence))
    bookkeeping = {group_id(g) for g in url_state}
    return [dict(id=group_id(g), count=g['count'], disposition='explained', evidence=[pin], automatic=True,
                 **(dict(cause=URL_STATE_CAUSE, tickets=['ct-9j3z']) if group_id(g) in bookkeeping else
                    dict(cause=AUTOMATIC_CAUSE, tickets=['ct-ud0b']))) for g in groups], []


def group_id(group):
    return f'{group["file"]}|{group["group"]}|{group["cause"]}'


def named_corrections(rule, corrections):
    """Split the link rule's changed answers into those a correction names and the rest (ct-4nax).

    Owner decision 2026-11-10, "Accept named corrections": a live link key, lookup key or address
    that answers another file passes only where the reviewed record names it as a correction: same
    kind, same key, and both bodies equal to the report's (for a lookup key or address, every
    candidate row it reaches shows that one file). Returns ({kind: waived keys}, {kind: refusal
    reasons}, reasons for corrections that match nothing). A key with any unnamed answer is
    refused; so is every key beyond the report's sample, which no entry can be matched against;
    and an entry that waives nothing refuses the record, so a stale or padded list cannot pass.
    One dictionary of corrections, one pass over the answers: O(findings + corrections).
    The bodies compared are the gate's own comparison's, never the record's.
    Cannot see: whether the candidate file is the right document, or whether a change was meant
    at all. A list copied from the report passes; only the review stands between them. That is
    the reviewed record's claim; ct-faan is the form that proves it from the published rejection
    records.
    """
    named = {(c['kind'], c['key'], c['live_body']): c['candidate_body'] for c in corrections}
    used, waived, refused = set(), {}, {}
    for kind, (prefix, what) in CORRECTED.items():
        answers, unnamed = rule[f'{prefix}changed_answers'], set()
        for answer in answers:
            name = (kind, answer['key'], answer['live_body'])
            shown = [answer['candidate_body']] if kind == 'link_key' else answer['candidate_bodies']
            if name in named and shown == [named[name]]:
                used.add(name)
            else:
                unnamed.add(answer['key'])
        listed = sorted({answer['key'] for answer in answers})
        waived[kind] = [key for key in listed if key not in unnamed]
        beyond = max(rule[f'{prefix}changed'] - len(listed), 0)
        refused[kind] = []
        if unnamed or beyond:
            # ct-4qld, ct-wscb: every key is named, up to the report's sample; the report has its files.
            keys = f' ({", ".join(sorted(unnamed))})' if unnamed else ''
            refused[kind].append(f'link rule: {len(unnamed) + beyond} live {what} answer another file{keys}')
        if beyond:
            refused[kind].append(f'link rule: {beyond} live {what} that answer another file are beyond the '
                                 f"report's sample, so no correction can name them")
    # Whole bodies: a correction one character off must be told apart from the report's.
    stale = [f'cause record: correction {kind} {key} from {live} to {named[kind, key, live]} matches no finding of the link rule'
             for kind, key, live in sorted(set(named) - used)]
    return waived, refused, stale


def verdict(report, causes):
    """Every reason the gates refuse, each naming the rule it broke.

    A vanished key (missing), a successor that is not a published key (dangling) and a check that
    could not run (unchecked) refuse whatever the record says: no record field touches them. A
    link key, lookup key or address that answers another file refuses unless the record, bound to
    this base and candidate, names it as a correction (`named_corrections`, ct-4nax). Also records
    in report['named_corrections'] how many keys of each kind a correction let through, and which.
    """
    reasons = []
    rule = report['link_rule']
    bound = causes is not None and (causes['base_release_id'], causes['candidate_release_id']) == (
        report['base_release'], report['candidate_release'])
    waived, refused, stale = named_corrections(rule, causes.get('corrections', []) if bound else [])
    report['named_corrections'] = {kind: dict(waived=len(keys), keys=keys) for kind, keys in waived.items()}
    if rule['missing']:
        reasons.append(f'link rule: {rule["missing"]} base link keys vanish (first {rule["missing_keys"][:5]})')
    if rule['dangling']:
        reasons.append(f'link rule: {rule["dangling"]} successors are not published keys (first {rule["dangling_keys"][:5]})')
    reasons += refused['link_key']
    for missing_input in rule['unchecked']:
        reasons.append(f'link rule: not checked: {missing_input}')
    reasons += refused['lookup_key'] + refused['address']
    actual = {group_id(g): g['count'] for g in report['failing']}
    entries = {e['id']: e for e in (causes or {}).get('groups', [])}
    if causes is not None:
        for side, key in (('base', 'base_release'), ('candidate', 'candidate_release')):
            if causes[f'{side}_release_id'] != report[key]:
                reasons.append(f'cause record: bound to {side} {causes[f"{side}_release_id"][:12]}, actual {report[key][:12]}')
    reasons += stale
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
    # ct-rhqw: the morning report, written once the night's outcome is known.
    write_meeting_updates(report, base_dir, candidate_dir, report_path.parent, refused=report['reasons'])
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
              f'{removed} show a removal notice. 0 vanish.', '']
    corrections = causes.get('corrections', [])
    if corrections:
        lines += [f'{len(corrections)} keys and addresses now answer another file on purpose, each named in the reviewed '
                  'cause record with both files (ct-4nax):', '',
                  '| Kind | Key | Live file | Now | Decision | Tickets |', '| --- | --- | --- | --- | --- | --- |']
        lines += [f'| {c["kind"]} | `{c["key"]}` | `{c["live_body"][:12]}` | `{c["candidate_body"][:12]}` | {c["decision"]} | '
                  f'{", ".join(c["tickets"])} |' for c in corrections]
        lines.append('')
    lines += ['## Row changes', '', '| File | Group | Cause | Count | Disposition | Tickets |', '| --- | --- | --- | --- | --- | --- |']
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
    notes.add_argument('--output-dir', type=Path, default=ROOT / 'docs/releases')
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
            report = require_release_gates(args.base, args.candidate, causes, report_path=args.output,
                                           evidence_base=args.evidence_base, evidence_candidate=args.evidence_candidate)
            waived = ', '.join(f'{n["waived"]} {kind}' for kind, n in report.get('named_corrections', {}).items() if n['waived'])
            print('release gates passed' + (f'; named corrections let through {waived}' if waived else ''))
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
