"""Install one privately distributed, byte-pinned DocSpec runtime without executing it."""
import argparse
from contextlib import closing
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

from congress_api.retention.derived_files import copy_checked
from congress_api.retention.docspec import NativeDatasets

MAX_BINARY_BYTES = 1024**3
SECRET_NAMES = {'DOCSPEC_CATALOG_TOKEN', 'DOCSPEC_S3_ACCESS_KEY_ID', 'DOCSPEC_S3_SECRET_ACCESS_KEY'}


class SetupFailure(ValueError):
    """A diagnostic that contains no input values or provider response bodies."""


def document(raw, label):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise SetupFailure(f'{label} must be valid JSON') from None


def artifact_descriptor(raw):
    value = document(raw, 'Runtime artifact descriptor')
    fields = {'version', 'platform', 'source_revision', 'bucket', 'key', 'bytes', 'sha256'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['version']) is not int
            or value['version'] != 1 or value['platform'] != 'linux-amd64'
            or not isinstance(value['source_revision'], str) or not re.fullmatch('[0-9a-f]{40}', value['source_revision'])
            or not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256'])
            or type(value['bytes']) is not int or not 0 < value['bytes'] <= MAX_BINARY_BYTES
            or not isinstance(value['bucket'], str) or not re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', value['bucket'])):
        raise SetupFailure('Runtime artifact descriptor requires exact version, platform, revision, location and bounded byte identity')
    expected = f"runtime/docspec/{value['source_revision']}/linux-amd64/{value['sha256']}/docspec"
    if value['key'] != expected:
        raise SetupFailure('Runtime artifact key differs from its revision, platform or digest')
    return value


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


def install(artifact, credentials, remote, directory, *, client):
    """Read exactly one selected private object; create no native workspace/provider state."""
    directory = Path(directory)
    if directory.is_symlink() or directory.exists():
        raise SetupFailure('Runtime installation requires a fresh directory')
    directory = directory.resolve()
    if any(char in str(directory) for char in '\r\n'):
        raise SetupFailure('Runtime output path cannot contain line breaks')
    # Existing directories, symlinks and interrupted installations require explicit
    # operator reconciliation. Never promote or overwrite a stale executable.
    remote_raw = Path(remote).read_bytes()
    remote_value = document(remote_raw, 'DocSpec remote configuration')
    references = remote_value.get('secret_env') if isinstance(remote_value, dict) else None
    if not isinstance(references, dict) or set(references.values()) != SECRET_NAMES:
        raise SetupFailure('DocSpec remote configuration must declare the three engine secret references')
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(directory / 'credentials.json', json.dumps(credentials).encode())
    private_write(directory / 'remote.json', remote_raw)
    configuration = dict(version=1, binary='docspec', workspace='workspace', remote='remote.json',
                         credentials='credentials.json', timeout_seconds=120)
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
    report = checker.check(config, artifact['sha256'])
    report.update(platform=artifact['platform'], source_revision=artifact['source_revision'],
                  artifact_bytes=artifact['bytes'], artifact_downloaded=True, native_provider_accessed=False,
                  remote_sha256=sha256(remote_raw).hexdigest())
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
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--github-env', type=Path, help='Export only the installed configuration path and approved binary digest.')
    args = parser.parse_args(argv)
    try:
        artifact = artifact_descriptor(args.artifact_descriptor.read_text() if args.artifact_descriptor else os.environ.get('DOCSPEC_RUNTIME_ARTIFACT'))
        credentials = engine_credentials(args.credentials_file.read_text() if args.credentials_file else os.environ.get('DOCSPEC_ENGINE_CREDENTIALS'))
        if args.credentials_file and args.credentials_file.stat().st_mode & 0o077:
            raise SetupFailure('Local DocSpec credentials require private file permissions (0600)')
        config, report = install(artifact, credentials, args.remote, args.directory, client=make_client(credentials))
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        if args.github_env:
            with args.github_env.open('a') as target:
                target.write(f"DOCSPEC_RUNTIME_CONFIG={config}\nDOCSPEC_BINARY_SHA256={artifact['sha256']}\n")
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
