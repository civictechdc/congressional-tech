"""Offline export, validated before an atomic local publication pointer changes."""
import argparse
from collections import ChainMap, Counter, defaultdict
import csv
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile

from committee_meeting import Catalog, SCHEMA_VERSION
from committee_meeting.common import Ref
from committee_meeting.provenance import Citation, Method, RetainedContent
from committee_meeting.publication import ExportPartition, InputSnapshot, PublicationManifest, SourceScope
from congress_api.adapters.common import AdapterContext
from congress_api.adapters import meetings as native, house, gpo, transcripts, findings, inventory, video_matches, recordings as curated_recordings
from congress_api.adapters import committee_metadata, committee_adjustments
from congress_api.adapters.committees import committee_lookup, ensure_committee_term
from .assemble import Assembly
from .coverage import build as coverage
from .ids import IdRegistry
from .issues import apply_decisions
from .query import write_queries
from .history import load_history, save_history, migrate_history

VERSION = "0.1.0"


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    data = Path(path).read_bytes()
    body = gzip.decompress(data) if data.startswith(b"\x1f\x8b") else data
    return data, body


def validate_selectors(catalog):
    from committee_meeting.catalog import _pointer_exists
    from committee_meeting.common import Model
    sources = {s.id: s for s in catalog.sources}
    def visit(value):
        if isinstance(value, Citation) and value.selector_type == "json_pointer":
            payload = sources[value.source.id].payload
            if payload is None or not _pointer_exists(payload, value.selector):
                raise ValueError(f"Citation does not resolve: {value.source.id} {value.selector}")
        elif isinstance(value, Model):
            for name in type(value).model_fields:
                visit(getattr(value, name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                visit(item)
    for record in catalog.records:
        visit(record)


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
    from congress_api.adapters.senate import official_events

    native_by_event = defaultdict(list)
    for row in rows:
        native_by_event[str(row['eventId'])].append(row)
    matches = defaultdict(set)
    for event in official_events(senate_state):
        saved = set(map(str, event['page'].get('events') or ()))
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


def export(*, meetings, output_dir, state_dir, gpo_path=None, house_state=None, senate_state=None,
           youtube_dir=None, inventory_state=None, recovered_witnesses=None, video_matches_path=None, recordings_path=None,
           transcript_files=(), issue_decisions=None, attempts=None, limit=None, as_of=None, revision=None, format="json", reuse_from=None, committees_path=None):
    if format not in ("json", "parquet"):
        raise ValueError("format must be json or parquet")
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if reuse_from is not None and format != "parquet":
        raise ValueError("publication reuse requires parquet format")
    transcript_files = tuple(transcript_files)
    attempt_receipt = json.loads(Path(attempts).read_text()) if attempts else {}
    provider_jobs = {'youtube':'youtube', 'congress.gov':'congress', 'govinfo':'congress', 'gpo-video-matches':'congress',
                     'docs.house.gov':'meetings', 'senate.committees':'meetings', 'meeting-inventory':'meetings', 'recovered-witnesses':'meetings',
                     'congress.gov:committees':'committees'}
    output, state = Path(output_dir), Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    with (state / "export.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reuse_key = None
        if reuse_from is not None:
            from .reuse import request_key, try_reuse, save_receipt
            reuse_key = request_key(files={
                'meetings': meetings, 'gpo': gpo_path, 'house': house_state, 'senate': senate_state,
                'inventory': inventory_state, 'recovered_witnesses': recovered_witnesses,
                'video_matches': video_matches_path, 'recordings': recordings_path,
                'issue_decisions': issue_decisions, 'attempts': attempts, 'committees': committees_path,
            }, youtube_dir=youtube_dir, transcript_files=transcript_files, format=format, limit=limit, as_of=as_of)
            if reused := try_reuse(output, state, reuse_from, reuse_key):
                return reused, None
        ids = IdRegistry(state / "ids.json")
        previous, previous_manifest = load_previous(output, state)
        previous_id = previous_manifest.publication_id if previous_manifest else None
        assembly = Assembly(previous, ids=ids, now=now)
        snapshots, scopes, reconciliation = [], [], []
        def context(path, provider, limitations=()):
            raw, body = read(path)
            input_id = provider + ":" + sha(raw)
            job = provider_jobs.get(provider)
            result = (attempt_receipt.get('jobs', {}).get(job) or {}).get('result')
            status = {'success':'succeeded','failure':'failed','cancelled':'not_run','skipped':'not_run'}.get(result,'unknown')
            checked_at = attempt_receipt.get('completed_at') if result else None
            if result:
                limitations = (*limitations, f"Collection job {job} concluded {result}; this job-level receipt does not establish individual source acquisition outcomes.")
            snapshots.append(InputSnapshot(id=input_id, provider=provider, artifact=RetainedContent(uri="sha256:" + sha(raw), sha256=sha(raw)),
                                            revision=revision if provider in ("congress.gov", "docs.house.gov", "senate.committees", "youtube", "meeting-inventory") else None,
                                            imported_at=now, last_attempt_at=checked_at, last_attempt_status=status, limitations=tuple(limitations)))
            return AdapterContext(now, input_id, provider, ids), body
        ctx, body = context(meetings, "congress.gov", ("Legacy native records lack per-record retrieval timestamps.",))
        rows = [json.loads(line) for line in body.splitlines() if line.strip()]
        rows.sort(key=native.meeting_key)
        all_meetings = rows
        total = len(rows)
        if limit:
            rows = rows[:limit]
        senate_input = None
        if senate_state:
            senate_context, senate_body = context(senate_state, 'senate.committees',
                ('Legacy checked dates may reflect seed import; live retrieval is established only by explicit receipts.',))
            senate_data = json.loads(senate_body)
            senate_input = (senate_context, senate_data)
            retained_ids = _retain_senate_meeting_ids(rows, senate_data, ids)
            if retained_ids:
                reconciliation.append({'provider': 'senate.committees', 'retained_meeting_id_aliases': retained_ids})
        assembly.add(native.records(rows, ctx))
        if committees_path:
            committee_context, committee_body = context(committees_path, 'congress.gov:committees')
            committee_rows = [json.loads(line) for line in committee_body.splitlines() if line.strip()]
            selected_congresses = {int(row['congress']) for row in rows}
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
        else:
            scopes.append(SourceScope(provider='congress.gov:committees', scope='Official Congress-scoped committee lists',
                                      status='not_collected', explanation='No retained committee metadata supplied; names do not establish committee type.'))
        reconciliation.append({"provider": "congress.gov", "input_records": total, "selected_records": len(rows),
                               "distinct_selected_identities": len({native.meeting_key(r) for r in rows})})
        lookup = {(int(r["congress"]), native.chamber(r.get("chamber")), str(r["eventId"])):
                  Ref(kind="meeting", id=ids("meeting", native.meeting_key(r))) for r in rows}
        scopes.insert(0, SourceScope(provider="congress.gov", scope="retained committee meeting records, all statuses", status="partial" if len(rows)<total else "included",
                                  input_snapshot_ids=(ctx.input_id,), explanation=f"Imported {len(rows)} of {total} retained records. Retention is not proof of complete upstream coverage."))
        # Load document metadata before supplemental events so every explicitly
        # identified committee can be linked without requiring a meeting match.
        gpo_context, gpo_rows, all_gpo = None, [], []
        if gpo_path:
            gpo_context, content = context(gpo_path, "govinfo", ("CSV does not preserve all raw MODS metadata or downloaded transcript bytes.",))
            all_gpo = list(csv.DictReader(io.StringIO(content.decode())))
            gpo_rows = all_gpo
            if limit:
                selected = [r for r in all_gpo if (int(r["congress"]), native.chamber(r["chamber"]), r["event_id"]) in lookup]
                selected_ids = {r["package_id"] for r in selected}
                gpo_rows = selected + [r for r in all_gpo if r["package_id"] not in selected_ids][:limit]
            assembly.add(gpo.committee_records(gpo_rows, gpo_context, existing=assembly.records))

        sources = (("docs.house.gov", house_state, house, "House parsed source state"),)
        if senate_state:
            from congress_api.adapters import senate
            sources += (("senate.committees", senate_state, senate, "Senate parsed source state"),)
        supplemental = []
        for provider, path, adapter, label in sources:
            if path:
                if provider == 'senate.committees':
                    c, data = senate_input
                else:
                    c, content = context(path, provider, ("Legacy checked dates may reflect seed import; live retrieval is established only by explicit receipts.",))
                    data = json.loads(content)
                if provider == "docs.house.gov" and limit:
                    data = {k: v for k, v in data.items() if any(x[2] == str(k) for x in lookup)}
                if provider == "senate.committees":
                    if limit:
                        # A bounded rehearsal must not admit every source-only
                        # historical event in the full retained Senate cache.
                        selected_events = {key[2] for key in lookup}
                        data = {host: {**site, 'pages': {url: page for url, page in site.get('pages', {}).items()
                                if selected_events.intersection(map(str, page.get('events') or ()))}}
                                for host, site in data.items()}
                    for event in senate.official_events(data):
                        source = c.source(f"senate-page|{event['host']}|{event['url']}", event['page'], event['url'])
                        evidence = c.evidence(source, selector='/event')
                        missing = list(ensure_committee_term(event['congress'], event['committee_code'],
                                       event['committee_code'], c, evidence, assembly.records))
                        if missing:
                            assembly.add([source, *missing])
                supplemental.append((provider, adapter, data, c))
                reconciliation.append({"provider": provider, "selected_top_level_entries": len(data)})
                scopes.append(SourceScope(provider=provider, scope=label, status="partial", input_snapshot_ids=(c.input_id,), explanation="Retained supplemental source records; uncollected meetings and unsupported layouts are not covered."))
            else:
                scopes.append(SourceScope(provider=provider, scope=label, status="not_collected", explanation="No input was supplied to this offline export."))
        if not senate_state:
            scopes.append(SourceScope(provider="senate.committees", scope="Senate parsed source state", status="not_collected", explanation="No input was supplied to this offline export."))

        adjustment_context, _ = context(committee_adjustments.__file__, 'committee-review')
        selected_congresses = {int(row['congress']) for row in rows} if limit else None
        for item in committee_metadata.adjustment_records(adjustment_context, assembly.records, congresses=selected_congresses):
            key = (item.kind, item.id)
            into = assembly.sources if item.kind == 'source_record' else assembly.records
            into[key] = item
            assembly.current.add(key)
        scopes.append(SourceScope(provider='committee-review', scope='Reviewed committee metadata corrections', status='included',
                                  input_snapshot_ids=(adjustment_context.input_id,),
                                  explanation='Cited corrections preserve original source names and classifications.'))
        committees = committee_lookup(assembly.records.values())
        for provider, adapter, data, c in supplemental:
            options = {'meetings': lookup}
            if provider == 'senate.committees':
                options.update(committee_terms=committees,
                               meeting_records={r.id: r for r in assembly.records.values() if r.kind == 'meeting'})
            assembly.add(adapter.records(data, c, **options))

        versions, print_versions = {}, {}
        print_decisions = []
        if gpo_path:
            c, data = gpo_context, gpo_rows
            assembled = list(gpo.records(data, c, meetings=lookup, committees=committees))
            assembly.add(assembled)
            reconciliation.append({"provider": "govinfo", "input_records": len(all_gpo), "selected_records": len(data),
                                   "distinct_selected_identities": len({r['package_id'] for r in data})})
            mats = {r.id: r for r in assembled if r.kind == "material"}
            for r in assembled:
                if r.kind == "material_version":
                    for identifier in mats[r.material.id].identifiers:
                        if "govinfo" in identifier.scheme or "gpo" in identifier.scheme:
                            versions[("govinfo", identifier.value)] = Ref(kind=r.kind, id=r.id)
                            print_versions[identifier.value] = (Ref(kind="material", id=r.material.id), Ref(kind=r.kind, id=r.id))
            from congress_api.inventory.prints import match_prints
            # The matcher owns its existing scope/rules. Ambiguous unscoped IDs
            # are excluded from association output rather than merged.
            eligible = [r for r in all_meetings if r.get("meetingStatus") in ("Scheduled", "Rescheduled") and int(r["congress"]) >= 113]
            match_prints(eligible, all_gpo, decisions=print_decisions)
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
                linked = {r.material.id: r.provenance for r in assembly.records.values()
                          if r.kind == "material_link" and r.role == "transcript" and r.subject.kind == "meeting"}
                from committee_meeting.issues import IssueResolution
                for key, issue in list(assembly.records.items()):
                    if issue.kind == "data_issue" and issue.category == "unlinked" and issue.subject.id in linked:
                        assembly.add([issue.model_copy(update={"status": "resolved", "resolution": IssueResolution(decided_at=now,
                            explanation="The existing print matcher supplied a supported association; its method and evidence remain on the link.", provenance=linked[issue.subject.id])})])
            scopes.append(SourceScope(provider="govinfo", scope="retained GPO package metadata", status="partial" if limit else "included", input_snapshot_ids=(c.input_id,), explanation=f"Imported {len(data)} packages; explicit event IDs and existing print matching rules supply associations with retained evidence."))
        else:
            scopes.append(SourceScope(provider="govinfo", scope="GPO packages", status="not_collected", explanation="No GPO input was supplied."))
        if youtube_dir:
            from youtube_api import adapters as youtube
            for path in sorted(Path(youtube_dir).glob("youtube_*.json")):
                c, content = context(path, "youtube")
                data = json.loads(content)
                videos = [v for table, entries in data.items() if table.startswith("youtube_videos_") for v in entries.values()]
                input_videos = len(videos)
                if limit:
                    videos = sorted(videos, key=lambda v: v["videoId"])[:limit]
                # Provider IDs in native video URLs are explicit associations.
                # The metadata adapter receives their source evidence unchanged.
                associations = defaultdict(list)
                for link in assembly.records.values():
                    if link.kind == "material_link" and link.role == "recording" and link.subject.kind == "meeting":
                        material = assembly.records[("material", link.material.id)]
                        for identifier in material.identifiers:
                            if identifier.scheme == "youtube.video":
                                associations[identifier.value].append((link.subject, link.provenance))
                imported = list(youtube.records(videos, c, meetings=associations))
                assembly.add(imported)
                reconciliation.append({"provider": "youtube", "input": path.name, "input_records": input_videos,
                                       "selected_records": len(videos), "distinct_selected_identities": len({v['videoId'] for v in videos})})
                video_materials = {r.id: r for r in imported if r.kind == "material"}
                for r in imported:
                    if r.kind == "material_version":
                        for identifier in video_materials[r.material.id].identifiers:
                            if identifier.scheme == "youtube.video":
                                versions[("youtube", identifier.value)] = Ref(kind=r.kind, id=r.id)
                scopes.append(SourceScope(provider="youtube", scope=path.name, status="partial", input_snapshot_ids=(c.input_id,), explanation="Retained metadata only; caption availability and reachability have not been checked by this export."))
        else:
            scopes.append(SourceScope(provider="youtube", scope="YouTube video metadata", status="not_collected", explanation="Only links carried by other supplied inputs are represented."))
        if recordings_path:
            c, content = context(recordings_path, "curated-recordings")
            decisions = list(csv.DictReader(io.StringIO(content.decode())))
            assembly.add(curated_recordings.records(decisions, c, meetings=lookup))
            reconciliation.append({"provider": "curated-recordings", "input_records": len(decisions), "selected_records": len(decisions)})
            scopes.append(SourceScope(provider="curated-recordings", scope="retained manual meeting-recording associations", status="included", input_snapshot_ids=(c.input_id,), explanation="Original notes and discovery method retained; links do not prove full coverage or current reachability."))
        else:
            scopes.append(SourceScope(provider="curated-recordings", scope="manual meeting-recording associations", status="not_collected", explanation="No retained manual associations supplied."))
        # Retained decisions enrich known identities; they do not trigger acquisition.
        materials = {r.id: r for r in assembly.records.values() if r.kind == "material"}
        material_versions = {r.material.id: Ref(kind=r.kind, id=r.id) for r in assembly.records.values() if r.kind == "material_version"}
        recordings, inventory_materials = {}, {}
        for material in materials.values():
            for identifier in material.identifiers:
                if identifier.scheme in ("youtube.video", "senate.filename"):
                    provider = "youtube" if identifier.scheme == "youtube.video" else "senate"
                    inventory_materials[(provider, identifier.value)] = Ref(kind="material", id=material.id)
                    if material.id in material_versions:
                        recordings[identifier.value] = (Ref(kind="material", id=material.id), material_versions[material.id])
                        versions[(provider, identifier.value)] = material_versions[material.id]
        if video_matches_path:
            c, content = context(video_matches_path, "gpo-video-matches")
            decisions = list(csv.DictReader(io.StringIO(content.decode())))
            packages = {key: pair[0] for key, pair in print_versions.items()}
            package_by_material = {v.id: k for k, v in packages.items()}
            package_meetings = defaultdict(list)
            package_evidence = defaultdict(list)
            for record in assembly.records.values():
                if record.kind == "material_link" and record.subject.kind == "meeting" and record.material.id in package_by_material:
                    package_meetings[package_by_material[record.material.id]].append(record.subject)
                    package_evidence[(package_by_material[record.material.id], record.subject.id)].append(record.provenance)
            assembly.add(video_matches.records(decisions, c, packages=packages, recordings=recordings,
                package_meetings=package_meetings, package_evidence=package_evidence))
            reconciliation.append({"provider": "gpo-video-matches", "input_records": len(decisions), "selected_records": len(decisions)})
            scopes.append(SourceScope(provider="gpo-video-matches", scope="retained package recording decisions", status="included", input_snapshot_ids=(c.input_id,), explanation="Aggregate matcher evidence retained; only single-meeting, single-date package associations create meeting links."))
        else:
            scopes.append(SourceScope(provider="gpo-video-matches", scope="package recording decisions", status="not_collected", explanation="No retained decisions supplied."))
        if inventory_state:
            for material in assembly.records.values():
                if material.kind == "material":
                    for identifier in material.identifiers:
                        if identifier.scheme in ("youtube.video", "senate.filename"):
                            provider = "youtube" if identifier.scheme == "youtube.video" else "senate"
                            inventory_materials[(provider, identifier.value)] = Ref(kind="material", id=material.id)
            c, content = context(inventory_state, "meeting-inventory")
            data = json.loads(content)
            assembly.add(inventory.records(data, c, meetings=lookup, materials=inventory_materials))
            reconciliation.append({"provider": "meeting-inventory", "input_records": sum(len(v) for v in data.values() if isinstance(v, dict)), "families": {k: len(v) for k,v in data.items() if isinstance(v,dict)}})
            scopes.append(SourceScope(provider="meeting-inventory", scope="retained caption, archive and witness observations", status="included", input_snapshot_ids=(c.input_id,), explanation="Unsupported ownership and cache-derived dates remain explicit issues; no caption content is invented."))
        else:
            scopes.append(SourceScope(provider="meeting-inventory", scope="caption, archive and witness observations", status="not_collected", explanation="No retained inventory supplied."))
        if recovered_witnesses:
            c, content = context(recovered_witnesses, "recovered-witnesses")
            data = list(csv.DictReader(io.StringIO(content.decode())))
            # Exact repeated descriptions of one meeting appearance can share
            # identity. Different descriptions remain separate, inspectable claims.
            def appearance_key(r):
                return (r.meeting.id, r.name.display, r.affiliation.model_dump_json() if r.affiliation else None, r.roles)
            known_appearances = {appearance_key(r): r.id for r in assembly.records.values() if r.kind == "appearance"}
            def recovered():
                for r in inventory.records({}, c, meetings=lookup, recovered_witnesses=data):
                    if r.kind == "appearance":
                        key = appearance_key(r)
                        if key in known_appearances:
                            r = r.model_copy(update={"id": known_appearances[key]})
                        else:
                            known_appearances[key] = r.id
                    yield r
            assembly.add(recovered())
            reconciliation.append({"provider": "recovered-witnesses", "input_records": len(data), "selected_records": len(data), "distinct_rows": len({json.dumps(r,sort_keys=True) for r in data})})
            scopes.append(SourceScope(provider="recovered-witnesses", scope="retained recovered witness rows", status="included", input_snapshot_ids=(c.input_id,), explanation="Unique explicit event associations supply listed appearances; title-derived nominees remain inferred. Exact repeated appearance descriptions share identity."))
        else:
            scopes.append(SourceScope(provider="recovered-witnesses", scope="recovered witness rows", status="not_collected", explanation="No recovered witness table supplied."))
        for path in transcript_files:
            c, _ = context(path, "transcript-artifact")
            assembly.add(transcripts.records([Path(path)], c, meetings=lookup, source_versions=versions))
            scopes.append(SourceScope(provider="transcript-artifact", scope=Path(path).name, status="included", input_snapshot_ids=(c.input_id,), explanation="Existing local artifact imported; no text generation or acquisition performed."))
        if not transcript_files:
            scopes.append(SourceScope(provider="transcript-artifact", scope="retained transcript bodies", status="not_collected", explanation="No body artifacts were supplied; metadata links do not establish captured or searchable text."))
        catalog = assembly.finish()
        if previous is not None: previous.close()
        if issue_decisions:
            c, content = context(issue_decisions, "curated-issue-decisions")
            catalog = apply_decisions(catalog, json.loads(content), c)
        validate_selectors(catalog)
        # Previous issue evidence may reference earlier inputs. Preserve those
        # snapshots from the previous manifest instead of inventing freshness.
        known = {s.id for s in snapshots}
        if previous_id:
            used = {s.input_snapshot_id for s in catalog.sources}
            snapshots += [s for s in previous_manifest.inputs if s.id in used and s.id not in known]
        if any(s.input_snapshot_id not in {v.id for v in snapshots} for s in catalog.sources):
            raise ValueError("A source refers to an input absent from the manifest")
        if format == "json":
            current_records = [r for r in catalog.records if (r.kind, r.id) in assembly.current]
            dated, appearances, materials, issues = defaultdict(list), defaultdict(int), defaultdict(set), defaultdict(list)
            for r in current_records:
                if r.kind == "occurrence" and r.scheduled_start:
                    dated[r.meeting.id].append(r.scheduled_start.model_dump(mode="json"))
                elif r.kind == "appearance": appearances[r.meeting.id] += 1
                elif r.kind == "material_link" and r.subject.kind == "meeting": materials[r.subject.id].add(r.material.id)
            for r in catalog.records:
                if r.kind == "data_issue" and r.status == "open": issues[r.subject.id].append(r.id)
            index = [{"id": r.id, "title": r.title, "congress": r.congress, "chamber": r.chamber,
                      "scheduled_dates": dated[r.id], "committee_ids": [v.committee.id for v in r.committees],
                      "appearance_count": appearances[r.id], "material_count": len(materials[r.id]), "issue_ids": issues[r.id]}
                     for r in current_records if r.kind == "meeting"]
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
            if format == "json":
                # Serialize records individually: a full Python JSON tree would
                # duplicate the largest artifact in memory before writing any bytes.
                with (stage / "catalog.json").open("wb") as stream:
                    stream.write(b'{"schema_version":' + json.dumps(SCHEMA_VERSION).encode())
                    for field, values in (("sources", catalog.sources), ("records", catalog.records)):
                        stream.write(b',"' + field.encode() + b'":[')
                        for i, record in enumerate(values):
                            if i: stream.write(b',')
                            stream.write(record.model_dump_json().encode())
                        stream.write(b']')
                    stream.write(b'}\n')
                descriptor("catalog.json", "download", "committee_meeting.Catalog", len(catalog.records))
                if print_decisions:
                    write("inputs/print-decisions.json", print_decisions, "sources", "congress_api.print-decisions", len(print_decisions))
                if attempt_receipt:
                    write("inputs/collection-attempt.json", attempt_receipt, "sources", "committee_explorer.collection-attempt", 1)
                write("indexes/meetings.json", {"schema_version": SCHEMA_VERSION, "rows": index}, "index", "committee_explorer.meetings", len(index))
                del index, dated, appearances, materials, issues, current_records
                locations, oversized = defaultdict(dict), []
                chunk_budget = 2 * 1024 * 1024
                def chunks(values, field, role, schema_name):
                    parts, keys, size, number = [], [], 0, 0
                    prefix = b'{"schema_version":' + json.dumps(SCHEMA_VERSION).encode() + b',"' + field.encode() + b'":['
                    def flush():
                        nonlocal parts, keys, size, number
                        if not parts: return
                        path = f"{role}/{number:05d}.json"
                        raw = prefix + b','.join(parts) + b']}\n'
                        write(path, None, role, schema_name, len(parts), raw=raw)
                        for key in keys:
                            locations[sha(key.encode())[:2]][key] = path
                        if len(raw) > chunk_budget:
                            oversized.append({"path": path, "byte_size": len(raw), "record_keys": keys})
                        number += 1
                        parts, keys, size = [], [], 0
                    for record in values:
                        raw = record.model_dump_json().encode()
                        if parts and size + len(raw) + len(prefix) + 4 > chunk_budget:
                            flush()
                        parts.append(raw)
                        keys.append(record.kind + "/" + record.id)
                        size += len(raw) + 1
                    flush()
                chunks(catalog.sources, "sources", "sources", "committee_explorer.sources")
                chunks(catalog.records, "records", "details", "committee_explorer.records")
                buckets = {}
                for bucket, entries in sorted(locations.items()):
                    path = f"indexes/locations/{bucket}.json"
                    buckets[bucket] = path
                    write(path, {"schema_version": SCHEMA_VERSION, "locations": entries}, "index", "committee_explorer.location-bucket", len(entries))
                write("indexes/locations.json", {"schema_version": SCHEMA_VERSION, "key_format": "<kind>/<id>",
                    "bucket_algorithm": "sha256-prefix-2", "buckets": buckets, "chunk_byte_budget": chunk_budget,
                    "oversized_single_records": oversized}, "index", "committee_explorer.locations", len(buckets))
                # The query and inverse-link indexes need their own working maps.
                # Release the completed locator maps before constructing those.
                del locations, buckets
            evidence_states = {}
            report = coverage(catalog, assembly.current, [s.id for s in snapshots], states_out=evidence_states)
            report["input_reconciliation"] = reconciliation
            report["source_observation_counts"] = dict(Counter(s.provider for s in catalog.sources))
            write("coverage.json", report, "coverage", "committee_explorer.coverage", len(report["metrics"]))
            if format == "parquet":
                from .parquet import write_catalog
                write_catalog(catalog, assembly.current, stage, descriptor, write, evidence_states)
            else:
                write_queries(catalog, assembly.current, write, evidence_states=evidence_states)
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
            history_records = ChainMap(assembly.records, assembly.sources)
            if issue_decisions:
                history_records = {(r.kind,r.id):r for values in (catalog.records,catalog.sources) for r in values}
            save_history(state, publication_id, history_records)
            ids.save()
            release = output / "releases" / publication_id
            release.parent.mkdir(exist_ok=True)
            if release.exists():
                shutil.rmtree(stage)
            else:
                stage.rename(release)
            pointer = {"schema_version": SCHEMA_VERSION, "publication_id": publication_id, "manifest_path": f"releases/{publication_id}/manifest.json",
                       "manifest_sha256": sha(manifest_raw), "media_type": "application/json"}
            temporary = output / ".CURRENT.json.tmp"
            temporary.write_bytes(encode(pointer))
            temporary.replace(output / "CURRENT.json")
            retained_manifest = state / ".publication.json.tmp"
            retained_manifest.write_bytes(manifest_raw)
            retained_manifest.replace(state / "publication.json")
            for old in (state / "issue-history").glob("*.sqlite"):
                if old.stem != publication_id: old.unlink()
            if reuse_key is not None:
                save_receipt(state, reuse_key, manifest)
            return manifest, catalog
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format", choices=("json", "parquet"), default="parquet")
    p.add_argument("--meetings", type=Path, required=True)
    p.add_argument("--committees-path", type=Path, help="Retained Congress-scoped committee metadata JSON Lines, optionally gzipped.")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--gpo-path", type=Path)
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
    args = p.parse_args()
    manifest, catalog = export(**vars(args))
    if catalog is None:
        print(f"Reused verified publication {manifest.publication_id}; inputs and implementation are unchanged")
    else:
        print(f"Published locally {manifest.publication_id}: {len(catalog.records)} records, {len(catalog.sources)} source observations")


if __name__ == "__main__":
    main()
