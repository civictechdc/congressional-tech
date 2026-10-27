"""One supported viewer command interface, including read-only attempt discovery."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from congress_shared.custody import write_atomic_bytes
from congress_shared.storage import connect_r2
from viewer_publication.resume import MAX_DESCRIPTOR_BYTES, parse_resume_descriptor

_REPO_ROOT = Path(__file__).resolve().parents[4]


def save_report(path, result):
    write_atomic_bytes(
        path,
        (json.dumps(result, indent=2) + '\n').encode('utf-8'),
        temp_mode='unique',
        fsync=True,
    )


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'verify-prepared', 'publish', 'describe-attempt', 'export-pins'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--public-url')
    parser.add_argument('--native-config', type=Path, default=os.environ.get('DOCSPEC_CONFIG'))
    parser.add_argument('--renderer-upgrade', action='store_true')
    parser.add_argument('--resume-preparation', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID'))
    parser.add_argument('--run-attempt', default=os.environ.get('GITHUB_RUN_ATTEMPT'))
    parser.add_argument('--artifact-id'); parser.add_argument('--artifact-digest')
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--resume', action='store_true'); parser.add_argument('--attempt')
    parser.add_argument('--resume-descriptor', type=Path)
    parser.add_argument('--version', default='v-export-01')
    parser.add_argument('--catalog-id', default='export-pin-catalog')
    parser.add_argument('--sources-pin')
    parser.add_argument('--components-pin')
    parser.add_argument('--publish-to-r2', action='store_true')
    tokens = list(sys.argv[1:] if argv is None else argv)
    result = parser.parse_args(tokens)
    result.explicit_options = {token.split('=', 1)[0] for token in tokens if token.startswith('--')}
    return result


def validate(args, attempts):
    if args.command!='prepare' and (args.renderer_upgrade or args.resume_preparation):
        raise ValueError('Renderer upgrade and preparation resume options require prepare')
    if args.command not in ('prepare', 'export-pins') and '--native-config' in args.explicit_options:
        raise ValueError('--native-config is used only for preparation and export-pins')
    if args.command != 'describe-attempt' and args.directory is None:
        raise ValueError(args.command + ' requires --directory')
    if args.command == 'prepare' and (not args.run_id or not args.run_attempt):
        raise ValueError('prepare requires --run-id and --run-attempt')
    if args.command != 'publish' and (args.resume or args.attempt or args.resume_descriptor or args.artifact_digest):
        raise ValueError('Resume and artifact digest options require publish')
    if args.command == 'publish':
        if args.resume_descriptor:
            if not args.resume:
                raise ValueError('--resume-descriptor requires explicit --resume')
            with args.resume_descriptor.open('rb') as stream:
                raw = stream.read(MAX_DESCRIPTOR_BYTES + 1)
            descriptor = parse_resume_descriptor(raw)
            if descriptor.get('version') != 1:
                raise ValueError('publish requires an accepted-publication resume descriptor, not a preparation checkpoint')
            for field, name in (('artifact_id','artifact_id'), ('artifact_digest','artifact_digest'),
                                ('attempt','attempt'), ('run_id','run_id'), ('repository','repository')):
                existing = getattr(args, name)
                if ('--' + name.replace('_','-')) in args.explicit_options and existing is not None and str(existing) != descriptor[field]:
                    raise ValueError('Resume descriptor conflicts with --' + name.replace('_','-'))
                setattr(args, name, descriptor[field])
            revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=_REPO_ROOT, text=True, timeout=10).strip()
            if revision != descriptor['revision']:
                raise ValueError('Check out the resume descriptor original revision before publishing')
        if bool(args.resume) != bool(args.attempt):
            raise ValueError('Explicit --resume and original --attempt are required together')
        if not all((args.artifact_id,args.artifact_digest,args.repository,args.run_id)):
            raise ValueError('publish requires original artifact ID, digest, repository and run ID')
        attempts.artifact_route({'id':args.artifact_id,'repository':args.repository})
    if args.command == 'describe-attempt' and (not args.repository or not args.run_id):
        raise ValueError('describe-attempt requires --repository and --run-id')


def make_client():
    return connect_r2(
        connect_timeout=15,
        read_timeout=180,
        retries={'total_max_attempts': 1},
    )


def failure_context(argv):
    """Recover only explicit output locations when argparse cannot return args."""
    tokens = list(sys.argv[1:] if argv is None else argv)
    values = {'report':None, 'directory':None}
    for index, token in enumerate(tokens):
        for name in values:
            flag = '--' + name
            if token.startswith(flag + '='):
                raw = token[len(flag)+1:]
            elif token == flag and index+1 < len(tokens) and not tokens[index+1].startswith('--'):
                raw = tokens[index+1]
            else:
                continue
            if raw:
                values[name] = Path(raw)
    from types import SimpleNamespace
    return SimpleNamespace(command=tokens[0] if tokens else None, attempt=None, run_id=None, **values)


def main(publisher, argv=None):
    import viewer_publication.attempt as attempts
    args = failure_context(argv)
    try:
        args = arguments(argv)
        validate(args, attempts)  # Validate every combination before constructing a mutation client.
        public_url = args.public_url or publisher.PUBLIC_URL
        if args.command == 'describe-attempt':
            result = attempts.lookup_attempt(args.repository, args.run_id, args.artifact_id)
        elif args.command == 'verify-prepared':
            receipt, manifest, prepared = attempts.verify_prepared(publisher, args.directory)
            result = dict(prepared, status='verified_prepared', files=len(receipt['files']))
        elif args.command == 'export-pins':
            from viewer_publication.filename_exports import export_viewer_pins
            native = None
            if args.native_config:
                from congress_api.retention.docspec import NativeDatasets
                native = NativeDatasets.from_config(args.native_config)
            sources_table = None
            components_table = None
            if native is None and args.directory:
                import pyarrow.parquet as pq
                src_file = args.directory / 'sources.parquet'
                cmp_file = args.directory / 'components.parquet'
                if src_file.is_file() and cmp_file.is_file():
                    sources_table = pq.read_table(src_file)
                    components_table = pq.read_table(cmp_file)
            export_result = export_viewer_pins(
                sources_table=sources_table,
                components_table=components_table,
                target_dir=args.directory,
                native=native,
                sources_pin=args.sources_pin,
                components_pin=args.components_pin,
                catalog_id=args.catalog_id or 'export-pin-catalog',
                version=args.version or 'v-export-01',
            )
            result = dict(export_result, status='exported_pins', directory=str(args.directory))
            if args.publish_to_r2:
                from viewer_publication.client import ConditionalManifestPublisher
                from viewer_publication.constants import BUCKET
                client = make_client()
                cond_pub = ConditionalManifestPublisher(client, bucket=BUCKET)
                manifest = export_result['manifest']
                rel_prefix = f"viewer-publications/releases/{args.version or 'v-export-01'}/viewer-v2/"
                for fname in ('sources.parquet', 'components.parquet', 'occurrences.parquet'):
                    fpath = args.directory / fname
                    if fpath.exists():
                        cond_pub.put_immutable_asset(rel_prefix + fname, fpath)
                pointer = {
                    'version': manifest['version'],
                    'catalog_id': manifest['info']['catalog_id'],
                    'manifest': f"releases/{args.version or 'v-export-01'}/manifest.json",
                    'published_at': manifest['published_at'],
                }
                pointer_receipt = cond_pub.publish_pointer(pointer)
                result['published'] = {
                    'pointer': pointer,
                    'receipt': {
                        'bucket': pointer_receipt.bucket,
                        'key': pointer_receipt.key,
                        'bytes': pointer_receipt.bytes,
                        'sha256': pointer_receipt.sha256,
                        'etag': pointer_receipt.etag,
                    },
                }
        else:
            client = make_client()
            if args.command == 'prepare':
                options = {}
                if args.renderer_upgrade:
                    options['renderer_upgrade'] = True
                if args.resume_preparation:
                    options['resume_preparation'] = True
                options['stage_event'] = lambda event: print(json.dumps(event, sort_keys=True), flush=True)
                if args.native_config:
                    from congress_api.retention.docspec import NativeDatasets
                    options['native'] = NativeDatasets.from_config(args.native_config)
                result = attempts.prepare(publisher, client, args.directory, run_id=args.run_id, run_attempt=args.run_attempt, public_url=public_url, **options)
            else:
                artifact = {'id':args.artifact_id, 'digest':args.artifact_digest, 'repository':args.repository, 'run_id':args.run_id}
                result = attempts.publish(publisher, client, args.directory, artifact=artifact, public_url=public_url, resume=args.resume, attempt=args.attempt)
        if args.report:
            save_report(args.report, result)
        if args.command == 'prepare' and os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                for key in ('status','artifact_name','attempt','preparation_sha256'):
                    if key in result:
                        stream.write(f'{key}={result[key]}\n')
        print(json.dumps(result, indent=2))
        return 0
    except BaseException as error:
        if isinstance(error, SystemExit) and error.code in (None,0):
            raise
        result = {'status':'failed', 'command':args.command, 'error_type':type(error).__name__,
                  'error':str(error) if isinstance(error, ValueError) else 'Command failed; original exception retained in traceback',
                  'attempt':args.attempt, 'run_id':args.run_id}
        # Never leave a prepared success report after an unsuccessful command.
        try:
            if args.report:
                save_report(args.report, result)
            if args.directory and args.directory.is_dir():
                save_report(args.directory / 'command-outcome.json', result)
        except BaseException as diagnostic:
            error.add_note('Outcome receipt save failed: ' + type(diagnostic).__name__)
        raise
