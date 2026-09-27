"""
Compare two ways of transcribing a hearing against its GPO print.

    python docs/youtube-coverage/research/scripts/transcribe_compare.py CHRG-118hhrg54254 8V3OGbZOLB0 <out_dir> [--proxy URL]

Route A: Gemini 3.5 Transcribe on the recording's audio (25-minute chunks, diarization, word
timestamps), then Gemini 3.8 Flash maps the speaker labels to people using the roster,
witness list and the video. Route B: Gemini 3.8 Flash watches the YouTube video directly in
25-minute windows and returns named turns in the same schema. Both are scored against the
print: word error rate of the spoken text (jiwer), each speaker's share of words, turn
counts, time and tokens. Writes gpo.json, routeA.json, routeB.json and compare.json.
"""
import csv, dataclasses, html, json, os, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src")); sys.path.insert(0, str(ROOT / "packages/youtube_api/src"))
import jiwer
import requests
from congress_api.transcribe import audio as A, gemini as G
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
    return [{k: v for k, v in dataclasses.asdict(p).items() if v and k not in ("speaker_label", "confidence", "honorific")} for p in participants.values()]


def main(package_id, video_id, out_dir, proxy=None):
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
    ## route A
    t0 = time.time(); audio = A.get_audio(out / "audio", video_id=video_id, proxy=proxy); dl = time.time() - t0
    parts = A.chunks(audio, minutes=25, overlap=5); t0 = time.time(); chunked = []
    for path, offset in parts:
        utts = G.transcribe_chunk(path, offset); chunked.append((utts, offset, offset + A.duration(path)))
        print(f"  A: chunk @{offset:.0f}s -> {len(utts)} utterances, {sum(len(u['words']) for u in utts)} words")
    utts = G.stitch(chunked); ta = time.time() - t0
    t0 = time.time(); res = G.resolve_speakers(utts, roster, meeting, youtube_id=video_id); tr = time.time() - t0
    mapping = {s["label"]: s for s in res.get("speakers", [])}
    A_participants, turns = {}, []
    for u in utts:
        s = mapping.get(u["speaker_label"], {"name": "Unknown", "role": "unknown", "confidence": 0})
        k = person_key(s["name"]) if s["name"] != "Unknown" else u["speaker_label"]
        if k not in A_participants:
            base = participants.get(k) or Person(name=s["name"], role=s["role"]); A_participants[k] = dataclasses.replace(base, speaker_label=u["speaker_label"], confidence=s.get("confidence"))
        turns.append(Turn(speaker=k, text=u["text"], start=u["start"], end=u["end"]))
    routeA = Transcript(header=dataclasses.replace(header, package_id=""), participants=A_participants, turns=turns, source=Source(kind="gemini_transcription", video_id=video_id, model=f"{G.TRANSCRIBE_MODEL} + {G.RESOLVER_MODEL}", notes=f"download {dl:.0f}s, transcribe {ta:.0f}s, resolve {tr:.0f}s"))
    (out / "routeA.json").write_text(routeA.to_json())
    ## route B
    dur = A.duration(audio); t0 = time.time(); B_turns, usage = [], {"in": 0, "out": 0}
    for start in range(0, int(dur), WINDOW):
        d = G.transcribe_video_window(video_id, start, min(start + WINDOW, dur), roster, meeting)
        B_turns += d.get("turns", []); usage["in"] += d.get("usage", {}).get("in", 0) or 0; usage["out"] += d.get("usage", {}).get("out", 0) or 0
        print(f"  B: window @{start}s -> {len(d.get('turns', []))} turns")
    tb = time.time() - t0
    B_participants, turns = {}, []
    for u in B_turns:
        k = person_key(u["speaker"]) if u["speaker"] != "Unknown" else "unknown"
        if k not in B_participants:
            base = participants.get(k) or Person(name=u["speaker"], role=u.get("role", "unknown")); B_participants[k] = dataclasses.replace(base, confidence=u.get("confidence"))
        turns.append(Turn(speaker=k, text=u["text"], start=u.get("start"), end=u.get("end")))
    routeB = Transcript(header=dataclasses.replace(header, package_id=""), participants=B_participants, turns=turns, source=Source(kind="gemini_transcription", video_id=video_id, model=G.RESOLVER_MODEL + " (video)", notes=f"{tb:.0f}s, tokens {usage}"))
    (out / "routeB.json").write_text(routeB.to_json())
    ## scores
    ref = norm(spoken_text(gpo))
    for name, t in (("A", routeA), ("B", routeB)):
        hyp = norm(spoken_text(t))
        results[name] = {"turns": len(t.turns), "words": len(hyp.split()), "wer": round(jiwer.wer(ref, hyp), 3), "shares": shares(t), "speakers_named": sum(1 for p in t.participants.values() if p.name != "Unknown" and not p.name.startswith("c")), "unknown_word_share": t and round(sum(len(u.text.split()) for u in t.turns if u.speaker == "unknown" or u.speaker.startswith("c")) / max(1, len(hyp.split())), 3), "time_s": t.source.notes}
    (out / "compare.json").write_text(json.dumps(results, indent=1))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "shares"} for k, v in results.items()}, indent=1))
    for k in ("gpo", "A", "B"):
        print(k, "top speakers:", dict(list(results[k]["shares"].items())[:7]))


if __name__ == "__main__":
    a = sys.argv[1:]; proxy = a[a.index("--proxy") + 1] if "--proxy" in a else None
    main(a[0], a[1], a[2], proxy)
