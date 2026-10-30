"""Execute B14 meeting fetchers through the shared raw Fetcher, ReceiptWriter and BodyStore."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from congress_api.acquisition import gpo as gpo_acq
from congress_api.acquisition import house as house_acq
from congress_api.acquisition import meetings as meetings_acq
from congress_api.acquisition import senate as senate_acq
from congress_api.acquisition.capture_scheduler import CapturePolicy, PACING, resolve_host
from congress_api.acquisition.fetcher import Fetcher, HostPacer
from congress_api.retention.archive_members import ZipLimits
from congress_api.retention.body_store import BodyStore, LocalAdapter, R2Adapter
from congress_api.retention.pipeline_raw import new_run_id
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.retention.writer_identity import writer_identity

ROOT = Path(__file__).resolve().parents[5]
DEFAULT_SCOPE = ROOT / 'model/registries/capture-scope.json'


def run_meeting_fetchers(
    *,
    store,
    identity,
    direct,
    provider=None,
    scope_path=DEFAULT_SCOPE,
    resolve=resolve_host,
    pace=None,
    headers=None,
    congress_endpoints=(),
    congress_detail_urls=(),
    gpo_since=None,
    gpo_packages=(),
    house_meetings=(),
    senate_urls=(),
    api_key=None,
    spool_limit=64 << 20,
    write_date=None,
):
    """Run B14 meeting fetchers through Fetcher + ReceiptWriter + BodyStore with no separate state files."""
    policy = CapturePolicy(scope_path, resolve=resolve)
    policy.require_capture()
    run_id = new_run_id()
    stamp_date = write_date or datetime.now(timezone.utc).date().isoformat()
    writer = ReceiptWriter(
        store,
        identity=identity,
        run_id=run_id,
        write_date=stamp_date,
        archive_limits=ZipLimits(),
    )
    pace = pace or HostPacer(PACING)
    if headers is None:
        def headers(url):
            if urlsplit(url).hostname in {'api.congress.gov', 'api.govinfo.gov'}:
                key = api_key or os.environ.get('DATA_GOV_API_KEY') or os.environ.get('CONGRESS_GOV_API_KEY')
                if not key:
                    raise ValueError('DATA_GOV_API_KEY is required for API meeting fetches')
                return {'X-Api-Key': key}
            return {}

    summary = {
        'run_id': run_id,
        'write_date': stamp_date,
        'congress_windows': [],
        'congress_details': [],
        'gpo_packages': [],
        'house_meetings': [],
        'senate_pages': [],
        'receipt_keys': [],
    }
    watermarks = {}
    with TemporaryDirectory(prefix='b14-meetings-') as spool:
        fetcher = Fetcher(
            scope=policy,
            direct=direct,
            provider=provider,
            pace=pace,
            directory=spool,
            spool_limit=spool_limit,
            headers=headers,
        )
        for item in congress_endpoints:
            spec = item if isinstance(item, dict) else {'endpoint': item}
            res = meetings_acq.relist_endpoint_window(
                fetcher,
                writer,
                spec['endpoint'],
                from_date_time=spec.get('from_date_time'),
                to_date_time=spec.get('to_date_time'),
                limit=int(spec.get('limit', 250)),
                watermarks=watermarks,
            )
            summary['congress_windows'].append(
                {
                    'endpoint': spec['endpoint'],
                    'complete': res['complete'],
                    'window_advanced': res['window_advanced'],
                    'pages_fetched': res['pages_fetched'],
                    'detail_count': len(res['detail_urls']),
                    'receipt_keys': res['receipt_keys'],
                }
            )
            summary['receipt_keys'].extend(res['receipt_keys'])

        for detail_url in congress_detail_urls:
            res = meetings_acq.fetch_detail_through_raw(fetcher, writer, detail_url)
            summary['congress_details'].append(res)
            summary['receipt_keys'].extend(res['receipt_keys'])

        if gpo_since:
            key = api_key or os.environ.get('DATA_GOV_API_KEY') or ''
            listed_pkgs = list(
                gpo_acq.list_collection(
                    gpo_since,
                    key,
                    fetcher=fetcher,
                    receipt_writer=writer,
                )
            )
            summary['gpo_listed_count'] = len(listed_pkgs)

        for package_id in gpo_packages:
            res = gpo_acq.fetch_package_through_raw(fetcher, writer, package_id)
            summary['gpo_packages'].append(res)
            summary['receipt_keys'].extend(res['receipt_keys'])

        for meeting in house_meetings:
            res = house_acq.fetch_through_raw(fetcher, writer, meeting)
            summary['house_meetings'].append(res)
            summary['receipt_keys'].extend(res['receipt_keys'])

        for page_url in senate_urls:
            res = senate_acq.fetch_page_through_raw(fetcher, writer, page_url)
            summary['senate_pages'].append(res)
            summary['receipt_keys'].extend(res['receipt_keys'])

    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, help='JSON specification of B14 meeting targets to fetch')
    parser.add_argument('--local-store', type=Path, help='Local create-only body/receipt store root')
    parser.add_argument('--bucket', default='congressional-tech-raw')
    parser.add_argument('--scope', type=Path, default=DEFAULT_SCOPE)
    parser.add_argument('--gpo-package', action='append', default=[])
    parser.add_argument('--senate-url', action='append', default=[])
    parser.add_argument('--congress-detail-url', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)

    spec_data = json.loads(args.spec.read_text(encoding='utf-8')) if args.spec else {}
    if not args.apply and args.local_store is None:
        plan_report = {
            'status': 'planned',
            'scope': str(args.scope),
            'gpo_packages': list(spec_data.get('gpo_packages', ())) + list(args.gpo_package),
            'senate_urls': list(spec_data.get('senate_urls', ())) + list(args.senate_url),
            'congress_detail_urls': list(spec_data.get('congress_detail_urls', ())) + list(args.congress_detail_url),
            'house_meetings': list(spec_data.get('house_meetings', ())),
            'congress_endpoints': list(spec_data.get('congress_endpoints', ())),
        }
        print(json.dumps(plan_report, indent=2, sort_keys=True))
        return plan_report

    if args.local_store is not None:
        store = BodyStore(LocalAdapter(args.local_store))
        identity = dict(
            job='b14-meeting-fetchers',
            commit=spec_data.get('commit') or '0' * 40,
            lockfile_digest=spec_data.get('lockfile_digest') or '0' * 64,
        )
    else:
        identity = writer_identity(ROOT, 'b14-meeting-fetchers')
        from congress_shared.storage import connect_r2
        store = BodyStore(
            R2Adapter(
                connect_r2(bucket=args.bucket, retries={'mode': 'standard', 'max_attempts': 5}),
                args.bucket,
            )
        )

    import requests
    from congress_api.transport.raw_adapters import DirectAdapter, ProviderAdapter
    session = requests.Session()
    provider = None
    if os.environ.get('ZYTE_TOKEN'):
        from congress_api.transport import zyte
        provider = ProviderAdapter(
            lambda payload: session.post(
                zyte.API,
                json=payload,
                auth=(zyte.token(), ''),
                stream=True,
                allow_redirects=False,
                timeout=(15, 300),
            )
        )

    result = run_meeting_fetchers(
        store=store,
        identity=identity,
        direct=DirectAdapter(session),
        provider=provider,
        scope_path=args.scope,
        congress_endpoints=spec_data.get('congress_endpoints', ()),
        congress_detail_urls=list(spec_data.get('congress_detail_urls', ())) + list(args.congress_detail_url),
        gpo_since=spec_data.get('gpo_since'),
        gpo_packages=list(spec_data.get('gpo_packages', ())) + list(args.gpo_package),
        house_meetings=spec_data.get('house_meetings', ()),
        senate_urls=list(spec_data.get('senate_urls', ())) + list(args.senate_url),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == '__main__':
    main()
