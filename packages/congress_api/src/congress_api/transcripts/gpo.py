"""
Download official GPO hearing transcripts as plain text, for search or summaries.

    gpo-transcripts --out-dir ~/transcripts --congress 118 --committee hsvr00
    gpo-transcripts --out-dir ~/transcripts --package-ids CHRG-118hhrg57177 CHRG-118hhrg57178

Reads hearing links from gpo_hearings.csv (see gpo-fetch) and writes one
<package_id>.txt per hearing. Files already downloaded are skipped, so the
command can be re-run to top up. Transcripts are large (all House and joint
hearings since 2013 are about 2 GB), so they are meant for a local folder, not
the repository.

New requests retain the original HTML and retrieval details in
source/<package_id>.json, including short responses excluded from plain text.
Existing text-only files are skipped without inventing their original HTML.

About 1 in 4 multi-hearing Appropriations volumes are scanned PDFs with no
text on GovInfo; those are reported and skipped.
"""

import csv
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

from congress_api.models.gpo import GpoEvidenceObservation
from congress_api.parsers.gpo import parse_transcript_html
from congress_api.parsers.gpo_text import has_proceeding_text
from congress_api.retention.gpo import write_observation
from congress_api.transport.http import get_with_retry

MIN_TEXT_CHARS = 10000


def main(out_dir, gpo_path, congress=None, committee=None, chamber=None, package_ids=None, nthreads=4):
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(gpo_path) as stream:
        rows = list(csv.DictReader(stream))
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
            response = get_with_retry(session, row["html_url"])
            source = parse_transcript_html(response.content, decoded_text=response.text)
            write_observation(GpoEvidenceObservation(**source.source.source_dict(),
                url=row['html_url'], retrieved_at=datetime.now(timezone.utc).isoformat(), acquisition='http'),
                out_dir / 'source' / f"{row['package_id']}.json")
            text = source.text.strip() + "\n"
            if len(text) < MIN_TEXT_CHARS and not has_proceeding_text(text):
                no_text.append(row["package_id"])
                return
            path = out_dir / f"{row['package_id']}.txt"
            temporary = path.with_suffix(path.suffix + '.tmp')
            try:
                temporary.write_text(text, encoding="utf-8")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except Exception as ex:
            failures.append(f"{row['package_id']}: {ex!r}")

    with ThreadPoolExecutor(nthreads) as pool:
        list(pool.map(fetch, todo))

    if no_text:
        logging.warning(f"{len(no_text)} short page(s) have no confirmed proceeding text; original HTML retained: {', '.join(no_text[:20])}")
    if failures:
        logging.error(f"{len(failures)} download(s) failed:\n  " + "\n  ".join(failures[:50]))
        sys.exit(1)
    logging.info(f"Transcripts are in {out_dir}")
