"""Offline export, validated before an atomic local publication pointer changes."""
import argparse
import csv
import fcntl
import gc
import gzip
import hashlib
import io
import json
import logging
import shutil
import tempfile
from collections import ChainMap, Counter, defaultdict
from collections.abc import Mapping
from contextlib import ExitStack
from datetime import datetime, timezone
from heapq import merge
from itertools import chain
from operator import attrgetter
from pathlib import Path

from committee_meeting import SCHEMA_VERSION
from committee_meeting.common import Ref
from committee_meeting.provenance import Citation, Method, RetainedContent
from committee_meeting.publication import ExportPartition, InputSnapshot, PublicationManifest, SourceScope
from congress_api.adapters import (
    committee_metadata,
    findings,
    gpo,
    house,
    inventory,
    transcripts,
    video_matches,
)
from congress_api.matching import committee_adjustments
from congress_api.matching.senate_events import official_events
from congress_api.adapters import meetings as native
from congress_api.adapters import recordings as curated_recordings
from congress_api.adapters.committees import committee_lookup, ensure_committee_term
from congress_api.adapters.common import AdapterContext
from congress_shared.custody import canonical_json_bytes, write_atomic_bytes
from congress_api.matching import reviewed_committees

from .assemble import Assembly, apply_saved_copies
from .coverage import build as coverage
from .history import RetainedSources, load_history, migrate_history, save_history
from .ids import IdRegistry
from .issues import apply_decisions
from .query import write_queries
from .recording_ids import retain_recording_ids

VERSION = "0.1.0"
LOGGER = logging.getLogger(__name__)


def encode(value):
    return canonical_json_bytes(value, ensure_ascii=False, trailing_newline=True)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _is_gzip(path):
    with Path(path).open("rb") as stream:
        return stream.read(2) == b"\x1f\x8b"


def _open_text(path):
    path = Path(path)
    if _is_gzip(path):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def read(path):
    data = Path(path).read_bytes()
    body = gzip.decompress(data) if data.startswith(b"\x1f\x8b") else data
    return data, body


def validate_selectors(catalog, retained=RetainedSources()):
    """Resolve every JSON-pointer citation; summarize the retained sources in the same pass.

    Citations of retained sources wait for one ordered scan of the issue history,
    which decodes one source at a time. Returns those sources' provider counts and
    input snapshot IDs, which the coverage report and manifest need.
    """
    from committee_meeting.catalog import _pointer_exists
    from committee_meeting.common import Model
    lazy_sources = hasattr(catalog.sources, "get_by_id") and hasattr(catalog.sources, "source_ids")
    catalog_source_ids = catalog.sources.source_ids() if lazy_sources else None
    sources = None if lazy_sources else {s.id: s for s in catalog.sources}
    cited_current = defaultdict(set)
    waiting = defaultdict(set)
    def check_payload(sid, payload, selector):
        if payload is None or not _pointer_exists(payload, selector):
            raise ValueError(f"Citation does not resolve: {sid} {selector}")
    def check(source, selector):
        check_payload(source.id, source.payload, selector)
    precollected = getattr(catalog.records, "_cited_json_pointers", None)
    if lazy_sources and precollected is not None and not getattr(catalog.records, "_extra", None):
        try:
            delattr(catalog.records, "_cited_json_pointers")
        except AttributeError:
            pass
        cited_current = {}
        waiting = {}
        for sid in list(precollected):
            selectors = precollected.pop(sid)
            sel_tuple = (selectors,) if isinstance(selectors, str) else tuple(selectors)
            if sid in catalog_source_ids:
                cited_current[sid] = sel_tuple
            else:
                waiting[sid] = sel_tuple
        del precollected
    else:
        def visit(value):
            if isinstance(value, Citation) and value.selector_type == "json_pointer":
                sid = value.source.id
                if lazy_sources:
                    if sid in catalog_source_ids:
                        cited_current[sid].add(value.selector)
                    else:
                        waiting[sid].add(value.selector)
                else:
                    source = sources.get(sid)
                    if source is None:
                        waiting[sid].add(value.selector)
                    else:
                        check(source, value.selector)
            elif isinstance(value, Model):
                for name in type(value).model_fields:
                    visit(getattr(value, name))
            elif isinstance(value, (tuple, list)):
                for item in value:
                    visit(item)
        for record in catalog.records:
            visit(record)
    if lazy_sources:
        if hasattr(catalog.sources, "iter_payloads_for_ids"):
            for sid, payload in catalog.sources.iter_payloads_for_ids(cited_current):
                for selector in sorted(cited_current[sid]):
                    check_payload(sid, payload, selector)
        else:
            for sid in sorted(cited_current):
                source = catalog.sources.get_by_id(sid)
                for selector in sorted(cited_current[sid]):
                    check(source, selector)
    providers, inputs = Counter(), set()
    if hasattr(retained, "iter_json_dicts"):
        for source in retained.iter_json_dicts():
            providers[source["provider"]] += 1
            inputs.add(source["input_snapshot_id"])
            for selector in waiting.pop(source["id"], ()):
                check_payload(source["id"], source.get("payload"), selector)
    else:
        for source in retained.records():
            providers[source.provider] += 1
            inputs.add(source.input_snapshot_id)
            for selector in waiting.pop(source.id, ()):
                check(source, selector)
    if waiting:
        identity = min(waiting)
        raise ValueError(f"Citation does not resolve: {identity} {min(waiting[identity])}")
    return providers, inputs


def load_previous(output, state):
    pointer = output / "CURRENT.json"
    if not pointer.exists():
        retained = state / "publication.json"
        if not retained.exists(): return None, None
        manifest = PublicationManifest.model_validate_json(retained.read_bytes())
        history = load_history(state, manifest.publication_id)
        if history is None: raise ValueError("Retained publication has no issue history")
        return history, manifest
    current = json.loads(pointer.read_text())
    manifest_path = output / current["manifest_path"]
    if file_sha(manifest_path) != current["manifest_sha256"]:
        raise ValueError("Current publication manifest digest differs from pointer")
    manifest = PublicationManifest.model_validate_json(manifest_path.read_bytes())
    history = load_history(state, manifest.publication_id)
    if history is None:
        def previous_records():
            for part in manifest.partitions:
                field = {"committee_explorer.records":"records", "committee_explorer.sources":"sources"}.get(part.schema_name)
                if field:
                    path = manifest_path.parent / part.path
                    if file_sha(path) != part.sha256: raise ValueError("Previous partition digest mismatch")
                    yield from json.loads(path.read_bytes())[field]
        migrate_history(state, manifest.publication_id, previous_records())
        history = load_history(state, manifest.publication_id)
    return history, manifest


def _retain_senate_meeting_ids(rows, senate_state, ids):
    """A first native record may continue an already-published official-page ID.

    Saved matches supply the association; titles and dates never merge IDs.
    Multiple existing source identities or ambiguous native IDs remain separate.
    """
    from collections import defaultdict

    from congress_api.models.senate import workflow_record

    native_by_event = defaultdict(list)
    for row in rows:
        native_by_event[str(row['eventId'])].append(row)
    matches = defaultdict(set)
    for event in official_events(senate_state):
        saved = set(map(str, workflow_record(senate_state.get(event['host']) or {}, event['url']).get('events') or ()))
        if len(saved) != 1:
            continue
        candidates = native_by_event.get(next(iter(saved)), ())
        if len(candidates) != 1:
            continue
        row = candidates[0]
        if (int(row['congress']) != event['congress'] or native.chamber(row.get('chamber')) == 'house'
                or not any(c.get('systemCode') == event['committee_code'] for c in row.get('committees') or ())):
            continue
        native_key = native.meeting_key(row)
        source_key = 'senate.committee|' + event['url']
        if ids.existing('meeting', source_key) is not None:
            matches[native_key].add(source_key)
    aliases = 0
    for native_key, source_keys in matches.items():
        if ids.existing('meeting', native_key) is not None:
            continue
        if len({ids.existing('meeting', key) for key in source_keys}) == 1:
            aliases += ids.alias('meeting', native_key, sorted(source_keys)[0])
    return aliases


def _recording_urls(records):
    """Exact player URLs identify an existing recording for retained matcher rows."""
    if hasattr(records, 'iter_kind'):
        recordings = {r.id for r in records.iter_kind('material') if r.details.type == 'recording'}
        versions = {r.id: r.material for r in records.iter_kind('material_version') if r.material.id in recordings}
        reps = records.iter_kind('representation')
    else:
        recordings = {r.id for r in records if r.kind == 'material' and r.details.type == 'recording'}
        versions = {r.id: r.material for r in records if r.kind == 'material_version' and r.material.id in recordings}
        reps = (r for r in records if r.kind == 'representation')
    urls = defaultdict(dict)
    for record in reps:
        if record.version.id in versions:
            for location in record.locations:
                if location.role == 'player':
                    urls[location.url][record.version.id] = (versions[record.version.id], record.version)
    # Conflicting versions need review; never choose one by iteration order.
    return {url: next(iter(matches.values())) for url, matches in urls.items() if len(matches) == 1}


class _SpilledGpoEvidence(Mapping):
    """Stream GPO upstream observations to an unlinked arena file; decode one package at a time."""

    def __init__(self, path):
        from congress_api.models.gpo import GpoEvidenceRecord
        from congress_api.retention.gpo import _iter_observation_lines
        from .assemble import _ArenaLog

        self._record_cls = GpoEvidenceRecord
        self._arena = _ArenaLog(".explorer-gpo-evidence-")
        self._index: dict[str, int] = {}
        try:
            for line in _iter_observation_lines(path):
                value = GpoEvidenceRecord.model_validate_json(line)
                package = value.package_id
                if package in self._index:
                    raise ValueError(f"Duplicate GPO evidence package: {package}")
                raw = line.encode("utf-8") if isinstance(line, str) else bytes(line)
                offset, length = self._arena.append(raw)
                self._index[package] = (offset << 28) | length
        except BaseException:
            self.close()
            raise

    def __contains__(self, key):
        return key in self._index

    def __getitem__(self, key):
        packed = self._index[key]
        raw = self._arena.read(packed >> 28, packed & 0xFFFFFFF)
        return self._record_cls.model_validate_json(raw).source_dict()

    def __iter__(self):
        return iter(self._index)

    def __len__(self):
        return len(self._index)

    def close(self):
        self._index.clear()
        self._arena.close()


def export(*, meetings, output_dir, state_dir, gpo_path=None, gpo_evidence_path=None, house_state=None, senate_state=None,
           youtube_dir=None, inventory_state=None, recovered_witnesses=None, video_matches_path=None, recordings_path=None,
           transcript_files=(), issue_decisions=None, attempts=None, limit=None, as_of=None, revision=None, format="parquet", reuse_from=None, committees_path=None,
           document_filenames=None, docspec_workspace=None):
    if format != "parquet":
        raise ValueError("Committee Explorer export requires parquet format; legacy sharded json export has been retired")
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    transcript_files = tuple(transcript_files)
    attempt_receipt = json.loads(Path(attempts).read_text()) if attempts else {}
    provider_jobs = {'youtube':'youtube', 'congress.gov':'congress', 'govinfo':'congress', 'gpo-video-matches':'congress',
                     'docs.house.gov':'meetings', 'senate.committees':'meetings', 'meeting-inventory':'meetings', 'recovered-witnesses':'meetings',
                     'congress.gov:committees':'committees'}
    output, state = Path(output_dir), Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    with (state / "export.lock").open("a") as lock, ExitStack() as cleanup:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reuse_key = None
        if reuse_from is not None:
            from .reuse import request_key, save_receipt, try_reuse
            reuse_key = request_key(files={
                'meetings': meetings, 'gpo': gpo_path, 'gpo_evidence': gpo_evidence_path, 'house': house_state, 'senate': senate_state,
                'inventory': inventory_state, 'recovered_witnesses': recovered_witnesses,
                'video_matches': video_matches_path, 'recordings': recordings_path,
                'issue_decisions': issue_decisions, 'attempts': attempts, 'committees': committees_path,
                'document_filenames': document_filenames,
            }, youtube_dir=youtube_dir, transcript_files=transcript_files, format=format, limit=limit, as_of=as_of, document_filenames=document_filenames)
            if reused := try_reuse(output, state, reuse_from, reuse_key):
                return reused, None
        ids = IdRegistry(state / "ids.json")
        previous, previous_manifest = load_previous(output, state)
        if previous is not None:
            # Retained sources are read from this file until the new history is saved.
            cleanup.callback(previous.close)
        previous_id = previous_manifest.publication_id if previous_manifest else None
        assembly = Assembly(previous, ids=ids, now=now)
        snapshots, scopes, reconciliation = [], [], []
        def context(path, provider, limitations=()):
            LOGGER.info('Reading retained %s input', provider)
            raw, body = read(path)
            return source_context(raw, provider, limitations), body

        def context_only(path, provider, limitations=()):
            LOGGER.info('Hashing retained %s input', provider)
            return source_context(file_sha(path), provider, limitations, is_digest=True)

        def context_jsonl(path, provider, limitations=()):
            LOGGER.info('Streaming retained %s JSONL input', provider)
            ctx = source_context(file_sha(path), provider, limitations, is_digest=True)
            with _open_text(path) as stream:
                rows = [json.loads(line) for line in stream if line.strip()]
            return ctx, rows

        def context_json(path, provider, limitations=()):
            LOGGER.info('Streaming retained %s JSON input', provider)
            ctx = source_context(file_sha(path), provider, limitations, is_digest=True)
            with _open_text(path) as stream:
                return ctx, json.load(stream)

        def context_csv(path, provider, limitations=()):
            LOGGER.info('Streaming retained %s CSV input', provider)
            ctx = source_context(file_sha(path), provider, limitations, is_digest=True)
            with _open_text(path) as stream:
                return ctx, list(csv.DictReader(stream))

        def source_context(raw, provider, limitations=(), *, is_digest=False):
            digest = raw if is_digest else sha(raw)
            input_id = provider + ":" + digest
            job = provider_jobs.get(provider)
            result = (attempt_receipt.get('jobs', {}).get(job) or {}).get('result')
            status = {'success':'succeeded','failure':'failed','cancelled':'not_run','skipped':'not_run'}.get(result,'unknown')
            checked_at = attempt_receipt.get('completed_at') if result else None
            if result:
                limitations = (*limitations, f"Collection job {job} concluded {result}; this job-level receipt does not establish individual source acquisition outcomes.")
            snapshots.append(InputSnapshot(id=input_id, provider=provider, artifact=RetainedContent(uri="sha256:" + digest, sha256=digest),
                                            revision=revision if provider in ("congress.gov", "docs.house.gov", "senate.committees", "youtube", "meeting-inventory") else None,
                                            imported_at=now, last_attempt_at=checked_at, last_attempt_status=status, limitations=tuple(limitations)))
            return AdapterContext(now, input_id, provider, ids)
        def assemble_inputs():
            """Keep adapter scratch data out of graph validation and publication."""
            ctx, rows = context_jsonl(meetings, "congress.gov", ("Legacy native records lack per-record retrieval timestamps.",))
            rows.sort(key=native.meeting_key)
            all_meetings = rows
            total = len(rows)
            if limit:
                rows = rows[:limit]
            senate_input = None
            if senate_state:
                from congress_api.models.senate import normalize_senate_state, workflow_record
                senate_context, senate_data = context_json(senate_state, 'senate.committees',
                    ('Legacy checked dates may reflect seed import; live retrieval is established only by explicit receipts.',))
                normalize_senate_state(senate_data)
                retained_ids = _retain_senate_meeting_ids(rows, senate_data, ids)
                if retained_ids:
                    reconciliation.append({'provider': 'senate.committees', 'retained_meeting_id_aliases': retained_ids})
                if limit:
                    selected_events = {str(r["eventId"]) for r in rows}
                    senate_data = {host: {**site, 'pages': {url: page for url, page in site.get('pages', {}).items()
                            if selected_events.intersection(map(str, workflow_record(site, url, page).get('events') or ()))}}
                            for host, site in senate_data.items()}
                    normalize_senate_state(senate_data)
                seen_senate_terms = set()
                senate_first_events = []
                for event in official_events(senate_data):
                    term_key = (event['congress'], event['committee_code'])
                    if term_key not in seen_senate_terms:
                        seen_senate_terms.add(term_key)
                        senate_first_events.append(event)
                senate_top_level_count = len(senate_data)
                senate_input = (senate_context, senate_first_events, senate_top_level_count)
                del senate_data
                gc.collect()
            recording_keys, recording_migration = retain_recording_ids(rows, ids)
            reconciliation.append(recording_migration)
            assembly.add(native.records(rows, ctx, recording_keys=recording_keys))
            del recording_keys
            selected_congresses = {int(row['congress']) for row in rows}
            if committees_path:
                committee_context, committee_rows = context_jsonl(committees_path, 'congress.gov:committees')
                if limit:
                    committee_rows = [row for row in committee_rows if int(row['congress']) in selected_congresses]
                for item in committee_metadata.records(committee_rows, committee_context, assembly.records):
                    # Metadata fills unknown classifications rather than treating
                    # the former unknown value as a competing source assertion.
                    key = (item.kind, item.id)
                    into = assembly.sources if item.kind == 'source_record' else assembly.records
                    into[key] = item
                    assembly.current.add(key)
                scopes.append(SourceScope(provider='congress.gov:committees', scope='Official Congress-scoped committee lists',
                                          status='partial' if limit else 'included', input_snapshot_ids=(committee_context.input_id,),
                                          explanation=f'Imported {len(committee_rows)} retained committee records; committees with no retained meetings may also appear.'))
                del committee_rows
            else:
                scopes.append(SourceScope(provider='congress.gov:committees', scope='Official Congress-scoped committee lists',
                                          status='not_collected', explanation='No retained committee metadata supplied; names do not establish committee type.'))
            reconciliation.append({"provider": "congress.gov", "input_records": total, "selected_records": len(rows),
                                   "distinct_selected_identities": len({native.meeting_key(r) for r in rows})})
            lookup = {(int(r["congress"]), native.chamber(r.get("chamber")), str(r["eventId"])):
                      Ref(kind="meeting", id=ids("meeting", native.meeting_key(r))) for r in rows}
            scopes.insert(0, SourceScope(provider="congress.gov", scope="retained committee meeting records, all statuses", status="partial" if len(rows)<total else "included",
                                      input_snapshot_ids=(ctx.input_id,), explanation=f"Imported {len(rows)} of {total} retained records. Retention is not proof of complete upstream coverage."))
            from congress_api.matching.meetings import in_inventory_scope
            eligible_meetings = [
                {k: r[k] for k in ("eventId", "congress", "date", "type", "title", "committees", "meetingDocuments") if k in r}
                for r in all_meetings
                if in_inventory_scope(r)
            ] if gpo_path else []
            del rows, all_meetings
            gc.collect()
            # Load document metadata before supplemental events so every explicitly
            # identified committee can be linked without requiring a meeting match.
            gpo_context, gpo_review_context, gpo_rows, all_gpo = None, None, [], []
            gpo_evidence = {}
            if gpo_evidence_path:
                evidence_context = context_only(gpo_evidence_path, "govinfo:upstream")
                gpo_evidence = _SpilledGpoEvidence(gpo_evidence_path)
                cleanup.callback(gpo_evidence.close)
                scopes.append(SourceScope(provider="govinfo:upstream", scope="retained MODS and transcript observations",
                    status="included", input_snapshot_ids=(evidence_context.input_id,),
                    explanation="Original bytes and acquisition metadata; cached replay is not a new upstream retrieval."))
            if gpo_path:
                gpo_context, all_gpo = context_csv(gpo_path, "govinfo", ("CSV does not preserve all raw MODS metadata or downloaded transcript bytes.",))
                gpo_review_context = context_only(reviewed_committees.__file__, 'gpo.committee-review')
                gpo_rows = all_gpo
                if limit:
                    selected = [r for r in all_gpo if (int(r["congress"]), native.chamber(r["chamber"]), r["event_id"]) in lookup]
                    selected_ids = {r["package_id"] for r in selected}
                    gpo_rows = selected + [r for r in all_gpo if r["package_id"] not in selected_ids][:limit]
                assembly.add(gpo.committee_records(gpo_rows, gpo_context, existing=assembly.records, review_context=gpo_review_context, evidence_by_package=gpo_evidence))

            sources = (("docs.house.gov", house_state, house, "House parsed source state"),)
            if senate_state:
                from congress_api.adapters import senate
                sources += (("senate.committees", senate_state, senate, "Senate parsed source state"),)
            supplemental = []
            for provider, path, adapter, label in sources:
                if path:
                    if provider == 'senate.committees':
                        c, senate_first_events, top_level_count = senate_input
                        senate_input = None
                        for event in senate_first_events:
                            source = c.source(f"senate-page|{event['host']}|{event['url']}", event['page'], event['url'])
                            evidence = c.evidence(source, selector='/event')
                            missing = list(ensure_committee_term(event['congress'], event['committee_code'],
                                           event['committee_code'], c, evidence, assembly.records))
                            if missing:
                                assembly.add([source, *missing])
                        del senate_first_events
                        rec_entry = {"provider": provider, "selected_top_level_entries": top_level_count}
                    else:
                        c = context_only(path, provider, ("Legacy checked dates may reflect seed import; live retrieval is established only by explicit receipts.",))
                        rec_entry = {"provider": provider, "selected_top_level_entries": 0}
                    supplemental.append((provider, adapter, path, c, rec_entry))
                    reconciliation.append(rec_entry)
                    scopes.append(SourceScope(provider=provider, scope=label, status="partial", input_snapshot_ids=(c.input_id,), explanation="Retained supplemental source records; uncollected meetings and unsupported layouts are not covered."))
                else:
                    scopes.append(SourceScope(provider=provider, scope=label, status="not_collected", explanation="No input was supplied to this offline export."))
            if not senate_state:
                scopes.append(SourceScope(provider="senate.committees", scope="Senate parsed source state", status="not_collected", explanation="No input was supplied to this offline export."))

            adjustment_context = context_only(committee_adjustments.__file__, 'committee-review')
            for item in committee_metadata.adjustment_records(adjustment_context, assembly.records, congresses=selected_congresses if limit else None):
                key = (item.kind, item.id)
                into = assembly.sources if item.kind == 'source_record' else assembly.records
                into[key] = item
                assembly.current.add(key)
            scopes.append(SourceScope(provider='committee-review', scope='Reviewed committee metadata corrections', status='included',
                                      input_snapshot_ids=(adjustment_context.input_id,),
                                      explanation='Cited corrections preserve original source names and classifications.'))
            committees = committee_lookup(
                assembly.records.iter_kind('committee_term')
                if hasattr(assembly.records, 'iter_kind')
                else assembly.records.values()
            )
            # Assembly validates and copies incoming models. Stream the originals so
            # a second complete GPO corpus does not survive alongside those copies.
            LOGGER.info('Assembling retained GPO records')
            if gpo_path:
                assembly.add(gpo.records(gpo_rows, gpo_context, meetings=lookup, committees=committees,
                    review_context=gpo_review_context, evidence_by_package=gpo_evidence))
            if hasattr(gpo_evidence, "close"):
                gpo_evidence.close()
            del gpo_evidence
            gc.collect()
            versions, print_versions = {}, {}
            print_decisions = []
            gpo_reconciliation = None
            gpo_selected_count = 0
            if gpo_path:
                from congress_api.matching.prints import match_prints
                gpo_selected_count = len(gpo_rows)
                gpo_reconciliation = {
                    "provider": "govinfo",
                    "input_records": len(all_gpo),
                    "selected_records": gpo_selected_count,
                    "distinct_selected_identities": len({r['package_id'] for r in gpo_rows}),
                }
                match_prints(eligible_meetings, all_gpo, decisions=print_decisions)
                gpo_mat_ids = {}
                mats_iter = (
                    assembly.records.iter_kind("material")
                    if hasattr(assembly.records, "iter_kind")
                    else (r for r in assembly.records.values() if r.kind == "material")
                )
                for r in mats_iter:
                    vals = tuple(
                        i.value
                        for i in r.identifiers
                        if "govinfo" in i.scheme or "gpo" in i.scheme
                    )
                    if vals:
                        gpo_mat_ids[r.id] = vals
                mv_iter = (
                    assembly.records.iter_kind("material_version")
                    if hasattr(assembly.records, "iter_kind")
                    else (r for r in assembly.records.values() if r.kind == "material_version")
                )
                for r in mv_iter:
                    vals = gpo_mat_ids.get(r.material.id)
                    if vals:
                        v_ref = Ref(kind=r.kind, id=r.id)
                        m_ref = Ref(kind="material", id=r.material.id)
                        for val in vals:
                            if transcript_files:
                                versions[("govinfo", val)] = v_ref
                            print_versions[val] = (m_ref, v_ref)
                del gpo_mat_ids
            del gpo_rows, all_gpo, eligible_meetings
            gc.collect()
            known_gpo_files = gpo.primary_rendition_index(
                assembly.records
                if hasattr(assembly.records, 'iter_kind')
                else [record for record in assembly.records.values()
                      if record.kind in {'material', 'material_version', 'representation'}]
            )
            for provider, adapter, path, c, rec_entry in supplemental:
                LOGGER.info('Assembling retained %s records', provider)
                with _open_text(path) as stream:
                    data = json.load(stream)
                if provider == "docs.house.gov":
                    if limit:
                        data = {k: v for k, v in data.items() if any(x[2] == str(k) for x in lookup)}
                    rec_entry["selected_top_level_entries"] = len(data)
                c.known_materials = known_gpo_files
                options = {'meetings': lookup}
                if provider == 'senate.committees':
                    if limit:
                        selected_events = {key[2] for key in lookup}
                        data = {host: {**site, 'pages': {url: page for url, page in site.get('pages', {}).items()
                                if selected_events.intersection(map(str, workflow_record(site, url, page).get('events') or ()))}}
                                for host, site in data.items()}
                    data = normalize_senate_state(data)
                    senate_events = {
                        str(ev)
                        for site in data.values()
                        for url, page in (site.get('pages') or {}).items()
                        for ev in (workflow_record(site, url, page).get('events') or ())
                    }
                    senate_meeting_ids = {ref.id for (_, _, ev), ref in lookup.items() if ev in senate_events}
                    meetings_iter = (
                        assembly.records.iter_kind('meeting')
                        if hasattr(assembly.records, 'iter_kind')
                        else (r for r in assembly.records.values() if r.kind == 'meeting')
                    )
                    occurrences_iter = (
                        assembly.records.iter_kind('occurrence')
                        if hasattr(assembly.records, 'iter_kind')
                        else (r for r in assembly.records.values() if r.kind == 'occurrence')
                    )
                    options.update(committee_terms=committees,
                                   meeting_records={r.id: r for r in meetings_iter if r.id in senate_meeting_ids},
                                   occurrence_records={r.id: r for r in occurrences_iter if r.meeting.id in senate_meeting_ids})
                assembly.add(adapter.records(data, c, **options))
                del data, options
                gc.collect()
            del supplemental, known_gpo_files, committees
            if gpo_path:
                c = gpo_context
                reconciliation.append(gpo_reconciliation)
                selected_events = {key[2] for key in lookup}
                print_decisions = [d for d in print_decisions if d["event_id"] in selected_events and d["package_id"] in print_versions]
                if print_decisions:
                    raw_decisions = encode(print_decisions)
                    input_id = "print-matches:" + sha(raw_decisions)
                    snapshots.append(InputSnapshot(id=input_id, provider="congress_api.inventory.prints", artifact=RetainedContent(uri="inputs/print-decisions.json", sha256=sha(raw_decisions)),
                                                   imported_at=now, limitations=("Derived offline from retained meeting and GPO inputs, using existing matcher rules.",)))
                    scopes.append(SourceScope(provider="congress_api.inventory.prints", scope="print-to-meeting associations", status="included", input_snapshot_ids=(input_id,),
                                              explanation="Existing matcher decisions computed from all supplied native/GPO context before applying the export selection."))
                    match_ctx = AdapterContext(now, input_id, "congress_api.inventory.prints", ids)
                    assembly.add(findings.print_links(print_decisions, match_ctx, meetings=lookup, versions=print_versions))
                    links_iter = (
                        assembly.records.iter_kind("material_link")
                        if hasattr(assembly.records, "iter_kind")
                        else (r for r in assembly.records.values() if r.kind == "material_link")
                    )
                    linked = {r.material.id: r.provenance for r in links_iter
                              if r.role == "transcript" and r.subject.kind == "meeting"}
                    from committee_meeting.issues import IssueResolution
                    issues_iter = (
                        assembly.records.iter_kind("data_issue")
                        if hasattr(assembly.records, "iter_kind")
                        else [r for r in assembly.records.values() if r.kind == "data_issue"]
                    )
                    for issue in issues_iter:
                        if issue.category == "unlinked" and issue.subject.id in linked:
                            assembly.add([issue.model_copy(update={"status": "resolved", "resolution": IssueResolution(decided_at=now,
                                explanation="The existing print matcher supplied a supported association; its method and evidence remain on the link.", provenance=linked[issue.subject.id])})])
                scopes.append(SourceScope(provider="govinfo", scope="retained GPO package metadata", status="partial" if limit else "included", input_snapshot_ids=(c.input_id, gpo_review_context.input_id), explanation=f"Imported {gpo_selected_count} packages; explicit committee IDs and cited document reviews establish committee ownership. Explicit event IDs and existing print matching rules separately supply meeting associations."))
            else:
                scopes.append(SourceScope(provider="govinfo", scope="GPO packages", status="not_collected", explanation="No GPO input was supplied."))
            gc.collect()
            if youtube_dir:
                from youtube_api import adapters as youtube
                from congress_shared.youtube_cache import decode_cache
                # Provider IDs in native video URLs are explicit associations.
                # The metadata adapter receives their source evidence unchanged.
                associations = defaultdict(list)
                if hasattr(assembly.records, "iter_kind"):
                    yt_ids_by_mat = {}
                    for m in assembly.records.iter_kind("material"):
                        yt_ids = tuple(i.value for i in m.identifiers if i.scheme == "youtube.video")
                        if yt_ids:
                            yt_ids_by_mat[m.id] = yt_ids
                    for link in assembly.records.iter_kind("material_link"):
                        if link.role == "recording" and link.subject.kind == "meeting":
                            for vid in yt_ids_by_mat.get(link.material.id, ()):
                                associations[vid].append((link.subject, link.provenance))
                    del yt_ids_by_mat
                else:
                    for link in assembly.records.values():
                        if link.kind == "material_link" and link.role == "recording" and link.subject.kind == "meeting":
                            material = assembly.records[("material", link.material.id)]
                            for identifier in material.identifiers:
                                if identifier.scheme == "youtube.video":
                                    associations[identifier.value].append((link.subject, link.provenance))
                for path in sorted(Path(youtube_dir).glob("youtube_*.json")):
                    c, content = context(path, "youtube")
                    cache = decode_cache(content)
                    del content
                    videos = [row for _, row in cache.videos()]
                    for channel in cache.channels():
                        assembly.add([c.source("youtube-channel|" + str(channel.get("handle") or channel.get("channelId")), channel)])
                    del cache
                    input_videos = len(videos)
                    if limit:
                        videos = sorted(videos, key=lambda v: v["videoId"])[:limit]
                    distinct_videos = len({v['videoId'] for v in videos})
                    selected_videos = len(videos)
                    video_mat_ids = {}
                    def _stream_youtube(videos_list, ctx):
                        for r in youtube.records(videos_list, ctx, meetings=associations):
                            if r.kind == "material":
                                yt_ids = tuple(i.value for i in r.identifiers if i.scheme == "youtube.video")
                                if yt_ids:
                                    video_mat_ids[r.id] = yt_ids
                            elif r.kind == "material_version" and transcript_files:
                                for vid in video_mat_ids.get(r.material.id, ()):
                                    versions[("youtube", vid)] = Ref(kind=r.kind, id=r.id)
                            yield r
                    assembly.add(_stream_youtube(videos, c))
                    reconciliation.append({"provider": "youtube", "input": path.name, "input_records": input_videos,
                                           "selected_records": selected_videos, "distinct_selected_identities": distinct_videos})
                    del videos, video_mat_ids
                    scopes.append(SourceScope(provider="youtube", scope=path.name, status="partial", input_snapshot_ids=(c.input_id,), explanation="Retained metadata only; caption availability and reachability have not been checked by this export."))
                del associations
            else:
                scopes.append(SourceScope(provider="youtube", scope="YouTube video metadata", status="not_collected", explanation="Only links carried by other supplied inputs are represented."))
            if recordings_path:
                c, decisions = context_csv(recordings_path, "curated-recordings")
                assembly.add(curated_recordings.records(decisions, c, meetings=lookup))
                reconciliation.append({"provider": "curated-recordings", "input_records": len(decisions), "selected_records": len(decisions)})
                scopes.append(SourceScope(provider="curated-recordings", scope="retained manual meeting-recording associations", status="included", input_snapshot_ids=(c.input_id,), explanation="Original notes and discovery method retained; links do not prove full coverage or current reachability."))
                del decisions
            else:
                scopes.append(SourceScope(provider="curated-recordings", scope="manual meeting-recording associations", status="not_collected", explanation="No retained manual associations supplied."))
            # Retained decisions enrich known identities; they do not trigger acquisition.
            recordings, inventory_materials = {}, {}
            recording_material_schemes = defaultdict(list)
            materials_iter = (
                assembly.records.iter_kind("material")
                if hasattr(assembly.records, "iter_kind")
                else (r for r in assembly.records.values() if r.kind == "material")
            )
            for material in materials_iter:
                for identifier in material.identifiers:
                    if identifier.scheme in ("youtube.video", "senate.filename"):
                        provider = "youtube" if identifier.scheme == "youtube.video" else "senate"
                        inventory_materials[(provider, identifier.value)] = Ref(kind="material", id=material.id)
                        recording_material_schemes[material.id].append((provider, identifier.value))
            versions_iter = (
                assembly.records.iter_kind("material_version")
                if hasattr(assembly.records, "iter_kind")
                else (r for r in assembly.records.values() if r.kind == "material_version")
            )
            for r in versions_iter:
                if r.material.id in recording_material_schemes:
                    v_ref = Ref(kind=r.kind, id=r.id)
                    m_ref = Ref(kind="material", id=r.material.id)
                    for provider, val in recording_material_schemes[r.material.id]:
                        recordings[val] = (m_ref, v_ref)
                        if transcript_files:
                            versions[(provider, val)] = v_ref
            del recording_material_schemes
            recordings.update(_recording_urls(assembly.records if hasattr(assembly.records, "iter_kind") else assembly.records.values()))
            if video_matches_path:
                c, decisions = context_csv(video_matches_path, "gpo-video-matches")
                packages = {key: pair[0] for key, pair in print_versions.items()}
                package_by_material = {v.id: k for k, v in packages.items()}
                package_meetings = defaultdict(list)
                package_evidence = defaultdict(list)
                links_iter = (
                    assembly.records.iter_kind("material_link")
                    if hasattr(assembly.records, "iter_kind")
                    else (r for r in assembly.records.values() if r.kind == "material_link")
                )
                for record in links_iter:
                    if record.subject.kind == "meeting" and record.material.id in package_by_material:
                        package_meetings[package_by_material[record.material.id]].append(record.subject)
                        package_evidence[(package_by_material[record.material.id], record.subject.id)].append(record.provenance)
                def _stream_video_matches():
                    for item in video_matches.records(decisions, c, packages=packages, recordings=recordings,
                            package_meetings=package_meetings, package_evidence=package_evidence):
                        if item.kind == "material":
                            for identifier in item.identifiers:
                                if identifier.scheme in ("youtube.video", "senate.filename"):
                                    prov = "youtube" if identifier.scheme == "youtube.video" else "senate"
                                    inventory_materials[(prov, identifier.value)] = Ref(kind="material", id=item.id)
                        yield item
                assembly.add(_stream_video_matches())
                reconciliation.append({"provider": "gpo-video-matches", "input_records": len(decisions), "selected_records": len(decisions)})
                scopes.append(SourceScope(provider="gpo-video-matches", scope="retained package recording decisions", status="included", input_snapshot_ids=(c.input_id,), explanation="Aggregate matcher evidence retained; only single-meeting, single-date package associations create meeting links."))
                del decisions, packages, package_by_material, package_meetings, package_evidence
            else:
                scopes.append(SourceScope(provider="gpo-video-matches", scope="package recording decisions", status="not_collected", explanation="No retained decisions supplied."))
            del recordings, print_versions, print_decisions
            if inventory_state:
                c, data = context_json(inventory_state, "meeting-inventory")
                assembly.add(inventory.records(data, c, meetings=lookup, materials=inventory_materials))
                reconciliation.append({"provider": "meeting-inventory", "input_records": sum(len(v) for v in data.values() if isinstance(v, dict)), "families": {k: len(v) for k,v in data.items() if isinstance(v,dict)}})
                scopes.append(SourceScope(provider="meeting-inventory", scope="retained caption, archive and witness observations", status="included", input_snapshot_ids=(c.input_id,), explanation="Unsupported ownership and cache-derived dates remain explicit issues; no caption content is invented."))
                del data
            else:
                scopes.append(SourceScope(provider="meeting-inventory", scope="caption, archive and witness observations", status="not_collected", explanation="No retained inventory supplied."))
            del inventory_materials
            if recovered_witnesses:
                c, data = context_csv(recovered_witnesses, "recovered-witnesses")
                from .recovered import reuse_appearances
                assembly.add(reuse_appearances(inventory.records({}, c, meetings=lookup, recovered_witnesses=data), assembly))
                reconciliation.append({"provider": "recovered-witnesses", "input_records": len(data), "selected_records": len(data), "distinct_rows": len({json.dumps(r,sort_keys=True) for r in data})})
                scopes.append(SourceScope(provider="recovered-witnesses", scope="retained recovered witness rows", status="included", input_snapshot_ids=(c.input_id,), explanation="Unique explicit event associations supply listed appearances; title-derived nominees remain inferred. Unique matching originating appearances retain their identity and richer fields."))
                del data
            else:
                scopes.append(SourceScope(provider="recovered-witnesses", scope="recovered witness rows", status="not_collected", explanation="No recovered witness table supplied."))
            for path in transcript_files:
                path = Path(path)
                body = path.read_bytes()
                c = source_context(body, "transcript-artifact")
                source = transcripts.TranscriptInput(data=body, name=path.name, uri=path.resolve().as_uri())
                assembly.add(transcripts.records([source], c, meetings=lookup, source_versions=versions))
                scopes.append(SourceScope(provider="transcript-artifact", scope=path.name, status="included", input_snapshot_ids=(c.input_id,), explanation="Existing local artifact imported; no text generation or acquisition performed."))
            if not transcript_files:
                scopes.append(SourceScope(provider="transcript-artifact", scope="retained transcript bodies", status="not_collected", explanation="No body artifacts were supplied; metadata links do not establish captured or searchable text."))
            del versions, lookup
            gc.collect()

        assemble_inputs()
        if document_filenames:
            apply_saved_copies(assembly, document_filenames)
        LOGGER.info('Validating %d records and %d source observations', len(assembly.records), len(assembly.sources))
        catalog = assembly.finish()
        # The catalog holds current sources; sources only old issues cite stay in
        # the previous history and stream from it wherever all sources are read.
        retained, assembled = assembly.retained, len(catalog.sources)
        LOGGER.info('Checking citations; %d source observations remain in issue history', len(retained))
        if issue_decisions:
            c, decision_rows = context_json(issue_decisions, "curated-issue-decisions")
            catalog = apply_decisions(catalog, decision_rows, c, retained)
            del decision_rows
        # Every identity is allocated. Release the registry before publication.
        current_source_ids = (
            catalog.sources.source_ids()
            if hasattr(catalog.sources, "source_ids")
            else {s.id for s in catalog.sources}
        )
        class _LiveSourceIds:
            def __contains__(self, item):
                return item in current_source_ids or item in retained.ids
        ids.stage(live_source_ids=_LiveSourceIds())
        del current_source_ids
        cleanup.callback(ids.discard)
        retained_providers, retained_inputs = validate_selectors(catalog, retained)
        # Previous issue evidence may reference earlier inputs. Preserve those
        # snapshots from the previous manifest instead of inventing freshness.
        known = {s.id for s in snapshots}
        current_inputs = (
            catalog.sources.input_snapshot_ids()
            if hasattr(catalog.sources, "input_snapshot_ids")
            else {s.input_snapshot_id for s in catalog.sources}
        )
        used = current_inputs | retained_inputs
        if previous_id:
            snapshots += [s for s in previous_manifest.inputs if s.id in used and s.id not in known]
        if not used <= {s.id for s in snapshots}:
            raise ValueError("A source refers to an input absent from the manifest")
        del retained_inputs, current_inputs, used, known, previous_manifest
        stage = Path(tempfile.mkdtemp(prefix=".building-", dir=output))
        partitions = []
        try:
            def descriptor(path, role, schema_name, count, congress=None, media_type="application/json"):
                dest = stage / path
                partitions.append(ExportPartition(path=path, role=role, schema_name=schema_name, schema_version=SCHEMA_VERSION,
                    media_type=media_type, sha256=file_sha(dest), byte_size=dest.stat().st_size, record_count=count, congress=congress))
            def write(path, value, role, schema_name, count, congress=None, raw=None):
                raw = encode(value) if raw is None else raw
                dest = stage / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
                descriptor(path, role, schema_name, count, congress)
            evidence_states = {}
            report = coverage(catalog, assembly.current, [s.id for s in snapshots], states_out=evidence_states)
            report["input_reconciliation"] = reconciliation
            current_providers = (
                catalog.sources.provider_counts()
                if hasattr(catalog.sources, "provider_counts")
                else Counter(s.provider for s in catalog.sources)
            )
            report["source_observation_counts"] = dict(current_providers + retained_providers)
            write("coverage.json", report, "coverage", "committee_explorer.coverage", len(report["metrics"]))
            del report, reconciliation, current_providers, retained_providers
            gc.collect()
            from .parquet import write_catalog
            LOGGER.info('Writing Parquet publication')
            write_catalog(
                catalog,
                assembly.current,
                stage,
                descriptor,
                write,
                evidence_states,
                retained.iter_json_dicts() if hasattr(retained, "iter_json_dicts") else retained.records(),
            )
            del evidence_states
            gc.collect()
            if docspec_workspace is not None:
                from .docspec_views import ExplorerDocSpecWorkspace
                with ExplorerDocSpecWorkspace(docspec_workspace) as ds_ws:
                    export_pins = ds_ws.sync_export(catalog, stage)
                partitions[:] = [
                    p.model_copy(
                        update={
                            "sha256": file_sha(stage / p.path),
                            "byte_size": (stage / p.path).stat().st_size,
                        }
                    )
                    for p in partitions
                ]
                write_atomic_bytes(
                    state / "export-pins.json",
                    encode(export_pins),
                    temp_path=state / ".export-pins.json.tmp",
                    fsync=False,
                )
            publication_id = sha(encode({"inputs": [s.id for s in snapshots], "partitions": [p.sha256 for p in partitions], "generated_at": now.isoformat()}))[:24]
            manifest = PublicationManifest(publication_id=publication_id, generated_at=now, producer=Method(name="committee-explorer-export", version=VERSION),
                inputs=tuple(snapshots), source_scopes=tuple(scopes), partitions=tuple(partitions), previous_publication_id=previous_id,
                limitations=("Offline export: import time is not a source check.", "Existing print matching rules run offline with explanations; video matching heuristics are not rerun.",
                             "Historical issue evidence may refer to records outside the current selection; meeting index describes the current selection.",))
            manifest_raw = encode(manifest.model_dump(mode="json"))
            (stage / "manifest.json").write_bytes(manifest_raw)
            for p in partitions:
                if file_sha(stage / p.path) != p.sha256 or (stage / p.path).stat().st_size != p.byte_size:
                    raise ValueError(f"Export verification failed: {p.path}")
            # Persist IDs before publishing references that depend on them.
            history_records = ChainMap(assembly.records, assembly.sources, retained)
            if issue_decisions:
                record_map = (
                    catalog.records.as_mapping()
                    if hasattr(catalog.records, "as_mapping")
                    else {(r.kind, r.id): r for r in catalog.records}
                )
                source_map = (
                    catalog.sources.as_mapping()
                    if hasattr(catalog.sources, "as_mapping")
                    else {(s.kind, s.id): s for s in catalog.sources}
                )
                history_records = ChainMap(record_map, source_map, retained)
            LOGGER.info('Saving retained issue history')
            save_history(state, publication_id, history_records)
            if previous is not None:
                previous.close()  # Its retained sources are now in the new history.
            LOGGER.info('Saving persistent IDs')
            ids.save()
            release = output / "releases" / publication_id
            release.parent.mkdir(exist_ok=True)
            if release.exists():
                shutil.rmtree(stage)
            else:
                stage.rename(release)
            pointer = {"schema_version": SCHEMA_VERSION, "publication_id": publication_id, "manifest_path": f"releases/{publication_id}/manifest.json",
                       "manifest_sha256": sha(manifest_raw), "media_type": "application/json"}
            write_atomic_bytes(
                output / "CURRENT.json",
                encode(pointer),
                temp_path=output / ".CURRENT.json.tmp",
                fsync=False,
            )
            write_atomic_bytes(
                state / "publication.json",
                manifest_raw,
                temp_path=state / ".publication.json.tmp",
                fsync=False,
            )
            for old in (state / "issue-history").glob("*.sqlite"):
                if old.stem != publication_id: old.unlink()
            if reuse_key is not None:
                save_receipt(state, reuse_key, manifest)
            return manifest, catalog
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s: %(message)s')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format", choices=("parquet",), default="parquet")
    p.add_argument("--meetings", type=Path, required=True)
    p.add_argument("--committees-path", type=Path, help="Retained Congress-scoped committee metadata JSON Lines, optionally gzipped.")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--gpo-path", type=Path)
    p.add_argument("--gpo-evidence-path", type=Path)
    p.add_argument("--house-state", type=Path)
    p.add_argument("--senate-state", type=Path)
    p.add_argument("--youtube-dir", type=Path)
    p.add_argument("--inventory-state", type=Path)
    p.add_argument("--recovered-witnesses", type=Path)
    p.add_argument("--video-matches-path", type=Path)
    p.add_argument("--recordings-path", type=Path)
    p.add_argument("--transcript", action="append", dest="transcript_files", type=Path, default=[])
    p.add_argument("--issue-decisions", type=Path, help="JSON list of documented resolved/dismissed issue decisions.")
    p.add_argument("--attempts", type=Path, help="Retained collection-job conclusion receipt; job scope does not imply individual source success.")
    p.add_argument("--limit", type=int, help="Bound a rehearsal; manifest declares the selected population.")
    p.add_argument("--as-of", type=datetime.fromisoformat)
    p.add_argument("--revision", help="Revision of supplied native/House/Senate/YouTube/inventory state. Separate CSV/body inputs are pinned by digest.")
    p.add_argument("--reuse-from", type=Path, help="Reuse an unchanged verified Parquet publication from this directory or the local output. Changed inputs, options, code or state rebuild it.")
    p.add_argument("--document-filenames", type=Path, help="Optional document-filenames table. Matching representation URLs receive a viewer-data saved copy.")
    p.add_argument("--docspec-workspace", type=Path, help="Optional docspec-rs workspace to publish immutable ExportPins for the six Parquet browser tables.")
    args = p.parse_args()
    manifest, catalog = export(**vars(args))
    if catalog is None:
        print(f"Reused verified publication {manifest.publication_id}; inputs and implementation are unchanged")
    else:
        # The returned catalog holds current sources only; count what was published.
        sources = sum(p.record_count for p in manifest.partitions
                      if p.schema_name == "committee_explorer.parquet.source_record")
        print(f"Published locally {manifest.publication_id}: {len(catalog.records)} records, {sources} source observations")


if __name__ == "__main__":
    main()
