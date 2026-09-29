"""Retain the official Congress-scoped committee lists used by the Explorer."""
import argparse
import csv
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

import requests

from congress_shared.auth import load_congress_api_key
from .meetings import API, get, read, write
from .models.congress import CommitteeRecord, CommitteeSnapshot
from .fetch.rejected import retain_rejected_page


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
    write(rows, output)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meetings-path', type=Path, required=True)
    parser.add_argument('--gpo-path', type=Path, help='Include Congresses represented by retained GPO documents')
    parser.add_argument('--output-path', type=Path, required=True)
    args = parser.parse_args()
    collect(**vars(args), api_key=load_congress_api_key())


if __name__ == '__main__':
    main()
