"""Fetch named public archive bodies into a scratch root the lake producers read as `local_root`.

    fetch_public_bodies.py --work-list candidates.parquet --root SCRATCH [--threads 8]

Each body's SHA-256 is verified against its name. Bounded by the candidate list; never writes remotely.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pyarrow.parquet as pq

BASE = 'https://congressional-data.spicygov.ai/'
AGENT = 'congressional-tech-measure/1'  # The CDN refuses Python's default agent.


def relative_paths(sha, suffix):
    named = f'bodies/sha256/{sha[:2]}/{sha}'
    return [named + value for value in dict.fromkeys([suffix or '', '.gz', ''])]


def original_bytes(data, relative):
    return gzip.decompress(data) if relative.endswith('.gz') else data


def fetch(root, sha, suffix, *, opener=urlopen):
    """Return bytes on disk for one body, or raise when no spelling verifies."""
    for relative in relative_paths(sha, suffix):
        target = Path(root) / relative
        if target.is_file():
            return target.stat().st_size
    for relative in relative_paths(sha, suffix):
        try:
            with opener(Request(BASE + relative, headers={'User-Agent': AGENT}), timeout=120) as response:
                data = response.read()
        except HTTPError as error:
            if error.code in (403, 404):
                continue
            raise
        if sha256(original_bytes(data, relative)).hexdigest() != sha:
            raise ValueError(f'Body failed verification: {relative}')
        target = Path(root) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.partial')
        partial.write_bytes(data)
        partial.replace(target)
        return len(data)
    raise FileNotFoundError(sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-list', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=8)
    args = parser.parse_args()
    items = pq.read_table(args.work_list, columns=['record_sha', 'stored_suffix']).to_pylist()
    with ThreadPoolExecutor(args.threads) as pool:
        sizes = list(pool.map(lambda item: fetch(args.root, item['record_sha'], item['stored_suffix']), items))
    print(f'{len(sizes)} bodies, {sum(sizes)} bytes on disk')


if __name__ == '__main__':
    main()
