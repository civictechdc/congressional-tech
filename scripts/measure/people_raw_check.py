"""Judge people.parquet and person_aliases.parquet in both directions from independent facts (ct-ha10).

    people_raw_check.py --release DIR [--before DIR] [--members PARQUET] [--terms PARQUET]
        [--raw-dir DIR] [--bodies-dir DIR] [--plant] --output OUT.json

Judges published people and person_aliases using raw MODS XML / Congress.gov JSON bytes (when
--raw-dir or --bodies-dir is supplied), dates, titles/positions, middle names/initials,
generational suffixes, and Member terms/names (never importing repository parsers or model
definitions):
  1. Forward direction (precision — no false merges):
     - Bijection: every canonical (superseded_by IS NULL) non-record witness row's person_key
       matches people.witness_keys, and superseded rows inherit their target's person_key;
     - No name-only or cross-organization merges: non-Member (grouping_basis != 'bioguide')
       people with 2+ appearances must never merge rows with empty/non-identifying organization
       or genuinely distinct organizations;
     - Middle-name / middle-initial & suffix conflict check: non-Member people must never merge
       rows stating conflicting middle initials or spelled-out middle names (e.g. 'Robert A. Cho'
       vs 'Robert B. Cho', 'Robert Alan Cho' vs 'Robert Brian Cho', 'Robert Alan Cho' vs
       'Robert Andrew Cho') or conflicting generational suffixes ('Jr.' vs 'Sr.', 'II' vs 'III');
     - Career-span & date-bounds check: verifies published first_seen_date/last_seen_date against
       hearing dates (from meetings.parquet and raw MODS <heldDate>), flags spans > 35 years as
       leads for human inspection, and hard-flags spans > 60 years;
     - Title / position coherence: non-Member multi-hearing clusters must not absorb sitting
       federal Member-only titles ('U.S. Senator', 'Representative in Congress', 'Member of Congress');
     - Member term & Bioguide coherence: bioguide-grouped people must match a real Bioguide ID in
       members.parquet, agree on Member name/nickname identity across rows, and align with Member
       service terms (flagging implausible >50y gaps and recording >2y unstated gaps as leads).
  2. Reverse direction (completeness — no missed exact merges or lost person/alias keys):
     - Separate non-Member person_keys sharing identical raw non-empty (name, organization) with
       compatible middle names/initials and suffixes are flagged as missed_exact_merge;
     - Every person_aliases row with status='unambiguous' or 'ambiguous' must point to live
       people.parquet target(s);
     - When --before is supplied, every prior person_key and person_aliases old_person_key must
       survive in people.parquet or be carried in person_aliases.parquet to valid live target(s).

With --plant, mutates copies in memory for:
  (a) cross_org_merge: merges two same-name people (or distinct-org people on minimal fixtures)
      from distinct organizations into one person_key;
  (b) conflicting_middle_merge: merges two witnesses with conflicting middle initials/names at
      the same organization;
  (c) missed_exact_merge: splits a multi-hearing exact-match person into two separate person_keys.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

LOCATOR_IDX = re.compile(r'witness\[(\d+)\]')
RECORD_TYPES = {'record_material', 'statement_for_record', 'member_statement'}
PREFIX_TITLES = {
    'mr', 'mrs', 'ms', 'miss', 'mx', 'dr', 'hon', 'honorable', 'the', 'rev', 'reverend',
    'sen', 'senator', 'rep', 'representative', 'gen', 'general', 'adm', 'admiral',
    'vadm', 'radm', 'ltg', 'mg', 'bg', 'vice', 'rear', 'brigadier',
    'col', 'colonel', 'lt', 'lieutenant', 'maj', 'major', 'capt', 'captain', 'sgt', 'sergeant',
    'cmdr', 'commander', 'cdr', 'chief', 'prof', 'professor', 'dean',
    'amb', 'ambassador', 'gov', 'governor', 'sec', 'secretary', 'judge', 'justice',
    'mayor', 'commissioner', 'chairman', 'chairwoman', 'chair', 'ranking', 'member',
    'congressman', 'congresswoman', 'delegate',
}
CREDENTIALS = {
    'phd', 'md', 'jd', 'esq', 'mba', 'mph', 'cpa', 'rn', 'dvm', 'edd', 'dds', 'mpa', 'mpp', 'msw',
    'faafp', 'facp', 'facs', 'faap', 'facc', 'pe', 'ret', 'retired',
    'usa', 'usn', 'usaf', 'usmc', 'uscg', 'ussf',
}
SURNAME_PARTICLES = {'van', 'von', 'de', 'del', 'della', 'la', 'le', 'di', 'da', 'du', 'st', 'mac', 'mc', 'dos', 'das'}
SUFFIX_MAP = {
    'jr': 'jr', 'junior': 'jr',
    'sr': 'sr', 'senior': 'sr',
    'ii': 'ii', '2nd': 'ii',
    'iii': 'iii', '3rd': 'iii',
    'iv': 'iv', '4th': 'iv',
    'v': 'v',
}
_ENTITY_SUFFIX_ONLY = {'inc', 'incorporated', 'llc', 'llp', 'corp', 'corporation', 'ltd', 'limited', 'pc', 'plc', 'pllc', 'co'}
_PLACEHOLDER_ORG_PHRASES = {
    'self', 'none', 'na', 'n a', 'unknown', 'tbd', 'witness', 'witnesses', 'panelist', 'guest',
    'individual', 'citizen', 'private citizen', 'senator', 'u s senator', 'united states senator',
    'representative', 'u s representative', 'united states representative', 'member of congress',
    'congressman', 'congresswoman',
}
_FED_MEMBER_POS_RE = re.compile(
    r'\b(u\.?\s*s\.?\s*senator|united states senator|representative in congress|member of congress)\b'
)
_NON_SITTING_POS_RE = re.compile(
    r'\b(former|retired|ex-|office of|staff|counsel|assistant|director|aide|chief of staff|'
    r'advisor|adviser|fellow|intern|nominee|nominated|to be)\b'
)
_LIGATURES = str.maketrans({
    'ß': 'ss', 'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
    '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
    '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4', '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9',
    "'": '', '’': '', '`': '',
})


def _hex(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return val.hex()
    return str(val).lower()


def _fold_ascii(text, *, is_org=False):
    cleaned = re.sub(r'[\u2010-\u2015\u2212/]+', ' ', str(text or '').translate(_LIGATURES))
    norm = unicodedata.normalize('NFKD', cleaned).encode('ascii', 'ignore').decode('ascii').lower()
    joined = ' '.join(re.findall(r'[a-z0-9]+', norm))
    if is_org and joined.startswith('the '):
        joined = joined[4:]
    return joined


def _is_non_identifying_org(org_folded):
    if not org_folded:
        return True
    return org_folded in _ENTITY_SUFFIX_ONLY or org_folded in _PLACEHOLDER_ORG_PHRASES


def _parse_name_parts(raw_name):
    """Independent parser returning (given_first, first_middle_token, suffix, clean_tokens) from raw name."""
    text = unicodedata.normalize('NFKC', str(raw_name or '')).strip()
    text = re.sub(r'\([^)]*\)', ' ', text)
    text = re.sub(r'["“][^"”]*["”]', ' ', text)
    text = re.sub(r"``[^']*''", ' ', text)
    text = re.sub(r"''[^']*''", ' ', text)
    text = re.sub(r"(?<=\s)['‘][^'’]+['’](?=\s|$)", ' ', text)

    parts = [p.strip() for p in text.split(',') if p.strip()]
    suffix = None
    if len(parts) >= 2:
        for tail in parts[1:]:
            tail_clean = tail.translate(_LIGATURES).replace('.', '')
            toks = re.findall(r'[a-z0-9]+', unicodedata.normalize('NFKD', tail_clean).encode('ascii', 'ignore').decode('ascii').lower())
            for tok in toks:
                if tok in SUFFIX_MAP and suffix is None:
                    suffix = SUFFIX_MAP[tok]
        first_clean = parts[0].translate(_LIGATURES).replace('.', '')
        first_words = re.findall(r'[a-z0-9]+', unicodedata.normalize('NFKD', first_clean).encode('ascii', 'ignore').decode('ascii').lower())
        second_clean = parts[1].translate(_LIGATURES).replace('.', '')
        second_words = re.findall(r'[a-z0-9]+', unicodedata.normalize('NFKD', second_clean).encode('ascii', 'ignore').decode('ascii').lower())
        is_inverted = (
            1 <= len(second_words) <= 3
            and second_words[0] not in (PREFIX_TITLES | CREDENTIALS | set(SUFFIX_MAP))
            and (
                (len(first_words) == 1 and first_words[0] not in PREFIX_TITLES)
                or (len(first_words) == 2 and first_words[0] in SURNAME_PARTICLES)
            )
        )
        text = f'{parts[1]} {parts[0]}' if is_inverted else parts[0]
    elif parts:
        text = parts[0]

    # Collapse hyphenated tokens (including OCR/publisher 'Holtz- Eakin') and strip periods/apostrophes
    text = re.sub(r'(?<=\w)\s*[\-\u2010-\u2015]\s*(?=\w)', '', text)
    text = text.translate(_LIGATURES).replace('.', '')
    folded = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()
    tokens = [t for t in re.findall(r'[a-z0-9]+', folded) if not t.isdigit()]

    while len(tokens) > 1 and (tokens[-1] in CREDENTIALS or tokens[-1] in SUFFIX_MAP):
        tok = tokens.pop()
        if tok in SUFFIX_MAP and suffix is None:
            suffix = SUFFIX_MAP[tok]
    while len(tokens) > 1 and tokens[0] in PREFIX_TITLES:
        tokens.pop(0)
    if len(tokens) > 2:
        tokens = [tokens[0], *[t for t in tokens[1:-1] if t not in PREFIX_TITLES and t not in CREDENTIALS], tokens[-1]]

    if len(tokens) < 2:
        return (tokens[0] if tokens else ''), None, suffix, tokens
    given = tokens[0]
    end_idx = len(tokens) - 1
    while end_idx > 1 and tokens[end_idx - 1] in SURNAME_PARTICLES:
        end_idx -= 1
    mid_tok = tokens[1] if end_idx > 1 else None
    return given, mid_tok, suffix, tokens


def _cluster_middle_tokens(tok_lists):
    """Extract middle tokens across a multi-row cluster after stripping shared trailing surname tokens."""
    valid = [t for t in tok_lists if len(t) >= 2]
    if len(valid) < 2:
        return []
    min_len = min(len(t) for t in valid)
    shared_tail = 1
    while shared_tail < min_len:
        if len({t[-(shared_tail + 1)] for t in valid}) == 1:
            shared_tail += 1
        else:
            break
    mids = []
    for t in valid:
        end_idx = len(t) - shared_tail
        while end_idx > 1 and t[end_idx - 1] in SURNAME_PARTICLES:
            end_idx -= 1
        if end_idx > 1:
            mids.append(t[1])
    return mids


def _parse_day(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if len(s) >= 10 and s[4] == '-':
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _select_package_held_date(package_id, held_date_strings):
    """Pick Congress-window <heldDate> when CHRG-<congress> lists multiple dates (e.g. placeholder + actual)."""
    days = sorted({d for d in (_parse_day(s) for s in held_date_strings) if d is not None})
    if not days:
        return None
    m = re.match(r'^CHRG-(\d{1,3})', str(package_id or ''))
    if m and len(days) > 1:
        cong = int(m.group(1))
        lo, hi = 1789 + (cong - 1) * 2 - 2, 1789 + cong * 2 + 2
        in_window = [d for d in days if lo <= d.year <= hi]
        if in_window:
            return in_window[0]
    return days[0]


def _find_events(obj):
    out = []
    if isinstance(obj, dict):
        if obj.get('eventId') is not None and ('witnesses' in obj or 'date' in obj or 'meetingStatus' in obj):
            out.append(obj)
        for v in obj.values():
            out.extend(_find_events(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_find_events(item))
    return out


class RawPeopleStore:
    """Optional raw-byte reader for Congress.gov JSON and GovInfo MODS XML witness/date facts."""

    def __init__(self, raw_dir=None, bodies_dirs=None, wanted_shas=None):
        self.raw_dir = Path(raw_dir) if raw_dir else None
        self.bodies_dirs = [Path(d) for d in (bodies_dirs or []) if Path(d).is_dir()]
        if self.raw_dir and (self.raw_dir / 'bodies/sha256').is_dir() and (self.raw_dir / 'bodies/sha256') not in self.bodies_dirs:
            self.bodies_dirs.append(self.raw_dir / 'bodies/sha256')
        self.enabled = bool((self.raw_dir and self.raw_dir.is_dir()) or self.bodies_dirs)
        self.cg_lines = {}
        self.mods_cache = {}
        if self.raw_dir and self.raw_dir.is_dir():
            receipts_dir = self.raw_dir / 'receipts/congress/meetings'
            if receipts_dir.is_dir():
                for path in sorted(receipts_dir.rglob('*')):
                    if not path.is_file() or path.name.endswith('.qualification.json'):
                        continue
                    with path.open('rb') as raw_fh:
                        magic = raw_fh.read(2)
                    open_fn = (lambda p=path: gzip.open(p, 'rb')) if (path.suffix == '.gz' or magic == b'\x1f\x8b') else (lambda p=path: p.open('rb'))
                    try:
                        with open_fn() as fh:
                            for raw_line in fh:
                                line = raw_line.rstrip(b'\r\n')
                                if not line.strip():
                                    continue
                                digest = sha256(line).hexdigest()
                                if wanted_shas is None or digest in wanted_shas:
                                    self.cg_lines.setdefault(digest, line)
                    except OSError:
                        continue

    def _local_body(self, sha):
        if not sha:
            return None
        for bdir in self.bodies_dirs:
            for suffix in ('.gz', '.json.gz', '.xml.gz', '.html.gz', ''):
                p = bdir / sha[:2] / (sha + suffix)
                if p.is_file():
                    raw = p.read_bytes()
                    if suffix.endswith('.gz') or raw[:2] == b'\x1f\x8b':
                        try:
                            return gzip.decompress(raw)
                        except OSError:
                            return None
                    return raw
        return None

    def inspect_witness(self, row):
        """Return (read_ok: bool, held_day: date | None) for targeted congress_gov / mods rows."""
        if not self.enabled:
            return False, None
        src = row.get('source')
        sha = _hex(row.get('record_sha'))
        loc = str(row.get('source_locator') or '')
        m = LOCATOR_IDX.search(loc)
        idx = int(m.group(1)) - 1 if m and int(m.group(1)) >= 1 else None

        if src == 'mods' and sha:
            if sha not in self.mods_cache:
                body = self._local_body(sha)
                if body is not None:
                    try:
                        root = ET.fromstring(body)
                        hds = [el.text.strip() for el in root.iter() if el.tag.endswith('heldDate') and el.text and el.text.strip()]
                        w_count = sum(1 for el in root.iter() if el.tag.endswith('witness'))
                        self.mods_cache[sha] = (hds, w_count)
                    except ET.ParseError:
                        self.mods_cache[sha] = None
                else:
                    self.mods_cache[sha] = None
            cached = self.mods_cache.get(sha)
            if cached is not None:
                hds, w_count = cached
                if idx is None or 0 <= idx < w_count:
                    return True, _select_package_held_date(row.get('package_id'), hds)
            return False, None

        if src == 'congress_gov' and sha:
            raw_line = self.cg_lines.get(sha) or self._local_body(sha)
            if raw_line is not None:
                try:
                    env = json.loads(raw_line)
                    ev_id = str(row.get('event_id') or '')
                    if not ev_id and str(row.get('occasion') or '').startswith('meeting:'):
                        ev_id = str(row['occasion']).split(':', 1)[1]
                    events = _find_events(env)
                    ev = next((e for e in events if str(e.get('eventId') or '') == ev_id), events[0] if events else None)
                    if ev is not None:
                        ev_day = _parse_day(ev.get('date'))
                        if idx is None or (isinstance(ev.get('witnesses'), list) and 0 <= idx < len(ev['witnesses'])):
                            return True, ev_day
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
            return False, None

        return False, None


def evaluate(
    people_rows,
    witness_rows,
    meeting_rows=(),
    alias_rows=(),
    before_people=(),
    member_rows=(),
    *,
    before_aliases=(),
    term_rows=(),
    raw_store=None,
    max_flags=100,
):
    flags = []
    leads = []
    counts = Counter()
    unread_raw_records = []

    people_by_key = {p['person_key']: p for p in people_rows}
    witness_by_key = {w['witness_key']: w for w in witness_rows}
    meeting_dates = {}
    for m in meeting_rows:
        if m.get('event_id') is not None:
            d = _parse_day(m.get('meeting_date') or m.get('started_on'))
            if d:
                meeting_dates[str(m['event_id'])] = d

    raw_witness_dates = {}
    if raw_store is not None and raw_store.enabled:
        for wk, w in sorted(witness_by_key.items()):
            src = w.get('source')
            if src in ('congress_gov', 'mods'):
                ok, r_day = raw_store.inspect_witness(w)
                if ok:
                    counts[f'raw_{src}_witnesses_read'] += 1
                    if r_day is not None:
                        raw_witness_dates[wk] = r_day
                else:
                    counts['unread_raw_witnesses'] += 1
                    unread_raw_records.append({
                        'witness_key': wk,
                        'source': src,
                        'record_sha': _hex(w.get('record_sha')),
                    })
            else:
                counts['non_targeted_source_witnesses'] += 1

    members_by_bio = {}
    member_terms_by_bio = defaultdict(list)
    for m in member_rows:
        if not m.get('bioguide_id'):
            continue
        bio = str(m['bioguide_id']).upper()
        members_by_bio[bio] = m
        for t in m.get('terms') or []:
            ts, te = _parse_day(t.get('start') or t.get('term_start')), _parse_day(t.get('end') or t.get('term_end'))
            if ts or te:
                member_terms_by_bio[bio].append((ts, te))
    for tr in term_rows:
        if not tr.get('bioguide_id'):
            continue
        bio = str(tr['bioguide_id']).upper()
        ts, te = _parse_day(tr.get('term_start') or tr.get('start')), _parse_day(tr.get('term_end') or tr.get('end'))
        if ts or te:
            member_terms_by_bio[bio].append((ts, te))

    def _witness_day(w):
        ev_id = str(w.get('event_id') or '')
        if ev_id in meeting_dates:
            return meeting_dates[ev_id]
        return raw_witness_dates.get(w['witness_key'])

    # 1a. Bijection & supersession inheritance on witness rows
    canonical_pks_from_witnesses = defaultdict(set)
    for w in witness_rows:
        wk = w['witness_key']
        pk = w.get('person_key')
        sup = w.get('superseded_by')
        if sup is not None:
            target = witness_by_key.get(sup)
            if target is not None and pk != target.get('person_key'):
                flags.append({
                    'kind': 'superseded_person_key_mismatch',
                    'witness_key': wk,
                    'person_key': pk,
                    'target_witness_key': sup,
                    'target_person_key': target.get('person_key'),
                })
            continue
        if w.get('witness_type') in RECORD_TYPES:
            continue
        if pk is not None:
            canonical_pks_from_witnesses[pk].add(wk)
            if pk not in people_by_key:
                flags.append({'kind': 'dangling_witness_person_key', 'witness_key': wk, 'person_key': pk})

    for pk, p in sorted(people_by_key.items()):
        pub_wks = set(p.get('witness_keys') or [])
        expected_wks = canonical_pks_from_witnesses.get(pk, set())
        if pub_wks != expected_wks:
            flags.append({
                'kind': 'person_witness_keys_bijection_mismatch',
                'person_key': pk,
                'only_in_people': sorted(pub_wks - expected_wks),
                'only_in_witnesses': sorted(expected_wks - pub_wks),
            })

    # 1b. Inspect every person row on independent facts (orgs, middle names/initials, suffixes, dates, titles, Member terms)
    for pk, p in sorted(people_by_key.items()):
        basis = p.get('grouping_basis')
        wks = p.get('witness_keys') or []
        w_rows = [witness_by_key[wk] for wk in wks if wk in witness_by_key]
        counts[f'people_basis_{basis}'] += 1

        pub_first = _parse_day(p.get('first_seen_date'))
        pub_last = _parse_day(p.get('last_seen_date'))
        known_w_days = [d for d in (_witness_day(w) for w in w_rows) if d is not None]
        if known_w_days and raw_store is not None and raw_store.enabled and len(known_w_days) == len(w_rows):
            if pub_first is not None and pub_first != min(known_w_days):
                flags.append({
                    'kind': 'person_date_bounds_mismatch',
                    'person_key': pk,
                    'field': 'first_seen_date',
                    'published': pub_first.isoformat(),
                    'raw': min(known_w_days).isoformat(),
                })
            if pub_last is not None and pub_last != max(known_w_days):
                flags.append({
                    'kind': 'person_date_bounds_mismatch',
                    'person_key': pk,
                    'field': 'last_seen_date',
                    'published': pub_last.isoformat(),
                    'raw': max(known_w_days).isoformat(),
                })

        if basis == 'bioguide':
            bio = str(p.get('bioguide_id') or pk).upper()
            mem = members_by_bio.get(bio)
            if members_by_bio and mem is None:
                flags.append({'kind': 'unknown_member_bioguide', 'person_key': pk, 'bioguide_id': bio})
            mem_name_str = ' '.join(
                str(mem.get(k) or '')
                for k in ('name', 'name_first', 'name_last', 'name_nickname')
            ) if mem else ''
            mem_toks = {t for t in _fold_ascii(mem_name_str).split() if len(t) >= 2}
            terms = member_terms_by_bio.get(bio, [])
            t_starts = [s for s, _ in terms if s is not None]
            t_ends = [e for _, e in terms if e is not None]

            for w in w_rows:
                w_bio = str(w.get('matched_bioguide_id') or w.get('bioguide_id') or '').upper()
                if w_bio and w_bio != bio:
                    flags.append({
                        'kind': 'conflicting_member_bioguide',
                        'person_key': pk,
                        'witness_key': w['witness_key'],
                        'person_bioguide': bio,
                        'witness_bioguide': w_bio,
                    })
                if mem_toks:
                    w_toks = {t for t in _fold_ascii(f"{w.get('name') or ''} {w.get('position') or ''}").split() if len(t) >= 2}
                    if w_toks and not (mem_toks & w_toks):
                        flags.append({
                            'kind': 'member_name_mismatch',
                            'person_key': pk,
                            'bioguide_id': bio,
                            'witness_key': w['witness_key'],
                            'member_name': mem.get('name') or mem_name_str.strip(),
                            'witness_name': w.get('name'),
                        })
                w_day = _witness_day(w)
                if w_day and t_starts and t_ends:
                    min_s, max_e = min(t_starts), max(t_ends)
                    if w_day < min_s or w_day > max_e:
                        gap_days = (min_s - w_day).days if w_day < min_s else (w_day - max_e).days
                        full_txt = f"{w.get('name') or ''} {w.get('position') or ''} {w.get('organization') or ''}".lower()
                        says_former = bool(_NON_SITTING_POS_RE.search(full_txt))
                        if gap_days > 365 * 50:
                            flags.append({
                                'kind': 'member_outside_term',
                                'person_key': pk,
                                'bioguide_id': bio,
                                'witness_key': w['witness_key'],
                                'hearing_date': w_day.isoformat(),
                                'term_span': [min_s.isoformat(), max_e.isoformat()],
                            })
                        elif gap_days > 365 * 2 and not says_former:
                            leads.append({
                                'kind': 'member_outside_term_lead',
                                'person_key': pk,
                                'bioguide_id': bio,
                                'witness_key': w['witness_key'],
                                'hearing_date': w_day.isoformat(),
                                'term_span': [min_s.isoformat(), max_e.isoformat()],
                            })
            continue

        if len(w_rows) < 2:
            continue
        counts['multi_appearance_non_member_people'] += 1

        if basis != 'reviewed':
            orgs_folded = set()
            tok_lists = []
            suffixes = set()
            days = list(known_w_days)
            if pub_first is not None:
                days.append(pub_first)
            if pub_last is not None:
                days.append(pub_last)

            for w in w_rows:
                org_f = _fold_ascii(w.get('organization'), is_org=True)
                if _is_non_identifying_org(org_f):
                    flags.append({
                        'kind': 'name_only_or_bare_org_merge',
                        'person_key': pk,
                        'witness_key': w['witness_key'],
                        'name': w.get('name'),
                        'organization': w.get('organization'),
                    })
                else:
                    orgs_folded.add(org_f)
                _, _, suf, toks = _parse_name_parts(w.get('name'))
                tok_lists.append(toks)
                if suf:
                    suffixes.add(suf)
                pos_l = str(w.get('position') or '').lower()
                full_l = f"{w.get('name') or ''} | {pos_l} | {w.get('organization') or ''}".lower()
                if _FED_MEMBER_POS_RE.search(pos_l) and not _NON_SITTING_POS_RE.search(full_l):
                    flags.append({
                        'kind': 'federal_member_title_in_non_member',
                        'person_key': pk,
                        'witness_key': w['witness_key'],
                        'name': w.get('name'),
                        'position': w.get('position'),
                    })

            if len(orgs_folded) > 1:
                flags.append({
                    'kind': 'cross_organization_merge',
                    'person_key': pk,
                    'name': p.get('name'),
                    'organizations': sorted(orgs_folded),
                })

            mids = _cluster_middle_tokens(tok_lists)
            mid_inits = {m[0] for m in mids if m}
            mid_words = {m for m in mids if len(m) >= 2}
            if len(mid_inits) > 1 or len(mid_words) > 1:
                flags.append({
                    'kind': 'conflicting_middle_or_suffix',
                    'why': 'middle_name_or_initial',
                    'person_key': pk,
                    'name': p.get('name'),
                    'middles': sorted(set(mids)),
                })

            if len(suffixes) > 1:
                flags.append({
                    'kind': 'conflicting_middle_or_suffix',
                    'why': 'suffix',
                    'person_key': pk,
                    'name': p.get('name'),
                    'suffixes': sorted(suffixes),
                })

            unique_days = sorted(set(days))
            if len(unique_days) >= 2:
                span_years = (unique_days[-1] - unique_days[0]).days / 365.25
                if span_years > 60:
                    flags.append({
                        'kind': 'implausible_date_span',
                        'person_key': pk,
                        'name': p.get('name'),
                        'span_years': round(span_years, 1),
                        'first_date': unique_days[0].isoformat(),
                        'last_date': unique_days[-1].isoformat(),
                    })
                elif span_years > 35:
                    leads.append({
                        'kind': 'long_career_span_lead',
                        'person_key': pk,
                        'name': p.get('name'),
                        'span_years': round(span_years, 1),
                        'first_date': unique_days[0].isoformat(),
                        'last_date': unique_days[-1].isoformat(),
                    })

    # 2a. Reverse direction: check for missed exact merges among separate non-Member people
    exact_buckets = defaultdict(list)
    for pk, p in sorted(people_by_key.items()):
        if p.get('grouping_basis') in ('bioguide', 'reviewed'):
            continue
        wks = p.get('witness_keys') or []
        for wk in wks:
            w = witness_by_key.get(wk)
            if not w:
                continue
            raw_n = str(w.get('name') or '').strip()
            raw_o = str(w.get('organization') or '').strip()
            org_f = _fold_ascii(raw_o, is_org=True)
            given, mid, suf, toks = _parse_name_parts(raw_n)
            if len(toks) >= 2 and len(given) >= 2 and not _is_non_identifying_org(org_f):
                exact_buckets[(raw_n.lower(), raw_o.lower())].append((pk, wk, mid, suf))

    for (raw_n, raw_o), entries in sorted(exact_buckets.items()):
        distinct_pks = sorted({e[0] for e in entries})
        if len(distinct_pks) > 1:
            mids = [e[2] for e in entries if e[2]]
            mid_inits = {m[0] for m in mids}
            mid_words = {m for m in mids if len(m) >= 2}
            sufs = {e[3] for e in entries if e[3]}
            if len(mid_inits) <= 1 and len(mid_words) <= 1 and len(sufs) <= 1:
                flags.append({
                    'kind': 'missed_exact_merge',
                    'raw_name': raw_n,
                    'raw_organization': raw_o,
                    'person_keys': distinct_pks,
                })

    # 2b. Validate all person_aliases targets & carry from before_people / before_aliases
    alias_by_old = {a['old_person_key']: a for a in alias_rows}
    for old_pk, al in sorted(alias_by_old.items()):
        st = al.get('status')
        if st == 'unambiguous':
            if al.get('person_key') not in people_by_key:
                flags.append({'kind': 'dangling_person_alias_target', 'old_person_key': old_pk, 'target': al.get('person_key')})
        elif st == 'ambiguous':
            cands = al.get('candidate_keys') or []
            if not cands or any(c not in people_by_key for c in cands):
                flags.append({'kind': 'dangling_person_alias_candidates', 'old_person_key': old_pk, 'candidates': list(cands)})

    for bp in before_people:
        old_pk = bp['person_key']
        if old_pk in people_by_key:
            counts['carried_person_keys'] += 1
            continue
        al = alias_by_old.get(old_pk)
        if al is None:
            flags.append({'kind': 'lost_person_key', 'old_person_key': old_pk, 'name': bp.get('name')})
            continue
        counts['aliased_person_keys'] += 1

    for ba in before_aliases:
        old_pk = ba['old_person_key']
        if old_pk in people_by_key:
            counts['republished_person_alias_keys'] += 1
            continue
        al = alias_by_old.get(old_pk)
        if al is None:
            flags.append({'kind': 'dropped_person_alias_row', 'old_person_key': old_pk, 'prior_status': ba.get('status')})
            continue
        counts['carried_person_alias_rows'] += 1
        if ba.get('status') == 'unambiguous' and ba.get('person_key') in people_by_key:
            if al.get('person_key') != ba.get('person_key'):
                flags.append({
                    'kind': 'changed_person_alias_target',
                    'old_person_key': old_pk,
                    'before_target': ba.get('person_key'),
                    'after_target': al.get('person_key'),
                })

    return {
        'counts': dict(counts),
        'unread_raw_records': unread_raw_records,
        'flag_count': len(flags),
        'flags_by_kind': dict(Counter(f['kind'] for f in flags)),
        'flags': flags if max_flags is None else flags[:max_flags],
        'lead_count': len(leads),
        'leads': leads[:50],
    }


def run_plants(
    people_rows,
    witness_rows,
    meeting_rows=(),
    alias_rows=(),
    before_people=(),
    member_rows=(),
    *,
    before_aliases=(),
    term_rows=(),
    raw_store=None,
):
    """Run all 3 plants: cross_org_merge, conflicting_middle_merge, and missed_exact_merge."""
    results = {}
    witness_by_key = {w['witness_key']: w for w in witness_rows}

    non_member_with_org = [
        p for p in people_rows
        if p.get('grouping_basis') in ('name_organization', 'singleton')
        and (p.get('witness_keys') or [])
        and not _is_non_identifying_org(_fold_ascii(witness_by_key.get(p['witness_keys'][0], {}).get('organization'), is_org=True))
    ]

    # Plant 1: prefer two same-name people from distinct organizations; fallback to any distinct-org pair on tiny fixtures
    by_name = defaultdict(list)
    for p in non_member_with_org:
        w0 = witness_by_key[p['witness_keys'][0]]
        _, _, _, toks = _parse_name_parts(w0.get('name'))
        if len(toks) >= 2:
            by_name[(toks[0], toks[-1])].append(p)

    pair_cross = None
    for group in by_name.values():
        if len(group) < 2:
            continue
        o1 = _fold_ascii(witness_by_key[group[0]['witness_keys'][0]].get('organization'), is_org=True)
        for cand in group[1:]:
            o2 = _fold_ascii(witness_by_key[cand['witness_keys'][0]].get('organization'), is_org=True)
            if o1 != o2:
                pair_cross = (group[0], cand)
                break
        if pair_cross:
            break

    if pair_cross is None:
        for i in range(min(len(non_member_with_org), 200)):
            p1 = non_member_with_org[i]
            o1 = _fold_ascii(witness_by_key[p1['witness_keys'][0]].get('organization'), is_org=True)
            for j in range(i + 1, min(len(non_member_with_org), 200)):
                p2 = non_member_with_org[j]
                o2 = _fold_ascii(witness_by_key[p2['witness_keys'][0]].get('organization'), is_org=True)
                if o1 != o2:
                    pair_cross = (p1, p2)
                    break
            if pair_cross:
                break

    if pair_cross:
        p1, p2 = pair_cross
        moved_wks = set(p2['witness_keys'])
        p_mut = [
            ({**p, 'witness_keys': sorted(set(p['witness_keys']) | moved_wks), 'grouping_basis': 'name_organization'}
             if p['person_key'] == p1['person_key'] else p)
            for p in people_rows if p['person_key'] != p2['person_key']
        ]
        w_mut = [
            ({**w, 'person_key': p1['person_key']} if w.get('person_key') == p2['person_key'] else w)
            for w in witness_rows
        ]
        res1 = evaluate(
            p_mut, w_mut, meeting_rows, alias_rows, before_people, member_rows,
            before_aliases=before_aliases, term_rows=term_rows, raw_store=raw_store, max_flags=None,
        )
        results['cross_org_merge'] = {
            'planted_person_key': p1['person_key'],
            'caught': any(f['kind'] == 'cross_organization_merge' and f.get('person_key') == p1['person_key'] for f in res1['flags']),
            'flags_by_kind': res1['flags_by_kind'],
        }
    else:
        results['cross_org_merge'] = {'caught': False, 'reason': 'no_eligible_pair'}

    # Plant 2: merge two witnesses at the same organization with conflicting middle names/initials
    target_p = next((p for p in non_member_with_org if len(p.get('witness_keys') or []) >= 2), non_member_with_org[0] if non_member_with_org else None)
    if target_p is not None:
        wk_first = target_p['witness_keys'][0]
        base_w = next(w for w in witness_rows if w['witness_key'] == wk_first)
        if len(target_p['witness_keys']) >= 2:
            wk_second = target_p['witness_keys'][1]
            p_mut2 = list(people_rows)
            w_mut2 = [
                ({**w, 'name': 'Robert Alan Cho'} if w['witness_key'] == wk_first
                 else ({**w, 'name': 'Robert Brian Cho', 'organization': base_w['organization']} if w['witness_key'] == wk_second else w))
                for w in witness_rows
            ]
        else:
            fake_wk = 'eeee0000eeee0002'
            p_mut2 = [
                ({**p, 'witness_keys': sorted([*p['witness_keys'], fake_wk]), 'grouping_basis': 'name_organization'}
                 if p['person_key'] == target_p['person_key'] else p)
                for p in people_rows
            ]
            w_mut2 = [
                ({**w, 'name': 'Robert Alan Cho'} if w['witness_key'] == wk_first else w)
                for w in witness_rows
            ] + [{
                **base_w,
                'witness_key': fake_wk,
                'name': 'Robert Brian Cho',
                'superseded_by': None,
            }]
        res2 = evaluate(
            p_mut2, w_mut2, meeting_rows, alias_rows, before_people, member_rows,
            before_aliases=before_aliases, term_rows=term_rows, raw_store=raw_store, max_flags=None,
        )
        results['conflicting_middle_merge'] = {
            'planted_person_key': target_p['person_key'],
            'caught': any(f['kind'] == 'conflicting_middle_or_suffix' and f.get('person_key') == target_p['person_key'] for f in res2['flags']),
            'flags_by_kind': res2['flags_by_kind'],
        }
    else:
        results['conflicting_middle_merge'] = {'caught': False, 'reason': 'no_eligible_person'}

    # Plant 3 (reverse direction): split a multi-hearing exact-match person into two person_keys
    multi_exact = None
    for p in people_rows:
        if p.get('grouping_basis') != 'name_organization' or len(p.get('witness_keys') or []) < 2:
            continue
        ws = [witness_by_key[wk] for wk in p['witness_keys'] if wk in witness_by_key]
        by_raw = defaultdict(list)
        for w in ws:
            rn, ro = str(w.get('name') or '').strip().lower(), str(w.get('organization') or '').strip().lower()
            if rn and ro and not _is_non_identifying_org(_fold_ascii(ro, is_org=True)):
                by_raw[(rn, ro)].append(w['witness_key'])
        hit = next(((rn_ro, wks) for rn_ro, wks in by_raw.items() if len(wks) >= 2), None)
        if hit:
            multi_exact = (p, hit[0], hit[1])
            break

    if multi_exact is not None:
        orig_p, (rn, ro), matching_wks = multi_exact
        split_wk = matching_wks[-1]
        fake_pk = 'dddd0000dddd0003'
        p_mut3 = [
            ({**p, 'witness_keys': [wk for wk in p['witness_keys'] if wk != split_wk]}
             if p['person_key'] == orig_p['person_key'] else p)
            for p in people_rows
        ] + [{
            **orig_p,
            'person_key': fake_pk,
            'witness_keys': [split_wk],
            'grouping_basis': 'singleton',
        }]
        w_mut3 = [
            ({**w, 'person_key': fake_pk} if (w['witness_key'] == split_wk or w.get('superseded_by') == split_wk) else w)
            for w in witness_rows
        ]
        res3 = evaluate(
            p_mut3, w_mut3, meeting_rows, alias_rows, before_people, member_rows,
            before_aliases=before_aliases, term_rows=term_rows, raw_store=raw_store, max_flags=None,
        )
        results['missed_exact_merge'] = {
            'planted_person_keys': [orig_p['person_key'], fake_pk],
            'caught': any(f['kind'] == 'missed_exact_merge' and fake_pk in f.get('person_keys', []) for f in res3['flags']),
            'flags_by_kind': res3['flags_by_kind'],
        }
    else:
        results['missed_exact_merge'] = {'caught': False, 'reason': 'no_eligible_multi_exact'}

    return results


def _read_parquet_cols(path: Path, wanted_cols: list[str]) -> list[dict]:
    pf = pq.ParquetFile(path)
    present = [c for c in wanted_cols if c in pf.schema_arrow.names]
    return pq.read_table(path, columns=present).to_pylist()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--before', type=Path, default=None)
    parser.add_argument('--members', type=Path, default=None)
    parser.add_argument('--terms', type=Path, default=None)
    parser.add_argument('--raw-dir', type=Path, default=None)
    parser.add_argument('--bodies-dir', type=Path, action='append', default=None)
    parser.add_argument('--plant', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)

    p_cols = ['person_key', 'name', 'bioguide_id', 'grouping_basis', 'witness_keys', 'appearance_count', 'organizations', 'positions', 'first_seen_date', 'last_seen_date']
    w_cols = ['witness_key', 'person_key', 'occasion', 'event_id', 'package_id', 'source', 'record_sha', 'source_locator', 'name', 'organization', 'position', 'witness_type', 'bioguide_id', 'matched_bioguide_id', 'superseded_by']
    al_cols = ['old_person_key', 'person_key', 'status', 'kind', 'decision_id', 'last_release_id', 'candidate_keys']
    mem_cols = ['bioguide_id', 'name', 'name_first', 'name_last', 'name_nickname', 'terms']

    people_rows = _read_parquet_cols(args.release / 'people.parquet', p_cols)
    witness_rows = _read_parquet_cols(args.release / 'witnesses.parquet', w_cols)
    meeting_rows = _read_parquet_cols(args.release / 'meetings.parquet', ['event_id', 'meeting_date', 'congress']) if (args.release / 'meetings.parquet').is_file() else []
    alias_rows = _read_parquet_cols(args.release / 'person_aliases.parquet', al_cols) if (args.release / 'person_aliases.parquet').is_file() else []
    before_people = _read_parquet_cols(args.before / 'people.parquet', ['person_key', 'name', 'witness_keys']) if args.before and (args.before / 'people.parquet').is_file() else []
    before_aliases = _read_parquet_cols(args.before / 'person_aliases.parquet', al_cols) if args.before and (args.before / 'person_aliases.parquet').is_file() else []
    member_rows = (
        _read_parquet_cols(args.members, mem_cols)
        if args.members and args.members.is_file()
        else (_read_parquet_cols(args.release / 'members.parquet', mem_cols) if (args.release / 'members.parquet').is_file() else [])
    )
    term_rows = _read_parquet_cols(args.terms, ['bioguide_id', 'term_start', 'term_end', 'start', 'end']) if args.terms and args.terms.is_file() else []

    raw_store = None
    if args.raw_dir or args.bodies_dir:
        wanted_shas = {_hex(w.get('record_sha')) for w in witness_rows if w.get('record_sha') is not None}
        raw_store = RawPeopleStore(raw_dir=args.raw_dir, bodies_dirs=args.bodies_dir, wanted_shas=wanted_shas)

    report = evaluate(
        people_rows, witness_rows, meeting_rows, alias_rows, before_people, member_rows,
        before_aliases=before_aliases, term_rows=term_rows, raw_store=raw_store,
    )
    if args.plant:
        plants = run_plants(
            people_rows, witness_rows, meeting_rows, alias_rows, before_people, member_rows,
            before_aliases=before_aliases, term_rows=term_rows, raw_store=raw_store,
        )
        report['plants'] = plants
        if not all(p.get('caught') for p in plants.values()):
            args.output.write_text(json.dumps(report, indent=2, default=str) + '\n')
            raise SystemExit(f"Planted case was not caught: {plants}")

    args.output.write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(json.dumps({
        'counts': report['counts'],
        'flag_count': report['flag_count'],
        'flags_by_kind': report['flags_by_kind'],
        'lead_count': report['lead_count'],
        'plants': report.get('plants'),
    }, default=str))
    return report


if __name__ == '__main__':
    main()
