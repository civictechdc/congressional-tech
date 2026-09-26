"""
Rewrite the generated tables in docs/youtube-coverage/findings.md from the weekly matcher's output.

    python docs/youtube-coverage/research/scripts/findings_tables.py

Each table sits between `<!-- table:NAME -->` and `<!-- /table:NAME -->` markers. The prose around
them is written by hand; only the marked blocks change.
"""
import collections, csv, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DOC = ROOT / "docs/youtube-coverage/findings.md"
VIDEOS = ROOT / "apps/committee_youtube/data/gpo_hearing_videos.csv"
GPO = ROOT / "apps/committee_youtube/data/gpo_hearings.csv"
CHANNELS = ROOT / "packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv"
YEARS = {"113": "2013–14", "114": "2015–16", "115": "2017–18", "116": "2019–20", "117": "2021–22", "118": "2023–24", "119": "2025–"}
FULL = ("full_recording", "full_recording_offsite")


def pct(n, d):
    return f"{n / d:.1%}" if d else "—"


def summary(rows, tracked, member):
    n = len(rows)
    c = collections.Counter()
    for r in rows:
        chs = {x.lower() for x in r["channels"].split()}
        if r["status"] == "full_recording":
            c["tracked" if chs & tracked else "member" if chs & member else "other"] += 1
        else:
            c[r["status"]] += 1
    lines = [("Full recording on a tracked committee channel", c["tracked"]),
             ("Full recording only on another YouTube channel (member, news, third party)", c["member"] + c["other"]),
             ("Full recording off YouTube (C-SPAN, an archive, another site)", c["full_recording_offsite"]),
             ("Only clips or opening statements on YouTube", c["clips_only"]),
             ("Never public video (closed session, written-only volume, errata)", c["not_public"]),
             ("No video found", c["no_video_found"]),
             ("Held before the committee's earliest tracked video", c["before_channel"]),
             ("Committee has no YouTube channel", c["committee_not_tracked"])]
    out = ["| Outcome | Hearings | Share |", "|---|---|---|"]
    out += [f"| {k} | {v:,} | {pct(v, n)} |" for k, v in lines if v]
    return out


def by_congress(rows, extra_cols):
    out = ["| Congress | Years | Hearings | Full recording | Clips only | Not public | None found |" + "".join(f" {c} |" for c, _ in extra_cols) + " Found |",
           "|---|---|---|---|---|---|---|" + "---|" * len(extra_cols) + "---|"]
    for cg in sorted({r["congress"] for r in rows}, key=int):
        rs = [r for r in rows if r["congress"] == cg]
        c = collections.Counter(r["status"] for r in rs)
        found = sum(c[s] for s in FULL)
        out.append(f"| {cg}th | {YEARS.get(cg, '')} | {len(rs):,} | {found:,} | {c['clips_only']:,} | {c['not_public']:,} | {c['no_video_found']:,} |"
                   + "".join(f" {c[s]:,} |" for _, s in extra_cols) + f" {pct(found, len(rs))} |")
    return out


def by_committee(rows, name_of, extra_cols, min_n=5):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[name_of(r)].append(r)
    table = []
    for name, rs in groups.items():
        if len(rs) < min_n:
            continue
        c = collections.Counter(r["status"] for r in rs)
        found = sum(c[s] for s in FULL)
        since = [r for r in rs if int(r["congress"]) >= 116]
        f19 = sum(1 for r in since if r["status"] in FULL)
        table.append((found / len(rs), name, len(rs), found, c, f"{f19 / len(since):.0%} of {len(since)}" if since else "—"))
    out = ["| Committee | Hearings | Full recording | Clips only | Not public | None found |" + "".join(f" {c} |" for c, _ in extra_cols) + " Found | Found since 2019 |",
           "|---|---|---|---|---|---|" + "---|" * len(extra_cols) + "---|---|"]
    for share, name, n, found, c, s19 in sorted(table, key=lambda t: (t[0], t[1])):
        out.append(f"| {name} | {n:,} | {found:,} | {c['clips_only']:,} | {c['not_public']:,} | {c['no_video_found']:,} |"
                   + "".join(f" {c[s]:,} |" for _, s in extra_cols) + f" {share:.0%} | {s19} |")
    return out


def main():
    channels = list(csv.DictReader(open(CHANNELS)))
    names = {c["systemCode"]: c["committee"] for c in channels}
    tracked = {h.lower() for c in channels for h in [c["handle"]] + c["secondary"].split(";") if h.strip()}
    member = {h.lower() for c in channels for h in (c.get("member_channels") or "").split(";") if h.strip()}
    gpo_names = {r["package_id"]: r["committee_name"] for r in csv.DictReader(open(GPO))}
    rows = [r for r in csv.DictReader(open(VIDEOS)) if int(r["congress"]) >= 113]
    hj = [r for r in rows if r["chamber"] != "senate"]
    sen = [r for r in rows if r["chamber"] == "senate"]
    house_name = lambda r: {"ssva00": "Senate Veterans' Affairs (House hearings, miscoded)"}.get(r["committee_code"]) or names.get(r["committee_code"]) or "(no committee code in GPO data)"
    senate_name = lambda r: {"hsvr00": "Veterans' Affairs (joint hearings, House code)", "ssva00": "Veterans' Affairs (Senate)"}.get(r["committee_code"]) or (
        names.get(r["committee_code"], "").replace("Senate ", "") or gpo_names.get(r["package_id"], "").replace("Committee on ", "") or "(no committee code in GPO data)")
    senate_cols = [("Before channel", "before_channel"), ("No channel", "committee_not_tracked")]
    tables = {
        "house_summary": summary(hj, tracked, member),
        "senate_summary": summary(sen, tracked, member),
        "house_congress": by_congress(hj, []),
        "house_committee": by_committee(hj, house_name, []),
        "senate_congress": by_congress(sen, senate_cols),
        "senate_committee": by_committee(sen, senate_name, senate_cols),
    }
    text = DOC.read_text()
    for name, lines in tables.items():
        pat = re.compile(rf"(<!-- table:{name} -->\n).*?(\n<!-- /table:{name} -->)", re.S)
        assert pat.search(text), f"no markers for {name}"
        text = pat.sub(lambda m: m.group(1) + "\n".join(lines) + m.group(2), text)
    DOC.write_text(text)
    hj_full = sum(1 for r in hj if r["status"] in FULL); since = [r for r in hj if int(r["congress"]) >= 116]
    print(f"house/joint {len(hj):,}: found {pct(hj_full, len(hj))}, since 2019 {pct(sum(1 for r in since if r['status'] in FULL), len(since))}, none since 2019 {sum(1 for r in since if r['status']=='no_video_found')}")
    sen_full = sum(1 for r in sen if r["status"] in FULL); ssince = [r for r in sen if int(r["congress"]) >= 116]
    print(f"senate {len(sen):,}: found {pct(sen_full, len(sen))}, since 2019 {pct(sum(1 for r in ssince if r['status'] in FULL), len(ssince))}")


if __name__ == "__main__":
    main()
