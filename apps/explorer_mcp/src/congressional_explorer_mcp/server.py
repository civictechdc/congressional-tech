"""The public MCP surface uses only the current published archive model."""
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .models import DocumentSearch, DocumentQuery, EntitySearch, EntityQuery, SqlQuery, ExplorerError
from .worker import Worker


def create_server(selection, *, timeout=10.0):
    worker = Worker(selection, timeout=timeout)

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
        'This server searches metadata; it does not read document bodies.'))

    async def call(method, query):
        try:
            return await worker.call(method, query)
        except ExplorerError as error:
            raise ToolError(str(error)) from error

    annotations = dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=annotations)
    async def get_dataset_info(table: str | None = None, relationship: str | None = None, recipe: str | None = None) -> dict:
        """Discover tables, coverage, and published relationship/recipe IDs.

        Pass one selector: table for columns, identity and incoming/outgoing IDs;
        relationship for keys and join meaning; recipe for parameterized DuckDB SQL.
        Also accepts table=schema, capture_scope, or capture_profile for published controls.
        Examples are guidance, never executed by this tool. Older releases may lack relationship metadata.
        """
        return await call('dataset_info', dict(table=table, relationship=relationship, recipe=recipe))

    @mcp.tool(annotations=annotations)
    async def search_documents(query: DocumentSearch) -> dict:
        """Find documents by title/filename or exact published entity keys; returns references and saved file URLs.

        Text matches metadata, not full document text. Hidden documents are excluded by default.
        """
        return await call('search_documents', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_document(query: DocumentQuery) -> dict:
        """Read a document reference: summary, paged sources, or paged recoveries.

        A recovery's kind and identity_note explain its relationship; a related file is not the original.
        """
        return await call('get_document', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def search_entities(query: EntitySearch) -> dict:
        """Search meetings, witnesses, recordings, committees, members, rosters, bills or nominations.

        Text searches published names/titles; filters are exact scalar field/value matches.
        Use query_sql for dates, nested fields and multi-table joins.
        """
        return await call('search_entities', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def get_entity(query: EntityQuery) -> dict:
        """Read an entity by its published primary key, or page its directly associated documents.

        get_dataset_info describes available keys. Rosters have compound keys; use search_entities.
        """
        return await call('get_entity', query.model_dump())

    @mcp.tool(annotations=annotations)
    async def query_sql(query: SqlQuery) -> dict:
        """Run one read-only DuckDB SELECT (WITH and FROM-first supported) with optional ? parameters.

        All published Parquet tables and the joined documents view are available. Nested types stay native.
        Use hex(blob) for identifiers and unhex(?) for lookups. Fractional numbers return as strings to preserve precision.
        Results have typed columns, a row/byte cap and a truncation flag; use SQL for further paging.
        Reads are limited to selected metadata files; network access, writes, extension loading and configuration changes are disabled.
        """
        return await call('query_sql', query.model_dump())

    return mcp
