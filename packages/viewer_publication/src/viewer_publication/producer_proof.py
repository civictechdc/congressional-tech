"""Gate 5 (ct-tk10): every pinned derived row names the code that produced it.

Rule (lead decision 2026-11-02): each row carries its producer's byte-hashed version,
and that version must be the current definition or one registered as compatible in
model/registries/compatible-versions.json (ct-deh9).
  - captures: `mapping_version` (captures.current_version(), written by the captures
    stage; cluster e1 adds the column). Every row is consumed, so every row must carry a
    current or compatible mapping. NULL or unknown refuses. v21 captures, written by an
    unrecorded pyarrow writer, carry none and are refused; the ct-kunv rebuild carries it.
  - readings, filename_readings, meeting/appearance/video/committee records:
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
writer_identity, which refuses a dirty tree. A daily publication has no records yet, so it
refuses until its producer writes them.

Runs in archive_publish_job.execute on the qualified runtime, before run_publish builds
or publishes anything. One native job: one filtered count per table, O(rows), no GROUP BY.

Cannot see: a forged stamp (a row stamped with the current version by other code); whether
the stamped code actually produced those bytes (only a rebuild proves that); snapshot-level
commit records, which the engine does not yet write (O9; proposed docspec-rs snapshot
summary properties); raw receipts and spicy-regs generations, whose producers are external.
"""
import json
from pathlib import Path

from congress_api.lake.tables import table_input
from congress_api.retention.provenance import run_job

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / 'model/registries/compatible-versions.json'
ROW_VERSIONED = {'readings': 'parser_version', 'filename_readings': 'catalog_version',
                 'meeting_records': 'parser_version', 'appearance_records': 'parser_version',
                 'video_records': 'parser_version', 'committee_records': 'parser_version'}


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


def _git(root, *args):
    import subprocess
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def snapshot_reasons(model, records, *, root=ROOT):
    """Refusals for the per-snapshot rule: one record per pinned table, bound to its selector."""
    import re
    reasons = []
    for name in [n for n in ('captures', *ROW_VERSIONED) if model.get(n) is not None]:
        record = (records or {}).get(name)
        if record is None:
            reasons.append(f'producer proof: {name}: no producer record (job and commit) for the pinned snapshot')
            continue
        selector = {k: v for k, v in model[name].items() if k != 'producer'}
        if record.get('input') != name or record.get('selector') != selector:
            reasons.append(f'producer proof: {name}: the producer record names another selector')
        commit, job = record.get('commit'), record.get('job')
        if not isinstance(commit, str) or re.fullmatch('[0-9a-f]{40}', commit) is None:
            reasons.append(f'producer proof: {name}: the producer record has no full commit')
            continue
        if _git(root, 'merge-base', '--is-ancestor', commit, 'HEAD').returncode != 0:
            reasons.append(f'producer proof: {name}: producing commit {commit[:12]} is not reachable from HEAD')
        elif not isinstance(job, str) or _git(root, 'cat-file', '-e', f'{commit}:{job}').returncode != 0:
            reasons.append(f'producer proof: {name}: job {job!r} is not a file checked in at {commit[:12]}')
    return reasons


def record(path, *, input, selector, job, root=ROOT):
    """Write a producer record from the clean checked-in tree that is producing the snapshot."""
    from congress_api.retention.writer_identity import writer_identity
    identity = writer_identity(root, job)
    value = dict(version=1, input=input, selector=selector, job=job, commit=identity['commit'],
                 lockfile_digest=identity['lockfile_digest'])
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=1) + '\n')
    return value


def require_producers(model, *, engine, work, mapping_current=None, records=None, root=ROOT):
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
    report, reasons = {}, snapshot_reasons(model, records, root=root)
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
