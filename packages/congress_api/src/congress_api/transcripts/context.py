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
import datetime as dt
import gzip
import logging
import re
import urllib.request
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE, DEFAULT_MEETINGS_FILE

from congress_api.parsers import speaker_names as names
from congress_api.models.congress import CommitteeMeeting
from congress_api.models.transcription import Header, Person
from congress_api.parsers.legislators import parse_legislators
from congress_api.parsers.witness_names import person_key

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
                m = CommitteeMeeting.model_validate_json(line); out[m.eventId] = m.source_dict()
    else:
        logging.warning(f"no meetings file at {path}; pass --meetings")
    return out


@lru_cache(maxsize=None)
def gpo_rows() -> list[dict]:
    path = PATHS["gpo"]
    if not Path(path).exists():
        logging.warning(f"no gpo_hearings.csv at {path}; pass --gpo-path")
        return []
    with open(path) as stream:
        return list(csv.DictReader(stream))


def mods_people(package_id: str) -> tuple[dict[str, Person], dict]:
    """Members and witnesses from a package's MODS, plus header facts."""
    return people_in_mods(fetch(MODS_URL.format(pkg=package_id)).decode("utf-8", "replace"))


def people_in_mods(x: str) -> tuple[dict[str, Person], dict]:
    """Members and witnesses named in a MODS record, plus header facts."""
    from congress_api.parsers.gpo import parse_mods_document
    from congress_api.parsers.gpo_hearings import mods_title, mods_witnesses
    document = parse_mods_document(x)
    people: dict[str, Person] = {}
    for member in document.members:
        name = next(((n.text or "").strip() for n in member.names if n.type == "authority-fnf"), "")
        if not name:
            continue
        p = Person(name=name, role="member", surname=names.surname(name),
                   party=member.party or "", state=member.state or "", bioguide_id=member.bio_guide_id or "",
                   honorific="Senator" if member.chamber == "S" else "")
        people[person_key(p.name)] = p
    for fields in mods_witnesses(document):
        p = Person(**fields, role="witness", surname=names.surname(fields["name"]))
        people[person_key(p.name)] = p
    scopes = [document.root, *document.related_items]
    def first(field):
        return next((scope.first(field) for scope in scopes if scope.first(field)), "")
    committee = next((c for scope in scopes for c in scope.committees), None)
    facts = {"title": next((title for scope in scopes if (title := mods_title(scope))), ""), "serial": first("preferred_citations"),
             "held_date": first("held_dates"), "congress": first("congresses"), "session": first("sessions"),
             "chamber": {"HOUSE": "house", "SENATE": "senate", "JOINT": "joint"}.get(first("chambers").upper(), "unknown"),
             "committee": next(((n.text or "").strip() for n in committee.names if n.type == "authority-standard"), "") if committee else "",
             "committee_code": (committee.authority_id or "") if committee else "",
             "subcommittee": next(((n.text or "").strip() for sub in committee.subcommittees for n in sub.names if n.type == "parsed"), "") if committee else ""}
    return people, facts


@lru_cache(maxsize=None)
def legislators_current() -> dict[str, dict]:
    try:
        data = parse_legislators(fetch(LEGISLATORS_URL))
    except Exception:
        return {}
    out = {}
    for native in data:
        l = native.source_dict()
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
    """Format an aware timestamp in Eastern time, applying the date's daylight-saving rules."""
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if t.tzinfo is None:
        return ""
    east = t.astimezone(ZoneInfo("America/New_York"))
    return f"{east.hour % 12 or 12}:{east.minute:02d} {'a.m.' if east.hour < 12 else 'p.m.'}"


def context_for_event(event_id: str, package_id: str = "") -> HearingContext:
    m = meetings().get(event_id)
    if not m and not package_id:
        raise KeyError(f"no meeting record for event {event_id}; pass --gpo-package or --video-id")
    m = m or {}
    codes = [c["systemCode"][:4] + "00" for c in m.get("committees", [])]
    chamber = {"House": "house", "Senate": "senate", "Joint": "joint", "NoChamber": "joint"}.get(m.get("chamber", ""), "unknown")
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
        if header.chamber == "unknown":
            header.chamber = facts.get("chamber", "unknown")
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
    from congress_api.matching.gpo_videos import VIDEO_ID
    from congress_api.parsers.senate_player import parse_player_url
    urls = [v.get("url", "") for v in (m.get("videos") or [])]
    return HearingContext(header=header, participants=participants, youtube_ids=[VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)],
                          senate_urls=[u for u in urls if parse_player_url(u)], scheduled_time_et=et_time(m.get("date", "")) if m.get("date") else "")
