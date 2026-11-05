"""Check a running HTTP deployment with the app's locked FastMCP client."""
import argparse
import asyncio
import json
import time

from fastmcp import Client

from congressional_explorer_mcp import __version__


async def check(url, release_id):
    timings = {}
    async with Client(url, timeout=120) as client:
        assert client.server_info is not None
        assert client.server_info.version == __version__, client.server_info.version
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            'get_dataset_info', 'search_documents', 'get_document',
            'search_entities', 'get_entity', 'query_sql',
        }
        assert all(tool.annotations.read_only_hint for tool in tools)

        async def call(name, arguments=None):
            started = time.monotonic()
            result = await client.call_tool(name, arguments or {})
            timings[name] = round(time.monotonic() - started, 3)
            return result.data

        info = await call('get_dataset_info')
        assert info['release_id'] == release_id, info['release_id']
        found = await call('search_documents', {'query': {'measure_key': '119-hr-1', 'limit': 1}})
        reference = found['rows'][0]['reference']
        assert reference['release_id'] == release_id
        document = await call('get_document', {'query': reference})
        assert document['rows'][0]['filename'] == found['rows'][0]['filename']
        entities = await call('search_entities', {'query': {
            'table': 'bills', 'filters': {'bill_id': '119-hr-1'}, 'limit': 1,
        }})
        assert entities['rows'][0]['bill_id'] == '119-hr-1'
        entity = await call('get_entity', {'query': {'table': 'bills', 'id': '119-hr-1'}})
        assert entity['rows'][0]['bill_id'] == '119-hr-1'
        count = await call('query_sql', {'query': {'sql': 'SELECT count(*) AS n FROM documents'}})
        assert count['rows'][0]['n'] > 0
        denied = await client.call_tool('query_sql', {'query': {'sql': 'DROP VIEW documents'}}, raise_on_error=False)
        assert denied.is_error and 'read-only SELECT' in denied.content[0].text
        async with Client(url, timeout=120) as second:
            assert second.server_info is not None
            assert second.server_info.version == __version__, second.server_info.version
            values = await asyncio.gather(*[
                current.call_tool('query_sql', {'query': {'sql': 'SELECT ? AS n', 'parameters': [n]}})
                for n, current in enumerate((client, second))
            ])
            assert [value.data['rows'] for value in values] == [[{'n': 0}], [{'n': 1}]]
        return {
            'status': 'ok', 'url': url, 'release_id': release_id, 'server_version': client.server_info.version,
            'tools': sorted(tool.name for tool in tools),
            'documents': count['rows'][0]['n'], 'seconds': timings,
            'write_rejected': True, 'concurrent_clients': 2,
        }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--release-id', required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(check(args.url, args.release_id)), indent=2))
