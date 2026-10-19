"""Frozen HTML classifiers and conservative reusable PDF acceptance checks.

PDF checks are promoted from webharvest_fetch_candidates.py. Both pypdf stream
checks and the all-page Poppler render remain required; preview is optional.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

_CACHE_LOCKS = {}
_CACHE_GUARD = threading.Lock()

VERSION = 'webharvest-validation-v1'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def immutable(path, value):
    """Publish a complete JSON file atomically and never overwrite an existing one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2) + '\n').encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def classifier_directory():
    """Real classifier sources. A frozen snapshot must not exec the command shims."""
    return Path(__file__).resolve().parents[2] / 'packages/corpus_recovery/src/corpus_recovery'


def freeze(directory, config):
    """Resume using retained classifier bytes, even after maintained code changes."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / 'validator.json'
    if manifest.exists():
        value = json.loads(manifest.read_text())
        if value['config'] != config:
            raise ValueError('Validator configuration changed; use a new snapshot directory')
        source = (directory / 'classifier.py').read_bytes()
        if digest(source) != value['classifier_sha256']:
            raise ValueError('Frozen classifier changed')
        implementation = (directory / 'validation.py').read_bytes()
        if digest(implementation) != value['implementation_sha256']:
            raise ValueError('Frozen validator implementation changed')
        return value
    source_dir = classifier_directory()
    source = (source_dir / 'html.py').read_bytes()
    classifier = directory / 'classifier.py'
    # This directory belongs exclusively to the caller's locked run.
    if classifier.exists() and classifier.read_bytes() != source:
        raise ValueError('Interrupted classifier snapshot differs; use a new directory')
    if not classifier.exists():
        classifier.write_bytes(source)
    implementation = Path(__file__).read_bytes()
    code_snapshot = directory / 'validation.py'
    if code_snapshot.exists() and code_snapshot.read_bytes() != implementation:
        raise ValueError('Interrupted validator snapshot differs; use a new directory')
    if not code_snapshot.exists():
        code_snapshot.write_bytes(implementation)
    value = {'version': VERSION, 'classifier_sha256': digest(source),
             'implementation_sha256': digest(implementation), 'config': config}
    value['validator_sha256'] = digest(json.dumps(value, sort_keys=True).encode())
    immutable(manifest, value)
    return value


def classify_cached(raw, directory, snapshot, validator):
    identity = (str(directory.resolve()), digest(raw), validator['validator_sha256'])
    with _CACHE_GUARD:
        lock = _CACHE_LOCKS.setdefault(identity, threading.Lock())
    with lock:
        return _classify_cached(raw, directory, snapshot, validator)


def _classify_cached(raw, directory, snapshot, validator):
    key = digest(raw) + '-' + validator['validator_sha256']
    path = directory / (key + '.json')
    if path.exists():
        value = json.loads(path.read_text())
        if value['body_sha256'] != digest(raw) or value['validator_sha256'] != validator['validator_sha256']:
            raise ValueError('Classifier cache identity changed')
    else:
        source = (snapshot / 'classifier.py').read_bytes()
        if digest(source) != validator['classifier_sha256']:
            raise ValueError('Frozen classifier changed')
        namespace = {}
        exec(compile(source, str(snapshot / 'classifier.py'), 'exec'), namespace)
        # Retained pre-package snapshots define the transcript wrapper as classify.
        classify = namespace.get('classify_transcripts', namespace['classify'])
        value = {'body_sha256': digest(raw), 'validator_sha256': validator['validator_sha256'],
                 'content': classify(raw)}
        try:
            immutable(path, value)
        except FileExistsError:
            # Parallel URLs can return identical bytes; the first complete cache wins.
            saved = json.loads(path.read_text())
            if saved != value:
                raise ValueError('Concurrent classifier cache differs')
            value = saved
    # Full extracted text and links live once in the cache, with hash provenance.
    summary = {k: v for k, v in value['content'].items() if k not in {'text', 'links'}}
    return summary, {'path': str(path.resolve()), 'sha256': digest(path.read_bytes()),
                     'validator_sha256': validator['validator_sha256']}


def validate_pdf(body, directory, *, preview=False):
    from pypdf import PdfReader
    directory.mkdir(parents=True, exist_ok=True)
    raw = body.read_bytes()
    result = {'valid_pdf': False, 'bytes': len(raw), 'sha256': digest(raw),
              'validator_version': VERSION, 'preview_requested': preview,
              'pdf_header': b'%PDF-' in raw[:1024], 'pdf_eof': b'%%EOF' in raw[-8192:]}
    if not result['pdf_header']:
        return dict(result, reason='not_pdf_bytes')
    try:
        try:
            reader = PdfReader(body, strict=True)
            count = len(reader.pages)
            result['strict_parser'] = True
        except Exception as error:
            result['strict_error_type'] = type(error).__name__
            reader = PdfReader(body, strict=False)
            count = len(reader.pages)
            result['strict_parser'] = False
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None:
                contents.get_data()
        result.update(pages=count, pages_decoded=count, encrypted=reader.is_encrypted)
        info = subprocess.run(['pdfinfo', str(body)], capture_output=True, timeout=45)
        (directory / 'pdfinfo.txt').write_bytes(info.stdout + info.stderr)
        render = subprocess.run(['pdftoppm', '-r', '18', '-gray', str(body)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
        (directory / 'all-pages-render.stderr').write_bytes(render.stderr)
        result.update(pdfinfo_exit=info.returncode, all_pages_render_exit=render.returncode,
                      all_pages_rendered=count if render.returncode == 0 else 0)
        result['valid_pdf'] = bool(result['pdf_eof'] and count > 0 and info.returncode == 0 and render.returncode == 0)
        result['reason'] = 'all_pages_decoded_and_rendered' if result['valid_pdf'] else 'validation_incomplete'
    except Exception as error:
        result.update(reason='validation_failed', error_type=type(error).__name__)
    # Preview has no role in acceptance and cannot revoke successful validation.
    if preview and result['valid_pdf']:
        try:
            image = subprocess.run(['pdftoppm', '-f', '1', '-singlefile', '-scale-to', '800', '-png',
                                    str(body), str(directory / 'first-page')], capture_output=True, timeout=45)
            result['preview_exit'] = image.returncode
            (directory / 'preview.stderr').write_bytes(image.stderr)
        except Exception as error:
            result['preview_error_type'] = type(error).__name__
    return result


def validate_pdf_frozen(body, directory, snapshot, validator, *, preview=False):
    source = (snapshot / 'validation.py').read_bytes()
    if digest(source) != validator['implementation_sha256']:
        raise ValueError('Frozen validator implementation changed')
    namespace = {'__file__': str(snapshot / 'validation.py')}
    exec(compile(source, str(snapshot / 'validation.py'), 'exec'), namespace)
    return namespace['validate_pdf'](body, directory, preview=preview)
