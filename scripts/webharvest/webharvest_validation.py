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
        if 'qualification_sha256' in value:
            for name, field in [('qualification.py', 'qualification_sha256'), ('html.py', 'qualification_html_sha256')]:
                if digest((directory / name).read_bytes()) != value[field]:
                    raise ValueError('Frozen qualification implementation changed')
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
    qualification = (source_dir / 'qualification.py').read_bytes()
    for name, data in [('qualification.py', qualification), ('html.py', source)]:
        target = directory / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Interrupted qualification snapshot differs; use a new directory')
        if not target.exists():
            target.write_bytes(data)
    value = {'qualification_sha256': digest(qualification), 'qualification_html_sha256': digest(source),
             'version': VERSION, 'classifier_sha256': digest(source),
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


def _validate_with_module(body, directory, module, *, preview=False, verified_body=None):
    from congress_shared.custody import verify_local_file
    verified = verified_body if verified_body is not None else verify_local_file(body)
    verified._require_custody(body)
    record = module.qualify(verified, directory / 'qualification-cache')
    result = dict(record)
    result.update(valid_pdf=record.status == 'qualified' and record.media_type == 'application/pdf',
                  bytes=verified.size_bytes, sha256=verified.sha256,
                  validator_version=VERSION, preview_requested=preview)
    # Preview is a separate, optional convenience and cannot revoke acceptance.
    if preview and result['valid_pdf']:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            image = subprocess.run(['pdftoppm', '-f', '1', '-singlefile', '-scale-to', '800', '-png',
                                    str(body), str(directory / 'first-page')], capture_output=True, timeout=45)
            result['preview_exit'] = image.returncode
            (directory / 'preview.stderr').write_bytes(image.stderr)
        except Exception as error:
            result['preview_error_type'] = type(error).__name__
    return result


def validate_pdf(body, directory, *, preview=False, verified_body=None):
    from corpus_recovery import qualification
    return _validate_with_module(body, directory, qualification, preview=preview, verified_body=verified_body)


def validate_pdf_frozen(body, directory, snapshot, validator, *, preview=False, verified_body=None):
    source = (snapshot / 'validation.py').read_bytes()
    if digest(source) != validator['implementation_sha256']:
        raise ValueError('Frozen validator implementation changed')
    namespace = {'__file__': str(snapshot / 'validation.py')}
    exec(compile(source, str(snapshot / 'validation.py'), 'exec'), namespace)
    if 'qualification_sha256' not in validator:
        if '_validate_with_module' in namespace:
            raise ValueError('Frozen shared qualification snapshot is missing its pinned implementation')
        return namespace['validate_pdf'](body, directory, preview=preview)
    import importlib.util
    import sys
    for name, field in [('qualification.py', 'qualification_sha256'), ('html.py', 'qualification_html_sha256')]:
        if digest((snapshot / name).read_bytes()) != validator[field]:
            raise ValueError('Frozen qualification implementation changed')
    import uuid
    name = '_frozen_qualification_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, snapshot / 'qualification.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        import inspect
        function=namespace['_validate_with_module']
        options=dict(preview=preview)
        if 'verified_body' in inspect.signature(function).parameters:
            options['verified_body']=verified_body
        return function(body, directory, module, **options)
    finally:
        del sys.modules[name]
