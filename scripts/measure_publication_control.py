#!/usr/bin/env python3
"""Measure an explicitly pinned small fixture against a chosen local checkout.

Only the in-memory Remote/custody adapters from the retained attempt tests are
used. No credentials, network requests or mutation clients are constructed.
Run each checkout in a fresh process using the same source directory/runtime.
"""
import argparse
import hashlib
import importlib.util
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from publication_costs import PublicationCosts


def installed_versions(names):
    """Record absent optional packages without changing the measured runtime."""
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def save_published_controls(remote, publisher, output):
    """Retain actual fixture publication bytes after all timed commands finish."""
    pointer = remote.objects[publisher.PREFIX + 'manifest.json']
    if len(pointer) > 4 * 1024**2:
        raise ValueError('Published fixture pointer exceeds evidence limit')
    descriptor = json.loads(pointer)['recovery']
    if descriptor['bytes'] > 32 * 1024**2:
        raise ValueError('Published fixture recovery exceeds evidence limit')
    recovery = remote.objects[publisher.PREFIX + descriptor['path']]
    if len(recovery) != descriptor['bytes'] or hashlib.sha256(recovery).hexdigest() != descriptor['sha256']:
        raise ValueError('Published fixture recovery differs from selected identity')
    (output / 'published-pointer.json').write_bytes(pointer)
    (output / 'published-recovery.json').write_bytes(recovery)


def run(checkout, source, output, source_manifest_sha256, *, maximum_source_bytes=1024**2, request_latency_ms=0):
    if not 0 <= request_latency_ms <= 10:
        raise ValueError('Fixture request latency must be between0 and10ms')
    checkout, source, output = checkout.resolve(), source.resolve(), output.resolve()
    if maximum_source_bytes < 1:
        raise ValueError('Source fixture byte ceiling must be positive')
    paths, total = [], 0
    for path in source.rglob('*'):
        if path.is_relative_to(source / 'public') or not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError('Source fixture contains a symbolic link')
        total += path.stat().st_size
        if total > maximum_source_bytes or len(paths) >= 4096:
            raise ValueError('Source fixture exceeds explicit byte/file ceiling')
        paths.append(path)
    manifest = source / 'indexes/catalog.json'
    if manifest not in paths or manifest.stat().st_size > min(maximum_source_bytes, 4 * 1024**2):
        raise ValueError('Source manifest missing or exceeds explicit byte ceiling')
    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest(manifest) != source_manifest_sha256:
        raise ValueError('Source manifest differs from the explicit input pin')
    source_files = {str(path.relative_to(source)): {'bytes': path.stat().st_size, 'sha256': digest(path)}
                    for path in paths}
    output.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(checkout / p) for p in ('scripts', 'apps/site/scripts', 'packages/congress_api/src', 'packages/house-naming/src')]
    spec = importlib.util.spec_from_file_location('control_cost_fixture', checkout / 'tests/test_viewer_publication_attempt.py')
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    publisher, attempts, remote = fixture.publisher, fixture.attempts, fixture.Remote(source)
    metrics = PublicationCosts(output)
    original_get, original_put, original_download, original_head = remote.get_object, remote.put_object, remote.download_file, remote.head_object
    def get(**kwargs):
        time.sleep(request_latency_ms / 1000)
        metrics.counts['get_requests'] += 1
        response = original_get(**kwargs)
        metrics.counts['remote_body_bytes_read'] += response['ContentLength']
        return response
    def put(**kwargs):
        time.sleep(request_latency_ms / 1000)
        metrics.counts['put_requests'] += 1
        body = kwargs['Body']
        metrics.counts['put_body_bytes'] += len(body) if isinstance(body, bytes) else kwargs['ContentLength']
        return original_put(**kwargs)
    def head(**kwargs):
        # The test adapter models HEAD using GET internally. Keep that detail
        # out of the request/full-body counters to model the actual SDK boundary.
        time.sleep(request_latency_ms / 1000)
        metrics.counts['head_requests'] += 1
        response = original_get(**kwargs); response['Body'].close()
        return {name: response[name] for name in ('ETag', 'ContentLength')}
    def download(bucket, key, destination):
        time.sleep(request_latency_ms / 1000)
        metrics.counts['download_requests'] += 1
        metrics.counts['download_bytes'] += len(remote.objects[key])
        return original_download(bucket, key, destination)
    remote.get_object, remote.put_object, remote.download_file, remote.head_object = get, put, download, head
    class Public(io.BytesIO):
        headers = {'Access-Control-Allow-Origin': '*'}
    publisher.open_public = lambda request, **kwargs: Public(remote.objects[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)])
    root, outcomes = output / 'attempt', {}
    inputs = {'source_manifest_sha256': source_manifest_sha256, 'source_files': source_files,
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip(),
        'source_identity': publisher.full_release_identity() if hasattr(publisher, 'full_release_identity') else attempts.content_identity(publisher),
        'python': sys.version, 'executable': sys.executable, 'maximum_source_bytes': maximum_source_bytes, 'controlled_request_latency_ms': request_latency_ms,
        'runtime': {'implementation': platform.python_implementation(), 'platform': platform.platform(),
            'machine': platform.machine(), 'packages': installed_versions(
                ('pyarrow', 'boto3', 'botocore', 'lxml', 'duckdb', 'zstandard', 'ijson'))},
        'command_process_model': 'source identity cache starts cold for each timed command; interpreter/import startup excluded',
        'prepared_recovery_supported': hasattr(publisher, 'prepare_recovery'),
        'measurement_sources': {name: digest(Path(__file__).with_name(name))
                                for name in ('publication_costs.py', 'measure_publication_control.py', 'benchmark_viewer_publication.py')}}
    def publish(*, resume=False, probe=lambda *args: None):
        return attempts.publish(publisher, remote, root, artifact={'id': '456'}, public_url=publisher.PUBLIC_URL,
            verify_artifact=fixture.custody, probe=probe, resume=resume, attempt=prepared['attempt'] if resume else None)
    def command_stage(name):
        # The real CLI commands run in separate processes. Clear only the shared
        # source identity cache before timing; keep reuse within each command.
        identity_module=sys.modules.get('viewer_release_identity')
        if identity_module is not None:identity_module._source_cache.clear()
        return metrics.stage(name)
    try:
        with metrics.instrument():
            with command_stage('accepted_preparation'):
                prepared = attempts.prepare(publisher, remote, root, run_id='123', run_attempt='1', public_url=publisher.PUBLIC_URL)
            with command_stage('successful_publication'):
                outcomes['successful_publication'] = publish()
            with command_stage('unchanged_poll'):
                outcomes['unchanged_poll'] = attempts.prepare(publisher, remote, output / 'noop', run_id='124', run_attempt='1', public_url=publisher.PUBLIC_URL)
            def refuse(*args):
                raise RuntimeError('Explicit bounded fixture probe failure')
            try:
                with command_stage('explicit_resume_failure'):
                    publish(resume=True, probe=refuse)
            except RuntimeError as error:
                outcomes['explicit_resume_failure'] = {'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)}
            else:
                raise AssertionError('Expected fixture failure did not occur')
            with command_stage('explicit_resume'):
                outcomes['explicit_resume'] = publish(resume=True)
        assert outcomes['successful_publication']['status'] == 'published'
        assert outcomes['unchanged_poll']['status'] == 'unchanged'
        assert outcomes['explicit_resume']['status'] == 'published'
        noop = next(s for s in metrics.stages if s['stage'] == 'unchanged_poll')['counts']
        assert not any(noop.get(name) for name in ('put_requests', 'download_requests', 'decode_iterator_passes'))
        save_published_controls(remote, publisher, output)
    except BaseException as error:
        outcomes['runner_failure'] = {'error_type': type(error).__name__, 'error': str(error)}
        raise
    finally:
        metrics.save(output / 'costs.json', inputs=inputs, outcomes=outcomes)
    return output / 'costs.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    parser.add_argument('--request-latency-ms', type=float, default=0)
    parser.add_argument('--maximum-source-bytes', type=int, default=1024**2)
    args = parser.parse_args()
    print(run(args.checkout, args.source, args.output, args.source_manifest_sha256,
              maximum_source_bytes=args.maximum_source_bytes, request_latency_ms=args.request_latency_ms))
