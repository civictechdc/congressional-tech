"""Measure a prepared complete release through the actual stdio MCP client.

Run with apps/explorer_mcp/.venv/bin/python; no producer imports or downloads.
RSS includes the server and all descendant processes, excluding this client.
"""
import argparse
import asyncio
from collections import defaultdict
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from threading import Event, Thread
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def sample_rss(stopped, samples):
    while not stopped.is_set():
        raw = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss=,comm='], text=True)
        rows = [line.split(None, 3) for line in raw.splitlines()]
        selected = {os.getpid()}
        while True:
            expanded = selected | {int(pid) for pid, parent, _, name in rows
                                   if int(parent) in selected and name.rsplit('/', 1)[-1] != 'ps'}
            if expanded == selected:
                break
            selected = expanded
        processes = {pid: int(rss) * 1024 for pid, _, rss, _ in rows
                     if int(pid) in selected and int(pid) != os.getpid()}
        samples.append((time.perf_counter(), processes))
        stopped.wait(.05)


async def measure(args):
    samples, calls = [], []
    stopped = Event()
    sampler = Thread(target=sample_rss, args=(stopped, samples), daemon=True)
    sampler.start()
    start = time.perf_counter()
    transport = StdioTransport(sys.executable, [
        '-m', 'congressional_explorer_mcp.cli', 'serve', '--data-dir', str(args.data_dir.resolve())
    ], keep_alive=False)
    try:
        async with Client(transport) as client:
            async def call(label, name, arguments):
                begin = time.perf_counter()
                try:
                    result = await client.call_tool(name, arguments)
                except Exception as error:
                    args.output.write_text(json.dumps(dict(status='failed', label=label,
                        arguments=arguments, error=str(error), calls=calls,
                        process_tree_peak_rss_bytes=max((sum(s[1].values()) for s in samples), default=0)),
                        indent=2) + '\n')
                    raise
                elapsed = time.perf_counter() - begin
                data = result.data
                assert not result.is_error, label
                size = len(encoded(data))
                assert size <= 128 << 10, (label, size)
                calls.append(dict(label=label, seconds=elapsed, data_bytes=size,
                                  rows=len(data.get('rows', [])), truncated=data.get('truncated', False)))
                return data

            info = await call('initial_discovery', 'get_dataset_info', {})
            startup = time.perf_counter() - start
            assert len(await client.list_tools()) == 6
            assert len(info['tables']) == 16 and info['relationships_version'] == 1
            for table in info['tables']:
                value = await call('table_discovery', 'get_dataset_info', {'table': table})
                assert value['available'] and value['identity']['fields']
            for relation in info['relationships']:
                value = await call('relationship_discovery', 'get_dataset_info', {'relationship': relation['id']})
                assert value['available'] and value['meaning']

            async def first(sql):
                data = await call('parameter_selection', 'query_sql', {'query': {'sql': sql}})
                assert data['rows'], sql
                return next(iter(data['rows'][0].values()))

            parameters = {
                'bill_id': await first('SELECT bill_id FROM bills ORDER BY bill_id LIMIT 1'),
                'nomination_id': await first('SELECT nomination_id FROM nominations ORDER BY nomination_id LIMIT 1'),
                'event_id': await first('SELECT event_id FROM meetings WHERE len(transcripts)>0 ORDER BY event_id LIMIT 1'),
                'witness_key': await first('SELECT unnest(witness_keys) AS witness_key FROM documents WHERE len(witness_keys)>0 LIMIT 1'),
                'system_code': await first('SELECT system_code FROM rosters ORDER BY system_code LIMIT 1'),
                'congress': await first('SELECT congress FROM rosters LIMIT 1'),
                'list_row': 0,
            }
            recipes = []
            for item in info['recipes']:
                recipe = await call('recipe_discovery', 'get_dataset_info', {'recipe': item['id']})
                assert recipe['available']
                recipes.append((recipe['id'], {'query': {'sql': recipe['sql'],
                    'parameters': [parameters[p['name']] for p in recipe['parameters']], 'limit': 100}}))

            document = await call('document_selection', 'search_documents', {'query': {'text': 'hearing', 'limit': 1}})
            reference = document['rows'][0]['reference']
            workload = [
                ('documents_text', 'search_documents', {'query': {'text': 'hearing', 'limit': 25}}),
                ('bill_documents', 'search_documents', {'query': {'measure_key': parameters['bill_id'], 'limit': 25}}),
                ('witnesses_text', 'search_entities', {'query': {'table': 'witnesses', 'text': 'Smith', 'limit': 25}}),
                ('document_detail', 'get_document', {'query': reference}),
                ('bill_record', 'get_entity', {'query': {'table': 'bills', 'id': parameters['bill_id']}}),
                ('aggregate', 'query_sql', {'query': {'sql': 'SELECT congress,count(*) AS documents FROM documents GROUP BY congress ORDER BY congress'}}),
                *[('recipe:' + name, 'query_sql', arguments) for name, arguments in recipes],
            ]
            for _ in range(3):
                for label, name, arguments in workload:
                    await call(label, name, arguments)
                begin = time.perf_counter()
                await asyncio.gather(*(call('concurrent:' + label, name, arguments)
                                       for label, name, arguments in workload[:4]))
                calls.append(dict(label='concurrent_batch', seconds=time.perf_counter()-begin))
    finally:
        stopped.set()
        sampler.join(timeout=3)
    grouped = defaultdict(list)
    for item in calls:
        grouped[item['label']].append(item)
    summary = {name: dict(count=len(values), median_seconds=statistics.median(v['seconds'] for v in values),
                          max_seconds=max(v['seconds'] for v in values), max_data_bytes=max(v.get('data_bytes', 0) for v in values))
               for name, values in grouped.items()}
    peak = max(samples, key=lambda sample: sum(sample[1].values()))
    result = dict(release_id=info['release_id'], tables=len(info['tables']), relationships=len(info['relationships']),
                  recipes=len(recipes), status='passed', host=platform.platform(), python=platform.python_version(),
                  startup_seconds=startup, process_tree_peak_rss_bytes=sum(peak[1].values()),
                  processes_at_peak=len(peak[1]), rss_samples=len(samples), rss_interval_target_seconds=.05,
                  observed_max_sample_interval_seconds=max(b[0]-a[0] for a,b in zip(samples,samples[1:])),
                  parameters=parameters, summary=summary, calls=calls)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('calls','parameters')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    asyncio.run(measure(parser.parse_args()))
