"""Gates 1 and 2 (ct-tk10) in the publish path: compare with the live release, keep every link key.

`require_release_gates` runs `release_comparison.compare` on the local candidate and the
fetched base (live) release, writes the report, then refuses unless
  - the link rule finds no missing key, no dangling key and no live link key, lookup key or
    address answering another file (no record can override it), and
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

from viewer_publication.release_comparison import ATTEMPTED_URLS, QUEUED_URLS

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
# meeting date to keep, so the band's date is taken as published. 500 is the coordinator's
# decision of 2026-11-10, made from an estimate of about 360. Measured since on that night's pair:
# at least 663 of 5,325 first schedules carried a date (a band longer than the shortest), 630 of
# them among the 1,132 the 2026-11-08 capture day fetched and 33 among the 4,193 from the
# 2026-10-31 backlog. So 500 stops a capture day like 2026-11-08.
AUTOMATIC_FIRST_SCHEDULE_CAP = 500


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


def cited_files_are_new(base_dir, candidate_dir, *, engine, captures, held, work):
    """Reasons a citation-only change cannot pass without a person (ct-syp1); empty when it can.

    The comparison shows only that the candidate is consistent with itself. Here every file hash
    the candidate cites for the first time (`release_comparison.new_citations`) is looked up in
    `captures`, which the candidate does not control: it must be the SHA-256 of a captured body,
    and every receipt holding that body must be absent from the live release's receipt set. So a
    made-up hash, and a file the live release could already have cited, both refuse.
    One engine query joining about 70 hashes to captures; the evidence file lists each hash's
    receipts. Cannot see: whether the file holds the published values, or the raw receipt line
    (the capture mapping is trusted for the hash; documents are checked against raw).
    """
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import run_job
    from viewer_publication.release_comparison import new_citations
    cited = new_citations(base_dir, candidate_dir)
    if not cited:
        return ['automatic causes: citations moved, but the candidate cites no file the live release does not']
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({'sha': cited}), work / 'cited-files.parquet')
    rows = run_job(work / 'citations', engine, inputs=[table_input('captures', _captures_source(captures)),
        dict(name='cited_files', kind='parquet', path=str(work / 'cited-files.parquet'))], steps=[], outputs=[],
        queries=[dict(name='files', sql="""SELECT DISTINCT k.sha,c.receipt_key FROM cited_files k
            JOIN captures c ON lower(encode(c.sha256,'hex'))=k.sha WHERE c.sha256 IS NOT NULL ORDER BY 1,2""")])['files']
    receipts = {}
    for row in rows:
        receipts.setdefault(row['sha'], []).append(row['receipt_key'])
    reasons = []
    for sha in cited:
        if sha not in receipts:
            reasons.append(f'automatic causes: cited file {sha[:16]} is not a body in the capture table')
        for key in receipts.get(sha, []):
            if key in held:
                reasons.append(f'automatic causes: cited file {sha[:16]} was already read by the live release ({key})')
    (work / 'citation-trace.json').write_text(json.dumps(dict(live_receipts=len(held), files=receipts), indent=1) + '\n')
    return reasons


def _url_state_rules():
    """SQL giving one reason for a url_state row the new lines do not imply, NULL when they do.

    Aliases: b (live row), c (candidate row), p (the address's new lines: n, and `good`, the time of
    its newest line the model's own good-fetch steps call good), x (its newest new line, and the
    interval the model's own band steps give it with the candidate's published meeting date).
    Times compare as epoch microseconds. Every
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
    # last_good_at as url-state.sql folds it: the later of the live value and the newest good line.
    good = ('epoch_us(c.last_good_at) IS NOT DISTINCT FROM CASE WHEN p.good IS NULL THEN epoch_us(b.last_good_at) '
            'ELSE greatest(p.good,coalesce(epoch_us(b.last_good_at),p.good)) END')
    has_pages = 'coalesce(len(c.linked_from),0)>0'
    wrong_band = 'next_attempt_at is not last_attempt plus the band of its published meeting date'
    # The band's date is anchored to the live release only where the live release had scheduled the
    # address; a first schedule has no live value to keep.
    date = ('recheck_meeting_date changed on an address the live release had scheduled',
            'b.attempts>0 AND c.recheck_meeting_date IS DISTINCT FROM b.recheck_meeting_date')
    pages = ('a page that linked a queued address is gone', 'NOT coalesce(list_has_all(c.linked_from,b.linked_from),false)')
    fetched = [
        ('changed with no new line', f'{n}=0'),
        ('attempts are not the live count plus the new lines', f'c.attempts IS DISTINCT FROM b.attempts+{n}'),
        ('the newest new line has no time', 'x.t IS NULL'),
        ('the newest new line ties the live last_attempt', 'b.last_attempt IS NOT NULL AND x.t=epoch_us(b.last_attempt)'),
        ('last_attempt, last_status or last_outcome is not the newest new line', f'{later} AND NOT ({newest})'),
        ('the latest attempt moved without a later new line', f"""NOT {later} AND (c.last_attempt IS DISTINCT FROM b.last_attempt
            OR c.last_status IS DISTINCT FROM b.last_status OR c.last_outcome IS DISTINCT FROM b.last_outcome
            OR c.next_attempt_at IS DISTINCT FROM b.next_attempt_at)"""),
        ('last_good_at is not the later of the live value and the newest good new line', f'NOT ({good})'),
        date,
        ('an address with attempts names linking pages', has_pages),
        (wrong_band, f'{later} AND NOT ({band})')]
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


def capture_job(work, engine, captures, *, keys, new_receipts=(), candidate_state=None):
    """One engine job and one scan of the capture input, for the trace and the url_state proof.

    The scan keeps only CAPTURE_COLUMNS (TRACE_COLUMNS with no url_state part) of the rows in `new_receipts` or holding a body whose first
    16 hex digits are in `keys`; both small sides are hash-built and the capture input is probed
    once. Returns `trace`: the receipt lines of every traced body, in every receipt (a body the
    live release also read must show), and, given `candidate_state` (the candidate's url_state
    file), `lines` and `newest` from the model's own steps over the new receipts' captures.
    """
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import run_job
    from viewer_publication.archive_model import evidence_steps, registry_inputs, source_steps
    from viewer_publication.archive_url_state import url_state_steps
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({'receipt_key': pa.array(sorted(new_receipts), pa.string())}), work / 'new-receipts.parquet')
    pq.write_table(pa.table({'prefix': pa.array(sorted(keys), pa.string())}), work / 'traced-keys.parquet')
    inputs = [table_input('lake_captures', _captures_source(captures)),
              dict(name='new_receipts', kind='parquet', path=str(work / 'new-receipts.parquet')),
              dict(name='traced_keys', kind='parquet', path=str(work / 'traced-keys.parquet'))]
    columns = CAPTURE_COLUMNS if candidate_state is not None else TRACE_COLUMNS
    steps = [dict(name='capture_rows', materialize=True, sql=f"""SELECT {','.join('c.' + c for c in columns)},
        n.receipt_key IS NOT NULL AS new_line,k.prefix
        FROM traced_keys k RIGHT JOIN (new_receipts n RIGHT JOIN lake_captures c ON c.receipt_key=n.receipt_key)
          ON k.prefix=substr(lower(encode(c.sha256,'hex')),1,16)
        WHERE n.receipt_key IS NOT NULL OR k.prefix IS NOT NULL""")]
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
    return run_job(work / 'job', engine, inputs=inputs, steps=steps, outputs=[], queries=queries)


def url_state_proof(d, candidate_dir, *, engine, captures, new_receipts, work, keys=()):
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
    raw by the caller, and a meeting date the live release published must be kept.
    Per address (`_url_state_rules`):
      fetched, before or now: at least one new line; attempts = live + new lines; when the newest
        new line is later than the live last_attempt (a tie refuses) it sets last_attempt,
        last_status and last_outcome, and next_attempt_at = last_attempt + its band; otherwise none
        of those moves; last_good_at is the later of the live value and the newest new line the
        model's own good-fetch steps (good-fetches.sql, url_state_good_lines) call good;
        recheck_meeting_date equals the live value when the live release had scheduled the address;
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
    d.table('url_pairs', f"""SELECT c.requested_url AS url,b,c FROM candidate_url_state c
        LEFT JOIN base_url_state b ON b.requested_url=c.requested_url
        WHERE b.requested_url IS NULL OR {' OR '.join(f'b.{column} IS DISTINCT FROM c.{column}' for column in common)}""")
    pages = {key.hex() for (key,) in d.rows("""SELECT DISTINCT k FROM (SELECT url,unnest(c.linked_from) AS k FROM url_pairs WHERE c.attempts=0)
        ANTI JOIN (SELECT url,unnest(b.linked_from) AS k FROM url_pairs WHERE b.requested_url IS NOT NULL) USING(url,k)""")}
    dated = d.one('SELECT count(*) FROM url_pairs WHERE c.attempts>0 AND coalesce(b.attempts,0)=0 AND c.recheck_meeting_date IS NOT NULL')
    result = capture_job(work, engine, captures, keys=set(keys) | pages, new_receipts=new_receipts,
                         candidate_state=Path(candidate_dir) / 'url_state.parquet')
    d.con.register('url_new_lines', pa.Table.from_pylist(result['lines'], schema=pa.schema([
        ('receipt_key', pa.string()), ('receipt_line', pa.int32()), ('requested_url', pa.string()), ('t', pa.int64()), ('good', pa.bool_())])))
    d.con.register('url_newest', pa.Table.from_pylist(result['newest'], schema=pa.schema([
        ('requested_url', pa.string()), ('t', pa.int64()), ('s', pa.int32()), ('o', pa.string()), ('interval_seconds', pa.int64())])))
    d.table('url_rows', f"""WITH p AS (SELECT requested_url,count(*) AS n,
          max(t) FILTER (WHERE good) AS good FROM url_new_lines GROUP BY 1)
        SELECT u.url,b.requested_url IS NOT NULL AS live,c.attempts>0 AS attempted,
          {''.join(f'b.{column} IS DISTINCT FROM c.{column} AS "moved {column}",' for column in common if column in URL_STATE_COLUMNS)}
          {_url_state_rules()} AS reason
        FROM url_pairs u LEFT JOIN p ON p.requested_url=u.url LEFT JOIN url_newest x ON x.requested_url=u.url""")
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
    # citation-only groups (ct-syp1) change no content, so they do not stop this proof; they get
    # their own check below, against the capture table.
    every = [dict(group, file=name) for name, facts in report['files'].items() for group in facts['groups']]
    differences = [g for g in every if not g.get('citation_only')]
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
    if len(every) > len(differences):
        reasons = cited_files_are_new(base_dir, candidate_dir, engine=engine, captures=captures, held=held, work=Path(work) / 'cited')
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
        reasons, summary, pages, url_lines, lines = url_state_proof(d, candidate_dir, engine=engine, captures=captures,
            new_receipts=set(candidate_receipt_keys) - held, work=work / 'url-state', keys=keys)
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


def verdict(report, causes):
    """Every reason the gates refuse, each naming the rule it broke."""
    reasons = []
    rule = report['link_rule']
    if rule['missing']:
        reasons.append(f'link rule: {rule["missing"]} base link keys vanish (first {rule["missing_keys"][:5]})')
    if rule['dangling']:
        reasons.append(f'link rule: {rule["dangling"]} successors are not published keys (first {rule["dangling_keys"][:5]})')
    if rule['changed']:
        # ct-4qld: every key is named, up to the report's sample; the report has each one's two files.
        reasons.append(f'link rule: {rule["changed"]} live link keys answer another file ({", ".join(rule["changed_keys"])})')
    for missing_input in rule['unchecked']:
        reasons.append(f'link rule: not checked: {missing_input}')
    for label, what in (('lookup', 'lookup keys'), ('address', 'addresses')):  # ct-wscb
        if rule[f'{label}_changed']:
            reasons.append(f'link rule: {rule[f"{label}_changed"]} live {what} answer another file ({", ".join(rule[f"{label}_changed_keys"])})')
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
