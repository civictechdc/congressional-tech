"""Bounded Poppler fallback for PDFs the primary reader cannot interpret.

Requires pdfinfo and pdftotext (poppler-utils). Processes read temporary input
files and cannot fetch URLs. Missing tools and refused output are explicit errors.
"""

from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
import selectors
import subprocess
import sys
from tempfile import TemporaryDirectory
import time


class PdfToolError(ValueError):
    """The alternate reader could not finish within its declared limits."""


class PdfToolTimeoutError(PdfToolError):
    """The reader exceeded its elapsed-time allowance."""


class PdfToolMemoryError(PdfToolError):
    """The reader exceeded its sampled resident-memory allowance."""


class PdfToolOutputError(PdfToolError):
    """The reader exceeded its bounded text or diagnostic output."""


BODY_LIMIT = 16 * 1024**2
OUTPUT_LIMIT = 1024**2
TIMEOUT = 10
MEMORY_LIMIT = 512 * 1024**2


def _resident_bytes(pid):
    """Poppler has no children; use the same system RSS units as capture's guard."""
    try:
        result = subprocess.run(['ps', '-o', 'rss=', '-p', str(pid)],
                                capture_output=True, text=True, timeout=1)
        if result.returncode not in (0, 1) or result.stderr.strip():
            raise PdfToolError('PDF reader memory measurement unavailable')
        return int(result.stdout.strip()) * 1024 if result.stdout.strip() else 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise PdfToolError('PDF reader memory measurement unavailable') from exc


def _run(command, *, output_limit=OUTPUT_LIMIT, timeout=TIMEOUT, memory_limit=None):
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
            while selector.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PdfToolTimeoutError('PDF tool deadline exceeded')
                if memory_limit is not None and _resident_bytes(process.pid) > memory_limit:
                    raise PdfToolMemoryError('PDF tool memory limit exceeded')
                for key, _ in selector.select(min(remaining, 0.1)
                                              if memory_limit or not selector.get_map() else remaining):
                    chunk = key.fileobj.read1(65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = output[key.data]
                    cap = output_limit if key.data == 'stdout' else 65536
                    if len(target) + len(chunk) > cap:
                        raise PdfToolOutputError('PDF tool output limit exceeded')
                    target.extend(chunk)
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise PdfToolTimeoutError('PDF tool deadline exceeded') from exc
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


def _read_file(path, tool, args):
    """Read a retained local PDF without allocating or copying its full body.

    A fresh subprocess limits CPU and (on Linux) address space before replacing
    itself with Poppler. The parent limits elapsed time, output and sampled RSS
    on both supported platforms. These checks do not constitute a sandbox.
    """
    path = Path(path).resolve()
    if not path.is_file():
        raise PdfToolError('PDF reader requires a regular local file')
    with path.open('rb') as source:
        if not source.read(1024).lstrip().startswith(b'%PDF-'):
            raise PdfToolError('PDF reader input is not a PDF')
    command = [sys.executable, str(Path(__file__).resolve()), tool, *args,
               str(path), *(['-'] if tool == 'pdftotext' else [])]
    return _run(command, memory_limit=MEMORY_LIMIT)[0]


def page_count_file(path):
    """Read structure only; a page count does not prove every page is readable."""
    import re
    info = _read_file(path, 'pdfinfo', [])
    pages = re.search(rb'^Pages:\s+([1-9][0-9]*)\s*$', info, re.M)
    if pages is None:
        raise PdfToolError('PDF reader reported no pages')
    return int(pages[1])


def opening_page_text_file(path, page):
    """Read one of the first two pages from a file within fixed reader bounds."""
    if page not in (1, 2):
        raise ValueError('Only the first two pages may be read')
    output = _read_file(path, 'pdftotext', ['-f', str(page), '-l', str(page), '-enc', 'UTF-8'])
    return output.decode('utf-8').removesuffix('\f')


if __name__ == '__main__':
    # Avoid preexec_fn, which is unsafe when metadata workers have threads.
    import os
    import resource
    if len(sys.argv) < 3 or sys.argv[1] not in ('pdfinfo', 'pdftotext'):
        raise SystemExit('Expected a supported PDF reader and arguments')
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    if sys.platform == 'linux':
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
    os.execvp(sys.argv[1], sys.argv[1:])
