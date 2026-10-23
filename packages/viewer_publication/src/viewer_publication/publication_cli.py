"""One supported viewer command interface, including read-only attempt discovery."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

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
    parser.add_argument('command', choices=('prepare', 'verify-prepared', 'publish', 'describe-attempt'))
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
    tokens = list(sys.argv[1:] if argv is None else argv)
    result = parser.parse_args(tokens)
    result.explicit_options = {token.split('=', 1)[0] for token in tokens if token.startswith('--')}
    return result


def validate(args, attempts):
    if args.command!='prepare' and (args.renderer_upgrade or args.resume_preparation):
        raise ValueError('Renderer upgrade options require prepare')
    if args.resume_preparation and not args.renderer_upgrade:
        raise ValueError('--resume-preparation requires --renderer-upgrade')
    if args.command != 'prepare' and '--native-config' in args.explicit_options:
        raise ValueError('--native-config is used only for preparation')
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
        else:
            client = make_client()
            if args.command == 'prepare':
                options = {}
                if args.renderer_upgrade:
                    options.update(renderer_upgrade=True,resume_preparation=args.resume_preparation)
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
