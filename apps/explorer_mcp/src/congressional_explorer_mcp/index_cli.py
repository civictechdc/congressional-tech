"""Internal extraction child and public resumable corpus-index preparation entry."""
import argparse
import json
from pathlib import Path
import sys

from .models import ExplorerError


def index_text(args):
    from .index_builder import build
    from .release import prepare, load_selection
    from .text_index import extraction_definition
    if args.plan:
        return dict(executed=False, definition=extraction_definition(), work=str(args.work),
                    output=str(args.output) if args.output else None, max_work_bytes=args.max_work_bytes,
                    body_timeout=args.body_timeout, child_memory_mb=args.memory_mb,
                    large_pdf_child_memory_mb=args.large_memory_mb,child_memory_enforcement='parent process-group RSS and deadline on macOS/Linux; Linux also applies RLIMIT_AS',
                    pdf_source_bytes=2<<30,pdf_decoded_bytes=2<<30,pdf_output_bytes=256<<20,
                    min_free_bytes=args.min_free_bytes,
                    snapshot_mode=args.snapshot_mode,
                    partial_limit=args.limit, policy='all supported sources; complete dispositions required for publication')
    if args.definition is not None and args.definition not in (extraction_definition()['sha256'],extraction_definition()['policy_sha256']):
        raise ExplorerError('Text extraction definition differs from the pinned app, dependencies or tools; no payloads opened')
    if args.snapshot_mode=='freeze':
        from .index_storage import preflight
        preflight(args.work)
    if args.manifest:
        from .release import resolve
        location, manifest, _ = resolve(args.manifest)
        if sum(item['size'] for item in manifest['files']) + (256 << 20) > args.max_work_bytes:
            raise ExplorerError('Index work budget cannot cover the verified metadata cache; no files downloaded')
        import shutil
        args.work.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(args.work).free < args.min_free_bytes + sum(item['size'] for item in manifest['files']) + (256 << 20):
            raise ExplorerError('Insufficient free space above the index floor for metadata preparation; no files downloaded')
        # Reuse the existing verified immutable metadata owner across retries.
        selection = prepare(args.work / 'metadata', location, archive_origin=args.archive_origin)
    else:
        selection = load_selection(args.data_dir)
    return build(selection, args.work, args.output, expected_definition=args.definition, limit=args.limit,
                 timeout=args.body_timeout, memory_mb=args.memory_mb, max_work_bytes=args.max_work_bytes,
                 retry_errors=args.retry_errors, only_sources=args.only_source,min_free_bytes=args.min_free_bytes,snapshot_mode=args.snapshot_mode,large_memory_mb=args.large_memory_mb)


def arguments(command):
    command.add_argument('--work', type=Path, required=True, help='Durable reusable text/index work directory')
    command.add_argument('--output', type=Path, help='New immutable SQLite artifact; requires a complete run')
    command.add_argument('--manifest', help='Source release manifest; defaults to the selected --data-dir')
    command.add_argument('--archive-origin', help='Verified archive body origin for local manifests')
    command.add_argument('--definition', help='Required portable preparation policy or explicitly qualified runtime definition SHA-256')
    command.add_argument('--limit', type=int, help='Bounded pilot/resume count; partial work cannot publish')
    command.add_argument('--only-source', action='append', help='Bounded pilot source key; other sources remain pending and cannot publish')
    command.add_argument('--body-timeout', type=float, default=120)
    command.add_argument('--memory-mb', type=int, default=768)
    command.add_argument('--large-memory-mb',type=int,default=4096,help='Hard process-family RSS for PDFs above the online 64MiB bound')
    command.add_argument('--max-work-bytes', type=int, default=16 << 30)
    command.add_argument('--min-free-bytes', type=int, default=15 << 30, help='Protected free-space floor beside index work/snapshot')
    command.add_argument('--snapshot-mode',choices=('freeze','copy'),default='freeze',help='Strict native CoW continuation, or separately admitted bulk-copy storage')
    command.add_argument('--retry-errors', action='store_true', help='Retry current unreadable bodies explicitly')
    command.add_argument('--plan', action='store_true', help='Inspect actual extraction/runtime definition and resource policy')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['extract-one', 'definition'])
    parser.add_argument('--target', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--memory-mb', type=int, default=768)
    args = parser.parse_args(argv)
    try:
        if args.command == 'definition':
            from .text_index import extraction_definition
            print(json.dumps(extraction_definition()))
        else:
            from .index_builder import extract_one
            extract_one(args.target, args.output, timeout=args.timeout, memory_mb=args.memory_mb)
        return 0
    except Exception as error:
        from urllib.error import URLError
        cause = error
        retryable = False
        while cause is not None:
            retryable = retryable or isinstance(cause, URLError)
            cause = cause.__cause__
        from .large_body_reader import LargePDFError
        if isinstance(error,LargePDFError):
            retryable=error.code in ('timeout','archive_fetch_failed')
        message = (str(error) or type(error).__name__)[-1200:]
        retryable = retryable or 'body fetch timed out' in message.lower() or 'failed to fetch archived' in message.lower()
        refusal='definition' if 'definition changed' in message.lower() else ('integrity' if 'sha-256 does not match' in message.lower() or 'outside archive_origin' in message.lower() else None)
        if isinstance(error,LargePDFError) and error.code not in ('backend_error','physical_page_mismatch','invalid_gzip','pdf_header_missing'):
            refusal=error.code
        if type(error).__name__=='IndexJobRefusal' or isinstance(error,MemoryError):
            refusal=refusal or 'resource_or_policy'
        print(json.dumps(dict(message=message, retryable=retryable,refusal=refusal,evidence=getattr(error,'evidence',None))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
