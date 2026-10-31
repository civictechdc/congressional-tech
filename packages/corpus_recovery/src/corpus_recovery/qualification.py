"""Bounded, reusable document readability checks for custody-verified bodies.

A caller must establish the digest with verify_local_file (or a trusted owned
write/copy) in this process. VerifiedFile's public constructor does not establish
byte integrity and must not receive unverified digests. Metadata custody permits
reuse without reopening bytes; reverify mutable files after a process restart.

One call owns one parser worker and at most one Poppler child at a time. The
caller owns aggregate concurrency. macOS offers no enforced address-space limit;
its process-tree RSS is sampled, so transient peaks can exceed the configured
threshold before termination. This module does not claim a hard RSS ceiling.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from congress_shared.custody import VerifiedFile

VERSION = 'recovery-qualification-v1'
WORKER_OUTPUT_LIMIT = 1024 * 1024
MONITOR_INTERVAL_SECONDS = 0.05
_REUSABLE_REASONS = {'all_pages_decoded_and_rendered', 'substantial_document_body',
    'input_limit_exceeded', 'page_limit_or_empty', 'decoded_byte_limit_exceeded',
    'missing_pdf_eof', 'unsupported_format', 'error_or_challenge',
    'historical_no_prepared_statement', 'empty_document_body', 'attachment_page',
    'short_text_needs_review', 'corrupt_pdf_stream', 'encrypted_pdf'}


@dataclass(frozen=True)
class QualificationConfig:
    timeout_seconds: float = 180
    max_pages: int = 2000
    max_decoded_bytes: int = 256 * 1024 * 1024
    max_input_bytes: int = 16 * 1024 * 1024
    max_memory_bytes: int = 1024 * 1024 * 1024
    max_cpu_seconds: int = 150
    render_dpi: int = 18

    def __post_init__(self):
        if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
               for value in asdict(self).values()):
            raise ValueError('Qualification limits must be positive')
        if any(type(value) is not int for name, value in asdict(self).items()
               if name != 'timeout_seconds'):
            raise ValueError('Qualification byte, page, CPU, and DPI limits must be integers')


class QualificationRecord(dict):
    """JSON-compatible qualification with attribute access."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _tool_version(name):
    path = shutil.which(name)
    if not path:
        return {'path': None, 'version': 'missing'}
    try:
        result = subprocess.run([path, '-v'], capture_output=True, timeout=5)
        version = (result.stdout + result.stderr).decode('utf-8', 'replace').splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        version = 'unavailable'
    return {'path': str(Path(path).resolve()), 'version': version}


def _identity():
    try:
        pypdf = importlib.metadata.version('pypdf')
    except importlib.metadata.PackageNotFoundError:
        pypdf = 'missing'
    try:
        lxml = importlib.metadata.version('lxml')
    except importlib.metadata.PackageNotFoundError:
        lxml = 'missing'
    return {'version': VERSION, 'implementation_sha256': _hash(Path(__file__).read_bytes()),
            'classifier_sha256': _hash(Path(__file__).with_name('html.py').read_bytes()),
            'python': sys.version, 'platform': sys.platform, 'pypdf': pypdf, 'lxml': lxml,
            'pdfinfo': _tool_version('pdfinfo'), 'pdftoppm': _tool_version('pdftoppm')}


def _finish(value):
    value = dict(value)
    value['qualification_sha256'] = _hash(_canonical(value))
    return QualificationRecord(value)


def verify_qualification_record(record, *, body_sha256=None, body_bytes=None,
                                require_qualified=False, validator=None, config=None):
    """Check serialized evidence and optional expected bindings without body I/O.

    This detects corruption and inconsistent claims; a checksum is not authority
    to trust caller-supplied results. Acceptance must use a result from qualify
    or an independently trusted artifact owner with pinned validator identity.
    """
    if not isinstance(record, dict):
        raise ValueError('Qualification record must be an object')
    value = dict(record)
    checksum = value.pop('qualification_sha256', None)
    try:
        valid_digest = checksum == _hash(_canonical(value))
    except (ValueError, TypeError):
        valid_digest = False
    if not valid_digest:
        raise ValueError('Qualification record integrity mismatch')
    sha = value.get('body_sha256')
    if (not isinstance(sha, str) or len(sha) != 64
            or any(c not in '0123456789abcdef' for c in sha)
            or type(value.get('body_bytes')) is not int or value['body_bytes'] < 0
            or not isinstance(value.get('validator'), dict)
            or not isinstance(value.get('config'), dict)
            or set(value['config']) != set(QualificationConfig.__dataclass_fields__)
            or value.get('status') not in ('qualified', 'unresolved')
            or 'media_type' not in value
            or value.get('media_type') not in (None, 'application/pdf', 'text/html')
            or ('retryable' in value and type(value['retryable']) is not bool)
            or not isinstance(value.get('reason'), str)):
        raise ValueError('Invalid qualification record fields')
    try:
        QualificationConfig(**value['config'])
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid qualification configuration') from error
    implementation = value['validator']
    for field in ('implementation_sha256', 'classifier_sha256'):
        digest = implementation.get(field)
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('Invalid qualification validator identity')
    if (implementation.get('version') != VERSION
            or any(not isinstance(implementation.get(name), str)
                   for name in ('python', 'platform', 'pypdf', 'lxml'))
            or any(not isinstance(implementation.get(name), dict)
                   or not isinstance(implementation[name].get('version'), str)
                   for name in ('pdfinfo', 'pdftoppm'))):
        raise ValueError('Invalid qualification validator identity')
    expected = {'body_sha256': body_sha256, 'body_bytes': body_bytes,
                'validator': validator, 'config': asdict(config) if isinstance(config, QualificationConfig) else config}
    if any(wanted is not None and value.get(name) != wanted for name, wanted in expected.items()):
        raise ValueError('Qualification record identity mismatch')
    if require_qualified and value['status'] != 'qualified':
        raise ValueError('Body qualification is incomplete')
    if value['status'] == 'qualified':
        if value.get('retryable', False):
            raise ValueError('Qualified result cannot require a retry')
        if value['body_bytes'] > value['config']['max_input_bytes']:
            raise ValueError('Qualified body exceeds input limit')
        if value['media_type'] == 'application/pdf':
            pages = value.get('pages')
            if (type(pages) is not int or not 0 < pages <= value['config']['max_pages']
                    or type(value.get('pages_decoded')) is not int or value.get('pages_decoded') != pages
                    or type(value.get('all_pages_rendered')) is not int or value.get('all_pages_rendered') != pages
                    or value.get('pdfinfo_exit') != 0 or value.get('all_pages_render_exit') != 0
                    or type(value.get('pdfinfo_exit')) is not int
                    or type(value.get('all_pages_render_exit')) is not int
                    or value.get('pdf_eof') is not True or value.get('pdf_header') is not True
                    or type(value.get('strict_parser')) is not bool or value.get('encrypted') is not False
                    or value['reason'] != 'all_pages_decoded_and_rendered'
                    or type(value.get('decoded_bytes')) is not int
                    or any(not implementation[name].get('path')
                           or implementation[name]['version'] in ('missing', 'unavailable')
                           for name in ('pdfinfo', 'pdftoppm'))
                    or not 0 <= value['decoded_bytes'] <= value['config']['max_decoded_bytes']):
                raise ValueError('Incomplete PDF qualification evidence')
        elif value['media_type'] != 'text/html' or value['reason'] != 'substantial_document_body':
            raise ValueError('Incomplete format qualification evidence')
    return QualificationRecord(value, qualification_sha256=checksum)


def _process_tree_rss(root):
    """Sample resident bytes for the worker and descendants, including Poppler."""
    output = subprocess.run(['ps', '-axo', 'pid=,ppid=,rss='], capture_output=True,
                            text=True, timeout=5, check=True).stdout
    rows = []
    for line in output.splitlines():
        try:
            pid, parent, rss = map(int, line.split())
            rows.append((pid, parent, rss))
        except ValueError:
            continue
    descendants = {root}
    while True:
        expanded = descendants | {pid for pid, parent, _ in rows if parent in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    return sum(rss for pid, _, rss in rows if pid in descendants) * 1024


def _read_record(path, key_data):
    with path.open('rb') as stream:
        raw = stream.read(WORKER_OUTPUT_LIMIT + 1)
    if len(raw) > WORKER_OUTPUT_LIMIT:
        raise ValueError('Qualification cache exceeds supported record size')
    try:
        return verify_qualification_record(json.loads(raw), **key_data)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError('Qualification cache integrity mismatch') from error


def qualify(body: VerifiedFile, cache_dir, *, config=QualificationConfig()):
    """Return durable evidence; retry incomplete runs on the next invocation.

    Cache reuse assumes trusted factory-established bytes and process-local file
    custody. It deliberately does not rehash a body before looking up the cache.
    """
    if not isinstance(body, VerifiedFile) or body.path is None:
        raise TypeError('body must be a process-local VerifiedFile')
    body._require_custody(body.path)
    if not isinstance(body.sha256, str) or len(body.sha256) != 64 or any(c not in '0123456789abcdef' for c in body.sha256):
        raise ValueError('Invalid verified body digest')
    if not isinstance(config, QualificationConfig):
        raise TypeError('config must be QualificationConfig')
    identity = _identity()
    key_data = {'body_sha256': body.sha256, 'body_bytes': body.size_bytes,
                'validator': identity, 'config': asdict(config)}
    key = _hash(_canonical(key_data))
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    locks = cache / '.locks'
    locks.mkdir(exist_ok=True)
    # Advisory locks survive independent callers/processes without duplicate
    # parsing. Retain the tiny lock inode: unlinking it would split waiters.
    with (locks / (key + '.lock')).open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        body._require_custody(body.path)
        return _qualify_locked(body, cache, key, key_data, config)


def _qualify_locked(body, cache, key, key_data, config):
    path = cache / (key + '.json')
    if path.exists():
        value = _read_record(path, key_data)
        body._require_custody(body.path)
        return value
    result = {'status': 'unresolved', 'media_type': None, 'reason': 'worker_failed'}
    if body.size_bytes > config.max_input_bytes:
        result['reason'] = 'input_limit_exceeded'
    else:
        with tempfile.TemporaryDirectory(prefix='qualification-', dir=cache) as scratch:
            request = {'body': str(body.path), 'config': asdict(config), 'scratch': scratch}
            process = None
            try:
                env = dict(os.environ)
                env['PYTHONPATH'] = os.pathsep.join(sys.path)
                started = time.monotonic()
                observed_peak, samples = 0, 0
                # Files avoid unbounded communicate() buffers on malformed input.
                with open(Path(scratch) / 'stdout', 'w+b') as stdout, open(Path(scratch) / 'stderr', 'w+b') as stderr:
                    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker'],
                        stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                        start_new_session=True, env=env)
                    deadline = started + config.timeout_seconds
                    first = True
                    while True:
                        try:
                            process.communicate(_canonical(request) if first else None,
                                timeout=max(0.000001, min(MONITOR_INTERVAL_SECONDS, deadline - time.monotonic())))
                            stdout.seek(0)
                            raw = stdout.read(WORKER_OUTPUT_LIMIT + 1)
                            if process.returncode == 0 and len(raw) <= WORKER_OUTPUT_LIMIT:
                                candidate = json.loads(raw)
                                if (not isinstance(candidate, dict)
                                        or candidate.get('status') not in ('qualified', 'unresolved')
                                        or not isinstance(candidate.get('reason'), str)):
                                    raise ValueError('Malformed worker result')
                                # Worker output cannot replace parent-owned identities.
                                if any(k in candidate for k in (*key_data, 'qualification_sha256')):
                                    raise ValueError('Worker replaced qualification identity')
                                verify_qualification_record(_finish({**key_data, **candidate}), **key_data)
                                result = candidate
                            else:
                                stderr.seek(max(0, stderr.seek(0, 2) - 4096))
                                result.update(reason='worker_failed', worker_exit=process.returncode,
                                              diagnostic=stderr.read(4096).decode('utf-8', 'replace'))
                            break
                        except subprocess.TimeoutExpired:
                            first = False
                            reason = None
                            if time.monotonic() >= deadline:
                                reason = 'worker_timeout'
                            else:
                                try:
                                    observed_peak = max(observed_peak, _process_tree_rss(process.pid))
                                    samples += 1
                                    if observed_peak > config.max_memory_bytes:
                                        reason = 'memory_limit_exceeded'
                                except (OSError, subprocess.SubprocessError):
                                    reason = 'resource_monitor_failed'
                            if reason:
                                result['reason'] = reason
                                break
                    result['resources'] = {'peak_sampled_tree_rss_bytes': observed_peak,
                        'rss_samples': samples, 'rss_sample_interval_seconds': MONITOR_INTERVAL_SECONDS,
                        'elapsed_seconds': time.monotonic() - started,
                        'memory_enforcement': 'sampled_tree_rss' if sys.platform == 'darwin' else 'per_process_rlimit_as_and_sampled_tree_rss',
                        'cpu_enforcement': 'per_process_rlimit_cpu', 'workers': 1,
                        'max_simultaneous_poppler_children': 1}
            except (OSError, ValueError, json.JSONDecodeError) as error:
                result.update(reason='worker_failed', diagnostic=type(error).__name__)
            finally:
                # Kill the whole session even after the worker exits: a malformed
                # worker can leave a validator child holding scratch files open.
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
    body._require_custody(body.path)
    value = _finish({**key_data, **result, 'retryable': result['reason'] not in _REUSABLE_REASONS})
    verify_qualification_record(value, **key_data)
    if value.retryable:
        # Preserve failures without poisoning the completed-result cache. A new
        # invocation is the caller's explicit retry; request budgets live there.
        attempts = cache / 'attempts'
        attempts.mkdir(exist_ok=True)
        path = attempts / (key + '-' + uuid.uuid4().hex + '.json')
    raw = _canonical(value) + b'\n'
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except FileExistsError:
            return _read_record(path, key_data)
    finally:
        temporary.unlink(missing_ok=True)
    return value


def _worker(request):
    import resource
    config = QualificationConfig(**request['config'])
    resource.setrlimit(resource.RLIMIT_CPU, (config.max_cpu_seconds, config.max_cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (WORKER_OUTPUT_LIMIT, WORKER_OUTPUT_LIMIT))
    # macOS does not support setting RLIMIT_AS; the parent monitors the full tree.
    if sys.platform != 'darwin':
        resource.setrlimit(resource.RLIMIT_AS, (config.max_memory_bytes, config.max_memory_bytes))
    path = Path(request['body'])
    with path.open('rb') as stream:
        prefix = stream.read(1024)
        stream.seek(max(0, path.stat().st_size - 8192))
        tail = stream.read(8192)
    if b'%PDF-' in prefix:
        return _pdf(path, prefix, tail, config)
    if prefix.lstrip().lower().startswith((b'<!doctype html', b'<html', b'<?xml')):
        if path.stat().st_size > config.max_decoded_bytes:
            return {'status': 'unresolved', 'media_type': 'text/html', 'reason': 'decoded_byte_limit_exceeded'}
        spec = importlib.util.spec_from_file_location('recovery_qualification_html', Path(__file__).with_name('html.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            classified = module.classify_transcripts(path.read_bytes())
            category = classified['category']
            return {'status': 'qualified' if category == 'substantial_document_body' else 'unresolved',
                    'media_type': 'text/html', 'reason': category}
        except Exception as error:
            return {'status': 'unresolved', 'media_type': 'text/html', 'reason': 'html_validation_failed', 'error_type': type(error).__name__}
    return {'status': 'unresolved', 'media_type': None, 'reason': 'unsupported_format'}


def _pdf(path, prefix, tail, config):
    result = {'status': 'unresolved', 'media_type': 'application/pdf', 'reason': 'validation_failed',
              'pdf_header': True, 'pdf_eof': b'%%EOF' in tail}
    if not result['pdf_eof']:
        result['reason'] = 'missing_pdf_eof'
        return result
    try:
        from pypdf import PdfReader, overwrite_configuration
        from pypdf.errors import LimitReachedError, PdfReadError
        # Maintained decoders stop expansion before allocating arbitrary stream
        # output. The cumulative decoded-byte check also covers multiple pages.
        overwrite_configuration(maximum_declared_stream_length=config.max_input_bytes,
            array_based_stream_maximum_output_length=config.max_decoded_bytes,
            zlib_maximum_output_length=config.max_decoded_bytes,
            lzw_maximum_output_length=config.max_decoded_bytes,
            run_length_maximum_output_length=config.max_decoded_bytes,
            jbig2_maximum_output_length=config.max_decoded_bytes,
            image_maximum_buffer_size=config.max_decoded_bytes,
            disable_legacy_handling=True)
        try:
            reader = PdfReader(path, strict=True)
            count = len(reader.pages)
            result['strict_parser'] = True
        except Exception as error:
            result['strict_error_type'] = type(error).__name__
            reader = PdfReader(path, strict=False)
            count = len(reader.pages)
            result['strict_parser'] = False
        result.update(pages=count, pages_decoded=0, encrypted=reader.is_encrypted)
        if reader.is_encrypted:
            result['reason'] = 'encrypted_pdf'
            return result
        if not count or count > config.max_pages:
            result['reason'] = 'page_limit_or_empty'
            return result
        decoded = 0
        for page in reader.pages:
            # pypdf can recover invalid compression as empty bytes while only
            # logging a warning. A successful get_data() alone is insufficient.
            class DecodeWarnings(logging.Handler):
                message = None
                def emit(self, record):
                    if self.message is None:
                        self.message = record.getMessage()[:4096]
            warnings = DecodeWarnings(logging.WARNING)
            logger = logging.getLogger('pypdf')
            logger.addHandler(warnings)
            try:
                contents = page.get_contents()
                data = contents.get_data() if contents is not None else b''
            finally:
                logger.removeHandler(warnings)
            if warnings.message is not None:
                result.update(reason='corrupt_pdf_stream', diagnostic=warnings.message)
                return result
            if contents is not None:
                decoded += len(data)
                if decoded > config.max_decoded_bytes:
                    result['reason'] = 'decoded_byte_limit_exceeded'
                    return result
                # Parsing the PDF object tree alone leaves page instructions
                # lazy; force their traversal before accepting the page.
                try:
                    _ = contents.operations
                except (PdfReadError, LimitReachedError) as error:
                    # Historical PDFs can have malformed text operands while
                    # their decoded streams remain readable by Poppler. Keep
                    # that fallback explicit; stream decoding itself must pass.
                    result.setdefault('content_parser_errors', []).append(
                        {'page': result['pages_decoded'] + 1, 'error_type': type(error).__name__})
                    result['content_parser_fallback'] = 'decoded_streams_and_all_page_poppler'
            result['pages_decoded'] += 1
        result['decoded_bytes'] = decoded
        with tempfile.TemporaryFile() as diagnostics:
            info = subprocess.run(['pdfinfo', str(path)], stdout=subprocess.DEVNULL, stderr=diagnostics)
            render = subprocess.run(['pdftoppm', '-r', str(config.render_dpi), '-gray', str(path)],
                                    stdout=subprocess.DEVNULL, stderr=diagnostics)
            diagnostics.seek(0)
            messages = diagnostics.read(WORKER_OUTPUT_LIMIT)
        # Poppler sometimes returns success while reporting corrupt page data.
        errors = any(marker in messages for marker in (b'Syntax Error:', b'Internal Error:', b'Error:'))
        result.update(pdfinfo_exit=info.returncode, all_pages_render_exit=render.returncode,
                      all_pages_rendered=count if render.returncode == 0 else 0)
        if errors:
            result['reason'] = 'corrupt_pdf_stream'
            result['diagnostic'] = messages[-4096:].decode('utf-8', 'replace')
        elif info.returncode == 0 and render.returncode == 0:
            result.update(status='qualified', reason='all_pages_decoded_and_rendered')
        else:
            result['reason'] = 'validation_incomplete'
    except ImportError as error:
        result.update(reason='dependency_missing', error_type=type(error).__name__)
    except LimitReachedError as error:
        result.update(reason='decoded_byte_limit_exceeded', error_type=type(error).__name__)
    except Exception as error:
        result.update(reason='validation_failed', error_type=type(error).__name__)
    return result


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    try:
        print(json.dumps(_worker(json.load(sys.stdin))))
    except BaseException as error:
        print(json.dumps({'status': 'unresolved', 'media_type': None,
                          'reason': 'worker_failed', 'error_type': type(error).__name__}))
