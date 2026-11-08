"""File-backed, verified PDF extraction for an isolated offline-index child.

The caller owns the child process's hard RSS/deadline limit and its work directory
after an abrupt kill. This helper bounds source, decoded and output bytes, checks
free disk before writes, and keeps tool subprocesses in that child's process group.
It never changes the online body's 64 MiB buffer limit.
"""
from contextlib import contextmanager
from functools import lru_cache
import gzip
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import inspect
import json
import logging
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
import zlib

from . import __version__
from .body_reader import _NoRedirectHandler, _validate_archive_url
from .models import ExplorerError
from .release import atomic_json, encoded

CHUNK_BYTES = 1 << 20
EXPECTED_POPPLER = '26.10.0'
LARGE_PDF_VERSION = 1


class LargePDFError(ExplorerError):
    """A bounded failure with evidence; the index owner decides retry/eligibility."""
    def __init__(self, reason, code, evidence=None):
        super().__init__(reason)
        self.code = code
        self.evidence = evidence or {}


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise LargePDFError('Offline PDF read exceeded its deadline', 'timeout')


def _disk(path, floor, additional=0):
    if shutil.disk_usage(path).free < floor + additional:
        raise LargePDFError('Offline PDF work would cross the configured free-disk floor', 'disk_floor')


@lru_cache(maxsize=1)
def large_pdf_definition():
    """Fingerprint PDF-only code and actual parser/tools, independently of other formats."""
    tools = {}
    for name in ('pdfinfo', 'pdftotext'):
        path = shutil.which(name)
        fact = dict(available=False)
        if path:
            try:
                proc = subprocess.run([path, '-v'], capture_output=True, timeout=5, check=False)
                reported = (proc.stderr or proc.stdout).decode(errors='replace').splitlines()[0]
                with open(path, 'rb') as stream:
                    digest = sha256()
                    while chunk := stream.read(CHUNK_BYTES):
                        digest.update(chunk)
                fact = dict(available=True, executable=str(Path(path).resolve()), version=reported,
                            sha256=digest.hexdigest(), qualified=reported == f'{name} version {EXPECTED_POPPLER}')
            except (OSError, subprocess.TimeoutExpired, IndexError):
                fact = dict(available=False, reason='Tool identity could not be read')
        tools[name] = fact
    try:
        fonttools = version('fonttools')
    except PackageNotFoundError:
        fonttools = None
    facts = dict(version=LARGE_PDF_VERSION, source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                 guards_sha256=sha256((inspect.getsource(_validate_archive_url)+inspect.getsource(_NoRedirectHandler)).encode()).hexdigest(),
                 python=platform.python_version(), pypdf=version('pypdf'), fonttools=fonttools, tools=tools,
                 text_policy='one stripped text value per physical page; retain empty pages; no OCR')
    return dict(sha256=sha256(encoded(facts)).hexdigest(), facts=facts)


class _WireReader:
    def __init__(self, stream, maximum, deadline):
        self.stream, self.maximum, self.deadline = stream, maximum, deadline
        self.bytes = 0
        self.digest = sha256()

    def read(self, size):
        if size < 0:
            raise LargePDFError('Unbounded archive reads are not supported', 'source_limit')
        _deadline(self.deadline)
        data = self.stream.read(min(size, CHUNK_BYTES, self.maximum-self.bytes+1))
        self.bytes += len(data)
        if self.bytes > self.maximum:
            raise LargePDFError('Offline PDF source exceeds its configured byte limit', 'source_limit')
        self.digest.update(data)
        return data


class _PrefixedReader:
    def __init__(self, prefix, stream):
        self.prefix, self.stream = prefix, stream

    def read(self, size):
        if self.prefix:
            head, self.prefix = self.prefix[:size], self.prefix[size:]
            return head + self.stream.read(size-len(head)) if len(head) < size else head
        return self.stream.read(size)


def _spool(target, path, *, deadline, source_limit, decoded_limit, disk_floor):
    url, expected, suffix = _validate_archive_url(target.get('saved_url'), target.get('archive_origin'),
                                                target.get('saved_body'), target.get('saved_suffix'))
    request = Request(url, headers={'User-Agent': f'CongressExplorerMCP/{__version__}'})
    decoded_digest, decoded_bytes = sha256(), 0
    opener = build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=max(.05, min(30, deadline-time.monotonic()))) as response:
            _validate_archive_url(response.geturl(),target.get('archive_origin'),target.get('saved_body'),suffix)
            wire = _WireReader(response, source_limit, deadline)
            prefix = wire.read(2)
            compressed = suffix == '.gz' and prefix == b'\x1f\x8b'
            source = gzip.GzipFile(fileobj=_PrefixedReader(prefix, wire)) if compressed else _PrefixedReader(prefix, wire)
            with path.open('wb') as output:
                while chunk := source.read(min(CHUNK_BYTES,decoded_limit-decoded_bytes+1)):
                    _deadline(deadline)
                    decoded_bytes += len(chunk)
                    if decoded_bytes > decoded_limit:
                        raise LargePDFError('Offline PDF decoded body exceeds its configured byte limit', 'decoded_limit')
                    _disk(path.parent, disk_floor, len(chunk))
                    output.write(chunk)
                    if compressed:
                        decoded_digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if compressed:
                source.close()
            wire_sha = wire.digest.hexdigest()
            decoded_sha = decoded_digest.hexdigest() if compressed else wire_sha
            if wire_sha == expected:
                binding = 'wire'
            elif compressed and decoded_sha == expected:
                binding = 'storage_gzip_decoded'
            else:
                raise LargePDFError('Archived PDF SHA-256 does not match the published body', 'body_digest_mismatch',
                                    dict(wire_sha256=wire_sha, decoded_sha256=decoded_sha,
                                         wire_bytes=wire.bytes,decoded_bytes=decoded_bytes))
            return dict(published_body=expected, suffix=suffix, wire_sha256=wire_sha, decoded_sha256=decoded_sha,
                        wire_bytes=wire.bytes, decoded_bytes=decoded_bytes, storage_encoding='gzip' if compressed else 'identity',
                        hash_binding=binding, declared_bytes=target.get('saved_bytes'))
    except LargePDFError:
        raise
    except (gzip.BadGzipFile, EOFError, zlib.error) as error:
        raise LargePDFError(f'Invalid archived PDF gzip stream: {error}', 'invalid_gzip') from error
    except (TimeoutError, HTTPError, URLError, OSError) as error:
        code = 'timeout' if 'timed out' in str(error).lower() else 'archive_fetch_failed'
        raise LargePDFError(f'Archived PDF fetch failed: {error}', code) from error


class _HashingWriter:
    def __init__(self, raw):
        self.raw, self.digest = raw, sha256()

    def write(self, value):
        count = self.raw.write(value)
        self.digest.update(value[:count])
        return count

    def flush(self):
        self.raw.flush()

    def tell(self):
        return self.raw.tell()


class _Output:
    def __init__(self, path, maximum, floor, deadline):
        self.path, self.maximum, self.floor, self.deadline = path, maximum, floor, deadline
        self.raw = path.open('wb')
        self.compressed = _HashingWriter(self.raw)
        self.gzip = gzip.GzipFile(filename='', mode='wb', fileobj=self.compressed, mtime=0)
        self.bytes = self.chars = self.pages = 0
        self.textless = []

    def write(self, value):
        data = value.encode('ascii')
        self.bytes += len(data)
        if self.bytes > self.maximum:
            raise LargePDFError('Offline PDF text exceeds its configured serialized-output limit', 'output_limit')
        _deadline(self.deadline)
        _disk(self.path.parent, self.floor, len(data))
        self.gzip.write(data)
        if self.raw.tell() > self.maximum:
            raise LargePDFError('Offline PDF compressed text exceeds its configured output limit', 'output_limit')

    def page(self, text):
        self.pages += 1
        self.chars += len(text)
        if not text:
            if self.textless and self.textless[-1][1] == self.pages-1:
                self.textless[-1][1] = self.pages
            else:
                self.textless.append([self.pages, self.pages])
        self.write('{"page":'+str(self.pages)+',"text":"')
        # Bound the temporary escaped value even when one physical page is large.
        for offset in range(0, len(text), 16384):
            self.write(json.dumps(text[offset:offset+16384], ensure_ascii=True)[1:-1])
        self.write('"}\n')

    def close(self):
        self.gzip.close()
        self.raw.flush()
        os.fsync(self.raw.fileno())
        self.raw.close()

    def evidence(self):
        return dict(page_count=self.pages, physical_page_count=self.pages, total_chars=self.chars,
                    textless_pages=sum(end-start+1 for start,end in self.textless),
                    textless_page_ranges=self.textless, serialized_bytes=self.bytes)


@contextmanager
def _writer(path, maximum, floor, deadline):
    output = _Output(path, maximum, floor, deadline)
    try:
        yield output
    finally:
        output.close()


class _PDFWarnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.count, self.messages, self.fonttools_missing, self.truncated = 0, [], False, False

    def emit(self, record):
        message = record.getMessage()
        self.count += 1
        self.fonttools_missing |= 'fontTools is required' in message
        self.truncated |= len(message)>1024 or len(self.messages)>=16
        if len(self.messages)<16:
            self.messages.append(message[:1024])

    def evidence(self):
        return dict(count=self.count,samples=self.messages,truncated=self.truncated)


@contextmanager
def _pdf_warnings():
    logger = logging.getLogger('pypdf')
    level, propagate = logger.level, logger.propagate
    warnings = _PDFWarnings()
    logger.addHandler(warnings)
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        yield warnings
    finally:
        logger.removeHandler(warnings)
        logger.setLevel(level)
        logger.propagate = propagate


def _pypdf(source, output, definition):
    from pypdf import PdfReader
    # Passing a path makes pypdf read that path into BytesIO; pass the live file handle.
    with _pdf_warnings() as warnings, source.open('rb') as stream:
        reader = PdfReader(stream, strict=False)
        count = len(reader.pages)
        if count == 0:
            raise LargePDFError('PDF reader reports no physical pages', 'backend_error')
        for page in reader.pages:
            output.page((page.extract_text() or '').strip())
        if output.pages != count:
            raise LargePDFError('PDF page traversal differs from its physical page count', 'physical_page_mismatch')
    result = dict(name='pypdf', version=definition['facts']['pypdf'], physical_page_count=count,
                  input_mode='seekable_file_handle',warnings=warnings.evidence())
    if warnings.fonttools_missing:
        raise LargePDFError('pypdf needs the missing fontTools dependency to decode this PDF font',
                            'backend_dependency_missing',dict(result,**output.evidence()))
    return result


def _tool(command, stdout, stderr, *, deadline, limit):
    _deadline(deadline)
    def cap_file():
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    with stdout.open('wb') as out, stderr.open('wb') as err:
        process = subprocess.Popen(command, stdout=out, stderr=err, preexec_fn=cap_file)
        try:
            result = process.wait(timeout=max(.05, deadline-time.monotonic()))
        except subprocess.TimeoutExpired as error:
            raise LargePDFError('Offline PDF tool exceeded its deadline', 'timeout') from error
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    with stderr.open('rb') as stream:
        detail = stream.read(4096).decode(errors='replace')
    if result:
        raise LargePDFError(f'{Path(command[0]).name} exited {result}: {detail}', 'backend_error')
    return dict(stderr_bytes=stderr.stat().st_size,stderr_sample=detail,stderr_truncated=stderr.stat().st_size>4096)


def _poppler(source, output, definition, work, deadline, output_limit, floor):
    info, text = (definition['facts']['tools'][name] for name in ('pdfinfo','pdftotext'))
    if not all(tool.get('qualified') for tool in (info,text)):
        raise LargePDFError(f'Poppler fallback requires qualified {EXPECTED_POPPLER} tools', 'tool_unqualified')
    info_out, err, text_out = work/'pdfinfo.txt', work/'tool.stderr', work/'poppler.txt'
    try:
        info_diagnostics=_tool([info['executable'], str(source)], info_out, err, deadline=deadline, limit=65536)
        found = re.search(r'^Pages:\s+([0-9]+)\s*$', info_out.read_text(errors='replace'), re.MULTILINE)
        if found is None or int(found[1]) < 1:
            raise LargePDFError('pdfinfo did not report a physical page count', 'physical_page_mismatch')
        physical = int(found[1])
        _disk(work, floor, output_limit)
        text_diagnostics=_tool([text['executable'],'-enc','UTF-8','-eol','unix',str(source),'-'], text_out, err,
                               deadline=deadline, limit=output_limit)
        parts = []
        with text_out.open(encoding='utf-8', errors='replace') as stream:
            while chunk := stream.read(65536):
                _deadline(deadline)
                pieces = chunk.split('\f')
                parts.append(pieces[0])
                for piece in pieces[1:]:
                    output.page(''.join(parts).strip())
                    parts = [piece]
            if any(parts):
                output.page(''.join(parts).strip())
        if output.pages != physical:
            raise LargePDFError(f'Poppler emitted {output.pages} page boundaries for {physical} physical pages', 'physical_page_mismatch')
        return dict(name='pdftotext', version=text['version'], executable=text['executable'], sha256=text['sha256'],
                    physical_page_count=physical, page_count_tool=info, input_mode='file', page_boundaries='form_feed',
                    diagnostics=dict(pdfinfo=info_diagnostics,pdftotext=text_diagnostics))
    finally:
        for path in (info_out, err, text_out):
            path.unlink(missing_ok=True)


def _hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def read_pdf_pages_verified(target, *, work_dir, timeout=600, max_source_bytes=2<<30,
                            max_decoded_bytes=2<<30, max_output_bytes=256<<20,
                            min_free_bytes=15<<30, backend='auto'):
    """Return a durable gzip JSONL pages_path and complete backend/source/page evidence.

    Consume pages_path as {page:int,text:str}; empty physical pages remain records.
    Use one private work_dir per body. The caller's child supervisor is the hard
    RSS/deadline boundary during library calls; SIGKILL cleanup belongs to it.
    """
    if backend not in ('auto','pypdf','poppler') or timeout <= 0:
        raise ExplorerError('Choose auto, pypdf or poppler and a positive offline PDF timeout')
    if any(type(value) is not int or value <= 0 for value in (max_source_bytes,max_decoded_bytes,max_output_bytes)) or min_free_bytes < 0:
        raise ExplorerError('Offline PDF byte bounds must be positive; disk floor must be nonnegative')
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    deadline, start = time.monotonic()+timeout, time.monotonic()
    definition = large_pdf_definition()
    # Validate the address even on reuse. The completion never grants a new fetch authority.
    _validate_archive_url(target.get('saved_url'),target.get('archive_origin'),target.get('saved_body'),target.get('saved_suffix'))
    identity = dict(saved_body=target['saved_body'],saved_suffix=target.get('saved_suffix'),definition=definition['sha256'],backend=backend)
    receipt, pages, partial, spool = (work/name for name in ('pdf-reading.json','pdf-pages.jsonl.gz','pdf-pages.partial','source.pdf.partial'))
    if receipt.exists():
        retained = json.loads(receipt.read_bytes())
        if retained.get('identity') != identity:
            raise LargePDFError('Offline PDF completion belongs to another body or reading definition', 'completion_incompatible')
        if not pages.is_file() or pages.stat().st_size != retained.get('completion_bytes') or _hash(pages) != retained.get('completion_sha256'):
            raise LargePDFError('Offline PDF completion bytes differ from their receipt', 'completion_corrupt')
        return dict(retained, pages_path=str(pages), reused=True)
    evidence = dict(identity=identity,extraction_definition=definition,attempts=[])
    textless_result = None
    try:
        _disk(work,min_free_bytes,max_decoded_bytes+2*max_output_bytes)
        evidence['source'] = _spool(target,spool,deadline=deadline,source_limit=max_source_bytes,
            decoded_limit=max_decoded_bytes,disk_floor=min_free_bytes)
        with spool.open('rb') as stream:
            if b'%PDF-' not in stream.read(1024):
                raise LargePDFError('Verified archived body has no PDF header in its first 1024 bytes','pdf_header_missing')
        selected = None
        for name in (('pypdf','poppler') if backend=='auto' else (backend,)):
            try:
                with _writer(partial,max_output_bytes,min_free_bytes,deadline) as output:
                    selected = (_pypdf(spool,output,definition) if name=='pypdf' else
                                _poppler(spool,output,definition,work,deadline,max_output_bytes,min_free_bytes))
                    page_evidence = output.evidence()
                page_evidence['completion_sha256'] = output.compressed.digest.hexdigest()
                evidence['attempts'].append(dict(backend=name,state='completed',**page_evidence))
                # An all-textless physical read is valid. A qualified second backend
                # may recover text; absent one, retain the valid textless reading.
                if name=='pypdf' and not output.chars and backend=='auto' and all(
                    definition['facts']['tools'][tool].get('qualified') for tool in ('pdfinfo','pdftotext')):
                    backup=work/'pdf-textless.partial'
                    os.replace(partial,backup)
                    textless_result=(selected,page_evidence,backup)
                    continue
                break
            except LargePDFError as error:
                evidence['attempts'].append(dict(backend=name,state='failed',reason=str(error),code=error.code,evidence=error.evidence))
                if name=='poppler' and textless_result is not None and error.code not in ('timeout','disk_floor','output_limit'):
                    selected,page_evidence,backup=textless_result
                    os.replace(backup,partial)
                    break
                if error.code in ('timeout','disk_floor','output_limit') or name=='poppler' or backend!='auto':
                    raise
            except Exception as error:
                evidence['attempts'].append(dict(backend=name,state='failed',reason=f'{type(error).__name__}: {str(error)[:2048]}'))
                if name=='poppler' and textless_result is not None:
                    selected,page_evidence,backup=textless_result
                    os.replace(backup,partial)
                    break
                if name=='poppler' or backend!='auto':
                    raise LargePDFError(f'Offline PDF {name} failed: {type(error).__name__}: {str(error)[:2048]}','backend_error') from error
        if selected is None:
            raise LargePDFError('No offline PDF backend completed','backend_error')
        if partial.stat().st_size>max_output_bytes:
            raise LargePDFError('Offline PDF compressed text exceeds its configured output limit','output_limit')
        os.replace(partial,pages)
        evidence.update(page_evidence,backend=selected,pages_path=str(pages),completion_bytes=pages.stat().st_size,
                        elapsed_seconds=time.monotonic()-start,reused=False)
        atomic_json(receipt,evidence)
        return evidence
    except LargePDFError as error:
        error.evidence = dict(evidence,failure=error.evidence,code=error.code,reason=str(error),elapsed_seconds=time.monotonic()-start)
        atomic_json(work/'pdf-failure.json',error.evidence)
        raise
    finally:
        spool.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)
        (work/'pdf-textless.partial').unlink(missing_ok=True)
