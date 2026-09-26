"""
Download official GPO hearing transcripts as plain text, for search or summaries.

    gpo-transcripts --out-dir ~/transcripts --congress 118 --committee hsvr00
    gpo-transcripts --out-dir ~/transcripts --package-ids CHRG-118hhrg57177 CHRG-118hhrg57178

Reads hearing links from gpo_hearings.csv (see gpo-fetch) and writes one
<package_id>.txt per hearing. Files already downloaded are skipped, so the
command can be re-run to top up. Transcripts are large (all House and joint
hearings since 2013 are about 2 GB), so they are meant for a local folder, not
the repository.

About 1 in 4 multi-hearing Appropriations volumes are scanned PDFs with no
text on GovInfo; those are reported and skipped.
"""
import argparse
import csv
import html
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE
from congress_api.gpo.fetch import get_with_retry

MIN_TEXT_CHARS = 10000  # shorter pages are title pages only (scanned PDF packages, errata)


def to_text(page: str) -> str:
    """GPO transcript HTML is one <pre> block; strip tags and entities."""
    return html.unescape(re.sub(r"<[^>]+>", "", page)).strip() + "\n"


def main(out_dir, gpo_path, congress=None, committee=None, chamber=None, package_ids=None, nthreads=4):
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(gpo_path)))
    if package_ids:
        wanted = set(package_ids)
        rows = [r for r in rows if r["package_id"] in wanted]
    if congress:
        rows = [r for r in rows if int(r["congress"]) in congress]
    if committee:
        rows = [r for r in rows if r["committee_code"] in committee]
    if chamber:
        rows = [r for r in rows if r["chamber"] in chamber]
    todo = [r for r in rows if not (out_dir / f"{r['package_id']}.txt").exists()]
    logging.info(f"{len(rows)} hearings selected, {len(rows) - len(todo)} already downloaded, fetching {len(todo)}")

    session = requests.Session()
    no_text, failures = [], []

    def fetch(row):
        try:
            text = to_text(get_with_retry(session, row["html_url"]).text)
            if len(text) < MIN_TEXT_CHARS:
                no_text.append(row["package_id"])
                return
            (out_dir / f"{row['package_id']}.txt").write_text(text, encoding="utf-8")
        except Exception as ex:
            failures.append(f"{row['package_id']}: {ex!r}")

    with ThreadPoolExecutor(nthreads) as pool:
        list(pool.map(fetch, todo))

    if no_text:
        logging.warning(f"{len(no_text)} package(s) have only a title page on GovInfo (scanned PDF or errata): {', '.join(no_text[:20])}")
    if failures:
        logging.error(f"{len(failures)} download(s) failed:\n  " + "\n  ".join(failures[:50]))
        sys.exit(1)
    logging.info(f"Transcripts are in {out_dir}")


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Download GPO hearing transcripts as plain text.")
    parser.add_argument("--out-dir", required=True, help="Local folder for <package_id>.txt files.")
    parser.add_argument("--gpo-path", type=Path, default=DEFAULT_GPO_HEARINGS_FILE)
    parser.add_argument("--congress", type=int, nargs="*", help="Only these congresses, e.g. 118 119.")
    parser.add_argument("--committee", nargs="*", help="Only these committee codes, e.g. hsvr00.")
    parser.add_argument("--chamber", nargs="*", choices=["house", "senate", "joint"])
    parser.add_argument("--package-ids", nargs="*")
    parser.add_argument("--nthreads", type=int, default=4)
    args = parser.parse_known_args()[0]
    main(args.out_dir, args.gpo_path, args.congress, args.committee, args.chamber, args.package_ids, args.nthreads)


if __name__ == "__main__":
    parse_args_and_run()
