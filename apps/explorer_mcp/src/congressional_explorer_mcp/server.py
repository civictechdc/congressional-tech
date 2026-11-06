"""The public MCP surface uses only the current published archive model."""
from contextlib import asynccontextmanager
from functools import partial
import time

import anyio

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from . import __version__
from .models import (DocumentSearch, DocumentQuery, DocumentBatch, EntitySearch, EntityQuery,
                     SqlQuery, ExplorerError, MAX_BYTES, BillActions, RollCalls, MemberBallots,
                     ActivityQuery, ResearchQuery)
from .worker import Worker
from .release import PUBLICATION, encoded, load_selection, prepare


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
        'Start with get_overview for capabilities and get_dataset_status for release dates and coverage. '
        'Use get_dataset_info relationship or recipe selectors for published joins and SQL examples. '
        'Search documents or entities, then follow published identifiers. '
        'Use query_sql for arbitrary joins, nested lists and aggregations across all release tables. '
        'Document references and page cursors belong to one release. Saved file URLs are for you to fetch and read. '
        'Missing tables mean unavailable, not zero records. Witnesses identify appearances, not deduplicated people. '
        "This server searches metadata and reads verified archived document bodies via get_document(section='text')."))

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
        use the bill_hearing_transcripts, nomination_transcripts, and witness_transcripts recipes for package_id-linked hearing transcripts.
        sort='archive' preserves archive order. sort='recent' or 'oldest' uses accepted dates by default;
        include_suspect and include_undated opt into those rows. Older releases keep literal dates and report unavailable qualification.
        """
        return await call('search_documents', query.model_dump())

    async def read_document(query, *, body_budget=None):
        if query.section == 'text':
            from .body_reader import MAX_BODY_BYTES, read_document_body
            target = await call('document_body_target', query.model_dump())
            if body_budget is not None:
                size = target.get('saved_bytes')
                charge = size if type(size) is int and size >= 0 else MAX_BODY_BYTES
                if charge > body_budget['remaining']:
                    raise ExplorerError('Batch body work budget reached; continue this item with get_document')
                body_budget['remaining'] -= charge
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
        """Page every recorded bill action in chronological source order, by bill or date window.

        since is inclusive and until exclusive (YYYY-MM-DD). Same-day source entries remain distinct by
        bill_id/action_index. stage is an upstream derived status; voice actions remain actions, not ballots.
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
        distinct by source occurrence key. Committee resolves one published code/name and matches its exact
        associations. Topic resolves a published bill subject, including meetings explicitly linked to those bills.
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
