"""Exercise real stalled decoder processes, rather than mocked timeout errors."""
import asyncio
from functools import partial
import json
import os
import subprocess
import sys
import time

import anyio
import pytest

from congressional_explorer_mcp import body_reader, pdf_decoder
from test_body_reader import make_pdf_bytes, local_archive_server, _prepare_body_fixture


def stalled_decoder(monkeypatch, tmp_path, stage):
    marker = tmp_path / 'started.json'
    original = subprocess.Popen
    processes = []
    # Replace only the parser inside a real decoder child. The production
    # supervisor, process group, cancellation, pipes and reap path all run.
    setup = f'''
import json, os, runpy, signal, sys, time
import pypdf
marker = {str(marker)!r}
def stall(*args, **kwargs):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(marker, 'w') as stream:
        json.dump(dict(pid=os.getpid()), stream)
    while True:
        time.sleep(.01)
'''
    if stage == 'constructor':
        setup += '\npypdf.PdfReader = stall\n'
    elif stage == 'page':
        setup += '''
class Page:
    extract_text = stall
class Reader:
    pages = [Page()]
pypdf.PdfReader = lambda *args, **kwargs: Reader()
'''
    else:
        tool = tmp_path / 'pdftotext'
        tool.write_text(f'#!{sys.executable}\n' + setup.split('import pypdf')[0] +
                        f'\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                        f'open({str(marker)!r}, "w").write(json.dumps(dict(pid=os.getpid())))\n'
                        'while True: time.sleep(.01)\n')
        tool.chmod(0o700)
        setup += f'''
import shutil
shutil.which = lambda name: {str(tool)!r}
def broken(*args, **kwargs):
    raise ValueError('Force real Poppler fallback')
pypdf.PdfReader = broken
'''
    setup += "\nsys.argv = ['pdf_decoder', sys.argv[1]]\nrunpy.run_module('congressional_explorer_mcp.pdf_decoder', run_name='__main__')\n"

    def launch(command, **kwargs):
        if command[1:3] == ['-m', 'congressional_explorer_mcp.pdf_decoder']:
            command = [sys.executable, '-c', setup, command[3]]
            process = original(command, **kwargs)
            processes.append(process)
            return process
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', launch)
    return marker, processes


def assert_stopped(marker, processes, *, reaped=False):
    assert processes and all(p.poll() is not None for p in processes)
    pid = json.loads(marker.read_text())['pid']
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    if reaped:
        pytest.fail(f'Poppler child {pid} was not reaped before its decoder exited')
    # A killed grandchild can briefly remain as a zombie awaiting init's reap.
    status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    assert not status or status.startswith('Z'), (pid, status)


@pytest.mark.parametrize('stage', ['constructor', 'page', 'poppler'])
def test_stalled_pdf_deadline_kills_decoder_family(monkeypatch, tmp_path, stage):
    marker, processes = stalled_decoder(monkeypatch, tmp_path, stage)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match='timed out'):
        body_reader._extract_pdf_pages(make_pdf_bytes(['First', 'Second']), deadline=started + 2)
    assert time.monotonic() - started < 4
    assert marker.exists(), 'The test must actually enter the stalled parser'
    assert_stopped(marker, processes, reaped=stage == 'poppler')


@pytest.mark.parametrize('cancel', ['scope', 'task'])
@pytest.mark.parametrize('stage', ['constructor', 'page', 'poppler'])
def test_cancellation_waits_for_pdf_cleanup(monkeypatch, tmp_path, stage, cancel):
    marker, processes = stalled_decoder(monkeypatch, tmp_path, stage)

    async def run():
        def decode():
            # PDF magic wins over the caption-like declared format too.
            return body_reader.extract_pages(make_pdf_bytes(['First', 'Second']), 'vtt',
                                             deadline=time.monotonic() + 20)

        async def cancel_when_started(scope=None, task=None):
            with anyio.fail_after(5):
                while not marker.exists():
                    await anyio.sleep(.01)
            if scope is not None:
                scope.cancel()
            else:
                task.cancel()

        if cancel == 'scope':
            async with anyio.create_task_group() as group:
                with anyio.CancelScope() as scope:
                    group.start_soon(partial(cancel_when_started, scope=scope))
                    await pdf_decoder.run_body_read(decode)
        else:
            task = asyncio.create_task(pdf_decoder.run_body_read(decode))
            await cancel_when_started(task=task)
            with pytest.raises(asyncio.CancelledError):
                await task
        assert_stopped(marker, processes, reaped=stage == 'poppler')

    asyncio.run(run())


def test_pdf_read_preserves_pages_and_backend_after_a_timeout():
    payload = make_pdf_bytes(['First physical page.', 'Second physical page.'])
    with pytest.raises(TimeoutError):
        body_reader._extract_pdf_pages(payload, deadline=time.monotonic() - 1)
    backend = {}
    assert body_reader._extract_pdf_pages(payload, deadline=time.monotonic() + 5, backend_info=backend) == [
        'First physical page.', 'Second physical page.']
    assert backend['name'] == 'pypdf' and backend['version'] == '6.21.4'


def test_queued_cancel_does_not_start_body_work():
    async def run():
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1
        called = []
        try:
            async with limiter:
                task = asyncio.create_task(pdf_decoder.run_body_read(lambda: called.append(True)))
                await anyio.sleep(.02)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            await anyio.sleep(.02)
            assert not called
        finally:
            limiter.total_tokens = previous
    asyncio.run(run())


def test_repeated_task_cancellation_waits_for_thread_cleanup():
    from threading import Event
    started, release, finished = Event(), Event(), Event()
    def work():
        started.set()
        release.wait(2)
        finished.set()
    async def run():
        task = asyncio.create_task(pdf_decoder.run_body_read(work))
        while not started.is_set():
            await anyio.sleep(.01)
        task.cancel()
        await anyio.sleep(.02)
        task.cancel()
        await anyio.sleep(.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    asyncio.run(run())


@pytest.mark.parametrize('consumer', ['document', 'citation', 'caption'])
def test_actual_consumers_cancel_decoder_and_preserve_cache(monkeypatch, tmp_path, consumer):
    from hashlib import sha256
    from fastmcp import Client
    from congressional_explorer_mcp.citations import text_citation
    from congressional_explorer_mcp.caption_reader import read_caption_page
    from congressional_explorer_mcp.hearing_models import TranscriptQuery
    from congressional_explorer_mcp.passage_reader import resolve_passage
    from congressional_explorer_mcp.reader import Reader
    from congressional_explorer_mcp.server import create_server

    payload = make_pdf_bytes(['First physical page.', 'Second physical page.'])
    digest = sha256(payload).digest()
    path = f'/bodies/sha256/{digest.hex()[:2]}/{digest.hex()}.pdf'
    with local_archive_server({path: payload}) as (origin, requests):
        directory, selected, keys = _prepare_body_fixture(tmp_path, [dict(
            filename='two-pages.pdf', format='pdf', saved_body=digest, saved_suffix='.pdf',
            saved_media_type='application/pdf', saved_bytes=len(payload))], origin)
        query = dict(release_id=selected['release_id'], link_key=keys[0], section='text', page=2, max_chars=18)
        reader = Reader(selected)
        try:
            target = reader.document_body_target(query)
        finally:
            reader.close()
        marker, processes = stalled_decoder(monkeypatch, tmp_path, 'page')

        async def run():
            async with Client(create_server(selected, data_dir=directory)) as client:
                await client.call_tool('get_overview')
                if consumer == 'document':
                    work = client.call_tool('get_document', dict(query=query))
                elif consumer == 'citation':
                    citation = text_citation(target, dict(kind='body_text', page=2, offset=0, length=18),
                                             'Second physical pa')
                    async def call(method, value):
                        return dict(release_id=selected['release_id']) if method == 'overview' else target
                    work = resolve_passage(citation, call, None, data_dir=directory)
                else:
                    async def resources(*args):
                        raise AssertionError('Direct captions do not need a resource map')
                    work = read_caption_page(dict(target, format='vtt'), TranscriptQuery(event_id=1), resources,
                                             data_dir=directory)
                task = asyncio.create_task(work)
                with anyio.fail_after(5):
                    while not marker.exists():
                        await anyio.sleep(.01)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                # FastMCP forwards client cancellation to the server task.
                with anyio.fail_after(3):
                    while processes and any(p.poll() is None for p in processes):
                        await anyio.sleep(.01)
                assert_stopped(marker, processes)
                assert not list((directory / 'bodies').glob('*'))
                monkeypatch.undo()
                result = await client.call_tool('get_document', dict(query=query))
                assert result.data['text'] == 'Second physical pa'
                assert result.data['page_count'] == 2
                assert list((directory / 'bodies').glob('*.json'))
                request_count = len(requests)
                cached = await client.call_tool('get_document', dict(query=query))
                assert cached.data == result.data and len(requests) == request_count
        asyncio.run(run())
