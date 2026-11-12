"""The public MCP surface uses only the current published archive model."""
from contextlib import asynccontextmanager
from functools import partial
import time

import anyio

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import StrictInt, StrictStr

from . import __version__
from .models import (DocumentSearch, DocumentQuery, DocumentBatch, TextSearch, EntitySearch, EntityQuery,
                     SqlQuery, ExplorerError, MAX_BYTES, BillActions, RollCalls, MemberBallots,
                     ActivityQuery, ResearchQuery)
from .worker import Worker
from .release import PUBLICATION, encoded, load_selection, prepare
from .hearing_models import HearingBundleQuery, TranscriptQuery


def create_server(selection=None, *, timeout=10.0, data_dir=None, publication=PUBLICATION, warm_on_start=False):
    if selection is None and data_dir is None:
        raise ValueError('A selected release or data directory is required')
    worker = Worker(selection, timeout=timeout)
    setup_lock = anyio.Lock()

    async def ensure_selection():
        if worker.selection is None:
            async with setup_lock:
                if worker.selection is None:
                    # Keep MCP initialization fast. The host may cancel a tool,
                    # but keep this lock until the preparer's thread finishes.
                    loader = partial(load_selection, data_dir) if (data_dir / 'selection.json').exists() else partial(prepare, data_dir, publication)
                    worker.selection = await anyio.to_thread.run_sync(loader)

    async def warm():
        await ensure_selection()
        return await worker.warm()

    @asynccontextmanager
    async def lifespan(server):
        try:
            if warm_on_start:
                await warm()
            yield
        finally:
            await worker.close()

    mcp = FastMCP('Congress Explorer', version=__version__, lifespan=lifespan, instructions=(
        'Start with get_overview for capabilities and get_dataset_status for release dates and coverage. '
        'Use get_dataset_info relationship or recipe selectors for published joins and SQL examples. '
        'Search documents or entities, then follow published identifiers. '
        'Use query_sql for arbitrary joins, nested lists and aggregations across all release tables. '
        'Document references and page cursors belong to one release. Saved file URLs are for you to fetch and read. '
        'Missing tables mean unavailable, not zero records. Witnesses identify appearances, not deduplicated people. '
        "Use search_documents for metadata and search_text for indexed document bodies and caption cues. "
        "Read verified archived document text with get_document(section='text'); get_dataset_status describes index coverage. "
        'Use get_hearing_bundle for a hearing dossier; get_transcript discovers release-bound official, committee and caption sources. '
        'Pass a returned citation to resolve_citation to reopen its original passage.'))

    @mcp.custom_route('/ready', methods=['GET'])
    async def ready(request):
        """Open and warm the exact selected data and its index before reporting readiness."""
        from starlette.responses import JSONResponse
        try:
            result = await warm()
            return JSONResponse(dict(status='ready', version=__version__, release_id=result['release_id']),
                                headers={'Cache-Control': 'no-store'})
        except Exception:
            return JSONResponse(dict(status='unavailable'), status_code=503,
                                headers={'Cache-Control': 'no-store'})

    async def call(method, query):
        try:
            await ensure_selection()
            return await worker.call(method, query)
        except (ExplorerError, OSError, ValueError, KeyError, TypeError) as error:
            raise ToolError(str(error)) from error

    annotations = dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        openWorldHint=selection is None)

    def bounded(result):
        if len(encoded(result))>MAX_BYTES:
            raise ExplorerError('Response exceeds 128 KiB; request fewer cues or a smaller max_chars window')
        return result

    async def caption_read(target,query):
        if worker.selection['manifest'].get('text_index'):
            retained=await call('indexed_caption_text',dict(source=target,query=query.model_dump()))
            if retained is not None:
                return bounded(retained)
        from .caption_reader import read_caption_page
        async def resources(ordinal,limit):
            return await call('caption_resource_page',dict(source=target,ordinal=ordinal,limit=limit))
        return bounded(await read_caption_page(target,query,resources,data_dir=data_dir,timeout=timeout))

    async def transcript_read(query):
        inventory=await call('transcript_inventory',query.model_dump())
        if query.source_id is None:
            return inventory
        target=inventory['target']
        if target['kind']=='captions':
            return await caption_read(target,query)
        if query.cursor:
            raise ExplorerError('Document transcripts use page and character offset, not a caption cursor')
        document=DocumentQuery(**target['document_reference'],section='text',offset=query.offset,page=query.page,max_chars=query.max_chars,limit=query.limit)
        # A document reference, rather than the event, remains the owner of body identity.
        result=await read_document(document)
        result.update(event_id=query.event_id,source=target,state='available')
        return bounded(result)

    @mcp.tool(annotations=annotations)
    async def get_transcript(event_id: StrictStr | StrictInt, kind: str | None = None, source_id: str | None = None,
                             offset: StrictInt = 0,limit: StrictInt = 25,page: StrictInt | None = None,max_chars: StrictInt = 8000,
                             cursor: str | None = None,release_id: str | None = None) -> dict:
        """Discover and read official transcripts, committee transcripts, or timestamped captions by meeting.

        Without source_id, returns a source inventory; offset/limit page that inventory. Choose a returned
        source_id and release_id to read its exact source. Document sources use page and character offset/max_chars;
        captions use cue offset/limit and next_cursor for efficient continuation across retained playlist segments.
        A caption read without a cursor skips up to 256 segments that hold no cue (e.g. silence before a hearing
        opens) and names them in skipped_segments; next_cursor pages read at most 32 segments each.
        Caption timestamps retain their source timebase. Package context stays labelled and does not establish
        event-specific coverage. Missing resources and unsupported playlists are explicit; only archived bytes are fetched.
        The inventory's captions field (as on meeting records) explains an absent caption source.
        """
        try:
            query=TranscriptQuery(event_id=event_id,kind=kind,source_id=source_id,offset=offset,limit=limit,page=page,
                                  max_chars=max_chars,cursor=cursor,release_id=release_id)
            with anyio.fail_after(timeout):
                return await transcript_read(query)
        except TimeoutError as error:
            raise ToolError('Transcript read timed out') from error
        except (ExplorerError,OSError,ValueError,KeyError,TypeError) as error:
            raise ToolError(str(error)) from error

    @mcp.tool(annotations=annotations)
    async def get_hearing_bundle(event_id: StrictStr | StrictInt,include: list[str] | None = None,limit: StrictInt = 10,
                                 offsets: dict[str,StrictInt] | None = None,release_id: str | None = None) -> dict:
        """Return a bounded hearing dossier using published meeting, witness and recording associations.

        Includes meeting, committees, current witnesses, prepared_testimony, official_transcripts,
        committee_transcripts, captions, recordings and coverage. A sitting Member of Congress acting officially is
        listed among witnesses as witness_type member_appearance with matched_bioguide_id and match_basis; the
        witnesses coverage count holds only outside witnesses. Narrow include to those section names;
        each section's next request continues it using offsets. Transcript rows carry get_transcript references.
        Original recording observations and event versus package_context scope remain intact.
        The meeting row's captions {advertised, archived, basis} separates publisher-advertised captions
        (basis advertised_not_archived) from retained tracks get_transcript can read (retained_track).
        Empty sections mean unknown; unavailable tables remain distinct from zero observations.
        """
        value=dict(event_id=event_id,limit=limit,offsets=offsets or {},release_id=release_id)
        if include is not None:
            value['include']=include
        query=HearingBundleQuery.model_validate(value)
        return await call('get_hearing_bundle',query.model_dump())

    @mcp.tool(annotations=annotations)
    async def resolve_citation(citation: dict) -> dict:
        """Reopen an exact PDF/text passage, publisher-selected witness statement, or caption cue.

        Pass the citation returned by a text or cue read. Citations bind to one release, saved body,
        reading version and exact location; this tool reports unavailable or different_source instead of
        silently following a changed release or body. Witness attribution requires an exact published
        occurrence association; ambiguous names never establish ownership.
        """
        from .passage_reader import resolve_passage
        try:
            with anyio.fail_after(timeout):
                if len(encoded(citation))>16384:
                    raise ExplorerError('Citation exceeds the supported reference size')
                return bounded(await resolve_passage(citation,call,caption_read,data_dir=data_dir,timeout=timeout))
        except TimeoutError as error:
            raise ToolError('Citation read timed out') from error
        except (ExplorerError,OSError,ValueError,KeyError,TypeError) as error:
            raise ToolError(str(error)) from error

    @mcp.tool(annotations=annotations)
    async def get_overview() -> dict:
        """Read compact capabilities, table names, limits, and focused discovery selectors."""
        return await call('overview', {})

    @mcp.tool(annotations=annotations)
    async def get_dataset_status() -> dict:
        """Read selected release/publication time, publisher update dates, observed coverage and gaps.

        Null dates are unavailable. Source updates, capture times, record dates and release publication are distinct.
        Bounds describe observed records and do not establish complete history. Reads retained metadata only.
        """
        return await call('dataset_status', {})

    @mcp.tool(annotations=annotations)
    async def search_text(query: TextSearch) -> dict:
        """Search the release's prepared full document bodies, testimony and retained caption cues.

        Phrase matching is literal token order; match=all/any combines words. Metadata search remains search_documents.
        Filter exact committee_key, document_type, witness_key (source association), source_kind or dates.
        Speaker matches literal publisher caption voice labels only. Unknown speakers are never inferred from witness names.
        Dates use published accepted qualification by default; include_suspect preserves explicitly requested literal suspect dates.
        Results include bounded exact snippets, body/page/offset or caption cue locations, citations and indexed coverage.
        The server queries the immutable prebuilt index and does not fetch or extract corpus bodies during search.
        """
        return await call('search_text', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_dataset_info(table: str | None = None, relationship: str | None = None, recipe: str | None = None) -> dict:
        """Discover tables, entity keys, coverage, and published relationship/recipe IDs.

        Pass one selector: table for columns, identity and incoming/outgoing IDs;
        relationship for keys and join meaning (also a pinned upstream relation's ID); recipe for parameterized DuckDB SQL.
        upstream_relations name SpicyRegs detail tables (actions, cosponsors, ballots, ...) by generation; tables available locally are listed separately; an upstream pin alone does not make rows queryable.
        Also accepts table=schema, capture_scope, or capture_profile for published controls.
        Recipe example parameters illustrate parameter format; substitute keys discovered via search_entities or search_documents.
        Examples are guidance, never executed by this tool. Older releases may lack relationship metadata.
        """
        return await call('dataset_info', dict(table=table, relationship=relationship, recipe=recipe))

    @mcp.tool(annotations=annotations)
    async def search_documents(query: DocumentSearch) -> dict:
        """Find documents by title/filename or exact published entity keys; returns references and saved file URLs.

        Text matches metadata, not full document text. Hidden documents are excluded by default.
        document_date is the document's own date; document_date_source says whether it came from the filename, content or the
        meeting date (null: no date). Where published, document_date_status 'suspect' marks a filename date that is far
        later than first capture or outside the document's Congress; treat it as a likely misreading, not the document's date.
        first_captured is when the archive first fetched it, and date_kind its basis
        (captured, import_day, unknown). Neither is a page-update date, and only a meeting-sourced date is the hearing date.
        measure_key and witness_key match direct list.<col>[] document annotations (list.measure_keys holds bill_ids);
        document_kind also matches the words the release's schema lists as the same kind (list.parquet synonyms,
        e.g. testimony and witness-statement).
        use the bill_hearing_transcripts, nomination_transcripts, and witness_transcripts recipes for package_id-linked hearing transcripts.
        sort='archive' preserves archive order. sort='recent' or 'oldest' uses accepted dates by default;
        include_suspect and include_undated opt into those rows. Older releases keep literal dates and report unavailable qualification.
        """
        return await call('search_documents', query.model_dump())

    async def read_document(query, *, body_budget=None):
        if query.section == 'text':
            indexed=await call('indexed_document_text',query.model_dump())
            if indexed is not None:
                return indexed
            from .body_reader import MAX_BODY_BYTES, read_document_body
            from .pdf_decoder import run_body_read
            target = await call('document_body_target', query.model_dump())
            if body_budget is not None:
                size = target.get('saved_bytes')
                charge = size if type(size) is int and size >= 0 else MAX_BODY_BYTES
                if charge > body_budget['remaining']:
                    raise ExplorerError('Batch body work budget reached; continue this item with get_document')
                body_budget['remaining'] -= charge
            try:
                with anyio.fail_after(timeout):
                    return await run_body_read(partial(read_document_body, target, query, data_dir=data_dir, timeout=timeout))
            except TimeoutError as error:
                raise ToolError('Document body read timed out') from error
            except (ExplorerError, OSError, ValueError, KeyError, TypeError) as error:
                raise ToolError(str(error)) from error
        return await call('get_document', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_document(query: DocumentQuery) -> dict:
        """Read a document summary, paged sources or recoveries, publisher declarations, or body text.

        Use section='text' with optional page, offset, max_chars, or query (keyword/regex snippet search)
        to read verified PDF, HTML, XML, or plain-text document bodies from the archive.
        Snippet matching uses a case-insensitive regex with a time limit. Invalid patterns are literal.
        Summary includes published_on and modified_on when supplied. They are publisher page dates.
        Use section='page_metadata' for paged declarations, including conflicting values and their source pointers.
        Use section='selected_text' with offset and max_chars for exact publisher-marked text and its citation.
        A recovery's kind states its relationship to the original, and identity_note adds an authored explanation when one
        was recorded (often null); a related file is not the original.
        """
        return await read_document(query)

    @mcp.tool(annotations=annotations)
    async def get_documents(query: DocumentBatch) -> dict:
        """Read up to ten release-bound document requests in input order, with independent errors and paging.

        Each item has get_document's query shape, including section='summary' or 'text'. Successful result values
        equal single-document responses. next_query continues that item; deferred items retain their original query.
        Work is sequential, shares one request deadline and 64 MiB of declared archived body bytes (unknown sizes
        reserve 64 MiB). The aggregate response stays within 128 KiB. Retry budget-deferred items with get_document
        or a smaller batch. An item too large for the remaining budget is not partially returned.
        """
        from .body_reader import MAX_BODY_BYTES
        result = dict(release_id=None, items=[dict(status='deferred', next_query=item.model_dump(exclude_none=True),
            reason='Batch response or work budget reached; continue this item') for item in query.items])
        deadline = time.monotonic() + timeout
        body_budget = dict(remaining=MAX_BODY_BYTES)
        for index, item in enumerate(query.items):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                with anyio.fail_after(remaining):
                    value = await read_document(item, body_budget=body_budget)
                result['release_id'] = value.get('release_id') or result['release_id']
                entry = dict(status='ok', result=value)
                continuation = item.model_dump(exclude_none=True)
                if value.get('next_cursor'):
                    continuation['cursor'] = value['next_cursor']
                    entry['next_query'] = continuation
                elif value.get('next_offset') is not None:
                    continuation['offset'] = value['next_offset']
                    entry['next_query'] = continuation
                elif value.get('next_page') is not None:
                    continuation.update(page=value['next_page'], offset=0)
                    entry['next_query'] = continuation
            except TimeoutError:
                break
            except (ToolError, ExplorerError, OSError, ValueError, KeyError, TypeError) as error:
                entry = dict(status='error', error=str(error)[:2000], reference=dict(release_id=item.release_id, link_key=item.link_key))
                if 'work budget reached' in str(error):
                    continue
            previous = result['items'][index]
            result['items'][index] = entry
            if len(encoded(result)) > MAX_BYTES:
                result['items'][index] = previous
        if worker.selection is not None:
            result['release_id'] = worker.selection['release_id']
        return result

    @mcp.tool(annotations=annotations)
    async def search_entities(query: EntitySearch) -> dict:
        """Search any table the release's schema keys by a published identifier (get_dataset_info lists entity_keys).

        Text searches published names/titles/short_titles; filters are exact scalar field/value matches.
        rosters holds seat assignments (bioguide_id, system_code, role title); use the committee_roster recipe or members table for member names.
        Integer filters accept integers or base-10 integer strings; decimals, exponents and booleans are rejected.
        Use query_sql for dates, nested fields and multi-table joins.
        """
        return await call('search_entities', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_entity(query: EntityQuery) -> dict:
        """Read an entity by its published primary key, or page its directly associated documents.

        get_dataset_info lists entity_keys. Compound keys (rosters, meeting_coverage, ...) use search_entities.
        Default mode='detail' preserves all fields. mode='summary' reads scalar columns; fields selects exact published
        columns and always retains the primary key. get_dataset_info(table=...) lists available and summary fields.
        Omitted nested details remain available with mode='detail', fields, or query_sql list slicing.
        section='documents' follows direct list.<col>[] document annotations (list.measure_keys holds bill_ids);
        use nomination_transcripts, bill_hearing_transcripts, and witness_transcripts recipes for package_id-linked hearing transcripts.
        Integer IDs accept leading zeros and surrounding whitespace; decimals, exponents and booleans are rejected.
        Meeting records add captions: advertised (publisher video metadata or a recording says captions exist),
        archived (retained caption tracks) and basis (retained_track, advertised_not_archived, or the coverage reason).
        For a saved HLS (m3u8) track, saved_url downloads the retained playlist file.
        Relative segment paths refer to the publisher's playlist context. Use the publisher recording link for playback.
        """
        return await call('get_entity', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def query_sql(query: SqlQuery) -> dict:
        """Run one read-only DuckDB SELECT (WITH and FROM-first supported) with optional ? parameters.

        All published Parquet tables and the joined documents view are available. Nested types stay native.
        Use SELECT * EXCLUDE (facts) FROM documents when scanning document rows without provenance facts.
        Use hex(blob) for identifiers and unhex(?) for lookups. Fractional numbers return as strings to preserve precision.
        SQL compares system_code exactly. Codes are lowercase; a full committee usually ends 00 and its subcommittees
        share its first four letters (hsif00, hsif14), so match a committee family by prefix, e.g. LIKE 'hsif%'.
        committees.parent_system_code is authoritative where a task force's prefix differs from its parent's.
        Results have typed columns, a row/byte cap and a truncation flag; use SQL for further paging.
        Reads are limited to selected metadata files; network access, writes, extension loading and configuration changes are disabled.
        """
        return await call('query_sql', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_bill_actions(query: BillActions) -> dict:
        """Page every recorded bill action by calendar date and supplied local clock time, by bill or date window.

        since is inclusive and until exclusive (YYYY-MM-DD). Same-day source entries remain distinct by
        bill_id/action_index. Parseable local times sort first, then unknown times; no timezone is inferred.
        stage is an upstream derived status; voice actions remain actions, not ballots.
        Chamber follows source_system_name where explicit; source_generation/reference identify pinned rows.
        Missing detail tables return unavailable coverage, never a fabricated empty history.
        """
        return await call('get_bill_actions', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_roll_calls(query: RollCalls) -> dict:
        """Page full roll-call rows by vote_id, bill_id, chamber or inclusive/exclusive date window.

        Reads the entire selected roll-call input, including votes outside local bill/nomination profiles.
        Totals and individual ballots remain separate. bill_references retains source bill-action associations even outside local bill profiles.
        vote_day owns calendar filtering; vote_date preserves the publisher literal and its precision.
        """
        return await call('get_roll_calls', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_member_ballots(query: MemberBallots) -> dict:
        """Page individual ballots by vote_id, member_key or bioguide_id, with optional dated vote window.

        member_key preserves upstream member identity even where bioguide_id is unavailable.
        position and position_normalized stay distinct. Date filters join the roll call's vote_day;
        literal ballot vote_date is retained. Ballots are not vote totals or voice-vote actions.
        """
        return await call('get_member_ballots', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_activity(query: ActivityQuery) -> dict:
        """Read dated legislative events: bill actions, roll calls, nomination received/latest action, meeting schedules.

        since is inclusive, until exclusive; omitted until means onward. Dates have day precision and remain
        distinct by source occurrence key. Same-day actions follow supplied local clock time, then unknown times;
        no timezone is inferred. Committee resolves one published code/name and matches its exact
        associations. Topic resolves a published bill subject, including meetings explicitly linked to those bills. Roll calls follow direct
        bill_id and supported bill references without duplicating the vote.
        Coverage reports missing sources; schedules do not establish that a meeting occurred.
        """
        return await call('get_activity', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def run_research_query(query: ResearchQuery) -> dict:
        """Run recent_bills, pending_nominations, hearings_by_committee or legislation_by_subject.

        Dates filter introduced, received or meeting_date, since inclusive/until exclusive; order is newest
        date then canonical ID. committee is one exact published code or unambiguous name; subject is one
        published subject label. Ambiguous input returns candidates. Pending means no terminal action recorded
        in a known latest action in this snapshot; missing latest actions remain unknown. Source references,
        missing fields and unavailable collection coverage are explicit. Continue with the returned cursor.
        """
        return await call('run_research_query', query.model_dump())

    return mcp
