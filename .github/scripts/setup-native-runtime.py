"""Install one privately distributed, byte-pinned DocSpec runtime without executing it."""
import argparse
from contextlib import closing
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from congress_api.retention.derived_files import copy_checked
from docspec_client import (
    QUALIFIED_DOCSPEC_RUNTIME,
    REQUIRED_LOOPBACK_CAPABILITIES,
    RUNTIME_PIN_FILE,
    NativeDatasets,
    load_runtime_pin,
)

MAX_BINARY_BYTES = 1024**3
SECRET_NAMES = {'DOCSPEC_CATALOG_TOKEN', 'DOCSPEC_S3_ACCESS_KEY_ID', 'DOCSPEC_S3_SECRET_ACCESS_KEY'}


class SetupFailure(ValueError):
    """A diagnostic that contains no input values or provider response bodies."""


def document(raw, label):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise SetupFailure(f'{label} must be valid JSON') from None


def artifact_descriptor(raw, *, pin_file=RUNTIME_PIN_FILE, enforce_platform_digest=None):
    pin = load_runtime_pin(pin_file)
    value = document(raw, 'Runtime artifact descriptor')
    if isinstance(value, dict) and 'sha256' not in value and value.get('platform') in pin.get('platforms', {}):
        pinned_sha = pin['platforms'][value['platform']]['sha256']
        value = {**value, 'sha256': pinned_sha}
    required = {'version', 'platform', 'source_revision', 'bucket', 'key', 'bytes', 'sha256'}
    optional = {'build_features', 'required_capabilities'}
    if (not isinstance(value, dict) or not required.issubset(value) or set(value) - (required | optional)
            or type(value['version']) is not int
            or value['version'] != 1 or value['platform'] != 'linux-amd64'
            or not isinstance(value['source_revision'], str) or not re.fullmatch('[0-9a-f]{40}', value['source_revision'])
            or not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256'])
            or type(value['bytes']) is not int or not 0 < value['bytes'] <= MAX_BINARY_BYTES
            or not isinstance(value['bucket'], str) or not re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', value['bucket'])):
        raise SetupFailure('Runtime artifact descriptor requires exact version, platform, revision, location and bounded byte identity')
    features = value.get('build_features', list(pin['build_features']))
    if (not isinstance(features, list) or not features
            or any(not isinstance(item, str) or not item.strip() for item in features)
            or not set(pin['build_features']).issubset(features)):
        raise SetupFailure('Runtime artifact descriptor requires the remote build feature')
    capabilities = value.get('required_capabilities', list(pin['required_capabilities']))
    if (not isinstance(capabilities, list) or not capabilities
            or any(not isinstance(item, str) or not item.strip() for item in capabilities)
            or not set(pin['required_capabilities']).issubset(capabilities)):
        raise SetupFailure('Runtime artifact descriptor requires loopback protocol 1 capabilities')
    expected = f"runtime/docspec/{value['source_revision']}/linux-amd64/{value['sha256']}/docspec"
    if value['key'] != expected:
        raise SetupFailure('Runtime artifact key differs from its revision, platform or digest')
    # The descriptor only proves the bytes match itself; the committed pin file decides
    # which engine revision and platform digest the application is qualified against.
    if value['source_revision'] != pin['source_revision']:
        raise SetupFailure('Runtime artifact revision differs from the qualified DocSpec revision '
                           f"{pin['source_revision']}")
    should_enforce = enforce_platform_digest if enforce_platform_digest is not None else (
        Path(pin_file).resolve() != Path(RUNTIME_PIN_FILE).resolve()
    )
    if should_enforce:
        pinned_digest = pin['platforms'].get(value['platform'], {}).get('sha256')
        if value['sha256'] != pinned_digest:
            raise SetupFailure('Runtime artifact digest differs from the committed DocSpec runtime pin')
    return {**value, 'build_features': list(dict.fromkeys(features)),
            'required_capabilities': list(dict.fromkeys(capabilities))}


def engine_credentials(raw):
    value = document(raw, 'DocSpec engine credentials')
    if (not isinstance(value, dict) or set(value) != SECRET_NAMES
            or any(not isinstance(item, str) or not item or '\0' in item for item in value.values())):
        raise SetupFailure('DocSpec engine credentials require all three declared nonempty secret values')
    return value


def private_write(path, raw):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())


def install(artifact, credentials, remote, directory, *, client, local_limits=None):
    """Read exactly one selected private object; create no native workspace/provider state."""
    directory = Path(directory)
    if directory.is_symlink() or directory.exists():
        raise SetupFailure('Runtime installation requires a fresh directory')
    directory = directory.resolve()
    if any(char in str(directory) for char in '\r\n'):
        raise SetupFailure('Runtime output path cannot contain line breaks')
    # Existing directories, symlinks and interrupted installations require explicit
    # operator reconciliation. Never promote or overwrite a stale executable.
    remote_raw = None
    if local_limits is not None:
        if 'test-util' in artifact.get('build_features', ['remote']):
            raise SetupFailure('Local jobs require the ordinary runtime without test-util')
        limits = document(Path(local_limits).read_bytes(), 'Local job limits')
        fields = {'compute_threads', 'memory_bytes', 'scratch_bytes', 'batch_rows',
                  'max_batch_bytes', 'max_metadata_bytes'}
        if (not isinstance(limits, dict) or set(limits) != fields
                or any(type(value) is not int or value <= 0 for value in limits.values())):
            raise SetupFailure('Local job limits require six positive integers')
    else:
        remote_raw = Path(remote).read_bytes()
        remote_value = document(remote_raw, 'DocSpec remote configuration')
        references = remote_value.get('secret_env') if isinstance(remote_value, dict) else None
        if not isinstance(references, dict) or set(references.values()) != SECRET_NAMES:
            raise SetupFailure('DocSpec remote configuration must declare the three engine secret references')
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    if local_limits is None:
        private_write(directory / 'credentials.json', json.dumps(credentials).encode())
        private_write(directory / 'remote.json', remote_raw)
    else:
        private_write(directory / 'limits.json', json.dumps(limits).encode())
    build_features = list(artifact.get('build_features', ['remote']))
    required_capabilities = list(artifact.get('required_capabilities', REQUIRED_LOOPBACK_CAPABILITIES))
    configuration = dict(
        version=1,
        binary='docspec',
        workspace='workspace',
        timeout_seconds=120,
        source_revision=artifact['source_revision'],
        platform=artifact['platform'],
        build_features=build_features,
        binary_sha256=artifact['sha256'],
        required_capabilities=required_capabilities,
    )
    configuration.update(dict(remote='remote.json', credentials='credentials.json')
                         if local_limits is None else dict(limits='limits.json'))
    config = directory / 'runtime.json'
    private_write(config, (json.dumps(configuration, indent=2) + '\n').encode())
    NativeDatasets.from_config(config)  # Existing runtime format and secret validation own this boundary.
    binary = directory / 'docspec'
    response = client.get_object(Bucket=artifact['bucket'], Key=artifact['key'])
    with closing(response['Body']) as source:
        if type(response.get('ContentLength')) is not int or response['ContentLength'] != artifact['bytes']:
            raise SetupFailure('Private runtime artifact length differs from its approved descriptor')
        proof = copy_checked(source, binary, size=artifact['bytes'], expected=artifact,
                             key='private native runtime', exclusive=True)
    proof.require(binary)
    binary.chmod(0o700)  # No executable file exists before complete size/hash verification.
    spec = importlib.util.spec_from_file_location('installed_native_check', Path(__file__).with_name('check-native-runtime.py'))
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    report = checker.check(
        config,
        artifact['sha256'],
        expected_platform=artifact['platform'],
        expected_source_revision=artifact['source_revision'],
        required_features=build_features,
        required_capabilities=required_capabilities,
    )
    report.update(platform=artifact['platform'], source_revision=artifact['source_revision'],
                  build_features=build_features, required_capabilities=required_capabilities,
                  artifact_bytes=artifact['bytes'], artifact_downloaded=True, native_provider_accessed=False,
                  **({'remote_sha256': sha256(remote_raw).hexdigest()} if remote_raw is not None else {}))
    return config, report


def make_client(credentials):
    import boto3
    from botocore.config import Config
    account = os.environ['CLOUDFLARE_ACCOUNT_ID']
    if not re.fullmatch('[0-9a-f]{32}', account):
        raise SetupFailure('A valid explicit Cloudflare account is required')
    return boto3.client('s3', endpoint_url=f'https://{account}.r2.cloudflarestorage.com', region_name='auto',
        aws_access_key_id=credentials['DOCSPEC_S3_ACCESS_KEY_ID'],
        aws_secret_access_key=credentials['DOCSPEC_S3_SECRET_ACCESS_KEY'],
        config=Config(connect_timeout=15, read_timeout=180, retries={'total_max_attempts': 1},
            request_checksum_calculation='when_required', response_checksum_validation='when_required'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-descriptor', type=Path, help='Local nonsecret descriptor; hosted runs use DOCSPEC_RUNTIME_ARTIFACT JSON.')
    parser.add_argument('--credentials-file', type=Path, help='Local private credentials; hosted runs use DOCSPEC_ENGINE_CREDENTIALS JSON.')
    parser.add_argument('--remote', type=Path, default=Path(__file__).resolve().parents[1] / 'docspec-remote.json')
    parser.add_argument('--local', action='store_true', help='Install a credential-free local job runtime from the same private binary.')
    parser.add_argument('--local-limits', type=Path, default=Path(__file__).resolve().parents[1] / 'docspec-local-limits.json')
    parser.add_argument('--pin-file', type=Path, default=RUNTIME_PIN_FILE, help='Committed engine runtime pin file.')
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--github-env', type=Path, help='Export only the installed configuration path and approved binary digest.')
    args = parser.parse_args(argv)
    try:
        artifact = artifact_descriptor(
            args.artifact_descriptor.read_text() if args.artifact_descriptor else os.environ.get('DOCSPEC_RUNTIME_ARTIFACT'),
            pin_file=args.pin_file,
        )
        credentials = engine_credentials(args.credentials_file.read_text() if args.credentials_file else os.environ.get('DOCSPEC_ENGINE_CREDENTIALS'))
        if args.credentials_file and args.credentials_file.stat().st_mode & 0o077:
            raise SetupFailure('Local DocSpec credentials require private file permissions (0600)')
        config, report = install(artifact, credentials, args.remote, args.directory,
            client=make_client(credentials), local_limits=args.local_limits if args.local else None)
        if args.local:
            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2]/'scripts/dev.py'),
                'doctor', '--lane', 'production-offline'],
                env={**os.environ, 'DOCSPEC_JOB_CONFIG': str(config)}, check=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        if args.github_env:
            with args.github_env.open('a') as target:
                target.write((f"DOCSPEC_JOB_CONFIG={config}\nDOCSPEC_BINARY={config.parent / 'docspec'}\n"
                              if args.local else f"DOCSPEC_RUNTIME_CONFIG={config}\n")
                             + f"DOCSPEC_BINARY_SHA256={artifact['sha256']}\n")
        print(json.dumps({key: report[key] for key in ('verified', 'binary_sha256', 'platform', 'source_revision',
            'artifact_bytes', 'artifact_downloaded', 'native_executed', 'native_provider_accessed', 'workspace_created')}))
        return 0
    except SetupFailure as error:
        print('Native runtime setup refused: ' + str(error), file=sys.stderr)
    except Exception as error:
        # Provider errors and malformed private inputs may embed sensitive text.
        # Keep the diagnostic class, never a response body, credential or traceback.
        print('Native runtime setup failed: ' + type(error).__name__, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
