"""Install an approved, credential-free Linux local-job archive before CI tests."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from congress_api.retention.derived_files import copy_checked, file_identity
from docspec_client import RUNTIME_PIN_FILE, NativeDatasets, load_runtime_pin, runtime_pin_digest

FILES = {'docspec', 'runtime.json', 'limits.json', 'build.json'}
PINS = {'source_revision', 'platform', 'build_features', 'binary_sha256'}
LIMITS = {'compute_threads', 'memory_bytes', 'scratch_bytes', 'batch_rows',
          'max_batch_bytes', 'max_metadata_bytes'}
MAX_ARCHIVE_BYTES = 1024**3


def install_archive(archive, expected_sha256, directory, *, proof=None, pin_file=None):
    """Check complete archive custody, then expose exactly four validated files."""
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('An approved archive SHA-256 is required')
    actual = proof.require(archive) if proof is not None else file_identity(archive)
    if actual['sha256'] != expected_sha256 or not 0 < actual['bytes'] <= MAX_ARCHIVE_BYTES:
        raise ValueError('Local runtime archive digest or size differs from approval')
    directory = Path(directory)
    if directory.exists() or directory.is_symlink():
        raise ValueError('Local runtime requires a fresh installation directory')
    directory.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.local-runtime-', dir=directory.parent))
    try:
        seen, binary = set(), None
        with tarfile.open(archive, 'r:gz') as source:
            for member in source:
                if member.name not in FILES or member.name in seen or not member.isfile():
                    raise ValueError('Archive requires four unique regular root files')
                cap = MAX_ARCHIVE_BYTES if member.name == 'docspec' else 1024**2
                if not 0 < member.size <= cap:
                    raise ValueError('Runtime archive member exceeds its size bound')
                if member.name == 'docspec' and not member.mode & 0o111:
                    raise ValueError('Runtime binary must be declared executable')
                with source.extractfile(member) as stream:
                    checked = copy_checked(stream, stage/member.name, size=member.size, exclusive=True)
                if member.name == 'docspec':
                    binary = checked
                seen.add(member.name)
        if seen != FILES:
            raise ValueError('Runtime archive is missing a required file')
        config = json.loads((stage/'runtime.json').read_text())
        build = json.loads((stage/'build.json').read_text())
        limits = json.loads((stage/'limits.json').read_text())
        allowed = {'version', 'binary', 'limits', 'workspace', 'timeout_seconds', 'required_capabilities'} | PINS
        if (not isinstance(config, dict) or set(config)-allowed or type(config.get('version')) is not int
                or config['version'] != 1 or any(config.get(k) != v for k,v in
                    {'binary':'./docspec', 'limits':'./limits.json', 'workspace':'./workspace'}.items())
                or not isinstance(build, dict) or set(build) != PINS | {'version'}
                or type(build['version']) is not int or build['version'] != 1
                or any(config.get(k) != build[k] for k in PINS)
                or build['platform'] != 'linux-amd64'
                or not isinstance(build['source_revision'], str) or not re.fullmatch('[0-9a-f]{40}', build['source_revision'])
                or not isinstance(build['binary_sha256'], str) or build['binary_sha256'] != binary['sha256']
                or not isinstance(build['build_features'], list) or 'remote' not in build['build_features']
                or 'test-util' in build['build_features']):
            raise ValueError('Local runtime configuration and build pins must agree')
        if (not isinstance(limits, dict) or set(limits) != LIMITS
                or any(type(value) is not int or value <= 0 for value in limits.values())):
            raise ValueError('Local runtime requires the six approved positive integer limits')
        if pin_file is not None:
            pin = load_runtime_pin(pin_file)
            pinned_sha256 = runtime_pin_digest(build['platform'], pin_path=pin_file)
            if build['source_revision'] != pin['source_revision'] or build['binary_sha256'] != pinned_sha256:
                raise ValueError('Local runtime build pins differ from the committed runtime pin file')
        (stage/'docspec').chmod(0o700)
        NativeDatasets.from_config(stage/'runtime.json').verify_runtime(required_features=['remote'])
        # Fresh destination owns the exposure; no stale or concurrent install is overwritten.
        directory.mkdir(mode=0o700, exist_ok=False)
        for name in FILES:
            os.rename(stage/name, directory/name)
        return directory.resolve()/'runtime.json'
    finally:
        shutil.rmtree(stage)


def require_https(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Approved local runtime URL requires credential-free HTTPS')
    return url


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--github-env', type=Path, required=True)
    parser.add_argument('--pin-file', type=Path, default=RUNTIME_PIN_FILE)
    parser.add_argument('--platform', default='linux-amd64')
    parser.add_argument('--archive-sha256', help='Optional explicit archive SHA-256 override; defaults to committed pin file.')
    args = parser.parse_args(argv)
    try:
        url = require_https(os.environ.get('DOCSPEC_LOCAL_RUNTIME_URL', ''))
        pin = load_runtime_pin(args.pin_file)
        digest = args.archive_sha256 or runtime_pin_digest(args.platform, pin_path=args.pin_file)
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Committed runtime pin must supply a 64-char SHA-256 digest')
        runner = Path(os.environ['RUNNER_TEMP']).resolve()
        for path in (args.directory, args.github_env):
            if path.is_symlink() or not path.resolve().is_relative_to(runner) or any(c in str(path) for c in '\r\n'):
                raise ValueError('Runtime outputs require owned RUNNER_TEMP paths')
        if not args.github_env.is_file():
            raise ValueError('GITHUB_ENV must be an existing runner file')
        with tempfile.TemporaryDirectory(prefix='local-runtime-download-', dir=runner) as work:
            archive = Path(work)/'runtime.tar.gz'
            with build_opener(HTTPSRedirects()).open(url, timeout=180) as source:
                size = int(source.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_ARCHIVE_BYTES:
                    raise ValueError('Runtime download requires a bounded Content-Length')
                proof = copy_checked(source, archive, size=size, expected={'bytes':size, 'sha256':digest}, exclusive=True)
            config = install_archive(archive, digest, args.directory, proof=proof,
                                     pin_file=args.pin_file if args.archive_sha256 is None else None)
        env = {**os.environ, 'DOCSPEC_JOB_CONFIG':str(config)}
        root = Path(__file__).resolve().parents[2]
        subprocess.run([sys.executable, str(root/'scripts/dev.py'), 'doctor', '--lane', 'production-offline'],
                       cwd=root, env=env, check=True)
        with args.github_env.open('a') as target:
            target.write(f'DOCSPEC_JOB_CONFIG={config}\nDOCSPEC_SOURCE_REVISION={pin["source_revision"]}\n')
        print('Approved credential-free local runtime installed; offline doctor passed.')
        return 0
    except ValueError as error:
        # Only authored diagnostics; download/provider errors may embed URL values.
        print('Local runtime setup refused (' + type(error).__name__ + '). Check the approved artifact and metadata.', file=sys.stderr)
    except Exception as error:
        print('Local runtime setup failed: ' + type(error).__name__, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
