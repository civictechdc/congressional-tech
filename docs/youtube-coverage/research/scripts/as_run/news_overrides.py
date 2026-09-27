"""
Write the news-channel search's accepted finds into hearing_video_overrides.csv (September 2026).

    python news_overrides.py <scratch>   # scratch holds news_candidates.json, for the channel handles

The 26 date-confirmed hearings in news_search_confirmed.csv were reviewed by hand; the accepted
package IDs, their videos and the reason for each are the `accepted` list below (the committed
record of the review is agent_results/news_search_review_decisions.json). Rows replace the
research verdict for the same hearing, keeping the old verdict in the note. Nine volumes of the
2019 impeachment markup get the recordings of volume V, whose wrong GPO date had reserved them
(the archive review later set the document-only volumes not_public).
"""
import csv, json, sys

S = sys.argv[1]
handle = {c["videoId"]: c["channel"] for h in json.load(open(f"{S}/news_candidates.json")) for c in h["candidates"]}
path = "apps/committee_youtube/data/hearing_video_overrides.csv"
rows = list(csv.DictReader(open(path))); cols = list(rows[0].keys()); ov = {r["package_id"]: r for r in rows}
imp = ov["CHRG-116hhrg39405"]
accepted = [
    ("CHRG-113jhrg95506", "GMW7q6aL0Qk", "Sen. Cardin's channel has the full briefing 'The Trajectory of Democracy: Why Hungary Matters' (2:33), posted the day it was held, witnesses in the description."),
    ("CHRG-113jhrg82471", "PYufnOixR1E", "UC Berkeley Haas posted the hearing (1:10) the next day as 'Prof. Laura Tyson: Lessons from Reagan...'; description dates it July 31, 2013 and says the video begins partway in."),
    ("CHRG-113hhrg82994", "lu-Ji8AeE2g", "Witness organization HCM Strategists posted the hearing (2:03) as 'Kristin D. Hultquist Testifies on Simplifying Federal Student Aid - House Committee Hearing (2013)'; its description misnames the committee as Senate HELP."),
    ("CHRG-113hhrg87497", "tzk8eKzro9U", "Roll Call's 'Full House Judiciary Committee U.S. Department of Justice Oversight Hearing' (3:35), Attorney General Holder, April 8, 2014."),
    ("CHRG-113hhrg87518", "jmBzqRDKfXE", "FAR MAROC posted the subcommittee hearing 'U.S. Policy Toward Morocco' (1:07) the next day, witnesses named in the description."),
    ("CHRG-114hhrg92556", "LC-fFl5wvkg", "A third-party upload of C-SPAN's coverage of the hearing (2:38), 'January 13, 2015 C-SPAN' in the description."),
    ("CHRG-114hhrg94691", "rfdklOV9lyo", "Save the Congo! posted 'US Policy Toward Rwanda - Congressional Hearing held on May 20, 2015' (2:22), the Africa subcommittee hearing."),
    ("CHRG-115hhrg33410", "ap6kEao6dbA", "The Royal Examiner (Front Royal, VA) posted the field hearing at the ATF canine center (45 min), the day it was held."),
    ("CHRG-116hhrg36878", "kOvYFjru3Cg uB8iniHd5x4", "'Defense Officials Testify on FY 2020 Budget Request' parts 1/2 and 2/2 (2:29 + 1:12), Shanahan and Dunford before HASC, March 26, 2019, on a DoD video archive channel."),
    ("CHRG-117hhrg44926", "GD4QV1vIfZw", "A government-contracting YouTuber's copy of the hearing (1:13), posted the next day under the hearing's title. Medium confidence."),
    ("CHRG-117hhrg45515", "mFDT2ROSqP0", "The Hill's 'House Homeland Security Committee holds hearing examining FEMA readiness' (2:37), the day of the virtual hearing."),
    ("CHRG-117hhrg45383", "HKMzwjqbN_Q", "Forbes Breaking News posted the subcommittee hearing (1:29) under its exact title the next day."),
    ("CHRG-117hhrg46009", "On4xDO-skWw kLvyAGhSpL8", "The Hill (2:18) and Reuters (2:19) livestreamed Yellen and Powell before the committee, September 30, 2021."),
    ("CHRG-118hhrg61961", "STyMT2gOkxk", "The Union Herald posted the MilCon-VA subcommittee hearing on the VHA FY2025 shortfall (1:38) the next day."),
]
new_rows = [(pid, "found_untracked", vids, " ".join(handle.get(v, "") for v in vids.split()).strip(), f"News-channel search (Sept 2026): {why}") for pid, vids, why in accepted]
new_rows += [(pid, "found_tracked", imp["video_ids"], imp["channel"], "Volume of the H. Res. 755 markup (Dec 11-13, 2019); same recordings as CHRG-116hhrg39405, whose wrong GPO date had reserved the videos for another day.")
             for pid in ("CHRG-116hhrg39401", "CHRG-116hhrg39402", "CHRG-116hhrg39403", "CHRG-116hhrg39404", "CHRG-116hhrg39406", "CHRG-116hhrg39407", "CHRG-116hhrg39408", "CHRG-116hhrg39409", "CHRG-116hhrg39411")]
for pid, verdict, vids, ch, note in new_rows:
    prev = ov.get(pid)
    if prev:
        note = f"{note} (research verdict was {prev['verdict']}: {prev['note'][:160]})" if prev["note"] else note
        prev.update(verdict=verdict, video_ids=vids, channel=ch, lock="", note=note)
    else:
        rows.append({"package_id": pid, "verdict": verdict, "video_ids": vids, "channel": ch, "lock": "", "note": note})
with open(path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(len(new_rows), "rows written")
