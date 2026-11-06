"""Orchestration for corpus recovery campaigns across canonical owner modules.

Target inventory, archive/publisher discovery, body qualification, source-native
identity acceptance, retained imports, reconciliation, and URL state evaluation
each delegate to their single canonical owner without duplicating policy.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from congress_shared.custody import canonical_json_bytes, write_atomic_bytes
from congress_api.parsers.document_links import http_url
from congress_api.retention.provenance import (
    file_pin, load_stage, parquet_output, run_job, verify_local_file,
)
from corpus_recovery.campaign import import_candidate, plan
from corpus_recovery.cdx import key as surt_key
from corpus_recovery.discovery import (
    _source_url, campaign_lookup, govinfo_bill_candidate,
    govinfo_document_candidate, house_listing_candidate, wayback_lookup,
)
from corpus_recovery.discovery_runtime import DiscoveryRuntime
from corpus_recovery.inventory import build_target_inventory, narrow_address_repairs
from corpus_recovery.qualification import (
    QualificationConfig, qualify, verify_qualification_record,
)
from corpus_recovery.reconcile import import_reconciled_stage, reconcile


def pin_file(path: str | Path) -> dict[str, str]:
    """Return a `{path, sha256}` pin dictionary for a local file."""
    resolved = Path(path).resolve()
    return {'path': str(resolved), 'sha256': file_pin(resolved)['sha256']}


def _archive_lookup_url(url: str) -> bool:
    """Whether archive indexes can be queried for this exact spelling.

    Mirrors the target guards of `wayback_lookup` / `webharvest_lookup`, so any
    ValueError they raise afterwards is a configuration or contract failure.
    """
    return _source_url(url) and surt_key(url) is not None


def discover_target_candidates(
    targets: Iterable[str | Mapping[str, Any]], *, runtime: DiscoveryRuntime | None = None,
    wayback_call: Any | None = None, webharvest_call: Any | None = None,
    webharvest_collections: Iterable[str] = (),
    house_listings: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    govinfo_documents: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    govinfo_bills: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    max_pages: int = 2, page_size: int = 1000,
    from_timestamp: str | None = None, to_timestamp: str | None = None,
    output: str | Path | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate candidate rows for targets using canonical discovery and link owners.

    Targets are literal URLs or rows with `target_url` and optional `context_url`.
    Archive and publisher lookups query the literal and every narrow repair. When
    `diagnostics` is a list, one entry per archive lookup is appended with its
    `complete`, `reason`, `evidence`, and (Wayback) `window`, so a negative result
    remains bounded by its actual coverage.
    """
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    collections = tuple(webharvest_collections)

    def record(
        target_url: str,
        candidate_url: str,
        source: str,
        *,
        preserve_candidate_literal: bool = False,
        **extra: Any,
    ) -> None:
        if not isinstance(target_url, str) or not target_url.strip():
            return
        if not isinstance(candidate_url, str) or not candidate_url.strip():
            return
        cleaned_candidate = candidate_url if preserve_candidate_literal else (http_url(candidate_url) or candidate_url)
        pair = (target_url, cleaned_candidate, extra.get('timestamp'))
        if not cleaned_candidate or pair in seen:
            return
        seen.add(pair)
        candidates.append({'target_url': target_url, 'candidate_url': cleaned_candidate, 'source': source, **extra})

    def record_cand(target_url: str, cand: Mapping[str, Any] | None) -> None:
        if cand is None:
            return
        extra = {k: v for k, v in cand.items() if k not in ('url', 'target_url', 'source')}
        # Archive and publisher candidate builders already validate their URLs;
        # never rewrite Wayback replay URLs through http_url().
        record(target_url, cand['url'], cand['source'], preserve_candidate_literal=True, **extra)

    def note(target_url: str, probe: str, lookup: str, result: Mapping[str, Any], **extra: Any) -> None:
        if diagnostics is not None:
            diagnostics.append({
                'target_url': target_url, 'probe_url': probe, 'lookup': lookup, **extra,
                'complete': result.get('complete'), 'reason': result.get('reason'),
                'evidence': result.get('evidence'), 'window': result.get('window'),
                'candidates': len(result.get('candidates', ())),
            })

    call = runtime.control if runtime is not None else wayback_call
    wh_call = runtime.control if runtime is not None and webharvest_call is None else webharvest_call

    for raw in targets:
        if isinstance(raw, Mapping):
            target_url, context_url = raw.get('target_url') or raw.get('url'), raw.get('context_url')
        else:
            target_url, context_url = raw, None
        if not isinstance(target_url, str) or not target_url.strip():
            continue

        repaired_urls: list[str] = []
        for repaired_url, basis in narrow_address_repairs(target_url, context_url):
            record(target_url, repaired_url, basis)
            if repaired_url not in repaired_urls and repaired_url != target_url:
                repaired_urls.append(repaired_url)
        lookup_keys = [target_url, *repaired_urls]
        for u in list(lookup_keys):
            bare = u.split('#', 1)[0]
            if bare and bare not in lookup_keys:
                lookup_keys.append(bare)
        default_probe = next((u for u in lookup_keys if _source_url(u)), http_url(target_url) or target_url)

        for lk in lookup_keys:
            probe = lk if _source_url(lk) else default_probe
            for item in (house_listings or {}).get(lk, ()):
                kw = dict(item)
                cand_url = kw.pop('candidate_url', kw.pop('candidate', None))
                record_cand(target_url, house_listing_candidate(probe, cand_url, **kw))

            for item in (govinfo_documents or {}).get(lk, ()):
                record_cand(target_url, govinfo_document_candidate(probe, **dict(item)))

            for item in (govinfo_bills or {}).get(lk, ()):
                record_cand(target_url, govinfo_bill_candidate(probe, **dict(item)))

        for probe in (u for u in lookup_keys if _archive_lookup_url(u)):
            if call is not None:
                wb = wayback_lookup(
                    probe, call, max_pages=max_pages, page_size=page_size,
                    from_timestamp=from_timestamp, to_timestamp=to_timestamp,
                )
                note(target_url, probe, 'wayback', wb)
                for cand in wb.get('candidates', ()):
                    record_cand(target_url, cand)
            if wh_call is not None:
                for collection in collections:
                    wh = campaign_lookup(probe, collection, wh_call, max_pages=max_pages, page_size=page_size)
                    note(target_url, probe, 'webharvest', wh, collection=collection)
                    for cand in wh.get('candidates', ()):
                        record_cand(target_url, cand)

    if output is not None:
        write_candidates_parquet(candidates, output)
    return candidates


_OPTIONAL_CANDIDATE_COLUMNS = (
    'original_url', 'timestamp', 'digest', 'collection', 'package_id', 'evidence',
    'listing_url', 'version', 'mapping', 'identifier_evidence', 'identity', 'stem',
)


def _candidate_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        return canonical_json_bytes(value).decode('utf-8')
    return str(value)


def write_candidates_parquet(candidates: Iterable[Mapping[str, Any]], output: str | Path) -> Path:
    """Write a deduplicated `candidates.parquet` table preserving candidate metadata.

    Accepts pipeline rows (`candidate_url`) or raw `discovery.py` candidates (`url`).
    Structured metadata (e.g. bill `identity`) is stored as canonical JSON text.
    """
    raw_list = list(candidates)
    present_optional = [
        col for col in _OPTIONAL_CANDIDATE_COLUMNS
        if any(r.get(col) is not None for r in raw_list)
    ]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in raw_list:
        t_url = r.get('target_url')
        c_url = r.get('candidate_url') or r.get('url')
        if not isinstance(t_url, str) or not t_url.strip() or not isinstance(c_url, str) or not c_url.strip():
            raise ValueError('Candidate rows require non-empty target_url and candidate_url (or url)')
        pair = (t_url, c_url)
        if pair in seen:
            continue
        seen.add(pair)
        row: dict[str, Any] = {
            'target_url': t_url,
            'candidate_url': c_url,
            'source': str(r.get('source') or ''),
        }
        for col in present_optional:
            row[col] = _candidate_text(r.get(col))
        rows.append(row)

    fields = [
        ('target_url', pa.string()),
        ('candidate_url', pa.string()),
        ('source', pa.string()),
        *[(col, pa.string()) for col in present_optional],
    ]
    schema = pa.schema(fields)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out_path)
    return out_path


def qualify_candidate_body(
    body_path: str | Path, cache_dir: str | Path, *,
    expected_sha256: str | None = None, config: QualificationConfig | None = None,
    require_qualified: bool = False,
) -> tuple[Any, Any]:
    """Verify local body custody and qualify exclusively through `qualification.qualify`."""
    cfg = config if config is not None else QualificationConfig()
    verified = verify_local_file(Path(body_path), expected_sha256=expected_sha256)
    record = qualify(verified, Path(cache_dir), config=cfg)
    if require_qualified:
        verify_qualification_record(
            dict(record), body_sha256=verified.sha256, body_bytes=verified.size_bytes,
            config=cfg, require_qualified=True,
        )
    return verified, record


def write_campaign_descriptor(
    descriptor_path: str | Path, *, campaign_id: str,
    targets_parquet: str | Path, candidates_parquet: str | Path,
    requirement: str = 'historical_exact', state: str | Path | None = None,
    state_profile: str | Path | None = None, state_requirements: str | Path | None = None,
    extra_tables: Mapping[str, str | Path] | None = None,
) -> Path:
    """Write a pinned version-1 campaign descriptor JSON file for `campaign.plan()`."""
    tables: dict[str, dict[str, str]] = {
        'targets': pin_file(targets_parquet),
        'candidates': pin_file(candidates_parquet),
    }
    if state is not None or state_profile is not None or state_requirements is not None:
        if state is None or state_profile is None or state_requirements is None:
            raise ValueError('State reuse requires state, state_profile, and state_requirements')
        tables['state'] = pin_file(state)
        tables['state_profile'] = pin_file(state_profile)
        tables['state_requirements'] = pin_file(state_requirements)
    for name, table_path in (extra_tables or {}).items():
        tables[name] = pin_file(table_path)

    descriptor = {
        'version': 1, 'campaign_id': campaign_id, 'requirement': requirement,
        'tables': tables, 'target_table': 'targets', 'candidate_table': 'candidates',
    }
    out = Path(descriptor_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json_bytes(descriptor) + b'\n'
    if out.exists():
        if out.read_bytes() != raw:
            raise ValueError('Campaign descriptor already pins different inputs; use a new descriptor path')
    else:
        write_atomic_bytes(out, raw)
    return out


def import_accepted_candidates(
    campaign_descriptor: str | Path, requests: Iterable[str | Path | Mapping[str, Any]], *,
    output_dir: str | Path, engine: Any, writer: Any, store: Any,
    qualification_config: QualificationConfig | None = None,
) -> list[dict[str, Any]]:
    """Qualify, verify source-native identity, and import candidates via `campaign.import_candidate`.

    Request files and operation directories are named by request digest only, so a
    rerun (in any order) resumes the same `import_candidate` operation, whose
    binding, operation id, and frozen receipts make the retry idempotent.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    cfg = qualification_config or QualificationConfig()
    for req in requests:
        if isinstance(req, (str, Path)):
            req_path = Path(req)
            req_digest = file_pin(req_path)['sha256'][:16]
        else:
            req_bytes = canonical_json_bytes(dict(req)) + b'\n'
            req_digest = sha256(req_bytes[:-1]).hexdigest()[:16]
            req_path = base / f'request-{req_digest}.json'
            if not req_path.is_file() or req_path.read_bytes() != req_bytes:
                write_atomic_bytes(req_path, req_bytes)
        results.append(
            import_candidate(
                campaign_descriptor, req_path, output=base / f'import-{req_digest}',
                engine=engine, writer=writer, store=store, qualification_config=cfg,
            )
        )
    return results


def _reusable_reconcile_stage(
    stage_dir: Path, *, accepted_path: Path, captures_parquet: Path, registry_path: Path,
    decided_at: str, decided_by: str,
) -> dict[str, Any]:
    """Return an existing sealed reconciliation stage when it was built from these inputs."""
    root, value = load_stage(stage_dir)
    inputs = dict(accepted=file_pin(accepted_path), captures=file_pin(captures_parquet),
                  registry=file_pin(registry_path))
    if value.get('kind') != 'recoveries' or value.get('inputs') != inputs:
        raise ValueError('Existing reconciliation stage was built from different inputs; use a new output_dir')
    # load_stage verified these staged JSONL files; the decision must also match.
    for item in value['files']:
        with (root / item['path']).open(encoding='utf-8') as lines:
            for line in lines:
                record = json.loads(line)
                if record.get('decided_at') != decided_at or record.get('decided_by') != decided_by:
                    raise ValueError('Existing reconciliation stage has a different decision; use a new output_dir')
    return value


def reconcile_and_import_retained(
    accepted_path: str | Path, captures_parquet: str | Path, registry_path: str | Path, *,
    output_dir: str | Path, engine: Any, decided_at: str, decided_by: str,
    writer: Any | None = None, imported_at: str | None = None,
    ready_only: bool = False,
    body_paths_by_sha256: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Run native reconciliation via `reconcile.reconcile` and import ready rows via `import_reconciled_stage`.

    A rerun reuses an existing sealed stage whose pinned inputs and decision match;
    `import_reconciled_stage` keeps receipt identities stable across retries.
    """
    staged_dir = Path(output_dir)
    if (staged_dir / 'manifest.json').exists():
        report = _reusable_reconcile_stage(
            staged_dir, accepted_path=Path(accepted_path), captures_parquet=Path(captures_parquet),
            registry_path=Path(registry_path), decided_at=decided_at, decided_by=decided_by,
        )
    else:
        report = reconcile(
            accepted_path, captures_parquet, registry_path, output=staged_dir,
            engine=engine, decided_at=decided_at, decided_by=decided_by,
        )
    import_res = import_reconciled_stage(
        staged_dir,
        writer=writer,
        ready_only=ready_only,
        imported_at=imported_at or decided_at,
        body_paths_by_sha256=body_paths_by_sha256,
    )
    return {**report, 'imported_receipts': import_res['imported_receipts']}


def _publish_file(staged: Path, final: Path) -> None:
    """Move a validated staged file into place without exposing a partial file."""
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staged, final)
    except OSError:
        # Different filesystem: copy beside the destination, then rename atomically.
        partial = final.with_name(final.name + '.partial')
        shutil.copyfile(staged, partial)
        os.replace(partial, final)
        staged.unlink()


def evaluate_campaign_url_state(
    work_dir: str | Path, *, engine: Any, inputs: list[dict[str, Any]],
    prep_steps: list[dict[str, Any]] | None = None,
    recovery_policy: Mapping[str, Any] | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Execute full `url_state_steps` + `url_state_diagnostics` and enforce zero invariant errors.

    `url_state.parquet` is written under `work_dir` and moved to `output_dir` only
    after the invariants pass; a failing table stays in `work_dir` for inspection.
    """
    from viewer_publication.archive_url_state import url_state_diagnostics, url_state_steps

    work = Path(work_dir)
    pol = dict(recovery_policy) if recovery_policy is not None else None
    steps = list(prep_steps or ()) + url_state_steps(recovery_policy=pol)
    staged_root = work / 'staged-outputs'
    staged_root.mkdir(parents=True, exist_ok=True)
    outputs = [
        parquet_output(staged_root, 'url_state', 'SELECT * FROM url_state ORDER BY requested_url', ['requested_url'])
    ]
    queries = list(url_state_diagnostics())
    result = run_job(work, engine, inputs=inputs, steps=steps, outputs=outputs, queries=queries)
    failing = {k: v for k, v in result['url_state_invariants'][0].items() if v}
    if failing:
        raise ValueError(f'URL state invariants failed: {failing}; staged table retained in {staged_root}')
    out_root = Path(output_dir) if output_dir is not None else work / 'outputs'
    final = out_root / 'url_state.parquet'
    _publish_file(staged_root / 'url_state.parquet', final)
    result['url_state_parquet'] = final
    return result


def run_recovery_campaign(
    work_dir: str | Path, *, campaign_id: str, targets: Any, engine: Any,
    policy: Any | None = None, captures: Any | None = None,
    states: Any | None = None, fetch_outcomes: Any | None = None,
    source_or_store: Any | None = None, history: Mapping[str, Any] | None = None,
    membership_origin: str = 'baseline', refresh_policy: str = 'historical_only',
    candidates: Iterable[Mapping[str, Any]] | None = None,
    discovery_kwargs: Mapping[str, Any] | None = None,
    import_requests: Iterable[str | Path | Mapping[str, Any]] = (),
    writer: Any | None = None, store: Any | None = None,
    requirement: str = 'historical_exact',
    state: str | Path | None = None,
    state_profile: str | Path | None = None,
    state_requirements: str | Path | None = None,
    qualification_config: QualificationConfig | None = None,
) -> dict[str, Any]:
    """Prepare one execution and import candidates; returned counts describe its initial plan.

    Resume with ``resume_recovery_campaign`` so changed state or discovery cannot
    overwrite the descriptor already bound to an import operation.
    """
    root = Path(work_dir)
    if (root / 'campaign.json').exists():
        raise ValueError('Campaign already prepared; use resume_recovery_campaign with its original descriptor')
    inputs_dir = root / 'inputs'
    inputs_dir.mkdir(parents=True, exist_ok=True)

    targets_parquet = inputs_dir / 'targets.parquet'
    inventory_rows = build_target_inventory(
        targets, policy=policy, history=history, source_or_store=source_or_store,
        captures=captures, states=states, fetch_outcomes=fetch_outcomes, output=targets_parquet,
        membership_origin=membership_origin, refresh_policy=refresh_policy,
    )
    diagnostics: list[dict[str, Any]] = []
    if candidates is None:
        discovery_targets = [
            {'target_url': r['target_url'], 'context_url': r.get('context_url')}
            for r in inventory_rows if not r['usable_direct'] and not r['acquisition_excluded']
        ]
        candidate_rows = discover_target_candidates(
            discovery_targets, diagnostics=diagnostics, **(dict(discovery_kwargs) if discovery_kwargs else {}),
        )
        write_atomic_bytes(inputs_dir / 'discovery-diagnostics.json', canonical_json_bytes(diagnostics) + b'\n')
    else:
        candidate_rows = [dict(c) for c in candidates]

    candidates_parquet = write_candidates_parquet(candidate_rows, inputs_dir / 'candidates.parquet')
    descriptor_path = write_campaign_descriptor(
        root / 'campaign.json', campaign_id=campaign_id,
        targets_parquet=targets_parquet, candidates_parquet=candidates_parquet,
        requirement=requirement, state=state, state_profile=state_profile,
        state_requirements=state_requirements,
    )
    initial_plan = plan(descriptor_path, output=root / 'plan', engine=engine)
    initial_counts = json.loads((root / 'plan/counts.json').read_text())

    imports: list[dict[str, Any]] = []
    if import_requests:
        if writer is None or store is None:
            raise ValueError('Importing candidates requires both writer and store')
        imports = import_accepted_candidates(
            descriptor_path, import_requests, output_dir=root / 'operations',
            engine=engine, writer=writer, store=store, qualification_config=qualification_config,
        )
    return {
        'descriptor': descriptor_path, 'targets': inventory_rows, 'candidates': candidate_rows,
        'discovery_diagnostics': diagnostics,
        'plan': initial_plan, 'counts': initial_counts, 'counts_phase': 'initial',
        'initial_plan': initial_plan, 'initial_counts': initial_counts, 'imports': imports,
    }


def resume_recovery_campaign(
    descriptor: str | Path, *, engine: Any,
    import_requests: Iterable[str | Path | Mapping[str, Any]] = (),
    writer: Any | None = None, store: Any | None = None,
    qualification_config: QualificationConfig | None = None,
) -> dict[str, Any]:
    """Resume frozen inputs without inventory, discovery, or a changed import binding."""
    descriptor = Path(descriptor)
    root = descriptor.parent
    initial_plan = plan(descriptor, output=root / 'plan', engine=engine)
    counts = json.loads((root / 'plan/counts.json').read_text())
    requests = list(import_requests)
    if requests and (writer is None or store is None):
        raise ValueError('Importing candidates requires both writer and store')
    imports = import_accepted_candidates(
        descriptor, requests, output_dir=root / 'operations', engine=engine,
        writer=writer, store=store, qualification_config=qualification_config,
    ) if requests else []
    return dict(descriptor=descriptor, plan=initial_plan, counts=counts,
                counts_phase='initial', initial_plan=initial_plan, initial_counts=counts, imports=imports)


__all__ = [
    'discover_target_candidates',
    'evaluate_campaign_url_state',
    'import_accepted_candidates',
    'pin_file',
    'qualify_candidate_body',
    'reconcile_and_import_retained',
    'run_recovery_campaign',
    'resume_recovery_campaign',
    'write_campaign_descriptor',
    'write_candidates_parquet',
]
