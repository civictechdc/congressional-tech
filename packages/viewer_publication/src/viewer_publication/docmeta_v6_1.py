"""Optional docmeta-v6_1 sidecar validation, DataFusion steps, and invariants."""
from pathlib import Path
import re

ROOT = Path(__file__).parents[4]

REQUIRED_PARTS = ('completed_no_llm', 'sha_dup_alias')
OPTIONAL_PARTS = ('llm_results',)
ALL_PARTS = (*REQUIRED_PARTS, *OPTIONAL_PARTS)
ALLOWED_FIELDS = frozenset((*ALL_PARTS, 'bundle_version'))

REQUIRED_DIRECT_COLUMNS = frozenset({
    'link_key',
    'doc_key',
    'saved_body',
    'package_id',
    'disposition',
    'v6_route',
    'filename',
    'effective_format',
    'primary_kind',
    'status',
    'congress',
    'chamber',
    'committees',
    'docmeta_json',
    'strict_v4_valid',
})
REQUIRED_ALIAS_COLUMNS = frozenset({
    'link_key',
    'doc_key',
    'saved_body',
    'package_id',
    'disposition',
    'sub_disposition',
    'v6_route',
    'filename',
    'effective_format',
    'canonical_link_key',
    'canonical_doc_key',
    'canonical_partition_bucket',
    'canonical_v6_route',
})

SQL_FILE = Path('model/sql/document-docmeta-v6-1.sql')


def validate_docmeta_spec(value, *, pin_fn, local_fn, base):
    """Validate an optional docmeta_v6_1 job-spec block and normalize local paths."""
    if not isinstance(value, dict):
        raise ValueError('docmeta_v6_1 input must be an object')
    unknown = set(value) - ALLOWED_FIELDS
    if unknown:
        raise ValueError('docmeta_v6_1 has unknown fields: ' + ', '.join(sorted(unknown)))
    missing = [name for name in REQUIRED_PARTS if value.get(name) is None]
    if missing:
        raise ValueError('docmeta_v6_1 requires: ' + ', '.join(missing))
    result = {}
    if 'bundle_version' in value and value['bundle_version'] is not None:
        version = value['bundle_version']
        if not isinstance(version, str) or not version.strip():
            raise ValueError('docmeta_v6_1 bundle_version must be a non-empty string')
        result['bundle_version'] = version
    for name in ALL_PARTS:
        entry = value.get(name)
        if entry is None:
            continue
        pin_fn(entry, {'path', 'sha256', 'size'})
        result[name] = dict(entry, path=local_fn(entry['path'], base))
    return result


def iter_docmeta_pins(value):
    """Yield `(label, pin)` pairs for every configured docmeta_v6_1 Parquet file."""
    if not isinstance(value, dict):
        return
    for name in ALL_PARTS:
        entry = value.get(name)
        if entry is not None:
            yield f'docmeta_v6_1 {name}', entry


def docmeta_profile_entry(value):
    """Extract digest-only pin metadata for the model profile record."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('docmeta_v6_1 profile entry requires a pinned bundle object')
    for name in REQUIRED_PARTS:
        entry = value.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f'docmeta_v6_1 profile missing {name}')
    out = {}
    if isinstance(value.get('bundle_version'), str) and value['bundle_version'].strip():
        out['bundle_version'] = value['bundle_version']
    for name in ALL_PARTS:
        entry = value.get(name)
        if entry is None:
            continue
        sha = entry.get('sha256')
        size = entry.get('size')
        if not isinstance(sha, str) or re.fullmatch('[a-f0-9]{64}', sha) is None or type(size) is not int or size < 0:
            raise ValueError(f'docmeta_v6_1 profile requires sha256 and size for {name}')
        out[name] = dict(sha256=sha, size=size)
    return out


def _require_schema_columns(path, required, *, label, source_candidates=()):
    import pyarrow.parquet as pq

    names = set(pq.read_schema(path).names)
    missing = sorted(required - names)
    if missing:
        raise ValueError(f'{label} missing required columns: ' + ', '.join(missing))
    if source_candidates:
        for col in source_candidates:
            if col in names:
                return col
        raise ValueError(f'{label} missing source column (one of {", ".join(source_candidates)})')
    return None


def _normalized_direct_sql(table_name, *, source_expr, empty=False):
    where_clause = ' WHERE false' if empty else ''
    return (
        f"SELECT arrow_cast(link_key,'FixedSizeBinary(8)') AS link_key,"
        f"cast(doc_key AS VARCHAR) AS doc_key,"
        f"arrow_cast(saved_body,'FixedSizeBinary(32)') AS saved_body,"
        f"cast(package_id AS VARCHAR) AS package_id,"
        f"cast(disposition AS VARCHAR) AS disposition,"
        f"cast(NULL AS VARCHAR) AS sub_disposition,"
        f"cast(v6_route AS VARCHAR) AS v6_route,"
        f"cast({source_expr} AS VARCHAR) AS docmeta_source,"
        f"cast('direct' AS VARCHAR) AS resolution_state,"
        f"false AS is_alias,"
        f"arrow_cast(NULL,'FixedSizeBinary(8)') AS canonical_link_key,"
        f"cast(NULL AS VARCHAR) AS canonical_doc_key,"
        f"cast(NULL AS VARCHAR) AS canonical_partition_bucket,"
        f"cast(NULL AS VARCHAR) AS canonical_v6_route,"
        f"cast(filename AS VARCHAR) AS filename,"
        f"cast(effective_format AS VARCHAR) AS effective_format,"
        f"cast(primary_kind AS VARCHAR) AS primary_kind,"
        f"cast(status AS VARCHAR) AS status,"
        f"cast(congress AS BIGINT) AS congress,"
        f"cast(chamber AS VARCHAR) AS chamber,"
        f"arrow_cast(committees,'List(Utf8)') AS committees,"
        f"cast(docmeta_json AS VARCHAR) AS docmeta_json,"
        f"cast(strict_v4_valid AS BOOLEAN) AS strict_v4_valid "
        f"FROM {table_name}{where_clause}"
    )


def docmeta_inputs_and_prelude(docmeta_v6_1):
    """Build native DataFusion inputs and normalized prelude steps for docmeta_v6_1."""
    if not isinstance(docmeta_v6_1, dict):
        raise ValueError('docmeta_v6_1 must be a bundle dictionary')
    for part in REQUIRED_PARTS:
        if not isinstance(docmeta_v6_1.get(part), dict) or not docmeta_v6_1[part].get('path'):
            raise ValueError(f'docmeta_v6_1 missing pinned input {part}')

    completed_path = docmeta_v6_1['completed_no_llm']['path']
    alias_path = docmeta_v6_1['sha_dup_alias']['path']
    completed_src = _require_schema_columns(
        completed_path,
        REQUIRED_DIRECT_COLUMNS,
        label='docmeta_v6_1 completed_no_llm',
        source_candidates=('zero_llm_source', 'docmeta_source'),
    )
    _require_schema_columns(
        alias_path,
        REQUIRED_ALIAS_COLUMNS,
        label='docmeta_v6_1 sha_dup_alias',
    )

    inputs = [
        dict(name='docmeta_v6_1_completed_raw', kind='parquet', path=completed_path),
        dict(name='docmeta_v6_1_alias_input', kind='parquet', path=alias_path),
    ]
    prelude = [
        dict(
            name='docmeta_v6_1_completed_input',
            sql=_normalized_direct_sql('docmeta_v6_1_completed_raw', source_expr=completed_src),
            materialize=True,
        ),
    ]

    llm_entry = docmeta_v6_1.get('llm_results')
    if llm_entry is not None:
        llm_path = llm_entry['path']
        llm_src = _require_schema_columns(
            llm_path,
            REQUIRED_DIRECT_COLUMNS,
            label='docmeta_v6_1 llm_results',
            source_candidates=('docmeta_source', 'zero_llm_source', 'model_id'),
        )
        inputs.append(dict(name='docmeta_v6_1_llm_results_raw', kind='parquet', path=llm_path))
        prelude.append(
            dict(
                name='docmeta_v6_1_llm_results_input',
                sql=_normalized_direct_sql('docmeta_v6_1_llm_results_raw', source_expr=llm_src),
                materialize=True,
            )
        )
    else:
        prelude.append(
            dict(
                name='docmeta_v6_1_llm_results_input',
                sql=_normalized_direct_sql('docmeta_v6_1_completed_raw', source_expr=completed_src, empty=True),
                materialize=True,
            )
        )

    return inputs, prelude


def docmeta_release_artifacts(*, evidence, settings, root=ROOT):
    """Return DataFusion steps, evidence Parquet output spec, and fail-closed diagnostics."""
    # Union completed and optional LLM results once; left-join tiny alias table (188 rows)
    # on the left per DataFusion hash-join rules so the larger canonical table is never
    # held as the build side of an outer join.
    steps = [
        dict(
            name='docmeta_v6_1_direct',
            sql='SELECT * FROM docmeta_v6_1_completed_input UNION ALL SELECT * FROM docmeta_v6_1_llm_results_input',
            materialize=True,
        ),
        dict(
            name='docmeta_v6_1_aliases_resolved',
            sql="""SELECT
                arrow_cast(a.link_key,'FixedSizeBinary(8)') AS link_key,
                cast(a.doc_key AS VARCHAR) AS doc_key,
                arrow_cast(a.saved_body,'FixedSizeBinary(32)') AS saved_body,
                coalesce(cast(a.package_id AS VARCHAR),c.package_id) AS package_id,
                cast(a.disposition AS VARCHAR) AS disposition,
                cast(a.sub_disposition AS VARCHAR) AS sub_disposition,
                cast(a.v6_route AS VARCHAR) AS v6_route,
                c.docmeta_source AS docmeta_source,
                CASE WHEN c.doc_key IS NOT NULL THEN 'sha_dup_alias_inherited'
                     ELSE 'sha_dup_alias_pending_llm' END AS resolution_state,
                true AS is_alias,
                arrow_cast(a.canonical_link_key,'FixedSizeBinary(8)') AS canonical_link_key,
                cast(a.canonical_doc_key AS VARCHAR) AS canonical_doc_key,
                cast(a.canonical_partition_bucket AS VARCHAR) AS canonical_partition_bucket,
                cast(a.canonical_v6_route AS VARCHAR) AS canonical_v6_route,
                cast(a.filename AS VARCHAR) AS filename,
                cast(a.effective_format AS VARCHAR) AS effective_format,
                c.primary_kind AS primary_kind,
                c.status AS status,
                c.congress AS congress,
                c.chamber AS chamber,
                c.committees AS committees,
                c.docmeta_json AS docmeta_json,
                c.strict_v4_valid AS strict_v4_valid
            FROM docmeta_v6_1_alias_input a
            LEFT JOIN docmeta_v6_1_direct c
              ON a.canonical_link_key=c.link_key AND a.canonical_doc_key=c.doc_key""",
            materialize=True,
        ),
        dict(
            name='docmeta_v6_1_unified',
            sql='SELECT * FROM docmeta_v6_1_direct UNION ALL SELECT * FROM docmeta_v6_1_aliases_resolved',
            materialize=True,
        ),
    ]
    extra = [
        dict(
            name='docmeta_v6_1.parquet',
            path=str(Path(evidence) / 'docmeta_v6_1.parquet'),
            sql=(Path(root) / SQL_FILE).read_text(),
            settings=settings,
        )
    ]
    diagnostics = [
        dict(
            name='docmeta_v6_1_invariants',
            sql="""SELECT
                (SELECT count(*) FROM (SELECT link_key FROM docmeta_v6_1_unified GROUP BY link_key HAVING count(*)>1)) AS duplicate_docmeta_link_keys,
                (SELECT count(*) FROM (SELECT doc_key FROM docmeta_v6_1_unified GROUP BY doc_key HAVING count(*)>1)) AS duplicate_docmeta_doc_keys,
                (SELECT count(*) FROM docmeta_v6_1_unified u LEFT ANTI JOIN details d ON u.link_key=d.link_key AND u.doc_key=d.doc_key) AS missing_release_documents,
                (SELECT count(*) FROM docmeta_v6_1_unified u JOIN details d ON u.link_key=d.link_key AND u.doc_key=d.doc_key WHERE u.saved_body IS DISTINCT FROM d.saved_body) AS saved_body_mismatches,
                (SELECT count(*) FROM docmeta_v6_1_aliases_resolved WHERE canonical_partition_bucket='completed_no_llm' AND resolution_state<>'sha_dup_alias_inherited') AS missing_completed_canonical_aliases,
                (SELECT count(*) FROM docmeta_v6_1_direct WHERE docmeta_json IS NULL OR trim(docmeta_json)='' OR strict_v4_valid IS DISTINCT FROM true) AS invalid_direct_docmeta_rows,
                (SELECT count(*) FROM docmeta_v6_1_aliases_resolved WHERE resolution_state='sha_dup_alias_inherited' AND (docmeta_json IS NULL OR trim(docmeta_json)='' OR strict_v4_valid IS DISTINCT FROM true)) AS invalid_inherited_aliases""",
        )
    ]
    return steps, extra, diagnostics
