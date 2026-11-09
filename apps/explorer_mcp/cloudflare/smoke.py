"""Check hosted readiness and the app's normal research tools over real HTTP."""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.request import Request, urlopen

from fastmcp import Client

from congressional_explorer_mcp import __version__
from congressional_explorer_mcp.validation import check_client


async def check(url, release_id, *, plan=None, require_research=False):
    readiness_url = url.removesuffix('/mcp').rstrip('/') + '/ready'
    def readiness():
        request = Request(readiness_url, headers={'User-Agent': f'congress-explorer-smoke/{__version__}'})
        with urlopen(request, timeout=120) as response:
            assert response.status == 200
            return json.load(response)
    ready = await asyncio.to_thread(readiness)
    assert ready == dict(status='ready', version=__version__, release_id=release_id), ready
    async with Client(url, timeout=120) as client:
        result = await check_client(client, release_id, plan=plan, require_research=require_research)
        async with Client(url, timeout=120) as second:
            assert second.server_info is not None and second.server_info.version == __version__
            values = await asyncio.gather(*[
                current.call_tool('query_sql', {'query': {'sql': 'SELECT ? AS n', 'parameters': [n]}})
                for n, current in enumerate((client, second))
            ])
            assert [value.data['rows'] for value in values] == [[{'n': 0}], [{'n': 1}]]
        return dict(result, url=url, readiness=ready, concurrent_clients=2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--probe-plan', type=Path)
    parser.add_argument('--require-research', action='store_true')
    args = parser.parse_args()
    plan = json.loads(args.probe_plan.read_text()) if args.probe_plan else None
    print(json.dumps(asyncio.run(check(args.url, args.release_id, plan=plan, require_research=args.require_research)), indent=2))
