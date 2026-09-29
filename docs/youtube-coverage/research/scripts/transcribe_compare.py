"""
Compare two ways of transcribing a hearing against its GPO print.

    python docs/youtube-coverage/research/scripts/transcribe_compare.py CHRG-118hhrg54254 8V3OGbZOLB0 <out_dir>

Scores the package's route (Gemini 3.8 Flash on the YouTube video in 25-minute windows,
named turns) against the print: word error rate of the spoken text (jiwer), speaker
attribution on aligned words, turn counts, time and tokens. Writes gpo.json, routeB.json
and compare.json. The September 2026 run also included "route A", Gemini 3.5 Transcribe on
the audio plus a speaker resolver; its outputs are kept as routeA_*.json in
research/data/transcribe_compare/ but that code was removed from the package after it
lost on attribution (66-74% against 85%). Needs `pip install jiwer`.
"""
import csv, html, json, os, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src")); sys.path.insert(0, str(ROOT / "packages/youtube_api/src"))
import jiwer
import requests
from congress_api.transcribe import gemini as G
from congress_api.transcribe.gpo_parse import parse_gpo_text
from congress_api.transcribe.metadata import context_for_event, mods_people
from congress_api.transcribe.schema import Header, Person, Transcript, Turn, Source, person_key

WINDOW = 25 * 60


def norm(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("’", "'"))
    return re.sub(r"\s+", " ", text).strip()


def spoken_text(t: Transcript) -> str:
    return " ".join(u.text for u in t.turns if u.kind != "direction")


def shares(t: Transcript) -> dict:
    counts = {}
    for u in t.turns:
        if u.kind == "direction": continue
        p = t.participants.get(u.speaker); name = (p.surname or p.name) if p else u.speaker
        counts[name] = counts.get(name, 0) + len(u.text.split())
    total = sum(counts.values()) or 1
    return {k: round(v / total, 3) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}


def roster_json(participants):
    return [{k: v for k, v in p.model_dump(mode="json").items() if v and k not in ("speaker_label", "confidence", "honorific")} for p in participants.values()]


def main(package_id, video_id, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rows = {r["package_id"]: r for r in csv.DictReader(open(ROOT / "apps/committee_youtube/data/gpo_hearings.csv"))}
    row = rows[package_id]
    ## ground truth: the print
    people, facts = mods_people(package_id)
    header = Header(title=facts["title"], chamber=row["chamber"], congress=int(facts["congress"]), session=int(facts["session"] or 0) or None, committee=facts["committee"], committee_code=facts["committee_code"], subcommittee=facts["subcommittee"], date=facts["held_date"], serial=facts["serial"], package_id=package_id, event_id=row["event_id"])
    text = html.unescape(re.sub(r"<[^>]+>", "", requests.get(row["html_url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text))
    gpo = parse_gpo_text(text, header, people, source_url=row["html_url"])
    (out / "gpo.json").write_text(gpo.to_json())
    ctx = context_for_event(row["event_id"], package_id=package_id) if row["event_id"] else None
    participants = dict(gpo.participants); participants.update({k: v for k, v in (ctx.participants if ctx else {}).items() if k not in participants})
    roster = roster_json(participants)
    meeting = {"title": header.title, "committee": header.committee, "subcommittee": header.subcommittee, "date": header.date, "chamber": header.chamber}
    print(f"GPO print: {len(gpo.turns)} turns, {len(spoken_text(gpo).split())} words, speakers {list(shares(gpo))[:8]}")
    results = {"gpo": {"turns": len(gpo.turns), "words": len(spoken_text(gpo).split()), "shares": shares(gpo)}}
    ## route B
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        dur = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)["duration"]
    t0 = time.time(); B_turns, usage = [], {"in": 0, "out": 0}
    for start in range(0, int(dur), WINDOW):
        d = G.transcribe_window(roster, meeting, start, min(start + WINDOW, dur), youtube_id=video_id)
        B_turns += d.get("turns", []); usage["in"] += d.get("usage", {}).get("in", 0) or 0; usage["out"] += d.get("usage", {}).get("out", 0) or 0
        print(f"  B: window @{start}s -> {len(d.get('turns', []))} turns")
    tb = time.time() - t0
    B_participants, turns = {}, []
    for u in B_turns:
        k = person_key(u["speaker"]) if u["speaker"] != "Unknown" else "unknown"
        if k not in B_participants:
            base = participants.get(k) or Person(name=u["speaker"], role=u.get("role", "unknown")); B_participants[k] = base.model_copy(update={"confidence": u.get("confidence")})
        turns.append(Turn(speaker=k, text=u["text"], start=u.get("start"), end=u.get("end")))
    routeB = Transcript(header=header.model_copy(update={"package_id": ""}), participants=B_participants, turns=turns, source=Source(kind="gemini_transcription", video_id=video_id, model=G.MODEL + " (video)", notes=f"{tb:.0f}s, tokens {usage}"))
    (out / "routeB.json").write_text(routeB.to_json())
    ## scores
    ref = norm(spoken_text(gpo))
    for name, t in (("B", routeB),):
        hyp = norm(spoken_text(t))
        results[name] = {"turns": len(t.turns), "words": len(hyp.split()), "wer": round(jiwer.wer(ref, hyp), 3), "shares": shares(t), "speakers_named": sum(1 for p in t.participants.values() if p.name != "Unknown"), "unknown_word_share": round(sum(len(u.text.split()) for u in t.turns if u.speaker == "unknown") / max(1, len(hyp.split())), 3), "time_s": t.source.notes}
    (out / "compare.json").write_text(json.dumps(results, indent=1))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "shares"} for k, v in results.items()}, indent=1))
    for k in ("gpo", "B"):
        print(k, "top speakers:", dict(list(results[k]["shares"].items())[:7]))


if __name__ == "__main__":
    main(*sys.argv[1:4])
