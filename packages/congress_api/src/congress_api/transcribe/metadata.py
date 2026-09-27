"""
Who was in the room: the participants and header facts for a hearing, from the sources the
pipeline already keeps.

- The Congress.gov meeting record (`congress-meetings`): title, date and time, committees,
  witnesses with organization and position, official video links.
- GPO's MODS record for a printed hearing: members with party, state and bioguide ID (role
  COMMMEMBER), witnesses with affiliations, serial, session. When the hearing itself isn't
  printed, the MODS of the committee's nearest printed hearing in the same Congress gives the
  roster.
- congress-legislators (unitedstates/congress-legislators) fills party, state and bioguide
  for current members when nothing else does.
"""
from __future__ import annotations

import csv
import dataclasses
import logging
import datetime as dt
import gzip
import html
import json
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE, DEFAULT_MEETINGS_FILE

from congress_api.transcribe import names
from congress_api.transcribe.schema import Header, Person, person_key

MODS_URL = "https://www.govinfo.gov/metadata/pkg/{pkg}/mods.xml"
LEGISLATORS_URL = "https://unitedstates.github.io/congress-legislators/legislators-current.json"
HONORIFIC = {"M": "Mr.", "F": "Ms."}


@dataclasses.dataclass
class HearingContext:
    header: Header
    participants: dict[str, Person]
    youtube_ids: list[str]
    senate_urls: list[str]
    scheduled_time_et: str = ""   # "2:30 p.m." from the meeting record, when the print's gavel time isn't known


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


PATHS = {"gpo": str(DEFAULT_GPO_HEARINGS_FILE), "meetings": str(DEFAULT_MEETINGS_FILE)}


def set_paths(gpo_path: str, meetings_path: str) -> None:
    PATHS.update(gpo=gpo_path, meetings=meetings_path)
    meetings.cache_clear(); gpo_rows.cache_clear()


@lru_cache(maxsize=None)
def meetings() -> dict[str, dict]:
    out, path = {}, PATHS["meetings"]
    if Path(path).exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                m = json.loads(line); out[m["eventId"]] = m
    else:
        logging.warning(f"no meetings file at {path}; pass --meetings")
    return out


@lru_cache(maxsize=None)
def gpo_rows() -> list[dict]:
    path = PATHS["gpo"]
    if not Path(path).exists():
        logging.warning(f"no gpo_hearings.csv at {path}; pass --gpo-path")
    return list(csv.DictReader(open(path))) if Path(path).exists() else []


def mods_people(package_id: str) -> tuple[dict[str, Person], dict]:
    """Members and witnesses from a package's MODS, plus header facts."""
    return people_in_mods(fetch(MODS_URL.format(pkg=package_id)).decode("utf-8", "replace"))


## a title before a name: civil ("Mr.", "The Honorable", "Ambassador"), clerical, or a military rank, in full
##  ("Lieutenant General", "Master Chief Petty Officer") or abbreviated ("Lt. Gen.", "LTG"), with "(Ret.)" after it
TITLE_WORD = ("(?:" + "|".join("""Hon Honorable Mr Ms Mrs Mx Dr Prof Professor Rev Reverend Pastor Rabbi Sister Sir Senator Sen Representative Rep Ambassador Amb
    Governor Gov Mayor President Officer Detective Sheriff Chief Lieutenant Lt Major Maj Brigadier Brig Vice Rear General Gen Admiral Adm Colonel Col Commander
    Cmdr Captain Capt Sergeant Sgt Master Command Technical Staff Petty Specialist Spc GEN LTG MG BG ADM VADM RADM COL LTC MAJ CPT CDR""".split()) + r")\.?")
TITLE = re.compile(r"^(?:The )?(" + TITLE_WORD + ")(?: " + TITLE_WORD + r")*(?: [(\[](?:Dr|[Rr]et(?:ired)?)\.?[)\]])? ")
SUFFIX = re.compile(r"^(Jr|Sr|II|III|IV)\.?$")
DEGREE = re.compile(r"^(?:(?:Ph|Ed|Psy|Pharm|Sc|M|J)\.? ?D|Dr\.? ?P\.? ?H|Esq)\.?$")
## letters after a name: "Ph.D.", "F.A.A.P.", "MPA", "USN (Ret.)"
CREDENTIAL = re.compile(r"^(?:(?:[A-Z]\.?){2,6}|(?:Ph|Ed|Psy|Pharm|Sc)\.? ?D\.?|Dr\.? ?P\.? ?H\.?|Esq\.?)(?: \(Ret\.?\))?$|^\(Ret\.?\)$")
CONNECTIVE = {"and", "of", "for", "the", "to", "in", "on", "from", "by", "with", "at"}
## a post rather than a person ("State Director"), a name GPO ran together with the post ("Byrum, John Executive
##  Director"), or a document listed among the witnesses ("Printed Hearing Record") holds a noun of office or of paper
NOT_A_NAME = {"director", "manager", "officer", "president", "secretary", "administrator", "commissioner", "commissioners", "chairman", "chairwoman", "counsel",
              "attorney", "founder", "owner", "executive", "specialist", "professional", "coordinator", "advocate", "advocacy", "superintendent", "treasurer",
              "record", "testimony", "statement", "hearing", "panel", "witnesses"}


def is_name(text: str) -> bool:
    """Could this be a person's name? GPO's witness lines include contents lines ("Answers to questions from
    the following ...") and the broken-off end of a position ("Security Officer and Security Services
    Administrator"); neither is two to six capitalised words without a connective, a noun of office or paper, or a digit."""
    words = [w.strip(",.-/").lower() for w in text.split()]
    return 2 <= len(words) <= 6 and text[:1].isupper() and not any(c.isdigit() for c in text) and not (CONNECTIVE | NOT_A_NAME) & set(words)


def witness(text: str) -> Person:
    """A witness from GPO's line for them. GPO writes the line three ways: "Mr. Nels Leader, Vice President,
    Bread Alone Bakery", "Richard J. Powell, Executive Director, ClearPath", and surname first, "Campbell, Jr.,
    J.H., President and CEO, Associated Grocers". A name written in order has at least two words before the
    first comma, so a single word there is a surname, alone or with its suffix ("Chodak III, Dr. Paul"). Some
    records carry the contents line instead ("Statement of Dr. Robert D. Putnam, ...", "Panel One Thomas J.
    Murphy, ...")."""
    text = re.sub(r"^\s*(?:(?:opening |prepared |written )?(?:statements?|testimony|remarks) (?:of|by|from)|accompanied by:?|witness(?:es)?:?|panel \w+:?)\s+", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*\([^)]*\d[^)]*\)|\s*[(\[](?:\w+ )?(?:ret|retired|fmr|former)\.?[)\]]", "", text, flags=re.I)  # "Gary Kennedy (H.R. 1963)", "J. Roy Robinson (Ret.)"
    title = TITLE.match(text)
    parts = [s.strip() for s in text[title.end() if title else 0:].split(",") if s.strip()]
    name, rest = (parts[0] if parts else ""), parts[1:]
    if len(name.split()) == 2 and SUFFIX.match(name.split()[1]):
        name, rest = name.split()[0], [name.split()[1]] + rest
    if name and " " not in name and rest:
        suffix = rest.pop(0) if SUFFIX.match(rest[0]) else ""
        ## "Woodruff, Ph.D., MPH, Tracey": degrees stand before the given name; initials in their place ("J.H.") are the given name
        after = next((i for i, s in enumerate(rest) if not CREDENTIAL.match(s)), None)
        if DEGREE.match(rest[0]) and after and is_name(f"{rest[after]} {name}"):
            rest = rest[after:]
        given = rest.pop(0) if rest else ""
        title = title or TITLE.match(given + " ")  # "Roe, Hon. David P., a Representative in Congress ..."
        given = TITLE.sub("", given + " ").split()
        if given and SUFFIX.match(given[-1]):
            suffix = given.pop()  # "Mehan, G. Tracy III"
        name = " ".join(filter(None, [*given, name, suffix]))
    elif rest and SUFFIX.match(rest[0]):
        name = f"{name} {rest.pop(0)}"
    name = re.sub(r"\s*[(\[][^)\]]*[)\]]?$", "", name)  # "Elton John (Via Videoconference)", "Tom Malinowski [D-NJ]", "Lorne W. Craner (former Assistant Secretary"
    words = name.split()
    while len(words) > 2 and CREDENTIAL.match(words[-1]) and not SUFFIX.match(words[-1]):
        words.pop()  # "Brian S. Eifler USA", "Puneet S. Arora MD MS"
    name, rest = " ".join(words), [s for s in rest if not CREDENTIAL.match(s)]
    honorific = title.group(1) if title else ""
    return Person(name=name, role="witness", honorific=honorific if honorific in ("Mr.", "Ms.", "Mrs.", "Dr.") else "", surname=names.surname(name),
                  position=rest[0] if rest else "", organization=", ".join(rest[1:]))


def people_in_mods(x: str) -> tuple[dict[str, Person], dict]:
    """Members and witnesses named in a MODS record, plus header facts."""
    people: dict[str, Person] = {}
    for m in re.finditer(r'<congMember\b([^>]*)>(.*?)</congMember>', x, re.S):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        name = re.search(r'<name type="authority-fnf">([^<]+)</name>', m.group(2))
        if not name:
            continue
        p = Person(name=name.group(1).strip(), role="member", surname=names.surname(name.group(1).strip()), party=attrs.get("party", ""), state=attrs.get("state", ""), bioguide_id=attrs.get("bioGuideId", ""))
        p.honorific = "Senator" if attrs.get("chamber") == "S" else ""
        people[person_key(p.name)] = p
    for w in re.findall(r"<witness>([^<]+)</witness>", x):
        p = witness(html.unescape(w))
        if is_name(p.name):
            people[person_key(p.name)] = p
    g = lambda pat: (re.search(pat, x, re.S).group(1).strip() if re.search(pat, x, re.S) else "")
    facts = {"title": g(r"<searchTitle>([^<]+)</searchTitle>"), "serial": g(r"<preferredCitation>([^<]+)</preferredCitation>"), "held_date": g(r"<heldDate>([^<]+)</heldDate>"),
             "congress": g(r"<congress>(\d+)</congress>"), "session": g(r"<session>(\d+)</session>"),
             "committee": g(r'<congCommittee[^>]*>.*?<name type="authority-standard">([^<]+)</name>'), "committee_code": g(r'<congCommittee authorityId="([^"]+)"'),
             "subcommittee": g(r'<subCommittee>\s*<name type="parsed">([^<]+)</name>')}
    return people, facts


@lru_cache(maxsize=None)
def legislators_current() -> dict[str, dict]:
    try:
        data = json.loads(fetch(LEGISLATORS_URL))
    except Exception:
        return {}
    out = {}
    for l in data:
        term = l["terms"][-1]
        out[l["id"]["bioguide"]] = {"name": f"{l['name'].get('first', '')} {l['name'].get('last', '')}".strip(), "last": l["name"].get("last", ""), "party": {"Democrat": "D", "Republican": "R", "Independent": "I"}.get(term.get("party"), term.get("party", "")[:1]), "state": term.get("state", ""), "chamber": "sen" if term["type"] == "sen" else "rep", "gender": l.get("bio", {}).get("gender", "")}
    return out


def roster_for(committee_code: str, congress: int, exclude_package: str = "") -> dict[str, Person]:
    """Members of a committee in a Congress, from the MODS of its nearest printed hearing."""
    rows = [r for r in gpo_rows() if r["committee_code"] == committee_code and r["congress"] == str(congress) and r["record_type"] == "hearing" and r["package_id"] != exclude_package]
    for r in sorted(rows, key=lambda r: r["held_date"], reverse=True)[:3]:
        try:
            people, _ = mods_people(r["package_id"])
        except Exception:
            continue
        members = {k: p for k, p in people.items() if p.role == "member"}
        if members:
            return members
    return {}


def et_time(iso: str) -> str:
    """'2019-12-05T15:00:00Z' -> '10:00 a.m.' Eastern (standard time November-March, daylight time otherwise)."""
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if t.tzinfo is None:
        return ""
    east = t.astimezone(dt.timezone(dt.timedelta(hours=-5 if t.month in (11, 12, 1, 2, 3) else -4)))
    return f"{east.hour % 12 or 12}:{east.minute:02d} {'a.m.' if east.hour < 12 else 'p.m.'}"


def context_for_event(event_id: str, package_id: str = "") -> HearingContext:
    m = meetings().get(event_id)
    if not m and not package_id:
        raise KeyError(f"no meeting record for event {event_id}; pass --gpo-package or --video-id")
    m = m or {}
    codes = [c["systemCode"][:4] + "00" for c in m.get("committees", [])]
    chamber = {"House": "house", "Senate": "senate"}.get(m.get("chamber", ""), "joint")
    header = Header(title=(m.get("title") or "").strip(), chamber=chamber, congress=int(m["congress"]) if m.get("congress") else None,
                    committee=(m.get("committees") or [{}])[0].get("name", ""), committee_code=codes[0] if codes else "", date=m.get("date", "")[:10], event_id=event_id,
                    location=(m.get("location") or {}).get("room", "") and f"Room {m['location']['room']}, {m['location'].get('building', '')}".strip(", "))
    participants: dict[str, Person] = {}
    for w in m.get("witnesses") or []:
        name = re.sub(r"^(The )?(Hon\.|Honorable) ", "", w.get("name", "")).strip()
        hon = re.match(r"(Mr|Ms|Mrs|Dr)\.", name)
        p = Person(name=re.sub(r"^(Mr|Ms|Mrs|Dr)\. ", "", name), role="witness", honorific=hon.group(0) if hon else "", organization=w.get("organization", ""), position=w.get("position", ""))
        p.surname = names.surname(p.name) if p.name else ""
        participants[person_key(p.name)] = p
    if package_id:
        people, facts = mods_people(package_id)
        participants.update({k: v for k, v in people.items() if k not in participants or not participants[k].organization})
        header.title = header.title or facts["title"]; header.serial = facts["serial"]; header.package_id = package_id
        header.date = header.date or facts["held_date"]; header.congress = header.congress or (int(facts["congress"]) if facts["congress"] else None)
        header.session = int(facts["session"]) if facts["session"] else None
        header.committee = facts["committee"] or header.committee; header.committee_code = facts["committee_code"] or header.committee_code; header.subcommittee = facts["subcommittee"]
    if header.committee_code and header.congress and not any(p.role == "member" for p in participants.values()):
        participants.update(roster_for(header.committee_code, header.congress, exclude_package=package_id))
    leg = legislators_current()
    for p in participants.values():
        if p.role in ("member", "chair", "ranking_member") and p.bioguide_id in leg:
            l = leg[p.bioguide_id]; p.party = p.party or l["party"]; p.state = p.state or l["state"]
            p.honorific = "Senator" if l["chamber"] == "sen" else HONORIFIC.get(l["gender"], p.honorific or "Mr.")
    from congress_api.gpo.match import VIDEO_ID
    from congress_api.senate.isvp import parse_player_url
    urls = [v.get("url", "") for v in (m.get("videos") or [])]
    return HearingContext(header=header, participants=participants, youtube_ids=[VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)],
                          senate_urls=[u for u in urls if parse_player_url(u)], scheduled_time_et=et_time(m.get("date", "")) if m.get("date") else "")
