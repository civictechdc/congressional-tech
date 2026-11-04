"""The public MCP surface uses only the current published archive model."""
from contextlib import asynccontextmanager
from functools import partial

import anyio

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .models import DocumentSearch, DocumentQuery, EntitySearch, EntityQuery, SqlQuery, ExplorerError
from .worker import Worker
from .release import PUBLICATION, load_selection, prepare


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

    mcp = FastMCP('Congress Explorer', lifespan=lifespan, instructions=(
        'Start with get_dataset_info to see available tables and scope. '
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
        """Read a document reference: summary, paged sources, paged recoveries, or verified body text.

        Use section='text' with optional page, offset, max_chars, or query (keyword/regex snippet search)
        to read verified PDF, HTML, XML, or plain-text document bodies from the archive.
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
                raise ToolError('Document body fetch or extraction timed out') from error
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
