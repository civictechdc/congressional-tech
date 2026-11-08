"""Gate 5 (ct-tk10): every pinned derived row names the code that produced it.

Rule (lead decision 2026-11-02): each row carries its producer's byte-hashed version,
and that version must be the current definition or one registered as compatible in
model/registries/compatible-versions.json (ct-deh9).
  - captures: `mapping_version` (captures.current_version(), written by the captures
    stage; cluster e1 adds the column). Every row is consumed, so every row must carry a
    current or compatible mapping. NULL or unknown refuses. v21 captures, written by an
    unrecorded pyarrow writer, carry none and are refused; the ct-kunv rebuild carries it.
  - readings, filename_readings, meeting/appearance/video/committee/playlist records:
    `parser_version` / `catalog_version`. The publish spec's pins must equal the current
    definitions (archive_model_job.validate_spec) and the model reads only rows at those
    versions (pinned-readings, selected-records). A row with a NULL version refuses here;
    rows at other versions are retained history the model never reads, reported but not
    refused. Readings rows are not re-read.
`receipt writer_job/writer_commit` columns are raw-receipt provenance, not this proof.

Per snapshot (ct-tk10 "records the producing code revision and job"): every pinned table
has a producer record, pinned in the publish spec as `producers: {table: {path, sha256,
size}}`, holding {version: 1, input, selector, job, commit}. The selector must equal the
pinned one, `job` must be a file checked in at `commit`, and `commit` must be reachable from
the publishing HEAD (the publish checkout fetches full history). `record` writes one through
writer_identity, which refuses a dirty tree. The publish spec's records are anchors; a daily
run records each head it moves in the raw bucket (congress_api.lake.producer_records), naming
the base it appended onto, and the chain is checked back to an anchor.

Runs in archive_publish_job.execute on the qualified runtime, before run_publish builds
or publishes anything. One native job: one filtered count per table, O(rows), no GROUP BY.

Cannot see: a forged stamp (a row stamped with the current version by other code); whether
the stamped code actually produced those bytes (only a rebuild proves that); snapshot-level
commit records, which the engine does not yet write (O9; proposed docspec-rs snapshot
summary properties); raw receipts and spicy-regs generations, whose producers are external.
"""
import json
import os
import shutil
from pathlib import Path

from congress_api.lake.producer_records import PIN_FIELDS
from congress_api.lake.tables import table_input
from congress_api.retention.provenance import run_job

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / 'model/registries/compatible-versions.json'
ROW_VERSIONED = {'readings': 'parser_version', 'filename_readings': 'catalog_version',
                 'meeting_records': 'parser_version', 'appearance_records': 'parser_version',
                 'video_records': 'parser_version', 'committee_records': 'parser_version', 'playlist_records': 'parser_version'}


def _lit(value):
    return "'" + str(value).replace("'", "''") + "'"


def compatible(parser, current, *, registry=REGISTRY):
    """Older versions registered as standing in for `current` (ct-deh9 entries)."""
    value = json.loads(Path(registry).read_text())
    return {e['version'] for e in value.get('entries', []) if e.get('parser') == parser and e.get('current') == current}


def pinned_terms(name, model):
    """SQL predicate: the row is at a version the model reads for this table."""
    versions = model['parser_versions']
    if name == 'readings':
        return ' OR '.join(f"(parser={_lit(p)} AND parser_version IN ({','.join(map(_lit, {v, *compatible(p, v)}))}))"
                           for p, v in sorted(versions.items()) if isinstance(v, str))
    if name == 'filename_readings':
        current = model['catalog_version']
        return f"catalog_version IN ({','.join(map(_lit, {current, *compatible('filename_readings', current)}))})"
    sources = versions.get(name, {})
    return ' OR '.join(f"(source={_lit(s)} AND parser_version IN ({','.join(map(_lit, {v, *compatible(f'{name}.{s}', v)}))}))"
                       for s, v in sorted(sources.items())) or 'false'


def proof_queries(model, present, *, mapping_current):
    """One query per table; columns are named <table>__<rule>."""
    queries = []
    if 'captures' in present:
        allowed = ','.join(map(_lit, sorted({mapping_current, *compatible('captures', mapping_current)})))
        queries.append(dict(name='captures', sql=f"""SELECT
            count(*) FILTER (WHERE mapping_version IS NULL) AS captures__mapping_version_null,
            count(*) FILTER (WHERE mapping_version IS NOT NULL AND mapping_version NOT IN ({allowed})) AS captures__mapping_version_unknown
            FROM captures"""))
    for name, column in ROW_VERSIONED.items():
        if name in present:
            queries.append(dict(name=name, sql=f"""SELECT
                count(*) FILTER (WHERE {column} IS NULL) AS {name}__{column}_null,
                count(*) FILTER (WHERE {column} IS NOT NULL AND NOT ({pinned_terms(name, model)})) AS {name}__other_versions_retained
                FROM {name}"""))
    return queries


RULES = {
    'mapping_version_null': 'row carries no producer version (captures.mapping_version is NULL)',
    'mapping_version_unknown': 'producer version is neither the current mapping nor registered compatible',
    'parser_version_null': 'row carries no producer version (parser_version is NULL)',
    'catalog_version_null': 'row carries no producer version (catalog_version is NULL)',
}


CAPTURES_STAGE = 'packages/congress_api/src/congress_api/cli/captures_ingest.py'
DAILY = 'packages/congress_api/src/congress_api/lake/daily.py'
BACKFILL = 'packages/viewer_publication/src/viewer_publication/archive_backfill_job.py'
IMPORT = 'packages/viewer_publication/src/viewer_publication/archive_import_job.py'
# The checked-in jobs that may produce each table; a record naming any other file refuses.
PRODUCERS = {
    'captures': {CAPTURES_STAGE, DAILY, BACKFILL, IMPORT},
    'readings': {'packages/congress_api/src/congress_api/cli/readings.py', DAILY, BACKFILL, IMPORT},
    'filename_readings': {DAILY, BACKFILL, IMPORT},
    'meeting_records': {DAILY, BACKFILL, IMPORT},
    'appearance_records': {DAILY, BACKFILL, IMPORT},
    'video_records': {DAILY, BACKFILL, IMPORT},
    'committee_records': {DAILY, BACKFILL, IMPORT},
    'playlist_records': {DAILY, BACKFILL, IMPORT},
}
# Older producers hashed installed library versions (sniff: pypdf, lxml), so report the versions
# the commit's own uv.lock pins rather than today's environment.
VERSIONS_AT_COMMIT = """import importlib, importlib.metadata, json, tomllib
with open('uv.lock', 'rb') as stream:
    locked = {p['name']: p['version'] for p in tomllib.load(stream)['package'] if 'version' in p}
installed = importlib.metadata.version
importlib.metadata.version = lambda name: locked.get(name.lower().replace('_', '-')) or installed(name)
def version(module, call):
    try:
        return call(importlib.import_module('congress_api.lake.' + module))
    except ImportError:
        return None  # the table's producer did not exist at this commit
out = dict(captures=version('captures', lambda m: m.current_version()),
    readings=version('readings', lambda m: {p: m.current_version(p)
        for p in ('sniff', 'html', 'xml', 'json', *getattr(m, 'READ_AS', {}))}),
    filename_readings=version('filenames', lambda m: m.current_version()),
    module=importlib.import_module('congress_api.lake.captures').__file__)
for name in ['meeting_records', 'appearance_records', 'video_records', 'committee_records', 'playlist_records']:
    out[name] = version(name, lambda m: m.current_versions())
print(json.dumps(out))
"""


def _poppler_pin_at(commit, root):
    """The Poppler release `commit` pinned in test-suites.toml, or None before the pin existed."""
    import subprocess
    import tomllib
    shown = subprocess.run(['git', '-C', str(root), 'show', f'{commit}:test-suites.toml'], capture_output=True)
    if shown.returncode:
        return None
    return tomllib.loads(shown.stdout.decode()).get('environment', {}).get('poppler', {}).get('version')


def versions_at(commit, *, root=ROOT, cache={}):
    """Each table's byte-hashed producer version computed from the code at `commit`.

    The version functions hash their own source and registries, so the tree at that commit
    is extracted (packages, model, uv.lock) and the functions run there. Never trusts
    a version the record states.
    """
    import subprocess
    import sys
    import tarfile
    import tempfile
    from io import BytesIO
    if (str(root), commit) in cache:
        return cache[str(root), commit]
    archive = subprocess.run(['git', '-C', str(root), 'archive', commit, 'packages', 'model', 'uv.lock'],
                             capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix='producer-versions-') as directory:
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            tar.extractall(directory, filter='data')
        src = os.pathsep.join(str(Path(directory) / path) for path in
                             ('packages/congress_api/src', 'packages/house-naming/src'))
        env = dict(os.environ, PYTHONPATH=src)
        pinned = _poppler_pin_at(commit, root)
        if pinned:
            # Older sniff versions hash `pdfinfo -v`/`pdftotext -v`; answer with the commit's own pin.
            shims = Path(directory) / '.poppler-pin'
            shims.mkdir()
            for tool in ('pdfinfo', 'pdftotext'):
                real = shutil.which(tool)
                script = shims / tool
                script.write_text(f'#!/bin/sh\nif [ "$1" = "-v" ]; then echo "{tool} version {pinned}" >&2; exit 0; fi\n'
                                  + (f'exec "{real}" "$@"\n' if real else 'exit 127\n'))
                script.chmod(0o755)
            env['PATH'] = os.pathsep.join([str(shims), env.get('PATH', '')])
        result = subprocess.run([sys.executable, '-c', VERSIONS_AT_COMMIT], cwd=directory, capture_output=True, text=True,
                                env=env)
        if result.returncode:
            raise ValueError(f'producer proof: versions could not be computed at {commit[:12]}: {result.stderr.strip()[-300:]}')
        value = json.loads(result.stdout)
        if not Path(value.pop('module')).resolve().is_relative_to(Path(directory).resolve()):
            raise ValueError('producer proof: the version functions did not run from the extracted commit')
    cache[str(root), commit] = value
    return value


def expected_versions(name, model, mapping_current):
    """The version(s) the pinned rows carry for one table."""
    if name == 'captures':
        return mapping_current
    if name == 'readings':
        from congress_api.lake.compatible_versions import DERIVED_PARSERS, LEAF_PARSERS
        selected = model['parser_versions']
        return {p: selected[p] for p in (*LEAF_PARSERS, *(p for p in DERIVED_PARSERS if p in selected))}
    if name == 'filename_readings':
        return model['catalog_version']
    return model['parser_versions'].get(name)


def _git(root, *args):
    import subprocess
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def _is_delta(record):
    return record.get('delta_only') is True or record.get('final_reconciliation_required') is True


def import_origin_problem(name, source, origin):
    """Check that a pinned origin can account for the complete file being imported."""
    if not isinstance(origin, dict):
        return 'an import needs a producer record object'
    if origin.get('input') != name:
        return 'the import origin names another table'
    if _is_delta(origin):
        return 'a staged delta cannot be the origin of a complete table'
    selector = origin.get('selector')
    if not isinstance(selector, dict) or selector.get('kind') not in ('parquet', 'native_table'):
        return 'the import origin must name a Parquet artifact or native snapshot'
    if selector['kind'] == 'native_table':
        try:
            table_input(name, {key: selector[key] for key in PIN_FIELDS})
        except (KeyError, ValueError):
            return 'the import origin needs an exact native table pin'
    elif (not isinstance(source, dict)
          or any(source.get(key) is None or source[key] != selector.get(key) for key in ('sha256', 'size'))):
        return 'the Parquet origin does not match the import source pin'
    return None


def _record_reasons(name, record, model, mapping_current, root, *, label, selector=None, versions=True, allow_delta=False):
    """One record's refusals: version, registered job, full reachable commit, job checked in
    there and, when the record's code produced the rows, the versions recomputed there."""
    import re
    reasons = []
    if not allow_delta and _is_delta(record):
        return [f'producer proof: {label}: a staged delta cannot produce a complete table']
    if selector is not None and (record.get('input') != name or record.get('selector') != selector):
        reasons.append(f'producer proof: {label}: the producer record names another selector')
    commit, job = record.get('commit'), record.get('job')
    if record.get('version') != 1:
        return reasons + [f'producer proof: {label}: unknown producer record version {record.get("version")!r}']
    if job not in PRODUCERS.get(name, ()):
        return reasons + [f'producer proof: {label}: job {job!r} is not a producer registered for this table']
    if not isinstance(commit, str) or re.fullmatch('[0-9a-f]{40}', commit) is None:
        return reasons + [f'producer proof: {label}: the producer record has no full commit']
    if _git(root, 'merge-base', '--is-ancestor', commit, 'HEAD').returncode != 0:
        return reasons + [f'producer proof: {label}: producing commit {commit[:12]} is not reachable from HEAD']
    if _git(root, 'cat-file', '-e', f'{commit}:{job}').returncode != 0:
        return reasons + [f'producer proof: {label}: job {job!r} is not a file checked in at {commit[:12]}']
    if versions:
        try:
            computed = versions_at(commit, root=root).get(name)
        except ValueError as error:
            return reasons + [f'producer proof: {label}: {error}']
        expected = expected_versions(name, model, mapping_current)
        if name == 'readings' and isinstance(computed, dict):
            # A capable writer can also produce a release that omits derived metadata.
            computed = {parser: value for parser, value in computed.items() if parser in expected}
        if computed != expected:
            reasons.append(f'producer proof: {label}: the code at {commit[:12]} computes another version than the pinned rows carry')
    return reasons


def _import_reasons(name, record, model, mapping_current, root, *, label, versions=True):
    origin = record.get('origin')
    if not isinstance(origin, dict) or not isinstance(origin.get('record'), dict):
        return [f'producer proof: {label}: an import record needs the origin record of the job that produced the rows']
    if origin['record'].get('job') == IMPORT:
        return [f'producer proof: {label}: an import cannot name another import as its origin']
    if problem := import_origin_problem(name, record.get('source'), origin['record']):
        return [f'producer proof: {label} origin: {problem}']
    return _record_reasons(name, origin['record'], model, mapping_current, root, label=f'{label} origin', versions=versions)


def _chain_reasons(name, record, model, mapping_current, root, ledger, *, label):
    """A daily record's bases, back to a checked-in anchor or the table's first snapshot.

    Each link: the base is the same table, an ancestor of the head reached by appends only
    (the head's Iceberg metadata), and its record is the one pinned by hash. Older links
    are not version-checked: their rows' versions are the row rule's concern.
    """
    from congress_api.lake.producer_records import appended_from, pin_of
    if ledger is None:
        return [f'producer proof: {label}: a daily record\'s base cannot be read without the producer record store']
    head = record['selector']
    lineage = ledger.lineage(head['metadata_location'])
    current, seen = record, set()
    while True:
        base = current.get('base')
        if not isinstance(base, dict) or not isinstance(base.get('selector'), dict):
            return [f'producer proof: {label}: a daily record must name the base snapshot it appended onto']
        selector, pinned = base['selector'], base.get('record')
        if selector.get('table_uuid') != head.get('table_uuid'):
            return [f'producer proof: {label}: the base snapshot belongs to another table']
        if not appended_from(lineage, current['selector']['snapshot'], selector.get('snapshot')):
            return [f'producer proof: {label}: base snapshot {selector.get("snapshot")} is not an ancestor reached by appends only']
        if selector.get('snapshot') is None:
            return [] if pinned is None else [f'producer proof: {label}: an empty base has no record']
        if selector['snapshot'] in seen:
            return [f'producer proof: {label}: the base chain repeats a snapshot']
        seen.add(selector['snapshot'])
        found = ledger.find(name, selector)
        if (found is None or not isinstance(pinned, dict)
                or {k: found[1].get(k) for k in ('sha256', 'size')} != {k: pinned.get(k) for k in ('sha256', 'size')}):
            return [f'producer proof: {label}: the record of base snapshot {selector["snapshot"]} is missing or differs from its pin']
        prior, reference = found
        if pin_of(prior.get('selector') or {}) != pin_of(selector):
            return [f'producer proof: {label}: the base record names another snapshot']
        link = f'{label} base {selector["snapshot"]}'
        if prior.get('job') == IMPORT:
            if 'anchor' not in reference:
                return [f'producer proof: {link}: an import record in the chain must be checked in beside the publish spec']
            return (_record_reasons(name, prior, model, mapping_current, root, label=link, versions=False)
                    or _import_reasons(name, prior, model, mapping_current, root, label=link, versions=False))
        found_reasons = _record_reasons(name, prior, model, mapping_current, root, label=link, versions=False)
        if found_reasons:
            return found_reasons
        if prior.get('job') != DAILY:
            return [f'producer proof: {link}: only daily records chain to a base']
        current = prior


def snapshot_reasons(model, records, *, root=ROOT, mapping_current=None, ledger=None):
    """Refusals for the per-snapshot rule: one record per pinned table, bound to its selector.

    An import (archive_import_job) copies rows it did not produce, so its record must carry
    `origin`, the record of the job that did; the origin is checked like any producer (its
    commit reachable, its versions equal to the rows') except for its selector, which names
    the source snapshot the import copied and verified. An import cannot be its own origin.
    A daily record appended onto a base; its chain is checked through `ledger`.
    """
    reasons = []
    for name in [n for n in ('captures', *ROW_VERSIONED) if model.get(n) is not None]:
        record = (records or {}).get(name)
        if record is None:
            reasons.append(f'producer proof: {name}: no producer record (job and commit) for the pinned snapshot')
            continue
        selector = {k: v for k, v in model[name].items() if k != 'producer'}
        imported = record.get('job') == IMPORT
        found = _record_reasons(name, record, model, mapping_current, root, label=name, selector=selector, versions=not imported)
        reasons += found
        if found:
            continue
        if imported:
            reasons += _import_reasons(name, record, model, mapping_current, root, label=name)
        elif record.get('job') == DAILY and selector.get('kind') == 'native_table':
            reasons += _chain_reasons(name, record, model, mapping_current, root, ledger, label=name)
    return reasons


def find_records(model, ledger, anchors):
    """The record for each pinned snapshot: from the ledger, else the table's anchor (which then
    reports its own selector mismatch)."""
    records = {}
    for name in [n for n in ('captures', *ROW_VERSIONED) if model.get(n) is not None]:
        found = ledger.find(name, model[name]) if ledger is not None else None
        if found is not None:
            records[name] = found[0]
        elif name in anchors:
            records[name] = json.loads(anchors[name])
    return records


def record(path, *, input, selector, job, root=ROOT):
    """Write a producer record from the clean checked-in tree that is producing the snapshot."""
    from congress_api.retention.writer_identity import writer_identity
    identity = writer_identity(root, job)
    value = dict(version=1, input=input, selector=selector, job=job, commit=identity['commit'],
                 lockfile_digest=identity['lockfile_digest'])
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=1) + '\n')
    return value


def require_producers(model, *, engine, work, mapping_current=None, records=None, root=ROOT, ledger=None):
    """Refuse unless every consumed row of every pinned table names a current or compatible producer.

    Returns the per-table report, including retained-history counts that do not refuse.
    """
    from docspec_client.models import DocSpecFailure
    if mapping_current is None:
        from congress_api.lake import captures
        mapping_current = captures.current_version()
    present = [name for name in ('captures', *ROW_VERSIONED) if model.get(name) is not None]
    inputs = []
    for name in present:
        selector = model[name]
        source = selector['path'] if selector.get('kind') == 'parquet' else {k: v for k, v in selector.items() if k != 'kind'}
        inputs.append(table_input(name, source))
    report, reasons = {}, snapshot_reasons(model, records, root=root, mapping_current=mapping_current, ledger=ledger)
    for query in proof_queries(model, present, mapping_current=mapping_current):
        try:
            rows = run_job(Path(work) / query['name'], engine, inputs=[i for i in inputs if i['name'] == query['name']],
                           steps=[], outputs=[], queries=[query])[query['name']]
        except DocSpecFailure as error:
            column = 'mapping_version' if query['name'] == 'captures' else ROW_VERSIONED[query['name']]
            if column in str(error):
                reasons.append(f'producer proof: {query["name"]} has no {column} column; every row must carry its producer version')
                continue
            raise
        for key, count in rows[0].items():
            table, rule = key.split('__', 1)
            report[key] = count
            if count and rule in RULES:
                reasons.append(f'producer proof: {table}: {count} rows: {RULES[rule]}')
    if reasons:
        raise ValueError('Publication refused by gate 5:\n' + '\n'.join(reasons))
    return report
