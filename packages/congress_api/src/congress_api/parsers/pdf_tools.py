"""Bounded Poppler fallback for PDFs the primary reader cannot interpret.

Requires pdfinfo and pdftotext (poppler-utils). Processes read temporary input
files and cannot fetch URLs. Missing tools and refused output are explicit errors.
"""

from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
import selectors
import subprocess
from tempfile import TemporaryDirectory
import time


class PdfToolError(ValueError):
    """The alternate reader could not finish within its declared limits."""


BODY_LIMIT = 16 * 1024**2
OUTPUT_LIMIT = 1024**2
TIMEOUT = 10


def _run(command, *, output_limit=OUTPUT_LIMIT, timeout=TIMEOUT):
    """Drain both pipes within byte/time limits; always reap the child."""
    output = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise PdfToolError('PDF tool unavailable') from exc
    try:
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            for name in output:
                selector.register(getattr(process, name), selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PdfToolError('PDF tool deadline exceeded')
                for key, _ in selector.select(remaining):
                    chunk = key.fileobj.read1(65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = output[key.data]
                    cap = output_limit if key.data == 'stdout' else 65536
                    if len(target) + len(chunk) > cap:
                        raise PdfToolError('PDF tool output limit exceeded')
                    target.extend(chunk)
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise PdfToolError('PDF tool deadline exceeded') from exc
            if code:
                raise PdfToolError('PDF tool rejected document')
        return bytes(output['stdout']), bytes(output['stderr'])
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


@lru_cache(maxsize=1)
def reader_versions():
    """Include external reader identity in new readings; old readings stay valid."""
    result = {'pypdf': version('pypdf')}
    for tool in ('pdfinfo', 'pdftotext'):
        try:
            stdout, stderr = _run([tool, '-v'], output_limit=65536)
            result[tool] = (stdout + stderr).decode('utf-8', errors='replace').splitlines()[0]
        except (PdfToolError, IndexError):
            result[tool] = 'unavailable'
    return result


def _read(data, tool, args):
    if len(data) > BODY_LIMIT:
        raise PdfToolError('PDF alternate reader input limit exceeded')
    with TemporaryDirectory(prefix='pdf-read-') as directory:
        path = Path(directory) / 'source.pdf'
        path.write_bytes(data)
        return _run([tool, *args, str(path), *(['-'] if tool == 'pdftotext' else [])])[0]


def readable_pdf(data):
    """Establish readable PDF structure, not completeness or substantive content."""
    import re
    try:
        info = _read(data, 'pdfinfo', [])
    except PdfToolError:
        return False
    pages = re.search(rb'^Pages:\s+([1-9][0-9]*)\s*$', info, re.M)
    return pages is not None


def opening_page_text(data, page):
    """Extract only the requested opening page, preserving page boundaries."""
    if page not in (1, 2):
        raise ValueError('Only the first two pages may be read')
    output = _read(data, 'pdftotext', ['-f', str(page), '-l', str(page), '-enc', 'UTF-8'])
    return output.decode('utf-8').removesuffix('\f')
