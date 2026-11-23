"""SereneDB Docs Search's read-only tools on the existing Congress Explorer server."""
import json
from typing import Annotated
from urllib.parse import urlsplit

import anyio
from fastmcp import Context
from fastmcp.exceptions import ToolError
import httpx2 as httpx
from pydantic import Field

from .models import MAX_BYTES


def backend_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('SpicyEngine requires a configured HTTP origin')
    return value.rstrip('/')


def register_tools(server, origin, selected_release, timeout):
    """Match the upstream search_docs, read_section and docs_health tool names and arguments."""
    annotations = dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
    search_mode = {}

    async def request(ctx, release, method, path, **kwargs):
        client = ctx.lifespan_context['archive_search']
        try:
            with anyio.fail_after(timeout):
                async with client.stream(method, path, **kwargs) as response:
                    if response.status_code == 409:
                        raise ToolError('The cited search index changed. Search again for a current citation.')
                    if response.status_code == 404:
                        raise ToolError('The cited section was not found.')
                    if response.status_code == 400:
                        raise ToolError('SpicyEngine rejected the search or section reference.')
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_BYTES:
                            raise ToolError('Search response exceeds the supported size. Request fewer results.')
                        data.extend(chunk)
            result = json.loads(data)
        except (httpx.HTTPError, TimeoutError, UnicodeError, ValueError) as exc:
            raise ToolError('Archive search is unavailable. Retry shortly.') from exc
        if not isinstance(result, dict) or result.get('release_id') != release:
            raise ToolError('SpicyEngine is not serving the archive release selected by Congress Explorer.')
        return result

    def section_path(url):
        path = url.removeprefix(origin + '/') if url.startswith(origin + '/') else url.removeprefix('/')
        if not path.startswith(('page?', 'v1/record?')):
            raise ToolError('Use the archive section URL returned by search_docs.')
        return '/' + path

    @server.tool(annotations=annotations)
    async def docs_health(ctx: Context) -> dict:
        """Check archive document search, its publication, indexed document count and search mode."""
        release = await selected_release()
        result = await request(ctx, release, 'GET', '/v1/health')
        if result.get('searchType') not in ('fulltext', 'hybrid'):
            raise ToolError('SpicyEngine returned an unknown search mode.')
        search_mode.clear()
        search_mode[release] = result['searchType']
        return result

    @server.tool(annotations=annotations)
    async def search_docs(query: Annotated[str, Field(min_length=1, max_length=1000)], ctx: Context,
                          limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 5) -> dict:
        """Search congressional archive documents by keywords or quoted phrase. Open a hit's url with read_section.

        Results include a snippet and the publisher listing when available. Use search_text for caption cues.
        """
        release = await selected_release()
        mode = search_mode.get(release)
        if mode is None:
            mode = (await docs_health(ctx))['searchType']
        result = await request(ctx, release, 'POST', '/v1/search', json=dict(q=query, mode=mode, limit=limit))
        for hit in result['results']:
            hit['url'] = origin + section_path(hit['url'])
            if hit.get('end_url'):
                hit['end_url'] = origin + section_path(hit['end_url'])
        return result

    @server.tool(annotations=annotations)
    async def read_section(url: Annotated[str, Field(min_length=1, max_length=32768)], ctx: Context) -> dict:
        """Read the archived page or document opening at the exact URL returned by search_docs."""
        path = section_path(url)
        result = await request(ctx, await selected_release(), 'GET', '/v1/section', params={'url': path})
        result['url'] = origin + section_path(result['url'])
        return result
