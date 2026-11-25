"""Independent bidirectional raw check for fuzzy organization merges (ct-6him AC #5).

    org_fuzzy_raw_check.py --release DIR --output OUT.json [--output-md OUT.md]
    org_fuzzy_raw_check.py --witnesses FILE --witness-organizations FILE
        [--organizations FILE] [--meetings FILE] [--committees FILE] [--detail FILE]
        --output OUT.json [--verify-planted]
    org_fuzzy_raw_check.py --verify-planted [--output OUT.json]

Judges organization merges directly from raw witness appearance fields
(`organization`, `on_behalf_of`, `location`/`state`/`address`, `position`/`title`,
`committee`/`subcommittee`, `witness_type`) and output `organizations` /
`witness_organizations` tables without importing repository parsers, model packages,
or reading model definitions or registries.

Checks in both directions:
  1. Direction 1 — Suspicious over-merges (same `org_id`):
     - Geographic/political scope or state mismatches (longest-match first so
       "West Virginia" and "Virginia" resolve to disjoint states US:WV vs US:VA;
       directional modifiers, National vs International/World, city/county/campus/
       numbered branch mismatches);
     - Acronym collisions vs independent character-trigram cosine similarity;
     - Conflicting witness metadata context (`location` state, `position`/`witness_type`
       governance tier, `committee` policy domains) where trigram similarity does not
       support identity.
  2. Direction 2 — Likely missed merges (different `org_id`):
     - Blocks cleanly on shared rare 3-character trigrams via a prefix-filtered inverted
       index (no all-pairs comparison across large corpora);
     - Flags pairs across separate `org_id`s with high character-trigram Dice/Jaccard
       and compatible geographic/scope/metadata context while distinguishing legitimate
       splits (e.g., Virginia vs West Virginia Council of Churches) from punctuation,
       article, corporate-suffix, or typo misses.
  3. Complete accounting of unread records:
     - Names every skipped/unread appearance row (exact counts + row/key identifiers)
       for blank org text, null witness_key, superseded unlinked, unmatched linkage,
       dangling linkage, or truncated input.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
import json
import math
from pathlib import Path
import re
import unicodedata
from typing import Any

import pyarrow.parquet as pq

# Longest-match US states, DC, territories, and well-known multi-word non-state place traps.
_MULTIWORD_PLACE_TRAPS: dict[str, str] = {
    "kansas city": "PLACE:kansas_city",
    "oklahoma city": "PLACE:oklahoma_city",
    "virginia beach": "PLACE:virginia_beach",
    "west palm beach": "PLACE:west_palm_beach",
    "new york city": "US:NY",
    "city of new york": "US:NY",
    "george washington": "PERSON_NAME:george_washington",
}

_US_STATE_PHRASES: list[tuple[str, str]] = [
    ("district of columbia", "US:DC"),
    ("washington d c", "US:DC"),
    ("washington dc", "US:DC"),
    ("west virginia", "US:WV"),
    ("north carolina", "US:NC"),
    ("south carolina", "US:SC"),
    ("north dakota", "US:ND"),
    ("south dakota", "US:SD"),
    ("new hampshire", "US:NH"),
    ("new jersey", "US:NJ"),
    ("new mexico", "US:NM"),
    ("new york", "US:NY"),
    ("rhode island", "US:RI"),
    ("puerto rico", "US:PR"),
    ("u s virgin islands", "US:VI"),
    ("virgin islands", "US:VI"),
    ("american samoa", "US:AS"),
    ("northern mariana islands", "US:MP"),
    ("washington state", "US:WA"),
    ("state of washington", "US:WA"),
    ("alabama", "US:AL"),
    ("alaska", "US:AK"),
    ("arizona", "US:AZ"),
    ("arkansas", "US:AR"),
    ("california", "US:CA"),
    ("colorado", "US:CO"),
    ("connecticut", "US:CT"),
    ("delaware", "US:DE"),
    ("florida", "US:FL"),
    ("georgia", "US:GA"),
    ("guam", "US:GU"),
    ("hawaii", "US:HI"),
    ("idaho", "US:ID"),
    ("illinois", "US:IL"),
    ("indiana", "US:IN"),
    ("iowa", "US:IA"),
    ("kansas", "US:KS"),
    ("kentucky", "US:KY"),
    ("louisiana", "US:LA"),
    ("maine", "US:ME"),
    ("maryland", "US:MD"),
    ("massachusetts", "US:MA"),
    ("michigan", "US:MI"),
    ("minnesota", "US:MN"),
    ("mississippi", "US:MS"),
    ("missouri", "US:MO"),
    ("montana", "US:MT"),
    ("nebraska", "US:NE"),
    ("nevada", "US:NV"),
    ("ohio", "US:OH"),
    ("oklahoma", "US:OK"),
    ("oregon", "US:OR"),
    ("pennsylvania", "US:PA"),
    ("tennessee", "US:TN"),
    ("texas", "US:TX"),
    ("utah", "US:UT"),
    ("vermont", "US:VT"),
    ("virginia", "US:VA"),
    ("wisconsin", "US:WI"),
    ("wyoming", "US:WY"),
]

_US_STATE_ABBREVS: set[str] = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR",
    "VI", "GU", "AS", "MP",
}

_STATE_NAME_BY_CODE: dict[str, str] = {
    code.split(":")[1]: name for name, code in _US_STATE_PHRASES if code.startswith("US:")
}

# Build longest-first regex for multi-word traps + US state phrases.
_ALL_GEO_PATTERNS = sorted(
    {**{k: v for k, v in _MULTIWORD_PLACE_TRAPS.items()}, **dict(_US_STATE_PHRASES)}.items(),
    key=lambda kv: len(kv[0]),
    reverse=True,
)
_GEO_PHRASE_MAP: dict[str, str] = dict(_ALL_GEO_PATTERNS)
_GEO_PHRASE_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k, _ in _ALL_GEO_PATTERNS) + r")\b"
)

_DC_RAW_RE = re.compile(r"\b(?:Washington,?\s*D\.?\s*C\.?|D\.?\s*C\.?)(?=\s|$|[,;)])")
_POSTAL_IN_COMMA_RE = re.compile(
    r"(?:,\s*|\(\s*)([A-Z]{2})(?:\s*\)|\s+\d{5}(?:-\d{4})?|\s*$)"
)
_STANDALONE_STATE_ABBR_RE = re.compile(r"^\s*([A-Z]{2})\s*$")
_TRAILING_CITY_STATE_RE = re.compile(
    r",\s*([A-Za-z][A-Za-z .'-]{1,40}),\s*(D\.?\s*C\.?|[A-Z]{2}|"
    + "|".join(re.escape(name) for name, _ in _US_STATE_PHRASES)
    + r")\s*$",
    re.IGNORECASE,
)
_TRAILING_STATE_ONLY_RE = re.compile(
    r",\s*(D\.?\s*C\.?|[A-Z]{2}|"
    + "|".join(re.escape(name) for name, _ in _US_STATE_PHRASES)
    + r")\s*$",
    re.IGNORECASE,
)

_DIRECTION_MAP: dict[str, str] = {
    "north": "north", "northern": "north",
    "south": "south", "southern": "south",
    "east": "east", "eastern": "east",
    "west": "west", "western": "west",
    "northeast": "northeast", "northeastern": "northeast", "north east": "northeast",
    "northwest": "northwest", "northwestern": "northwest", "north west": "northwest",
    "southeast": "southeast", "southeastern": "southeast", "south east": "southeast",
    "southwest": "southwest", "southwestern": "southwest", "south west": "southwest",
    "midwest": "midwest", "midwestern": "midwest",
    "central": "central",
    "upper": "upper", "lower": "lower",
}
_DIRECTION_RE = re.compile(
    r"\b("
    + "|".join(sorted((re.escape(k) for k in _DIRECTION_MAP), key=len, reverse=True))
    + r")\b"
)

_POLITICAL_SCOPE_RE = re.compile(
    r"\b(international|world|worldwide|global|national|nationwide|inter-?american|trans-?atlantic)\b"
)
_FOREIGN_COUNTRY_MAP: dict[str, str] = {
    "canada": "canada", "canadian": "canada",
    "mexico": "mexico", "mexican": "mexico",
    "united kingdom": "uk", "british": "uk", "england": "uk", "scotland": "uk", "wales": "uk",
    "europe": "europe", "european": "europe",
    "china": "china", "chinese": "china",
    "japan": "japan", "japanese": "japan",
    "australia": "australia", "australian": "australia",
    "germany": "germany", "german": "germany",
    "france": "france", "french": "france",
    "israel": "israel", "israeli": "israel",
    "taiwan": "taiwan", "taiwanese": "taiwan",
    "korea": "korea", "korean": "korea",
    "russia": "russia", "russian": "russia",
    "india": "india", "indian": "india",
}
_FOREIGN_EXEMPT_RE = re.compile(
    r"\b(american indian\w*|indian (?:tribe\w*|nation\w*|affairs|health|education|gaming|child|country)|"
    r"new england)\b"
)
_FOREIGN_COUNTRY_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in _FOREIGN_COUNTRY_MAP), key=len, reverse=True)) + r")\b"
)
_US_PREFIX_RE = re.compile(r"\b(u\s*s|united states|american)\b")
_FEDERAL_BODY_RE = re.compile(
    r"\b(department of|government accountability office|environmental protection agency|"
    r"securities and exchange commission|small business administration|"
    r"agency for international development|federal |house of representatives|senate|"
    r"postal service|coast guard|marine corps|air force|army|navy|congressional)\b"
)

_COUNTY_RE = re.compile(r"\b([a-z][a-z .'-]{1,30}?)\s+county\b")
_CITY_OF_RE = re.compile(r"\b(?:city|town|village|borough|port)\s+of\s+([a-z][a-z .'-]{1,30})\b")
_BRANCH_PLACE_RE = re.compile(
    r"(?:\bat\b|\bof\b|,)\s+("
    r"austin|dallas|houston|san antonio|el paso|arlington|fort worth|"
    r"berkeley|davis|irvine|los angeles|san diego|san francisco|santa barbara|santa cruz|riverside|merced|"
    r"chicago|boston|new york|philadelphia|pittsburgh|baltimore|seattle|denver|atlanta|miami|"
    r"minneapolis|detroit|cleveland|cincinnati|columbus|indianapolis|nashville|memphis|"
    r"st\.?\s*louis|saint\s+louis|kansas city|new orleans|charlotte|raleigh|durham|chapel hill|"
    r"ann arbor|madison|cambridge|new haven|princeton|ithaca|richmond|charlottesville|"
    r"salt lake city|provo|phoenix|tucson|portland|sacramento|oakland|honolulu|anchorage|"
    r"buffalo|rochester|syracuse|albany|tampa|orlando|jacksonville|louisville|lexington|"
    r"des moines|omaha|birmingham|knoxville|tuscaloosa|boulder|spokane|tacoma|boise"
    r")\b"
)
_BRANCH_NUM_RE = re.compile(
    r"\b(?:(local|district|chapter|region|circuit|post|lodge|branch|council|ward|division)\s+(?:no\.?\s*)?([0-9]+|[ivx]{1,5})|"
    r"([0-9]+)(?:st|nd|rd|th)\s+(district|circuit))\b"
)

_CORP_SUFFIX_TOKENS = {
    "inc", "incorporated", "llc", "llp", "pllc", "pc", "plc", "corp", "corporation",
    "ltd", "limited", "co", "company", "lp", "gp", "pa", "sc", "na", "assoc", "assn",
}
_PLACEHOLDER_ORGS = {
    "self", "none", "na", "n a", "unknown", "tbd", "witness", "witnesses", "panelist",
    "guest", "individual", "citizen", "private citizen", "unaffiliated", "independent",
    *_CORP_SUFFIX_TOKENS,
}
_STOPWORDS = {
    "the", "of", "and", "for", "in", "on", "at", "to", "by", "a", "an",
    "u", "s", "us", "united", "states", "america", "american", "national",
}
_GENERIC_ORG_WORDS = {
    "association", "institute", "council", "foundation", "center", "society", "committee",
    "commission", "department", "office", "bureau", "agency", "administration", "board",
    "federation", "coalition", "alliance", "network", "group", "organization", "league",
    "union", "service", "services", "corporation", "company", "incorporated", "university",
    "college", "school", "academy", "hospital", "system", "research", "policy", "fund",
    "national", "american", "united", "states", "international", "federal", "public", "state",
}

_ACRONYM_TOKEN_RE = re.compile(r"^[A-Z0-9][A-Z0-9&./-]{1,9}$")
_PAREN_ACRONYM_RE = re.compile(r"\(([A-Z][A-Z0-9&-]{1,8})\)\s*$")

_NON_SITTING_POS_RE = re.compile(
    r"\b(former|retired|ex-|past|emeritus|nominee|nominated|to be)\b"
)
_FEDERAL_POS_RE = re.compile(
    r"\b(u\.?\s*s\.?\s*(?:senator|representative|secretary|attorney|ambassador|marshal|"
    r"district judge|circuit judge|surgeon general)|member of congress|congress(?:man|woman)|"
    r"comptroller general|surgeon general|postmaster general|joint chiefs)\b"
)
_STATE_POS_RE = re.compile(
    r"\b(governor|lieutenant governor|lt\.?\s*governor|state senator|state representative|"
    r"state assembly\w*|state delegate|state attorney general|state treasurer|state auditor|"
    r"state comptroller|state superintendent|state health officer|state veterinarian)\b"
)
_LOCAL_POS_RE = re.compile(
    r"\b(mayor|city council\w*|county commissioner|county executive|county supervisor|"
    r"county sheriff|borough president|town manager|village president|alderman)\b"
)

_COMMITTEE_DOMAIN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("agriculture", re.compile(r"\b(agriculture|forestry|nutrition)\b|^hsag|^ssaf")),
    ("armed_services", re.compile(r"\b(armed services|defense|military)\b|^hsas|^ssas")),
    ("veterans", re.compile(r"\bveterans\b|^hsvr|^ssva")),
    ("banking_finance", re.compile(r"\b(banking|financial services|housing|urban affairs)\b|^hsba|^ssbk")),
    ("tax_budget", re.compile(r"\b(ways and means|finance|budget|appropriations)\b|^hswm|^ssfi|^hsbu|^ssbu|^hsap|^ssap")),
    ("judiciary", re.compile(r"\b(judiciary|ethics|intelligence)\b|^hsju|^ssju|^hlig|^slin")),
    ("education_labor", re.compile(r"\b(education|workforce|labor|health, education)\b|^hsed|^sshr")),
    ("energy_environment", re.compile(r"\b(energy|natural resources|environment|public works|interior)\b|^hsif|^hsii|^ssep|^sseg")),
    ("foreign_affairs", re.compile(r"\b(foreign affairs|foreign relations)\b|^hsfa|^ssfr")),
    ("transportation", re.compile(r"\b(transportation|infrastructure|commerce, science)\b|^hspw|^sscm")),
    ("homeland_oversight", re.compile(r"\b(homeland security|oversight|governmental affairs|government reform)\b|^hshm|^hsgo|^ssga")),
    ("small_business", re.compile(r"\bsmall business\b|^hssm|^sssb")),
    ("science_tech", re.compile(r"\b(science, space|technology)\b|^hssy")),
]


def _ws(value: Any) -> str:
    return " ".join(str(value or "").split())


def _fold_ascii(text: Any) -> str:
    norm = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(norm.lower().split())


def _clean_alnum(text: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _fold_ascii(text)))


def _hex(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return str(value).lower()


def _char_trigram_counts(text: str) -> Counter[str]:
    clean = _clean_alnum(text)
    if not clean:
        return Counter()
    padded = f"  {clean}  "
    return Counter(padded[i:i + 3] for i in range(len(padded) - 2))


def _char_trigram_set(text: str) -> frozenset[str]:
    return frozenset(_char_trigram_counts(text))


def _trigram_cosine(a: str, b: str) -> float:
    ca = _char_trigram_counts(a)
    cb = _char_trigram_counts(b)
    if not ca or not cb:
        return 0.0
    dot = sum(ca[k] * cb[k] for k in ca.keys() & cb.keys())
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _trigram_dice(sa: frozenset[str], sb: frozenset[str]) -> float:
    if not sa or not sb:
        return 0.0
    return (2.0 * len(sa & sb)) / (len(sa) + len(sb))


def _trigram_jaccard(sa: frozenset[str], sb: frozenset[str]) -> float:
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _strip_trailing_hq_location(raw: str) -> tuple[str, str | None, str | None]:
    """Split optional trailing `, City, ST` or `, ST` HQ suffix from an org string."""
    s = _ws(raw)
    m = _TRAILING_CITY_STATE_RE.search(s)
    if m:
        core = s[:m.start()].strip(" ,;")
        city = _clean_alnum(m.group(1))
        st_raw = m.group(2).strip()
        state = _resolve_state_token(st_raw)
        if core and state:
            return core, state, city or None
    m2 = _TRAILING_STATE_ONLY_RE.search(s)
    if m2:
        core = s[:m2.start()].strip(" ,;")
        st_raw = m2.group(1).strip()
        state = _resolve_state_token(st_raw)
        if core and state and st_raw.upper() != "CO":
            return core, state, None
    return s, None, None


def _resolve_state_token(tok: str) -> str | None:
    if not tok:
        return None
    if re.fullmatch(r"D\.?\s*C\.?", tok.strip(), re.IGNORECASE):
        return "US:DC"
    up = tok.strip().upper()
    if up in _US_STATE_ABBREVS:
        return f"US:{up}"
    low = _clean_alnum(tok)
    return _GEO_PHRASE_MAP.get(low) if _GEO_PHRASE_MAP.get(low, "").startswith("US:") else None


def _core_org_text(raw: str) -> str:
    """Normalized core name removing leading `the`, trailing parenthetical acronym, trailing HQ `, City, ST`, and corporate suffixes."""
    s = _ws(raw)
    s = _PAREN_ACRONYM_RE.sub("", s).strip()
    core, _, _ = _strip_trailing_hq_location(s)
    toks = re.findall(r"[a-z0-9]+", _fold_ascii(core))
    if toks and toks[0] == "the":
        toks = toks[1:]
    while len(toks) > 1 and toks[-1] in _CORP_SUFFIX_TOKENS:
        toks.pop()
    # Normalize leading U.S. / United States on federal entities or US orgs
    if len(toks) >= 3 and toks[:2] == ["u", "s"]:
        toks = toks[2:]
    elif len(toks) >= 3 and toks[:2] == ["united", "states"]:
        toks = toks[2:]
    return " ".join(toks)


def _extract_geo_scope(raw: str) -> dict[str, Any]:
    """Extract independent geographic, state, directional, political scope, city/county, and branch qualifiers."""
    s = _ws(raw)
    core_part, hq_state, hq_city = _strip_trailing_hq_location(s)
    core_folded = _clean_alnum(core_part)

    # First handle D.C. / Washington, D.C. explicitly on raw core_part before punctuation folding
    dc_hits = bool(_DC_RAW_RE.search(core_part))
    scrubbed = _DC_RAW_RE.sub(" ", core_part)
    scrubbed_clean = _clean_alnum(scrubbed)

    core_states: set[str] = {"US:DC"} if dc_hits else set()
    ambiguous_places: set[str] = set()

    def _consume_geo(match: re.Match[str]) -> str:
        phrase = match.group(1)
        code = _GEO_PHRASE_MAP.get(phrase, "")
        if code.startswith("US:"):
            if phrase == "washington":
                ambiguous_places.add("washington")
            else:
                core_states.add(code)
        elif code.startswith("PLACE:"):
            ambiguous_places.add(code)
        return " "

    remainder = _GEO_PHRASE_RE.sub(_consume_geo, scrubbed_clean)

    # Check explicit uppercase postal abbreviations inside `, ST` or `(ST)` in core_part
    for abbr in _POSTAL_IN_COMMA_RE.findall(core_part):
        if abbr in _US_STATE_ABBREVS and abbr != "CO":
            core_states.add(f"US:{abbr}")
    m_st = _STANDALONE_STATE_ABBR_RE.match(core_part)
    if m_st and m_st.group(1) in _US_STATE_ABBREVS:
        core_states.add(f"US:{m_st.group(1)}")

    # Extract directional qualifiers AFTER multi-word state names ("West Virginia", "North Carolina") were consumed!
    directions = {_DIRECTION_MAP[m] for m in _DIRECTION_RE.findall(remainder)}

    # Political scope tiers (national vs international/world vs foreign country)
    scopes: set[str] = set()
    for m in _POLITICAL_SCOPE_RE.findall(core_folded):
        if m in ("international", "world", "worldwide", "global", "inter-american", "interamerican", "trans-atlantic", "transatlantic"):
            scopes.add("international")
        elif m in ("national", "nationwide"):
            scopes.add("national")

    foreign_cleaned = _FOREIGN_EXEMPT_RE.sub(" ", core_folded)
    foreign_countries = {_FOREIGN_COUNTRY_MAP[m] for m in _FOREIGN_COUNTRY_RE.findall(foreign_cleaned)}

    # Counties, explicit City of X, campus/branch places, and numeric locals/districts
    places: set[str] = set()
    for m in _COUNTY_RE.findall(core_folded):
        places.add(f"county:{_clean_alnum(m)}")
    for m in _CITY_OF_RE.findall(core_folded):
        places.add(f"city:{_clean_alnum(m)}")
    for m in _BRANCH_PLACE_RE.findall(core_folded):
        places.add(f"place:{_clean_alnum(m)}")

    branches: set[str] = set()
    for kind1, num1, num2, kind2 in _BRANCH_NUM_RE.findall(core_folded):
        if kind1 and num1:
            branches.add(f"{kind1}:{num1}")
        elif num2 and kind2:
            branches.add(f"{kind2}:{num2}")

    return {
        "core_text": core_part,
        "core_states": frozenset(core_states),
        "hq_state": hq_state,
        "hq_city": hq_city,
        "all_states": frozenset(core_states | ({hq_state} if hq_state else set())),
        "ambiguous_places": frozenset(ambiguous_places),
        "directions": frozenset(directions),
        "scopes": frozenset(scopes),
        "foreign_countries": frozenset(foreign_countries),
        "places": frozenset(places),
        "branches": frozenset(branches),
        "is_federal_body": bool(_FEDERAL_BODY_RE.search(core_folded)),
        "has_us_marker": bool(_US_PREFIX_RE.search(core_folded)),
    }


def _geo_scope_conflicts(ga: dict[str, Any], gb: dict[str, Any], raw_a: str, raw_b: str) -> list[str]:
    """Return list of geographic/political/branch conflict descriptions between two org strings."""
    conflicts: list[str] = []

    # 1. Core state mismatch (e.g., Virginia -> US:VA vs West Virginia -> US:WV, or US:VA vs none)
    sa, sb = ga["core_states"], gb["core_states"]
    if sa != sb:
        # Allow Washington, DC vs none ONLY when both are federal bodies or core text matches
        if sa and sb:
            conflicts.append(f"core_states:{sorted(sa)}!={sorted(sb)}")
        else:
            only = sa or sb
            # Check if one just spelled out a federal body with DC or state HQ vs core
            if not (only == {"US:DC"} and (ga["is_federal_body"] or gb["is_federal_body"])):
                conflicts.append(f"core_state_present_on_one_side:{sorted(sa)}!={sorted(sb)}")

    # 2. Trailing HQ state/city conflict (`Acme, Austin, TX` vs `Acme, Boston, MA` or `Austin, TX` vs `Dallas, TX`)
    # Allow DC lobbying/hearing suffix vs non-DC HQ when core organization names are otherwise identical.
    if ga["hq_state"] and gb["hq_state"] and ga["hq_state"] != gb["hq_state"]:
        both_non_dc = ga["hq_state"] != "US:DC" and gb["hq_state"] != "US:DC"
        same_core = _clean_alnum(ga["core_text"]) == _clean_alnum(gb["core_text"])
        if both_non_dc or not same_core:
            conflicts.append(f"hq_state:{ga['hq_state']}!={gb['hq_state']}")
    if ga["hq_city"] and gb["hq_city"] and ga["hq_city"] != gb["hq_city"]:
        if (ga["hq_state"] != "US:DC" and gb["hq_state"] != "US:DC") or (
            _clean_alnum(ga["core_text"]) != _clean_alnum(gb["core_text"])
        ):
            conflicts.append(f"hq_city:{ga['hq_city']}!={gb['hq_city']}")
    # Cross-check non-DC HQ state on one side vs core state on the other
    if ga["hq_state"] and ga["hq_state"] != "US:DC" and gb["core_states"] and ga["hq_state"] not in gb["core_states"]:
        conflicts.append(f"hq_vs_core_state:{ga['hq_state']}not_in{sorted(gb['core_states'])}")
    if gb["hq_state"] and gb["hq_state"] != "US:DC" and ga["core_states"] and gb["hq_state"] not in ga["core_states"]:
        conflicts.append(f"hq_vs_core_state:{gb['hq_state']}not_in{sorted(ga['core_states'])}")

    # 3. Directional qualifiers (e.g., North vs South, Eastern vs Western)
    da, db = ga["directions"], gb["directions"]
    if da != db and (da or db):
        conflicts.append(f"directions:{sorted(da)}!={sorted(db)}")

    # 4. Political / scope qualifiers (`national` vs `international`/`world`, or `national` vs `<US state>`)
    sca, scb = ga["scopes"], gb["scopes"]
    if sca != scb and (sca and scb):
        conflicts.append(f"political_scope:{sorted(sca)}!={sorted(scb)}")
    elif (sca and (gb["core_states"] - {"US:DC"})) or (scb and (ga["core_states"] - {"US:DC"})):
        # National org vs state org (e.g. National Council of Churches vs Virginia Council of Churches)
        conflicts.append(f"national_vs_state_scope:{sorted(sca)}/{sorted(ga['core_states'])}vs{sorted(scb)}/{sorted(gb['core_states'])}")

    # 5. Foreign country mismatch or US vs foreign country
    fa, fb = ga["foreign_countries"], gb["foreign_countries"]
    if fa != fb and (fa or fb):
        conflicts.append(f"foreign_country:{sorted(fa)}!={sorted(fb)}")

    # 6. Branch / city / county / numbered local/district qualifiers
    pa, pb = ga["places"], gb["places"]
    if pa and pb and pa != pb:
        conflicts.append(f"place_branch:{sorted(pa)}!={sorted(pb)}")
    bra, brb = ga["branches"], gb["branches"]
    if bra != brb and (bra or brb):
        conflicts.append(f"numbered_branch:{sorted(bra)}!={sorted(brb)}")

    # 7. Ambiguous place word (e.g. `Washington` vs `Washington, DC`)
    if ga["ambiguous_places"] != gb["ambiguous_places"] and (
        ("washington" in ga["ambiguous_places"] and "US:DC" in gb["core_states"])
        or ("washington" in gb["ambiguous_places"] and "US:DC" in ga["core_states"])
    ):
        conflicts.append("washington_state_vs_dc_ambiguity")

    return conflicts


def _is_short_acronym(raw: str) -> str | None:
    s = _ws(raw)
    if _ACRONYM_TOKEN_RE.match(s) and sum(c.isalpha() for c in s) >= 2:
        letters = re.sub(r"[^A-Z0-9]", "", s)
        if 2 <= len(letters) <= 8:
            return letters
    return None


def _embedded_acronym(raw: str) -> str | None:
    m = _PAREN_ACRONYM_RE.search(_ws(raw))
    return re.sub(r"[^A-Z0-9]", "", m.group(1)) if m else None


def _matches_initialism(acronym: str, phrase: str) -> bool:
    """True when `acronym` plausibly stands for `phrase` (allowing skipped stopwords/U.S.)."""
    acr = acronym.lower()
    words = [w for w in re.findall(r"[a-z0-9]+", _fold_ascii(phrase))]
    if len(words) < 2:
        return False
    all_initials = "".join(w[0] for w in words)
    content_initials = "".join(w[0] for w in words if w not in {"of", "and", "for", "the", "in", "on", "at", "to", "by"})
    non_us_initials = "".join(w[0] for w in words if w not in {"of", "and", "for", "the", "in", "on", "at", "to", "by", "u", "s", "us"})
    if acr in {all_initials, content_initials, non_us_initials}:
        return True
    # Subsequence check across word initials when acronym has >= 3 chars
    if len(acr) >= 3:
        it = iter(all_initials)
        if all(ch in it for ch in acr):
            return True
    return False


def _extract_location_geo(row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Parse (US:ST, city) from raw witness location/state/city/address fields."""
    parts = [
        _ws(row.get("location")),
        _ws(row.get("city")),
        _ws(row.get("state")),
        _ws(row.get("address")),
    ]
    loc_text = ", ".join(p for p in parts if p)
    if not loc_text:
        return None, None
    if _DC_RAW_RE.search(loc_text):
        return "US:DC", "washington"
    # Prefer trailing `, City, ST`
    m = _TRAILING_CITY_STATE_RE.search(loc_text)
    if m:
        st = _resolve_state_token(m.group(2))
        if st:
            return st, _clean_alnum(m.group(1)) or None
    for abbr in _POSTAL_IN_COMMA_RE.findall(loc_text):
        if abbr in _US_STATE_ABBREVS and abbr != "CO":
            return f"US:{abbr}", None
    m_st = _STANDALONE_STATE_ABBR_RE.match(loc_text)
    if m_st and m_st.group(1) in _US_STATE_ABBREVS:
        return f"US:{m_st.group(1)}", None
    clean = _clean_alnum(loc_text)
    for m_geo in _GEO_PHRASE_RE.finditer(clean):
        code = _GEO_PHRASE_MAP.get(m_geo.group(1), "")
        if code.startswith("US:"):
            return code, None
    return None, None


def _extract_jurisdiction_tier(row: Mapping[str, Any]) -> str | None:
    """Infer official governance tier (`federal`, `state`, `local`) from raw position & witness_type."""
    wtype = _ws(row.get("witness_type")).lower()
    if "government - federal" in wtype:
        return "federal"
    if "government - state" in wtype:
        return "state"
    if "government - local" in wtype:
        return "local"

    pos = _fold_ascii(row.get("position") or row.get("title") or "")
    if not pos or _NON_SITTING_POS_RE.search(pos):
        return None
    if _FEDERAL_POS_RE.search(pos):
        return "federal"
    if _STATE_POS_RE.search(pos):
        return "state"
    if _LOCAL_POS_RE.search(pos):
        return "local"
    return None


def _committee_domains(items: Iterable[str]) -> frozenset[str]:
    out: set[str] = set()
    for item in items:
        low = _fold_ascii(item)
        if not low:
            continue
        for domain, pattern in _COMMITTEE_DOMAIN_RULES:
            if pattern.search(low):
                out.add(domain)
    return frozenset(out)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    suf = path.suffix.lower()
    if suf == ".parquet":
        return pq.read_table(path).to_pylist()
    text = path.read_text(encoding="utf-8")
    if suf in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("rows", "records", "data", "witnesses", "organizations", "witness_organizations"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError(f"Unsupported JSON shape in {path}")


def _flatten_witness_records(rows: Sequence[Mapping[str, Any]], *, limit: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize flat witness rows or nested `appearance_records` rows, recording any truncated rows."""
    flat: list[dict[str, Any]] = []
    truncated: list[dict[str, Any]] = []

    def _push(rec: dict[str, Any]) -> None:
        if limit is not None and len(flat) >= limit:
            truncated.append({
                "row_index": rec["row_index"],
                "witness_key": rec.get("witness_key"),
                "reason": "truncated",
                "source": rec.get("source"),
                "record_sha": rec.get("record_sha"),
                "source_locator": rec.get("source_locator"),
                "raw_organization_preview": _ws(rec.get("organization"))[:120] or None,
            })
            return
        flat.append(rec)

    row_idx = 0
    for r in rows:
        if isinstance(r.get("appearances"), list):
            sha = _hex(r.get("record_sha"))
            src = r.get("source")
            ev = r.get("event_id")
            pkg = r.get("package_id")
            for app in r["appearances"]:
                if not isinstance(app, Mapping):
                    row_idx += 1
                    continue
                rec = dict(app)
                rec.setdefault("source", src)
                rec.setdefault("record_sha", sha)
                rec.setdefault("event_id", ev)
                rec.setdefault("package_id", pkg)
                rec["row_index"] = row_idx
                row_idx += 1
                _push(rec)
        else:
            rec = dict(r)
            rec["row_index"] = row_idx
            row_idx += 1
            _push(rec)
    return flat, truncated


def _build_committee_lookup(
    meeting_rows: Sequence[Mapping[str, Any]],
    committee_rows: Sequence[Mapping[str, Any]],
    detail_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[Any, list[str]], dict[str, list[str]], dict[str, str]]:
    """Map event_id -> committee labels and package_id -> committee labels independently."""
    comm_name_by_code: dict[str, str] = {}
    for c in committee_rows:
        code = _ws(c.get("system_code")).lower()
        name = _ws(c.get("name"))
        if code and name:
            comm_name_by_code[code] = name

    by_event: dict[Any, list[str]] = {}
    by_pkg: dict[str, list[str]] = {}
    for m in meeting_rows:
        labels: list[str] = []
        for item in m.get("committees") or []:
            code = _ws(item.get("system_code") if isinstance(item, Mapping) else item).lower()
            if code:
                labels.append(code)
                if code in comm_name_by_code:
                    labels.append(comm_name_by_code[code])
                if len(code) == 6 and (code[:4] + "00") in comm_name_by_code:
                    labels.append(comm_name_by_code[code[:4] + "00"])
        if labels:
            if m.get("event_id") is not None:
                by_event[m["event_id"]] = labels
            for tr in m.get("transcripts") or []:
                if isinstance(tr, Mapping) and tr.get("package_id"):
                    by_pkg[str(tr["package_id"])] = labels

    for d in detail_rows:
        pkg = d.get("package_id")
        if not pkg or str(pkg) in by_pkg:
            continue
        labels = []
        for code in d.get("committee_keys") or []:
            c = _ws(code).lower()
            if c:
                labels.append(c)
                if c in comm_name_by_code:
                    labels.append(comm_name_by_code[c])
        if labels:
            by_pkg[str(pkg)] = labels
    return by_event, by_pkg, comm_name_by_code


def _witness_committees(
    row: Mapping[str, Any],
    by_event: Mapping[Any, list[str]],
    by_pkg: Mapping[str, list[str]],
    comm_name_by_code: Mapping[str, str],
) -> list[str]:
    labels: list[str] = []
    for col in ("committee", "subcommittee", "committee_name", "subcommittee_name", "committee_key"):
        val = _ws(row.get(col))
        if val:
            labels.append(val)
            if val.lower() in comm_name_by_code:
                labels.append(comm_name_by_code[val.lower()])
    for col in ("committee_keys", "committees"):
        vals = row.get(col)
        if isinstance(vals, (list, tuple)):
            for item in vals:
                v = _ws(item.get("system_code") if isinstance(item, Mapping) else item)
                if v:
                    labels.append(v)
                    if v.lower() in comm_name_by_code:
                        labels.append(comm_name_by_code[v.lower()])
    ev = row.get("event_id")
    if ev is not None and ev in by_event:
        labels.extend(by_event[ev])
    pkg = row.get("package_id")
    if pkg and str(pkg) in by_pkg:
        labels.extend(by_pkg[str(pkg)])
    return sorted(set(labels))


def _linkage_index(
    witness_org_rows: Sequence[Mapping[str, Any]],
    org_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], set[str], list[dict[str, Any]]]:
    """Index linkage rows from `witness_organizations` (or `organizations.witness_keys`)."""
    by_wk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    known_org_ids = {
        _ws(o.get("org_id") or o.get("organization_id") or o.get("org_key"))
        for o in org_rows
        if _ws(o.get("org_id") or o.get("organization_id") or o.get("org_key"))
    }
    bad_links: list[dict[str, Any]] = []

    if witness_org_rows:
        for idx, link in enumerate(witness_org_rows):
            wk = _ws(link.get("witness_key") or link.get("appearance_key"))
            oid = _ws(link.get("org_id") or link.get("organization_id") or link.get("org_key"))
            role = _ws(link.get("role") or link.get("field") or link.get("source_field") or link.get("mention_kind")).lower() or None
            raw_hint = _ws(link.get("raw_organization") or link.get("raw_text") or link.get("org_string")) or None
            if not wk:
                bad_links.append({"row_index": idx, "witness_key": None, "org_id": oid or None, "reason": "orphan_linkage_null_witness_key"})
                continue
            if not oid:
                bad_links.append({"row_index": idx, "witness_key": wk, "org_id": None, "reason": "orphan_linkage_null_org_id"})
                continue
            if known_org_ids and oid not in known_org_ids:
                bad_links.append({"row_index": idx, "witness_key": wk, "org_id": oid, "reason": "dangling_witness_org_link_missing_org"})
            by_wk[wk].append({"org_id": oid, "role": role, "raw_hint": raw_hint, "link_index": idx})
    elif org_rows:
        for o in org_rows:
            oid = _ws(o.get("org_id") or o.get("organization_id") or o.get("org_key"))
            for wk in o.get("witness_keys") or []:
                wk_s = _ws(wk)
                if oid and wk_s:
                    by_wk[wk_s].append({"org_id": oid, "role": None, "raw_hint": None, "link_index": None})
    return by_wk, known_org_ids, bad_links


def _choose_raw_org_text(row: Mapping[str, Any], link: Mapping[str, Any]) -> tuple[str, str]:
    """Select the verbatim raw organization string from the appearance record for a linkage row."""
    role = link.get("role")
    org_txt = _ws(row.get("organization") or row.get("raw_organization") or row.get("org_name") or row.get("org"))
    behalf_txt = _ws(row.get("on_behalf_of") or row.get("behalf_of"))
    if role == "on_behalf_of":
        return behalf_txt, "on_behalf_of"
    if role == "organization":
        return org_txt, "organization"
    hint = link.get("raw_hint")
    if hint and behalf_txt and not org_txt:
        return behalf_txt, "on_behalf_of"
    if hint and behalf_txt and org_txt:
        if _clean_alnum(hint) in _clean_alnum(behalf_txt) and _clean_alnum(hint) not in _clean_alnum(org_txt):
            return behalf_txt, "on_behalf_of"
    if org_txt:
        return org_txt, "organization"
    if behalf_txt:
        return behalf_txt, "on_behalf_of"
    return "", "organization"


_CORP_SUFFIX_FAMILIES: dict[str, str] = {
    "inc": "inc", "incorporated": "inc",
    "llc": "llc", "pllc": "llc",
    "llp": "llp",
    "corp": "corp", "corporation": "corp",
    "ltd": "ltd", "limited": "ltd",
    "co": "co", "company": "co",
    "lp": "lp", "gp": "gp",
}


def _trailing_corp_family(raw: str) -> str | None:
    core, _, _ = _strip_trailing_hq_location(_PAREN_ACRONYM_RE.sub("", _ws(raw)).strip())
    toks = re.findall(r"[a-z0-9]+", _fold_ascii(core))
    if len(toks) > 1 and toks[-1] in _CORP_SUFFIX_FAMILIES:
        return _CORP_SUFFIX_FAMILIES[toks[-1]]
    return None


def _token_difference_is_minor(raw_a: str, raw_b: str) -> tuple[bool, str]:
    """Check whether two strings differ only by punctuation/articles/corporate suffix/U.S./1-char typo."""
    fam_a = _trailing_corp_family(raw_a)
    fam_b = _trailing_corp_family(raw_b)
    if fam_a and fam_b and fam_a != fam_b:
        return False, f"distinct_legal_suffixes:{fam_a}!={fam_b}"

    core_a = _core_org_text(raw_a)
    core_b = _core_org_text(raw_b)
    if core_a == core_b and core_a:
        if _clean_alnum(raw_a) == _clean_alnum(raw_b):
            return True, "punctuation_or_case_miss"
        return True, "article_suffix_or_us_miss"

    ta = core_a.split()
    tb = core_b.split()

    # Space-split typo check (e.g. `u s government` vs `usgovernment` -> concatenated alnum match)
    if "".join(ta) == "".join(tb) and ta:
        return True, "spacing_or_hyphen_miss"

    # Stopword-only or identical content-token differences (e.g. `Public Policy and Research` vs `Public Policy Research`)
    ca_toks = [w for w in ta if w not in _STOPWORDS]
    cb_toks = [w for w in tb if w not in _STOPWORDS]
    if ca_toks == cb_toks and ca_toks:
        return True, "stopword_or_punctuation_miss"

    if abs(len(ta) - len(tb)) > 1:
        return False, "distinct_word_counts"

    if len(ta) == len(tb):
        diffs = [(x, y) for x, y in zip(ta, tb) if x != y]
        if not diffs:
            return True, "punctuation_or_suffix_miss"
        if len(diffs) == 1:
            wa, wb = diffs[0]
            if min(len(wa), len(wb)) >= 5 and _edit_distance(wa, wb) <= 2:
                return True, "typo_or_spelling_variant"
        return False, f"distinct_content_words:{diffs[:3]}"
    return False, "distinct_words"


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _check_direction1_overmerges(
    org_records: Mapping[str, list[dict[str, Any]]],
    *,
    trigram_cosine_threshold: float = 0.68,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Direction 1: Detect suspicious over-merges within each `org_id`."""
    flags: list[dict[str, Any]] = []
    leads: list[dict[str, Any]] = []
    stats = Counter()

    for org_id in sorted(org_records):
        entries = org_records[org_id]
        stats["distinct_orgs_checked"] += 1

        by_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in entries:
            by_raw[e["raw_text"]].append(e)

        raw_strings = sorted(by_raw)
        if len(raw_strings) == 1:
            # Check leads for ambiguous single-string generic/acronym clusters with conflicting metadata
            raw0 = raw_strings[0]
            if _is_short_acronym(raw0) or _clean_alnum(raw0) in {
                "department of health", "department of transportation", "department of education",
                "department of agriculture", "department of labor", "chamber of commerce",
            }:
                non_dc_states = {e["loc_state"] for e in entries if e["loc_state"] and e["loc_state"] != "US:DC"}
                tiers = {e["tier"] for e in entries if e["tier"]}
                if len(non_dc_states) > 1 or len(tiers - {"non_gov"}) > 1:
                    leads.append({
                        "kind": "ambiguous_single_string_metadata_divergence",
                        "org_id": org_id,
                        "raw_strings": [raw0],
                        "location_states": sorted(non_dc_states),
                        "jurisdiction_tiers": sorted(tiers),
                        "witness_keys": [e["witness_key"] for e in entries[:10]],
                    })
            continue

        stats["multi_string_orgs_checked"] += 1
        # Precompute per-raw-string geo and metadata summaries
        geo_map = {s: _extract_geo_scope(s) for s in raw_strings}
        meta_map: dict[str, dict[str, Any]] = {}
        for s in raw_strings:
            rows = by_raw[s]
            loc_states = sorted({e["loc_state"] for e in rows if e["loc_state"]})
            non_dc_loc_states = sorted({st for st in loc_states if st != "US:DC"})
            tiers = sorted({e["tier"] for e in rows if e["tier"]})
            comm_domains = sorted({d for e in rows for d in e["committee_domains"]})
            meta_map[s] = {
                "loc_states": loc_states,
                "non_dc_loc_states": non_dc_loc_states,
                "tiers": tiers,
                "comm_domains": comm_domains,
                "witness_keys": [e["witness_key"] for e in rows],
            }

        # Check all distinct raw string pairs inside the same org_id (each org_id has few distinct strings)
        org_flag_emitted_kinds: set[str] = set()
        for i in range(len(raw_strings)):
            sa = raw_strings[i]
            ga = geo_map[sa]
            ma = meta_map[sa]
            acr_a = _is_short_acronym(sa)
            emb_a = _embedded_acronym(sa)
            for j in range(i + 1, len(raw_strings)):
                sb = raw_strings[j]
                gb = geo_map[sb]
                mb = meta_map[sb]
                acr_b = _is_short_acronym(sb)
                emb_b = _embedded_acronym(sb)

                raw_cos = _trigram_cosine(sa, sb)
                core_a = _core_org_text(sa)
                core_b = _core_org_text(sb)
                core_cos = _trigram_cosine(core_a, core_b) if (core_a and core_b) else raw_cos

                # Identical alphanumeric sequence (e.g. "AFL-CIO" vs "AFL_CIO", "NASDAQ" vs "Nasdaq")
                if re.sub(r"[^a-z0-9]", "", _fold_ascii(sa)) == re.sub(r"[^a-z0-9]", "", _fold_ascii(sb)):
                    continue

                # 1a. Geographic / political scope / branch conflict
                geo_conflicts = _geo_scope_conflicts(ga, gb, sa, sb)
                if geo_conflicts:
                    flags.append({
                        "direction": "direction1_overmerge",
                        "kind": "scope_or_state_conflict",
                        "org_id": org_id,
                        "raw_strings": [sa, sb],
                        "trigram_cosine": round(raw_cos, 4),
                        "core_trigram_cosine": round(core_cos, 4),
                        "conflicts": geo_conflicts,
                        "witness_keys": sorted(set(ma["witness_keys"][:5] + mb["witness_keys"][:5])),
                    })
                    org_flag_emitted_kinds.add("scope_or_state_conflict")
                    continue

                # 1b. Acronym collision vs independent trigram cosine
                acronym_hit = None
                if acr_a and acr_b and acr_a != acr_b:
                    acronym_hit = f"distinct_acronyms:{acr_a}!={acr_b}"
                elif acr_a and not acr_b and not _matches_initialism(acr_a, sb):
                    acronym_hit = f"acronym_initialism_mismatch:{acr_a}_vs_{sb}"
                elif acr_b and not acr_a and not _matches_initialism(acr_b, sa):
                    acronym_hit = f"acronym_initialism_mismatch:{acr_b}_vs_{sa}"
                elif (emb_a and emb_b and emb_a == emb_b) or (acr_a and emb_b == acr_a) or (acr_b and emb_a == acr_b):
                    if core_cos < 0.80:
                        acronym_hit = f"shared_acronym_divergent_expansions:{emb_a or acr_a}"
                if acronym_hit:
                    flags.append({
                        "direction": "direction1_overmerge",
                        "kind": "acronym_collision",
                        "org_id": org_id,
                        "raw_strings": [sa, sb],
                        "trigram_cosine": round(raw_cos, 4),
                        "core_trigram_cosine": round(core_cos, 4),
                        "conflicts": [acronym_hit],
                        "witness_keys": sorted(set(ma["witness_keys"][:5] + mb["witness_keys"][:5])),
                    })
                    org_flag_emitted_kinds.add("acronym_collision")
                    continue

                # Check if cluster holds an acronym alongside two divergent matching expansions
                # (handled pairwise above when expansions differ in core_cos < 0.80 if acronym embedded;
                # also check bare acronyms paired with multiple non-matching expansions below).

                # 1c. Witness metadata context conflict where trigram similarity does not support identity
                meta_conflicts: list[str] = []
                if raw_cos < 0.90:
                    st_a, st_b = set(ma["non_dc_loc_states"]), set(mb["non_dc_loc_states"])
                    if st_a and st_b and st_a.isdisjoint(st_b):
                        meta_conflicts.append(f"disjoint_witness_states:{sorted(st_a)}vs{sorted(st_b)}")
                    gov_a = {t for t in ma["tiers"] if t in {"federal", "state", "local"}}
                    gov_b = {t for t in mb["tiers"] if t in {"federal", "state", "local"}}
                    if gov_a and gov_b and gov_a.isdisjoint(gov_b):
                        meta_conflicts.append(f"disjoint_jurisdiction_tiers:{sorted(gov_a)}vs{sorted(gov_b)}")
                    if (
                        set(ma["loc_states"]) == {"US:DC"}
                        and set(mb["non_dc_loc_states"])
                        and gov_a == {"federal"}
                        and gov_b & {"state", "local"}
                    ) or (
                        set(mb["loc_states"]) == {"US:DC"}
                        and set(ma["non_dc_loc_states"])
                        and gov_b == {"federal"}
                        and gov_a & {"state", "local"}
                    ):
                        meta_conflicts.append("dc_federal_vs_state_local_location")

                    dom_a, dom_b = set(ma["comm_domains"]), set(mb["comm_domains"])
                    if dom_a and dom_b and dom_a.isdisjoint(dom_b) and (raw_cos < 0.80 or acr_a or acr_b):
                        meta_conflicts.append(f"disjoint_committee_domains:{sorted(dom_a)}vs{sorted(dom_b)}")

                if meta_conflicts:
                    flags.append({
                        "direction": "direction1_overmerge",
                        "kind": "metadata_context_conflict",
                        "org_id": org_id,
                        "raw_strings": [sa, sb],
                        "trigram_cosine": round(raw_cos, 4),
                        "core_trigram_cosine": round(core_cos, 4),
                        "conflicts": meta_conflicts,
                        "witness_keys": sorted(set(ma["witness_keys"][:5] + mb["witness_keys"][:5])),
                    })
                    org_flag_emitted_kinds.add("metadata_context_conflict")
                    continue

                # 1d. Low independent character-trigram cosine similarity
                # Exempt: clean acronym <-> single matching expansion without metadata conflict,
                # or core_cos >= 0.85 (e.g. `U.S. Chamber of Commerce` vs `Chamber of Commerce of the United States`
                # or `The Heritage Foundation` vs `Heritage Foundation`), or subunit containment.
                is_matching_acr_pair = (
                    (acr_a and not acr_b and _matches_initialism(acr_a, sb))
                    or (acr_b and not acr_a and _matches_initialism(acr_b, sa))
                )
                toks_a = {w for w in core_a.split() if w not in _STOPWORDS}
                toks_b = {w for w in core_b.split() if w not in _STOPWORDS}
                is_subunit_containment = bool(toks_a and toks_b and (toks_a <= toks_b or toks_b <= toks_a))

                # Catch high-boilerplate collisions (e.g. "American Heart Association" vs "American Hospital Association")
                # where overall raw_cos is inflated (~0.74) by generic words, yet non-generic core differs completely.
                non_generic_a = " ".join(sorted(toks_a - _GENERIC_ORG_WORDS))
                non_generic_b = " ".join(sorted(toks_b - _GENERIC_ORG_WORDS))
                non_generic_cos = (
                    _trigram_cosine(non_generic_a, non_generic_b)
                    if (non_generic_a and non_generic_b)
                    else core_cos
                )

                low_sim = (raw_cos < trigram_cosine_threshold and core_cos < 0.85 and not is_matching_acr_pair and not is_subunit_containment)
                boilerplate_collision = (
                    raw_cos < 0.82
                    and core_cos < 0.82
                    and non_generic_cos < 0.45
                    and not is_matching_acr_pair
                    and not is_subunit_containment
                )
                if low_sim or boilerplate_collision:
                    flags.append({
                        "direction": "direction1_overmerge",
                        "kind": "low_trigram_similarity",
                        "org_id": org_id,
                        "raw_strings": [sa, sb],
                        "trigram_cosine": round(raw_cos, 4),
                        "core_trigram_cosine": round(core_cos, 4),
                        "non_generic_trigram_cosine": round(non_generic_cos, 4),
                        "conflicts": ["boilerplate_word_swap" if boilerplate_collision and not low_sim else "trigram_cosine_below_threshold"],
                        "witness_keys": sorted(set(ma["witness_keys"][:5] + mb["witness_keys"][:5])),
                    })
                    org_flag_emitted_kinds.add("low_trigram_similarity")

        # Additional multi-expansion acronym check: if cluster contains an acronym (e.g. "AMA") AND
        # >=2 distinct full expansions ("American Medical Association" + "American Marketing Association")
        acrs = [s for s in raw_strings if _is_short_acronym(s)]
        fulls = [s for s in raw_strings if not _is_short_acronym(s)]
        if acrs and len(fulls) >= 2 and "acronym_collision" not in org_flag_emitted_kinds:
            for a_s in acrs:
                acr = _is_short_acronym(a_s)
                matching_fulls = [f for f in fulls if acr and _matches_initialism(acr, f)]
                if len(matching_fulls) >= 2:
                    for i in range(len(matching_fulls)):
                        for j in range(i + 1, len(matching_fulls)):
                            fa, fb = matching_fulls[i], matching_fulls[j]
                            if _trigram_cosine(fa, fb) < 0.85:
                                flags.append({
                                    "direction": "direction1_overmerge",
                                    "kind": "acronym_collision",
                                    "org_id": org_id,
                                    "raw_strings": [a_s, fa, fb],
                                    "trigram_cosine": round(_trigram_cosine(fa, fb), 4),
                                    "conflicts": [f"multiple_expansions_for_acronym:{acr}"],
                                    "witness_keys": sorted(set(meta_map[fa]["witness_keys"][:5] + meta_map[fb]["witness_keys"][:5])),
                                })

    return flags, leads, dict(stats)


def _check_direction2_missed_merges(
    org_records: Mapping[str, list[dict[str, Any]]],
    *,
    dice_threshold: float = 0.85,
    jaccard_threshold: float = 0.74,
    core_dice_threshold: float = 0.90,
    max_block_df: int = 300,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Direction 2: Rare-trigram inverted index blocking for likely missed merges across distinct org_ids."""
    stats = Counter()
    flags: list[dict[str, Any]] = []
    legitimate_splits: list[dict[str, Any]] = []

    # Build representative profiles per (org_id, distinct raw_text)
    profiles: list[dict[str, Any]] = []
    for org_id in sorted(org_records):
        by_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in org_records[org_id]:
            by_raw[e["raw_text"]].append(e)
        for raw_text in sorted(by_raw):
            rows = by_raw[raw_text]
            tset = _char_trigram_set(raw_text)
            if len(tset) < 5:
                continue
            core = _core_org_text(raw_text)
            core_tset = _char_trigram_set(core) if len(core) >= 8 else frozenset()
            profiles.append({
                "org_id": org_id,
                "raw_text": raw_text,
                "core_text": core,
                "tris": tset,
                "core_tris": core_tset,
                "geo": _extract_geo_scope(raw_text),
                "non_dc_loc_states": frozenset(e["loc_state"] for e in rows if e["loc_state"] and e["loc_state"] != "US:DC"),
                "gov_tiers": frozenset(e["tier"] for e in rows if e["tier"] in {"federal", "state", "local"}),
                "comm_domains": frozenset(d for e in rows for d in e["committee_domains"]),
                "witness_keys": [e["witness_key"] for e in rows[:5]],
            })

    if len(profiles) < 2:
        return flags, legitimate_splits, dict(stats)

    # Compute document frequency of 3-char trigrams across distinct profiles (including core trigrams for suffix misses)
    df: Counter[str] = Counter()
    for p in profiles:
        for g in (p["tris"] | p["core_tris"]):
            df[g] += 1

    # Prefix-filtered inverted index over rare trigrams (no O(N^2) all-pairs!)
    tau = max(0.50, min(jaccard_threshold, dice_threshold / (2.0 - dice_threshold)) - 0.12)
    order = sorted(range(len(profiles)), key=lambda i: (len(profiles[i]["tris"]), i))
    inv: dict[str, list[int]] = defaultdict(list)
    candidate_pairs: set[tuple[int, int]] = set()

    for idx in order:
        p = profiles[idx]
        combined = p["tris"] | p["core_tris"]
        ordered = sorted(combined, key=lambda g: (df[g], g))
        n = len(ordered)
        prefix_len = max(1, n - math.ceil(tau * n) + 1)
        prefix = ordered[:prefix_len]
        # Ensure at least the rarest trigram is considered if all prefix trigrams are slightly above max_block_df
        usable = [g for g in prefix if 2 <= df[g] <= max_block_df]
        if not usable and ordered:
            rarest = ordered[0]
            if 2 <= df[rarest] <= max_block_df * 3:
                usable = [rarest]
            elif df[rarest] > max_block_df * 3:
                stats["skipped_dense_trigram_blocks"] += 1

        stats["skipped_dense_trigram_slots"] += sum(1 for g in prefix if df[g] > max_block_df)
        for g in usable:
            for other_idx in inv.get(g, ()):
                if profiles[other_idx]["org_id"] == p["org_id"]:
                    continue
                pair = (other_idx, idx) if other_idx < idx else (idx, other_idx)
                candidate_pairs.add(pair)
            inv[g].append(idx)

    stats["candidate_pairs_evaluated"] = len(candidate_pairs)

    seen_org_pairs: set[tuple[str, str]] = set()
    for a_idx, b_idx in sorted(candidate_pairs):
        pa = profiles[a_idx]
        pb = profiles[b_idx]
        org_pair = (pa["org_id"], pb["org_id"]) if pa["org_id"] < pb["org_id"] else (pb["org_id"], pa["org_id"])
        if org_pair in seen_org_pairs:
            continue

        dice = _trigram_dice(pa["tris"], pb["tris"])
        jacc = _trigram_jaccard(pa["tris"], pb["tris"])
        core_dice = _trigram_dice(pa["core_tris"], pb["core_tris"]) if (pa["core_tris"] and pb["core_tris"]) else 0.0

        high_match = (
            dice >= dice_threshold
            or jacc >= jaccard_threshold
            or (core_dice >= core_dice_threshold and dice >= 0.72)
        )
        if not high_match:
            continue

        # Check whether this is a legitimate split vs a true missed merge
        geo_conflicts = _geo_scope_conflicts(pa["geo"], pb["geo"], pa["raw_text"], pb["raw_text"])
        meta_conflicts: list[str] = []
        if pa["non_dc_loc_states"] and pb["non_dc_loc_states"] and pa["non_dc_loc_states"].isdisjoint(pb["non_dc_loc_states"]):
            meta_conflicts.append(f"disjoint_witness_states:{sorted(pa['non_dc_loc_states'])}vs{sorted(pb['non_dc_loc_states'])}")
        if pa["gov_tiers"] and pb["gov_tiers"] and pa["gov_tiers"].isdisjoint(pb["gov_tiers"]):
            meta_conflicts.append(f"disjoint_jurisdiction_tiers:{sorted(pa['gov_tiers'])}vs{sorted(pb['gov_tiers'])}")

        minor_diff, diff_reason = _token_difference_is_minor(pa["raw_text"], pb["raw_text"])
        if (
            not minor_diff
            and pa["comm_domains"]
            and pb["comm_domains"]
            and pa["comm_domains"].isdisjoint(pb["comm_domains"])
        ):
            meta_conflicts.append(f"disjoint_committee_domains:{sorted(pa['comm_domains'])}vs{sorted(pb['comm_domains'])}")

        if geo_conflicts or meta_conflicts or not minor_diff:
            stats["legitimate_splits_verified"] += 1
            if len(legitimate_splits) < 50:
                legitimate_splits.append({
                    "org_ids": [pa["org_id"], pb["org_id"]],
                    "raw_strings": [pa["raw_text"], pb["raw_text"]],
                    "trigram_dice": round(dice, 4),
                    "trigram_jaccard": round(jacc, 4),
                    "split_reasons": geo_conflicts + meta_conflicts + ([diff_reason] if not minor_diff else []),
                })
            continue

        seen_org_pairs.add(org_pair)
        shared_comms = sorted(pa["comm_domains"] & pb["comm_domains"])
        shared_states = sorted(pa["non_dc_loc_states"] & pb["non_dc_loc_states"])
        flags.append({
            "direction": "direction2_missed_merge",
            "kind": "missed_merge",
            "reason": diff_reason,
            "org_ids": [pa["org_id"], pb["org_id"]],
            "raw_strings": [pa["raw_text"], pb["raw_text"]],
            "trigram_dice": round(dice, 4),
            "trigram_jaccard": round(jacc, 4),
            "core_trigram_dice": round(core_dice, 4),
            "compatible_context": {
                "shared_states": shared_states,
                "shared_committee_domains": shared_comms,
            },
            "witness_keys": sorted(set(pa["witness_keys"] + pb["witness_keys"])),
        })

    return flags, legitimate_splits, dict(stats)


def evaluate(
    witness_rows: Sequence[Mapping[str, Any]],
    witness_org_rows: Sequence[Mapping[str, Any]] = (),
    org_rows: Sequence[Mapping[str, Any]] = (),
    *,
    meeting_rows: Sequence[Mapping[str, Any]] = (),
    committee_rows: Sequence[Mapping[str, Any]] = (),
    detail_rows: Sequence[Mapping[str, Any]] = (),
    limit: int | None = None,
    max_flags: int | None = 200,
    max_unread_summary: int = 50,
    max_block_df: int = 300,
) -> dict[str, Any]:
    """Evaluate organization merges in both directions and account for every unread appearance row."""
    flat_rows, truncated_records = _flatten_witness_records(witness_rows, limit=limit)
    by_event, by_pkg, comm_name_by_code = _build_committee_lookup(meeting_rows, committee_rows, detail_rows)
    links_by_wk, _, bad_links = _linkage_index(witness_org_rows, org_rows)

    unread_records: list[dict[str, Any]] = list(truncated_records)
    org_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_witness_keys: set[str] = set()
    read_count = 0

    for row in flat_rows:
        wk = _ws(row.get("witness_key") or row.get("appearance_key"))
        src = row.get("source")
        sha = _hex(row.get("record_sha"))
        loc = row.get("source_locator")
        raw_org_preview = _ws(row.get("organization"))[:120] or None

        if not wk:
            unread_records.append({
                "row_index": row["row_index"],
                "witness_key": None,
                "reason": "null_or_blank_witness_key",
                "source": src,
                "record_sha": sha,
                "source_locator": loc,
                "raw_organization_preview": raw_org_preview,
            })
            continue

        seen_witness_keys.add(wk)
        links = links_by_wk.get(wk, [])
        if not links:
            org_val = _ws(row.get("organization"))
            behalf_val = _ws(row.get("on_behalf_of"))
            if not org_val and not behalf_val:
                reason = "blank_org_text"
            elif row.get("superseded_by") is not None and _ws(row.get("superseded_by")):
                reason = "superseded_unlinked"
            else:
                reason = "unmatched_in_witness_organizations"
            entry = {
                "row_index": row["row_index"],
                "witness_key": wk,
                "reason": reason,
                "source": src,
                "record_sha": sha,
                "source_locator": loc,
                "raw_organization_preview": raw_org_preview or (behalf_val[:120] if behalf_val else None),
            }
            if reason == "unmatched_in_witness_organizations":
                entry["is_placeholder"] = _clean_alnum(org_val) in _PLACEHOLDER_ORGS
            unread_records.append(entry)
            continue

        loc_state, loc_city = _extract_location_geo(row)
        tier = _extract_jurisdiction_tier(row)
        comms = _witness_committees(row, by_event, by_pkg, comm_name_by_code)
        comm_domains = _committee_domains(comms)

        for link in links:
            raw_text, source_field = _choose_raw_org_text(row, link)
            if not raw_text:
                unread_records.append({
                    "row_index": row["row_index"],
                    "witness_key": wk,
                    "org_id": link["org_id"],
                    "reason": "linked_blank_org_text",
                    "field": source_field,
                    "source": src,
                    "record_sha": sha,
                    "source_locator": loc,
                    "raw_organization_preview": None,
                })
                continue

            read_count += 1
            org_records[link["org_id"]].append({
                "witness_key": wk,
                "org_id": link["org_id"],
                "raw_text": raw_text,
                "source_field": source_field,
                "loc_state": loc_state,
                "loc_city": loc_city,
                "tier": tier,
                "committees": comms,
                "committee_domains": comm_domains,
            })

    for bl in bad_links:
        unread_records.append({
            "row_index": bl["row_index"],
            "witness_key": bl["witness_key"],
            "org_id": bl["org_id"],
            "reason": bl["reason"],
            "source": "witness_organizations",
            "record_sha": None,
            "source_locator": None,
            "raw_organization_preview": None,
        })
    for wk, links in sorted(links_by_wk.items()):
        if wk not in seen_witness_keys:
            for link in links:
                unread_records.append({
                    "row_index": link.get("link_index"),
                    "witness_key": wk,
                    "org_id": link["org_id"],
                    "reason": "dangling_witness_org_link_missing_witness",
                    "source": "witness_organizations",
                    "record_sha": None,
                    "source_locator": None,
                    "raw_organization_preview": link.get("raw_hint"),
                })

    d1_flags, leads, d1_stats = _check_direction1_overmerges(org_records)
    d2_flags, legit_splits, d2_stats = _check_direction2_missed_merges(
        org_records,
        max_block_df=max_block_df,
    )
    all_flags = d1_flags + d2_flags
    unread_by_reason = dict(sorted(Counter(r["reason"] for r in unread_records).items()))

    counts = {
        "total_witness_rows": len(flat_rows) + len(truncated_records),
        "processed_witness_rows": len(flat_rows),
        "read_linked_appearances": read_count,
        "unread_records_total": len(unread_records),
        "unread_by_reason": unread_by_reason,
        **d1_stats,
        **d2_stats,
        "direction1_flag_count": len(d1_flags),
        "direction2_flag_count": len(d2_flags),
    }

    return {
        "status": "passed" if not all_flags else "failed",
        "flag_count": len(all_flags),
        "direction1_flag_count": len(d1_flags),
        "direction2_flag_count": len(d2_flags),
        "flags_by_kind": dict(sorted(Counter(f["kind"] for f in all_flags).items())),
        "flags": all_flags if max_flags is None else all_flags[:max_flags],
        "lead_count": len(leads),
        "leads": leads[:50],
        "legitimate_splits_sample": legit_splits,
        "counts": counts,
        "unread_records": {
            "total_unread": len(unread_records),
            "by_reason": unread_by_reason,
            "summary": unread_records[:max_unread_summary],
            "records": unread_records,
        },
    }


def build_planted_baseline_fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Create a realistic clean baseline fixture covering valid merges and legitimate state splits."""
    witnesses = [
        # Valid homogeneous merges: article + U.S. prefix + corporate suffix
        {
            "witness_key": "wk_her_1",
            "organization": "The Heritage Foundation",
            "location": "Washington, DC",
            "position": "Senior Fellow",
            "committee": "House Committee on Ways and Means",
            "witness_type": "Non-Governmental",
        },
        {
            "witness_key": "wk_her_2",
            "organization": "Heritage Foundation",
            "location": "Washington, DC",
            "position": "Vice President",
            "committee": "Senate Committee on Finance",
            "witness_type": "Non-Governmental",
        },
        {
            "witness_key": "wk_doe_1",
            "organization": "U.S. Department of Energy",
            "location": "Washington, DC",
            "position": "Deputy Secretary",
            "committee": "Senate Committee on Energy and Natural Resources",
            "witness_type": "Government - Federal",
        },
        {
            "witness_key": "wk_doe_2",
            "organization": "Department of Energy",
            "location": "Washington, DC",
            "position": "Assistant Secretary",
            "committee": "House Committee on Energy and Commerce",
            "witness_type": "Government - Federal",
        },
        # Valid single-org multi-appearance
        {
            "witness_key": "wk_ama_1",
            "organization": "American Medical Association",
            "location": "Chicago, IL",
            "position": "President",
            "committee": "House Committee on Energy and Commerce",
            "witness_type": "Non-Governmental",
        },
        # Legitimate geographic split: Virginia vs West Virginia Council of Churches
        {
            "witness_key": "wk_vcc_1",
            "organization": "Virginia Council of Churches",
            "location": "Richmond, VA",
            "position": "Executive Director",
            "committee": "Senate Committee on the Judiciary",
            "witness_type": "Non-Governmental",
        },
        {
            "witness_key": "wk_wvcc_1",
            "organization": "West Virginia Council of Churches",
            "location": "Charleston, WV",
            "position": "Executive Director",
            "committee": "Senate Committee on the Judiciary",
            "witness_type": "Non-Governmental",
        },
    ]
    witness_orgs = [
        {"witness_key": "wk_her_1", "org_id": "org_heritage"},
        {"witness_key": "wk_her_2", "org_id": "org_heritage"},
        {"witness_key": "wk_doe_1", "org_id": "org_doe"},
        {"witness_key": "wk_doe_2", "org_id": "org_doe"},
        {"witness_key": "wk_ama_1", "org_id": "org_ama"},
        {"witness_key": "wk_vcc_1", "org_id": "org_va_churches"},
        {"witness_key": "wk_wvcc_1", "org_id": "org_wv_churches"},
    ]
    orgs = [
        {"org_id": "org_heritage", "canonical_name": "The Heritage Foundation"},
        {"org_id": "org_doe", "canonical_name": "U.S. Department of Energy"},
        {"org_id": "org_ama", "canonical_name": "American Medical Association"},
        {"org_id": "org_va_churches", "canonical_name": "Virginia Council of Churches"},
        {"org_id": "org_wv_churches", "canonical_name": "West Virginia Council of Churches"},
    ]
    return witnesses, witness_orgs, orgs


def run_planted_checks(
    witness_rows: Sequence[Mapping[str, Any]] | None = None,
    witness_org_rows: Sequence[Mapping[str, Any]] | None = None,
    org_rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    meeting_rows: Sequence[Mapping[str, Any]] = (),
    committee_rows: Sequence[Mapping[str, Any]] = (),
    detail_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Run planted wrong-merge and missed-merge scenarios and prove the check catches every plant."""
    if not witness_rows or not witness_org_rows:
        base_w, base_wo, base_o = build_planted_baseline_fixture()
        base_eval = evaluate(base_w, base_wo, base_o)
    else:
        base_w = [dict(r) for r in witness_rows]
        base_wo = [dict(r) for r in witness_org_rows]
        base_o = [dict(r) for r in org_rows]
        base_eval = None

    results: dict[str, Any] = {}
    if base_eval is not None:
        results["baseline_clean"] = {
            "passed": base_eval["flag_count"] == 0,
            "flag_count": base_eval["flag_count"],
            "legitimate_splits_verified": base_eval["counts"]["legitimate_splits_verified"],
        }

    # Plant 1 (ct-6him AC #5 required): Virginia Council of Churches + West Virginia Council of Churches wrong merge
    p1_w = list(base_w) + [
        {
            "witness_key": "plant_va_churches",
            "organization": "Virginia Council of Churches",
            "location": "Richmond, VA",
            "position": "Director",
            "committee": "Senate Committee on the Judiciary",
            "witness_type": "Non-Governmental",
        },
        {
            "witness_key": "plant_wv_churches",
            "organization": "West Virginia Council of Churches",
            "location": "Charleston, WV",
            "position": "Director",
            "committee": "Senate Committee on the Judiciary",
            "witness_type": "Non-Governmental",
        },
    ]
    p1_wo = list(base_wo) + [
        {"witness_key": "plant_va_churches", "org_id": "org_planted_va_wv"},
        {"witness_key": "plant_wv_churches", "org_id": "org_planted_va_wv"},
    ]
    p1_o = list(base_o) + [{"org_id": "org_planted_va_wv", "canonical_name": "Virginia Council of Churches"}]
    res1 = evaluate(
        p1_w, p1_wo, p1_o,
        meeting_rows=meeting_rows, committee_rows=committee_rows, detail_rows=detail_rows, max_flags=None,
    )
    hit1 = [
        f for f in res1["flags"]
        if f.get("org_id") == "org_planted_va_wv" and f["kind"] == "scope_or_state_conflict"
    ]
    results["virginia_west_virginia_merge"] = {
        "caught": bool(hit1),
        "expected_kind": "scope_or_state_conflict",
        "matched_flags": hit1,
    }

    # Plant 2: Conflicting witness state + federal/state position over-merge
    p2_w = list(base_w) + [
        {
            "witness_key": "plant_meta_1",
            "organization": "University of Washington",
            "location": "Seattle, WA",
            "position": "Governor's Higher Education Advisor",
            "committee": "Senate Committee on Health, Education, Labor, and Pensions",
            "witness_type": "Government - State",
        },
        {
            "witness_key": "plant_meta_2",
            "organization": "Washington University",
            "location": "St. Louis, MO",
            "position": "U.S. Federal Grant Commissioner",
            "committee": "Senate Committee on Health, Education, Labor, and Pensions",
            "witness_type": "Government - Federal",
        },
    ]
    p2_wo = list(base_wo) + [
        {"witness_key": "plant_meta_1", "org_id": "org_planted_meta"},
        {"witness_key": "plant_meta_2", "org_id": "org_planted_meta"},
    ]
    p2_o = list(base_o) + [{"org_id": "org_planted_meta", "canonical_name": "University of Washington"}]
    res2 = evaluate(
        p2_w, p2_wo, p2_o,
        meeting_rows=meeting_rows, committee_rows=committee_rows, detail_rows=detail_rows, max_flags=None,
    )
    hit2 = [
        f for f in res2["flags"]
        if f.get("org_id") == "org_planted_meta" and f["kind"] == "metadata_context_conflict"
    ]
    results["conflicting_metadata_overmerge"] = {
        "caught": bool(hit2),
        "expected_kind": "metadata_context_conflict",
        "matched_flags": hit2,
    }

    # Plant 3: Acronym collision over-merge
    p3_w = list(base_w) + [
        {
            "witness_key": "plant_acr_1",
            "organization": "AMA",
            "location": "Chicago, IL",
            "position": "Chief Medical Officer",
            "committee": "House Committee on Energy and Commerce",
        },
        {
            "witness_key": "plant_acr_2",
            "organization": "American Medical Association",
            "location": "Chicago, IL",
            "position": "President",
            "committee": "House Committee on Energy and Commerce",
        },
        {
            "witness_key": "plant_acr_3",
            "organization": "American Marketing Association",
            "location": "Chicago, IL",
            "position": "Executive Director",
            "committee": "House Committee on Energy and Commerce",
        },
    ]
    p3_wo = list(base_wo) + [
        {"witness_key": "plant_acr_1", "org_id": "org_planted_acr"},
        {"witness_key": "plant_acr_2", "org_id": "org_planted_acr"},
        {"witness_key": "plant_acr_3", "org_id": "org_planted_acr"},
    ]
    p3_o = list(base_o) + [{"org_id": "org_planted_acr", "canonical_name": "AMA"}]
    res3 = evaluate(
        p3_w, p3_wo, p3_o,
        meeting_rows=meeting_rows, committee_rows=committee_rows, detail_rows=detail_rows, max_flags=None,
    )
    hit3 = [
        f for f in res3["flags"]
        if f.get("org_id") == "org_planted_acr" and f["kind"] in {"acronym_collision", "low_trigram_similarity"}
    ]
    results["acronym_collision_overmerge"] = {
        "caught": bool(hit3),
        "expected_kind": "acronym_collision",
        "matched_flags": hit3,
    }

    # Plant 4 (Direction 2): Missed punctuation/suffix merge with compatible context
    p4_w = list(base_w) + [
        {
            "witness_key": "plant_miss_1",
            "organization": "Pacific Maritime Safety Institute",
            "location": "Seattle, WA",
            "position": "Executive Director",
            "committee": "House Committee on Transportation and Infrastructure",
        },
        {
            "witness_key": "plant_miss_2",
            "organization": "Pacific Maritime Safety Institute, Inc.",
            "location": "Seattle, WA",
            "position": "Director of Policy",
            "committee": "House Committee on Transportation and Infrastructure",
        },
    ]
    p4_wo = list(base_wo) + [
        {"witness_key": "plant_miss_1", "org_id": "org_planted_miss_a"},
        {"witness_key": "plant_miss_2", "org_id": "org_planted_miss_b"},
    ]
    p4_o = list(base_o) + [
        {"org_id": "org_planted_miss_a", "canonical_name": "Pacific Maritime Safety Institute"},
        {"org_id": "org_planted_miss_b", "canonical_name": "Pacific Maritime Safety Institute, Inc."},
    ]
    res4 = evaluate(
        p4_w, p4_wo, p4_o,
        meeting_rows=meeting_rows, committee_rows=committee_rows, detail_rows=detail_rows, max_flags=None,
    )
    hit4 = [
        f for f in res4["flags"]
        if f["kind"] == "missed_merge" and set(f.get("org_ids", ())) == {"org_planted_miss_a", "org_planted_miss_b"}
    ]
    results["missed_punctuation_suffix_merge"] = {
        "caught": bool(hit4),
        "expected_kind": "missed_merge",
        "matched_flags": hit4,
    }

    return results


def _format_markdown(report: Mapping[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Organization Fuzzy Merge Raw Check",
        "",
        f"- **Status**: `{report['status']}`",
        f"- **Flags**: `{report['flag_count']}` (Direction 1 over-merges: `{report['direction1_flag_count']}`, Direction 2 missed merges: `{report['direction2_flag_count']}`)",
        f"- **Leads**: `{report['lead_count']}`",
        f"- **Witness rows**: `{c['total_witness_rows']}` total, `{c['read_linked_appearances']}` linked appearances read, `{c['unread_records_total']}` unread",
        f"- **Orgs checked**: `{c['distinct_orgs_checked']}` distinct (`{c['multi_string_orgs_checked']}` multi-string), `{c['candidate_pairs_evaluated']}` rare-trigram pairs evaluated, `{c['legitimate_splits_verified']}` legitimate splits verified",
        "",
        "## Flags By Kind",
        "",
    ]
    if report["flags_by_kind"]:
        for k, v in report["flags_by_kind"].items():
            lines.append(f"- `{k}`: `{v}`")
    else:
        lines.append("- None")
    lines.extend(["", "## Unread Records By Reason", ""])
    if report["unread_records"]["by_reason"]:
        for k, v in report["unread_records"]["by_reason"].items():
            lines.append(f"- `{k}`: `{v}`")
    else:
        lines.append("- None")
    if report.get("plants"):
        lines.extend(["", "## Planted Defect Verification", ""])
        for name, res in report["plants"].items():
            ok = res.get("caught", res.get("passed"))
            lines.append(f"- `{name}`: `{'OK' if ok else 'FAILED'}`")
    return "\n".join(lines) + "\n"


def _resolve_optional_path(explicit: Path | None, release: Path | None, candidates: Sequence[str]) -> Path | None:
    if explicit is not None:
        return explicit
    if release is not None:
        for name in candidates:
            p = release / name
            if p.is_file():
                return p
    return None


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=None, help="Directory holding witness and org tables")
    parser.add_argument("--witnesses", "--appearances", dest="witnesses", type=Path, default=None)
    parser.add_argument("--witness-organizations", dest="witness_organizations", type=Path, default=None)
    parser.add_argument("--organizations", type=Path, default=None)
    parser.add_argument("--meetings", type=Path, default=None)
    parser.add_argument("--committees", type=Path, default=None)
    parser.add_argument("--detail", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on witness rows read (truncated rows are named)")
    parser.add_argument("--max-block-df", type=int, default=300, help="Max document frequency for rare-trigram blocking")
    parser.add_argument("--verify-planted", "--plant", dest="verify_planted", action="store_true")
    parser.add_argument("--fail-on-flags", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args(argv)

    w_path = _resolve_optional_path(
        args.witnesses,
        args.release,
        ("witnesses.parquet", "appearance_records.parquet", "witnesses.json", "witnesses.jsonl"),
    )
    wo_path = _resolve_optional_path(
        args.witness_organizations,
        args.release,
        ("witness_organizations.parquet", "witness_organizations.json", "witness_organizations.jsonl"),
    )
    o_path = _resolve_optional_path(
        args.organizations,
        args.release,
        ("organizations.parquet", "organizations.json", "organizations.jsonl"),
    )
    m_path = _resolve_optional_path(args.meetings, args.release, ("meetings.parquet", "meetings.json"))
    c_path = _resolve_optional_path(args.committees, args.release, ("committees.parquet", "committees.json"))
    d_path = _resolve_optional_path(args.detail, args.release, ("detail.parquet",))

    if w_path is None and not args.verify_planted:
        parser.error("Supply --release or --witnesses (or pass --verify-planted for standalone self-verification)")

    if w_path is not None:
        witness_rows = _read_records(w_path)
        witness_org_rows = _read_records(wo_path) if wo_path is not None else []
        org_rows = _read_records(o_path) if o_path is not None else []
        meeting_rows = _read_records(m_path) if m_path is not None else []
        committee_rows = _read_records(c_path) if c_path is not None else []
        detail_rows = _read_records(d_path) if d_path is not None else []
    else:
        witness_rows, witness_org_rows, org_rows = build_planted_baseline_fixture()
        meeting_rows, committee_rows, detail_rows = [], [], []

    report = evaluate(
        witness_rows,
        witness_org_rows,
        org_rows,
        meeting_rows=meeting_rows,
        committee_rows=committee_rows,
        detail_rows=detail_rows,
        limit=args.limit,
        max_block_df=args.max_block_df,
    )

    if args.verify_planted:
        plants = run_planted_checks(
            witness_rows if w_path is not None else None,
            witness_org_rows if w_path is not None else None,
            org_rows if w_path is not None else None,
            meeting_rows=meeting_rows,
            committee_rows=committee_rows,
            detail_rows=detail_rows,
        )
        report["plants"] = plants
        all_ok = all(
            res.get("caught", res.get("passed", False))
            for res in plants.values()
        )
        if not all_ok:
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
            raise SystemExit(f"Planted defect verification failed: {plants}")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    if args.output_md is not None:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(_format_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": report["status"],
                "flag_count": report["flag_count"],
                "direction1_flag_count": report["direction1_flag_count"],
                "direction2_flag_count": report["direction2_flag_count"],
                "flags_by_kind": report["flags_by_kind"],
                "lead_count": report["lead_count"],
                "counts": report["counts"],
                "plants": {
                    k: v.get("caught", v.get("passed")) for k, v in (report.get("plants") or {}).items()
                }
                if report.get("plants")
                else None,
            },
            default=str,
        )
    )

    if args.fail_on_flags and report["flag_count"] > 0:
        raise SystemExit(1)
    return report


if __name__ == "__main__":
    main()
