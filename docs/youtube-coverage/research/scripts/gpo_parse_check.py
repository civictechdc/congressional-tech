"""
Check the GPO print parser on prints from both chambers and several eras.

    python docs/youtube-coverage/research/scripts/gpo_parse_check.py

For each of nine prints it fetches the text, parses it with `congress_api.transcribe.gpo_parse`,
and prints one line: speaker turns, words captured against the file's words, the convening and
adjournment times, the presiding member, members present, distinct speakers, inserts, and any
speaker name that looks like a heading or a bare title. Exits non-zero if a print yields no
turns, loses more than 30% of its words, or produces an odd speaker name.
"""
import collections
import csv
import html
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src"))
from congress_api.models.transcription import Header
from congress_api.parsers.gpo_text import parse_gpo_text
from congress_api.transcripts.context import mods_people

PRINTS = {"house_2008": "CHRG-110hhrg46592", "house_2013": "CHRG-113hhrg88542", "house_2019": "CHRG-116hhrg38145", "judiciary_2023": "CHRG-118hhrg54254",
          "approps_volume": "CHRG-118hhrg54343", "senate_2014": "CHRG-113shrg92444", "senate_2019": "CHRG-116shrg39977", "senate_2024": "CHRG-118shrg55877", "jec_2017": "CHRG-115jhrg25919"}
ODD = re.compile(r"^(mr|ms|mrs|dr|chairman|the|statement|after|prepared)\b", re.I)


def main():
    rows = {r["package_id"]: r for r in csv.DictReader(open(ROOT / "apps/committee_youtube/data/gpo_hearings.csv"))}
    bad = 0
    for label, pkg in PRINTS.items():
        row = rows[pkg]
        try:
            people, facts = mods_people(pkg)
        except Exception:
            people, facts = {}, {"title": row["title"], "committee": "", "committee_code": row["committee_code"], "subcommittee": "", "held_date": row["held_date"], "serial": "", "congress": row["congress"], "session": ""}
        text = html.unescape(re.sub(r"<[^>]+>", "", requests.get(row["html_url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text))
        header = Header(title=facts["title"], chamber=row["chamber"], congress=int(row["congress"]), committee=facts["committee"], committee_code=facts["committee_code"], subcommittee=facts["subcommittee"], date=row["held_date"], package_id=pkg)
        t = parse_gpo_text(text, header, people, source_url=row["html_url"])
        spoken = [u for u in t.turns if u.kind != "direction"]
        words = sum(len(u.text.split()) for u in spoken); total = len(text.split())
        speakers = collections.Counter(t.participants[u.speaker].name if u.speaker in t.participants else u.speaker for u in spoken)
        odd = [n for n in speakers if ODD.match(n) or len(n.split()) > 4]
        presiding = t.participants[t.header.presiding].name if t.header.presiding in t.participants else "-"
        ok = spoken and words / total >= 0.7 and not odd
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label:15} {pkg}: turns {len(spoken):4} words {words:6}/{total:6} ({words / total:.0%}) | convened {t.header.time_convened or '-':9} adjourned {t.header.time_adjourned or '-':9} | presiding {presiding:22} present {len(t.header.present):2} | speakers {len(speakers):2}: {', '.join(n for n, _ in speakers.most_common(4))[:60]} | inserts {len(t.inserts)}" + (f" | ODD {odd}" if odd else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
