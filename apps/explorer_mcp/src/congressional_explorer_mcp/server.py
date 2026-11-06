"""The public MCP surface uses only the current published archive model."""
from contextlib import asynccontextmanager
from functools import partial

import anyio

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import StrictInt, StrictStr

from . import __version__
from .models import DocumentSearch, DocumentQuery, EntitySearch, EntityQuery, SqlQuery, ExplorerError, MAX_BYTES
from .worker import Worker
from .release import PUBLICATION, load_selection, prepare, encoded
from .hearing_models import HearingBundleQuery, TranscriptQuery


def create_server(selection=None, *, timeout=10.0, data_dir=None, publication=PUBLICATION):
    if selection is None and data_dir is None:
        raise ValueError('A selected release or data directory is required')
    worker = Worker(selection, timeout=timeout)
    setup_lock = anyio.Lock()

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield
        finally:
            await worker.close()

    mcp = FastMCP('Congress Explorer', version=__version__, lifespan=lifespan, instructions=(
        'Start with get_dataset_info to see available tables and scope. '
        'Use get_dataset_info relationship or recipe selectors for published joins and SQL examples. '
        'Search documents or entities, then follow published identifiers. '
        'Use query_sql for arbitrary joins, nested lists and aggregations across all release tables. '
        'Document references and page cursors belong to one release. Saved file URLs are for you to fetch and read. '
        'Missing tables mean unavailable, not zero records. Witnesses identify appearances, not deduplicated people. '
        "This server searches metadata and reads verified archived document bodies via get_document(section='text'). "
        'Use get_hearing_bundle for a hearing dossier; get_transcript discovers release-bound official, committee and caption sources. '
        'Pass a returned citation to resolve_citation to reopen its original passage.'))

    async def call(method, query):
        try:
            if worker.selection is None:
                async with setup_lock:
                    if worker.selection is None:
                        # Keep MCP initialization fast. The host may cancel a tool,
                        # but keep this lock until the preparer's thread finishes.
                        loader = partial(load_selection, data_dir) if (data_dir / 'selection.json').exists() else partial(prepare, data_dir, publication)
                        worker.selection = await anyio.to_thread.run_sync(loader)
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
        from .body_reader import read_document_body
        document=DocumentQuery(**target['document_reference'],section='text',offset=query.offset,page=query.page,max_chars=query.max_chars,limit=query.limit)
        # A document reference, rather than the event, remains the owner of body identity.
        body_target=await call('document_body_target',document.model_dump())
        result=await anyio.to_thread.run_sync(partial(read_document_body,body_target,document,data_dir=data_dir,timeout=timeout),abandon_on_cancel=True)
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
        Caption timestamps retain their source timebase. Package context stays labelled and does not establish
        event-specific coverage. Missing resources and unsupported playlists are explicit; only archived bytes are fetched.
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
        committee_transcripts, captions, recordings and coverage. Narrow include to those section names;
        each section's next request continues it using offsets. Transcript rows carry get_transcript references.
        Original recording observations and event versus package_context scope remain intact.
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
    async def get_dataset_info(table: str | None = None, relationship: str | None = None, recipe: str | None = None) -> dict:
        """Discover tables, entity keys, coverage, and published relationship/recipe IDs.

        Pass one selector: table for columns, identity and incoming/outgoing IDs;
        relationship for keys and join meaning (also a pinned upstream relation's ID); recipe for parameterized DuckDB SQL.
        upstream_relations name SpicyRegs detail tables (actions, cosponsors, ballots, ...) by generation; they are not in this release.
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
        use the bill_hearing_transcripts, nomination_transcripts, and witness_transcripts recipes for package_id-linked hearing transcripts.
        """
        return await call('search_documents', query.model_dump())

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
        if query.section == 'text':
            from .body_reader import read_document_body
            target = await call('document_body_target', query.model_dump())
            try:
                with anyio.fail_after(timeout):
                    return await anyio.to_thread.run_sync(
                        partial(read_document_body, target, query, data_dir=data_dir, timeout=timeout),
                        abandon_on_cancel=True,
                    )
            except TimeoutError as error:
                raise ToolError('Document body read timed out') from error
            except (ExplorerError, OSError, ValueError, KeyError, TypeError) as error:
                raise ToolError(str(error)) from error
        return await call('get_document', query.model_dump())

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
        section='documents' follows direct list.<col>[] document annotations (list.measure_keys holds bill_ids);
        use nomination_transcripts, bill_hearing_transcripts, and witness_transcripts recipes for package_id-linked hearing transcripts.
        Integer IDs accept leading zeros and surrounding whitespace; decimals, exponents and booleans are rejected.
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

    return mcp
