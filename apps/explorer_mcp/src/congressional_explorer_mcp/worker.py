"""One query process; cancellation and deadlines reclaim its connection and spill."""
import asyncio
import multiprocessing
import os
import socket
from tempfile import TemporaryDirectory
import time

from .models import ExplorerError, MAX_BYTES
from .release import encoded


def _offline(*args, **kwargs):
    raise OSError('Network access is disabled in the query process')


def _run(connection, selection, scratch):
    import duckdb
    from .reader import Reader

    for name in list(os.environ):
        if any(token in name.upper() for token in ('TOKEN', 'SECRET', 'PASSWORD', 'AWS_', 'API_KEY', 'CREDENTIAL')):
            os.environ.pop(name, None)
    socket.create_connection = socket.socket.connect = socket.socket.connect_ex = _offline
    reader = None
    try:
        reader = Reader(selection, scratch=scratch)
        connection.send({'ready': True})
        while message := connection.recv():
            method, query = message
            try:
                result = getattr(reader, method)(query)
                if len(encoded(result)) > MAX_BYTES:
                    raise ExplorerError('Response exceeds 128 KiB; select a table, fewer fields, or a smaller page')
                connection.send({'result': result})
            except duckdb.OutOfMemoryException:
                connection.send({'error': 'Query exceeded DuckDB memory limits; narrow the query', 'restart': True})
            except Exception as error:
                connection.send({'error': str(error)[:4000]})
    except (EOFError, BrokenPipeError):
        pass
    except Exception as error:
        connection.send({'error': str(error)[:4000], 'restart': True})
    finally:
        if reader is not None:
            reader.close()
        connection.close()


class Worker:
    def __init__(self, selection, *, timeout=10.0):
        if not 0 < timeout <= 120:
            raise ExplorerError('Query timeout must be greater than zero and at most 120 seconds')
        self.selection, self.timeout = selection, timeout
        self.lock = asyncio.Lock()
        self.pending = 0
        self.process = self.connection = self.scratch = None
        self.closed = False

    async def _receive(self, deadline):
        while time.monotonic() < deadline:
            if self.connection.poll():
                message = self.connection.recv()
                if 'error' in message:
                    if message.get('restart'):
                        await self._stop()
                    raise ExplorerError(message['error'])
                return message
            if not self.process.is_alive():
                await self._stop()
                raise ExplorerError('Query process exited; retry with a narrower query')
            await asyncio.sleep(.005)
        await self._stop()
        raise ExplorerError('Query exceeded its deadline; the query process was stopped')

    async def _start(self):
        context = multiprocessing.get_context('spawn')
        self.scratch = TemporaryDirectory(prefix='congress-mcp-query-')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_run, args=(child, self.selection, self.scratch.name), daemon=True)
        try:
            self.process.start()
            child.close()
            await self._receive(time.monotonic() + self.timeout)
        except BaseException:
            child.close()
            await self._stop()
            raise

    async def _stop(self):
        process, connection, scratch = self.process, self.connection, self.scratch
        self.process = self.connection = self.scratch = None
        if process:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                await asyncio.to_thread(process.join, 2)
                if process.is_alive():
                    process.kill()
                    await asyncio.to_thread(process.join)
            process.close()
        if connection:
            connection.close()
        if scratch:
            scratch.cleanup()

    async def call(self, method, query):
        if self.closed:
            raise ExplorerError('Server is closing')
        if self.pending >= 5:
            raise ExplorerError('Query queue is full: one active query and four pending')
        self.pending += 1
        try:
            async with self.lock:
                if self.closed:
                    raise ExplorerError('Server is closing')
                try:
                    if self.process is None:
                        await self._start()
                    self.connection.send((method, query))
                    return (await self._receive(time.monotonic() + self.timeout))['result']
                except (asyncio.CancelledError, EOFError, BrokenPipeError):
                    await asyncio.shield(self._stop())
                    raise
        finally:
            self.pending -= 1

    async def close(self):
        self.closed = True
        async with self.lock:
            await self._stop()
