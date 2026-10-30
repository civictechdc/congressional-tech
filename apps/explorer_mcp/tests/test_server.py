import asyncio
from pathlib import Path
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pytest

from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.release import prepare
from congressional_explorer_mcp.worker import Worker


def test_timeout_cancellation_restart_and_spill_cleanup(selection):
    async def run():
        worker = Worker(selection)
        try:
            assert (await worker.call('query_sql', {'sql':'SELECT 1 AS n'}))['rows'] == [{'n':1}]
            first_pid = worker.process.pid
            scratch = Path(worker.scratch.name)
            worker.timeout = .05
            with pytest.raises(ExplorerError,match='deadline'):
                await worker.call('query_sql', {'sql':'SELECT sum(sin(i::DOUBLE)) FROM range(1000000000) t(i)'})
            assert worker.process is None and not scratch.exists()
            worker.timeout = 10
            await worker.call('dataset_info', {})
            assert worker.process.pid != first_pid
            scratch = Path(worker.scratch.name)
            task = asyncio.create_task(worker.call('query_sql', {'sql':'SELECT sum(sin(i::DOUBLE)) FROM range(1000000000) t(i)'}))
            await asyncio.sleep(.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert worker.process is None and not scratch.exists()
            assert (await worker.call('query_sql', {'sql':'SELECT 2 AS n'}))['rows'] == [{'n':2}]
        finally:
            scratch = Path(worker.scratch.name) if worker.scratch else None
            await worker.close()
            assert scratch is None or not scratch.exists()
    asyncio.run(run())


def test_bounded_queue_and_closed_worker(selection):
    async def run():
        worker=Worker(selection)
        await worker.lock.acquire()
        tasks=[asyncio.create_task(worker.call('dataset_info',{})) for _ in range(5)]
        await asyncio.sleep(.01)
        with pytest.raises(ExplorerError,match='queue is full'):
            await worker.call('dataset_info',{})
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        assert worker.pending == 0
        worker.lock.release()
        await worker.close()
        with pytest.raises(ExplorerError,match='closing'):
            await worker.call('dataset_info',{})
    asyncio.run(run())


def test_real_stdio_tools_and_errors(tmp_path,phase2):
    selected=prepare(tmp_path,phase2,archive_origin='https://archive.example')
    async def run():
        transport=StdioTransport(sys.executable,['-m','congressional_explorer_mcp.cli','serve','--data-dir',str(tmp_path)],keep_alive=False)
        async with Client(transport) as client:
            tools=await client.list_tools()
            assert {t.name for t in tools} == {'get_dataset_info','search_documents','get_document','search_entities','get_entity','query_sql'}
            assert all(t.annotations.read_only_hint for t in tools)
            async def call(name, query=None):
                result=await client.call_tool(name,{'query':query} if query is not None else {})
                return result.data
            assert (await call('get_dataset_info'))['release_id'] == selected['release_id']
            relation = (await client.call_tool('get_dataset_info', {'relationship': 'document_meetings'})).data
            assert relation['match'] == 'decimal_string_to_integer'
            recipe = (await client.call_tool('get_dataset_info', {'recipe': 'bill_documents'})).data
            assert (await call('query_sql', {'sql': recipe['sql'], 'parameters': ['119-hr-1']}))['rows'][0]['filename'] == 'Agenda.pdf'
            found=await call('search_documents',{'measure_key':'119-hr-1'})
            assert (await call('get_document',found['rows'][0]['reference']))['rows'][0]['filename'] == 'Agenda.pdf'
            assert len((await call('search_entities',{'table':'witnesses','text':'Alex'}))['rows']) == 2
            assert (await call('get_entity',{'table':'bills','id':'119-hr-1'}))['rows'][0]['bill_id'] == '119-hr-1'
            assert (await call('query_sql',{'sql':'SELECT count(*) AS n FROM documents'}))['rows'] == [{'n':7}]
            error=await client.call_tool('query_sql',{'query':{'sql':'DROP VIEW documents'}},raise_on_error=False)
            assert error.is_error and 'read-only SELECT' in error.content[0].text
            assert (await call('query_sql',{'sql':'SELECT 1 AS alive'}))['rows'] == [{'alive':1}]
    asyncio.run(run())
