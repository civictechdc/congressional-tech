import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pypdf import PdfWriter
from congress_shared.custody import verify_local_file
from corpus_recovery import qualification as q


def pdf(path, pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open('wb') as output:
        writer.write(output)
    return verify_local_file(path)


def test_valid_pdf_and_cache_precedes_body_read(tmp_path, monkeypatch):
    body = pdf(tmp_path / 'body.pdf')
    first = q.qualify(body, tmp_path / 'cache')
    assert first.status == 'qualified'
    assert first.pages == first.pages_decoded == first.all_pages_rendered == 2
    original = Path.open
    def guarded(path, *args, **kwargs):
        if path == body.path:
            raise AssertionError('body reopened on cache hit')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    assert q.qualify(body, tmp_path / 'cache') == first


def test_bad_pdf_html_and_limits(tmp_path):
    cache = tmp_path / 'cache'
    for name, raw in [('fake', b'%PDF-1.7\nnot a PDF\n%%EOF'),
                      ('truncated', b'%PDF-1.7\nnot a PDF')]:
        path = tmp_path / name
        path.write_bytes(raw)
        assert q.qualify(verify_local_file(path), cache).status == 'unresolved'
    wall = tmp_path / 'wall'
    wall.write_text('<html><title>Access Denied</title><body>Blocked</body></html>')
    result = q.qualify(verify_local_file(wall), cache)
    assert result.status == 'unresolved' and result.reason == 'error_or_challenge'
    body = pdf(tmp_path / 'two.pdf')
    assert q.qualify(body, cache, config=q.QualificationConfig(max_pages=1)).reason == 'page_limit_or_empty'
    assert q.qualify(body, cache, config=q.QualificationConfig(max_input_bytes=1)).reason == 'input_limit_exceeded'


def test_cache_identity_integrity_and_mutation(tmp_path, monkeypatch):
    body = pdf(tmp_path / 'body.pdf')
    cache = tmp_path / 'cache'
    first = q.qualify(body, cache)
    changed = q.qualify(body, cache, config=q.QualificationConfig(max_pages=1))
    assert changed.qualification_sha256 != first.qualification_sha256
    identity = q._identity()
    monkeypatch.setattr(q, '_identity', lambda: {**identity, 'implementation_sha256': '0' * 64})
    assert q.qualify(body, cache).qualification_sha256 != first.qualification_sha256
    monkeypatch.undo()
    cache_file = next(p for p in cache.glob('*.json') if json.loads(p.read_text())['qualification_sha256'] == first.qualification_sha256)
    data = json.loads(cache_file.read_text())
    data['status'] = 'unresolved'
    cache_file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='integrity'):
        q.qualify(body, cache)
    body.path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='custody'):
        q.qualify(body, cache)


def test_timeout_cleanup_and_missing_tools(tmp_path, monkeypatch):
    body = pdf(tmp_path / 'body.pdf')
    cache = tmp_path / 'cache'
    result = q.qualify(body, cache, config=q.QualificationConfig(timeout_seconds=0.000001))
    assert result.reason == 'worker_timeout'
    assert not list(cache.glob('qualification-*'))
    monkeypatch.setenv('PATH', '/nonexistent')
    result = q.qualify(body, tmp_path / 'missing')
    assert result.status == 'unresolved'


def test_html_document_and_changed_body(tmp_path):
    path = tmp_path / 'document'
    path.write_text('<html><title>Testimony</title><div class="field-name-body">' +
                    'substantive testimony ' * 70 + '</div></html>')
    cache = tmp_path / 'cache'
    first = q.qualify(verify_local_file(path), cache)
    assert first.status == 'qualified' and first.media_type == 'text/html'
    path.write_text('<html><title>Testimony</title><nav>Navigation</nav></html>')
    second = q.qualify(verify_local_file(path), cache)
    assert second.status == 'unresolved' and second.body_sha256 != first.body_sha256


def test_worker_error_is_durable_and_scratch_removed(tmp_path, monkeypatch):
    body = pdf(tmp_path / 'body.pdf')
    identity = q._identity()
    monkeypatch.setattr(q.subprocess, 'Popen', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('failed')))
    # Avoid tool identity probes, which themselves use Popen.
    monkeypatch.setattr(q, '_identity', lambda: identity)
    cache = tmp_path / 'cache'
    result = q.qualify(body, cache)
    assert result.reason == 'worker_failed'
    assert list((cache / 'attempts').glob('*.json')) and not list(cache.glob('qualification-*'))


def content_pdf(path, data, *, compressed=False, pages=1):
    from pypdf.generic import DecodedStreamObject, NameObject
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=72, height=72)
        stream = DecodedStreamObject()
        stream.set_data(data)
        page[NameObject('/Contents')] = writer._add_object(stream.flate_encode() if compressed else stream)
    with path.open('wb') as output:
        writer.write(output)
    return verify_local_file(path)


def test_compressed_and_cumulative_decoded_limits(tmp_path):
    body = content_pdf(tmp_path / 'compressed.pdf', b'% comment\n' * 2000, compressed=True)
    assert body.size_bytes < 2000
    result = q.qualify(body, tmp_path / 'cache', config=q.QualificationConfig(max_decoded_bytes=2000))
    assert result.status == 'unresolved' and result.reason == 'decoded_byte_limit_exceeded'
    # Separate small streams also count against the full-document byte budget.
    body = content_pdf(tmp_path / 'multiple.pdf', b'% comment\n' * 10, pages=2)
    result = q.qualify(body, tmp_path / 'cache', config=q.QualificationConfig(max_decoded_bytes=150))
    assert result.status == 'unresolved' and result.reason == 'decoded_byte_limit_exceeded'


def test_corrupt_page_stream_cannot_qualify_even_when_poppler_returns_zero(tmp_path):
    from pypdf.generic import EncodedStreamObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    stream = EncodedStreamObject()
    stream._data = b'not valid zlib data'
    stream[NameObject('/Filter')] = NameObject('/FlateDecode')
    page[NameObject('/Contents')] = writer._add_object(stream)
    path = tmp_path / 'corrupt.pdf'
    with path.open('wb') as output:
        writer.write(output)
    result = q.qualify(verify_local_file(path), tmp_path / 'cache')
    assert result.status == 'unresolved'
    assert result.reason == 'corrupt_pdf_stream'


def worker_override(monkeypatch, path):
    identity = q._identity()
    original = q.subprocess.Popen
    monkeypatch.setattr(q, '_identity', lambda: identity)
    monkeypatch.setattr(q.subprocess, 'Popen',
                        lambda args, **kwargs: original([sys.executable, str(path)] if '--worker' in args else args, **kwargs))


def test_timeout_preserves_evidence_and_next_invocation_retries(tmp_path, monkeypatch):
    body = pdf(tmp_path / 'body.pdf')
    script = tmp_path / 'sleeper.py'
    script.write_text('import time\ntime.sleep(30)\n')
    cache = tmp_path / 'cache'
    with monkeypatch.context() as patch:
        worker_override(patch, script)
        result = q.qualify(body, cache, config=q.QualificationConfig(timeout_seconds=0.5))
    assert result.reason == 'worker_timeout'
    assert len(list((cache / 'attempts').glob('*.json'))) == 1
    assert not list(cache.glob('*.json'))
    assert q.qualify(body, cache, config=q.QualificationConfig(timeout_seconds=0.5)).status == 'qualified'
    assert len(list(cache.glob('*.json'))) == 1


@pytest.mark.parametrize('output', ['[]', '{"status":"qualified","reason":"pretend"}', 'bad json'])
def test_malformed_worker_output_is_unresolved_and_cleans_descendants(tmp_path, monkeypatch, output):
    import time
    body = pdf(tmp_path / 'body.pdf')
    child_pid = tmp_path / 'child.pid'
    script = tmp_path / 'bad_worker.py'
    script.write_text('import subprocess,sys\nfrom pathlib import Path\n'
                      'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n'
                      f'Path({str(child_pid)!r}).write_text(str(child.pid))\n'
                      f'print({output!r})\n')
    worker_override(monkeypatch, script)
    cache = tmp_path / 'cache'
    result = q.qualify(body, cache)
    assert result.status == 'unresolved' and result.reason == 'worker_failed'
    assert not list(cache.glob('qualification-*'))
    pid = int(child_pid.read_text())
    # A killed orphan may briefly remain a zombie until init reaps it.
    for _ in range(50):
        state = subprocess.run(['/bin/ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
        if not state or state.startswith('Z'):
            break
        time.sleep(0.01)
    assert not state or state.startswith('Z')


def test_sampled_process_tree_memory_ceiling_stops_worker(tmp_path, monkeypatch):
    body = pdf(tmp_path / 'body.pdf')
    script = tmp_path / 'sleeper.py'
    script.write_text('import time\ntime.sleep(30)\n')
    worker_override(monkeypatch, script)
    monkeypatch.setattr(q, '_process_tree_rss', lambda pid: 2 * 1024 * 1024)
    result = q.qualify(body, tmp_path / 'cache', config=q.QualificationConfig(max_memory_bytes=1024 * 1024))
    assert result.reason == 'memory_limit_exceeded'
    assert result.resources['peak_sampled_tree_rss_bytes'] == 2 * 1024 * 1024
    assert result.resources['rss_samples'] == 1
    assert not list((tmp_path / 'cache').glob('qualification-*'))


def test_real_worker_resource_observations_and_low_memory_refusal(tmp_path):
    body = pdf(tmp_path / 'body.pdf')
    record = q.qualify(body, tmp_path / 'cache')
    assert record.status == 'qualified'
    assert record.resources['workers'] == 1
    assert record.resources['max_simultaneous_poppler_children'] == 1
    assert record.resources['elapsed_seconds'] > 0
    if sys.platform == 'darwin':
        assert record.resources['memory_enforcement'] == 'sampled_tree_rss'
        result = q.qualify(body, tmp_path / 'cache', config=q.QualificationConfig(max_memory_bytes=1))
        assert result.reason == 'memory_limit_exceeded'
        assert result.resources['peak_sampled_tree_rss_bytes'] > 1


def test_parallel_same_body_launches_one_validator(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    body = pdf(tmp_path / 'body.pdf')
    identity = q._identity()
    monkeypatch.setattr(q, '_identity', lambda: identity)
    original = q.subprocess.Popen
    starts = []
    def counted(args, **kwargs):
        if '--worker' in args:
            starts.append(args)
        return original(args, **kwargs)
    monkeypatch.setattr(q.subprocess, 'Popen', counted)
    with ThreadPoolExecutor(max_workers=5) as pool:
        records = list(pool.map(lambda _: q.qualify(body, tmp_path / 'cache'), range(10)))
    assert len(starts) == 1
    assert all(record == records[0] for record in records)


def test_exact_configured_input_decoding_and_page_capacity_with_two_workers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from pypdf.generic import DecodedStreamObject, NameObject
    input_ceiling = 64 * 1024
    content = b'% decoded comment\n' * 64
    bodies = []
    for number in range(2):
        writer = PdfWriter()
        for _ in range(2):
            page = writer.add_blank_page(width=72, height=72)
            stream = DecodedStreamObject()
            stream.set_data(content)
            page[NameObject('/Contents')] = writer._add_object(stream.flate_encode())
        path = tmp_path / f'capacity-{number}.pdf'
        padding = 0
        for _ in range(4):
            writer.add_metadata({'/Title': str(number), '/Padding': 'x' * padding})
            with path.open('wb') as output:
                writer.write(output)
            padding += input_ceiling - path.stat().st_size
        bodies.append(verify_local_file(path))
        assert bodies[-1].size_bytes == input_ceiling
    config = q.QualificationConfig(max_input_bytes=input_ceiling, max_decoded_bytes=len(content) * 2,
                                   max_pages=2, timeout_seconds=5, max_cpu_seconds=3,
                                   max_memory_bytes=512 * 1024 * 1024)
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(lambda body: q.qualify(body, tmp_path / 'cache', config=config), bodies))
    assert all(record.status == 'qualified' and record.pages == 2
               and record.decoded_bytes == config.max_decoded_bytes for record in records)
    assert all(record.resources['elapsed_seconds'] < config.timeout_seconds for record in records)
    assert all(record.resources['peak_sampled_tree_rss_bytes'] <= config.max_memory_bytes for record in records)


def test_serialized_qualification_integrity_bindings_and_completion(tmp_path):
    body = pdf(tmp_path / 'body.pdf')
    result = q.qualify(body, tmp_path / 'cache')
    assert q.verify_qualification_record(json.loads(json.dumps(result)), body_sha256=body.sha256,
                                        body_bytes=body.size_bytes, require_qualified=True) == result
    with pytest.raises(ValueError, match='identity'):
        q.verify_qualification_record(result, body_sha256='0' * 64)
    with pytest.raises(ValueError, match='integrity'):
        q.verify_qualification_record(dict(result, pages=10))
    with pytest.raises(ValueError, match='PDF qualification'):
        q.verify_qualification_record(q._finish({k: (0 if k == 'pages_decoded' else v)
                                               for k, v in result.items() if k != 'qualification_sha256'}))
    unresolved = q.qualify(body, tmp_path / 'cache', config=q.QualificationConfig(max_pages=1))
    with pytest.raises(ValueError, match='incomplete'):
        q.verify_qualification_record(unresolved, require_qualified=True)


@pytest.mark.parametrize('limits', [{'timeout_seconds': float('nan')}, {'max_pages': 1.5},
                                    {'max_pages': True}, {'render_dpi': 0}, {'max_memory_bytes': float('inf')}])
def test_invalid_resource_configuration_is_rejected(limits):
    with pytest.raises(ValueError):
        q.QualificationConfig(**limits)
