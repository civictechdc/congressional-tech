"""Retain Congress-scoped committee lists plus full committee details and history."""
import argparse
import csv
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests

from congress_shared.auth import load_congress_api_key
from .meetings import API, get, read, write
from .models.congress import CommitteeDetail, CommitteeRecord, CommitteeSnapshot
from .retention.rejected_pages import retain_rejected_page


def detail_url(committee):
    """Use the publisher's committee endpoint without query credentials."""
    url = urlsplit(committee.get('url') or '')
    expected = rf'/v3/committee/(house|senate|joint)/{re.escape(committee["systemCode"])}'
    if url.scheme != 'https' or url.netloc != 'api.congress.gov' or not re.fullmatch(expected, url.path):
        raise ValueError(f'Invalid committee detail URL for {committee["systemCode"]}')
    return f'https://api.congress.gov{url.path}'


def collect(meetings_path, output_path, *, api_key, session=None, gpo_path=None):
    congresses = {int(row['congress']) for row in read(meetings_path).values()}
    if gpo_path:
        with Path(gpo_path).open(newline='') as stream:
            congresses.update(int(row['congress']) for row in csv.DictReader(stream) if row.get('congress'))
    congresses = sorted(congresses)
    if not congresses:
        raise ValueError('The retained meeting and document inputs have no Congresses')
    output = Path(output_path)
    existing = []
    if output.exists():
        with gzip.open(output, 'rt') as stream:
            existing = [CommitteeSnapshot.model_validate_json(line).source_dict() for line in stream if line.strip()]
    have = {row['congress'] for row in existing}
    refresh = set(congresses[-2:]) | (set(congresses) - have)
    rows = {f"{row['congress']}|{row['committee']['systemCode']}": row for row in existing if row['congress'] not in refresh}
    session = session or requests.Session()
    for congress in sorted(refresh):
        url, offset, count = f'{API}/committee/{congress}', 0, 0
        seen_codes = set()
        while True:
            page = get(session, url, api_key, {'limit': 250, 'offset': offset})
            retrieved = datetime.now(timezone.utc).isoformat()
            try:
                committees = [CommitteeRecord.model_validate(native).source_dict() for native in page['committees']]
                for committee in committees:
                    detail_url(committee)
            except (ValueError, TypeError, KeyError):
                retain_rejected_page(output_path, page, url=url, offset=offset)
                raise
            for committee in committees:
                code = committee['systemCode']
                if code in seen_codes:
                    raise ValueError(f'Duplicate committee {congress}/{code}; retained snapshot was not replaced')
                seen_codes.add(code)
                rows[f'{congress}|{code}'] = dict(congress=congress, committee=committee, _url=url, retrieved_at=retrieved)
            count += len(committees)
            if not page.get('pagination', {}).get('next'):
                break
            if not committees:
                raise ValueError(f'Committee pagination did not advance for Congress {congress}')
            offset += len(committees)
        if not count:
            raise ValueError(f'No committee metadata returned for Congress {congress}; retained snapshot was not replaced')
        print(f'Congress {congress}: {count} committee records', flush=True)
    # The detail endpoint has no Congress parameter. Fetch once per endpoint,
    # retain its own observation time, and never apply its current status/type
    # to historical Congress-specific list values.
    details = {row['detail_url']: {key: row[key] for key in ('detail', 'detail_url', 'detail_retrieved_at')}
               for row in existing if row.get('detail') is not None and row.get('detail_url') and row.get('detail_retrieved_at')}
    refresh_details = {detail_url(row['committee']) for row in rows.values() if row['congress'] in refresh}
    observed = {}
    for row in rows.values():
        url = detail_url(row['committee'])
        if url not in observed:
            if url in details and url not in refresh_details:
                observed[url] = details[url]
            else:
                response = get(session, url, api_key)
                try:
                    detail = CommitteeDetail.model_validate(response['committee']).source_dict()
                    if detail['systemCode'] != row['committee']['systemCode']:
                        raise ValueError('Committee detail identity does not match its listing')
                except (ValueError, TypeError, KeyError):
                    retain_rejected_page(output_path, response, url=url, offset=0)
                    raise
                observed[url] = dict(detail=detail, detail_url=url, detail_retrieved_at=datetime.now(timezone.utc).isoformat())
        row.update(observed[url])
    write(rows, output)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meetings-path', type=Path, required=True)
    parser.add_argument('--gpo-path', type=Path, help='Include Congresses represented by retained GPO documents')
    parser.add_argument('--output-path', type=Path, required=True)
    args = parser.parse_args()
    collect(**vars(args), api_key=load_congress_api_key())


def parse_args_and_run():
    """Console entry point; preserve main() for existing callers."""
    return main()


if __name__ == '__main__':
    main()
