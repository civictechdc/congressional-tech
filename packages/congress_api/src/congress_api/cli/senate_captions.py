"""
Download the captions of Senate hearing recordings from the Senate's own player, as plain text.

    senate-captions --out-dir ~/hearing-text/senate --urls "https://www.senate.gov/isvp/?comm=epw&filename=epw120623" ...
    senate-captions --out-dir ~/hearing-text/senate --urls-file links.txt

Recordings since about mid-2023 commonly carry an English WebVTT subtitle track;
both live and archive paths can provide one. Its segments are fetched concurrently
and joined into <filename>.txt. Older recordings may carry captions only inside
the video stream, which this tool doesn't decode. Absence from both WebVTT paths is recorded as
`none`; failed or incomplete checks are not indexed. Appends to <out-dir>/captions_index.csv:
filename, comm, kind (webvtt | none), characters. Current complete captures are skipped;
legacy entries without retained timing are rechecked when requested. Playlist and
segment text is retained in <filename>.captions.json.gz.
New checks also write caption_receipts/<record-key>.json with their observation
time and exact scope. Legacy index rows without receipts retain unknown check times.
"""

import argparse
import logging
import sys
from pathlib import Path

from congress_api.cli.common import positive
from congress_api.transcripts.senate import main


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Download Senate hearing captions from senate.gov as plain text.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--urls", nargs="*", default=[], help="Player URLs (senate.gov/isvp/?comm=...&filename=...).")
    parser.add_argument("--urls-file", type=Path, help="Text file with one player URL per line.")
    parser.add_argument("--nthreads", type=positive, default=4)
    args = parser.parse_args()
    urls = list(args.urls) + ([l.strip() for l in args.urls_file.read_text().splitlines() if l.strip()] if args.urls_file else [])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s : %(message)s")
    if not urls:
        sys.exit("No player URLs given.")
    main(args.out_dir, urls, args.nthreads)


if __name__ == "__main__":
    parse_args_and_run()
