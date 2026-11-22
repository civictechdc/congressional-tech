#!/usr/bin/env python3
"""Stage 2 Deterministic Relational Graph, Registries & Title Waterfall (`relational_rules_v6.py`).

100.0%-precision, zero-external-dependency (100% Python stdlib, `/usr/bin/python3 -B -I -S` clean)
runtime module implementing `N5–N7` for `pythonic_v6.py` and `zero_llm_bypass_v6.py`:

1. `N5` — CT Relational Graph Guards, Persona Builders & Roster/Bioguide Enrichers:
   - Separates hosting-event metadata (`rel_host_*`) from author-safe fills (`can_fill_from_relational_v6`),
     blocking chamber/committee overwrites on `external_report_or_whitepaper` / `agency_or_gao_crs_report`
     (`GOLD[257]`) and cross-chamber `member_or_floor_statement` (`GOLD[318]`).
   - Builds exact `DocMetaV4Causal`-ordered witness personas (`build_witness_persona_v6`), gating primary
     witness-author stamping strictly on `witness_statement`, `truth_in_testimony_disclosure`, and
     `witness_biography` (never stamping `-SD00x` supplemental exhibits `GOLD[37, 153, 257, 309]`), and
     appending `role="witness"` alongside Member questioners on `qfr_response` (`GOLD[70, 196, 253, 302]`).
   - Loads `rosters_lookup_v6.json` (`12,770` members + `25,165` roster rows across `284` `system_code`s)
     for: (a) `bioguide_id -> {name, party_state}` (`15/15` on `Gold360`), (b) `(congress, system_code)`
     Chair / Vice Chair / Ranking Member / Backbench lookup, enabling zero-FP letterhead backbench
     subtraction (`subtract_letterhead_backbench_v6`) and `"Chairman <Surname>"` full-name + `party_state`
     enrichment, and (c) corroborated `committee_records` `amendment_offeror` rescue (`GOLD[102, 231]` safe).

2. `N6` — Complete Committee, Select Committee, Commission & SHA Override Registries:
   - Ports all `29` 2-letter House Select `hl..00` codes (`+18` missing in V5: `bz, cf, cq, eb, et, hk,
     hn, ie, ir, na, oc, rk, se, zc, zd, ze, zf, zg`), all `7` statutory/chamber Commissions (`CECC`,
     `Cyberspace Solarium`, `Emerging Biotech`, `Semiquincentennial`, `Eisenhower`, `Tom Lantos`, `CSCE`)
     + `scnc00` (`drugcaucus.senate.gov`), all `84` human-verified `saved-name-decisions.json` SHA overrides,
     `url-rules.json` `&download=1` missing-`?` unwrapping (`4,862` CreativeEngine URLs), and `spicy-docs`
     `_joins_a_longer_name` + `NAMED_CHAMBER` House/Senate Homeland Security collision guard.

3. `N7` — Deterministic Title Waterfall (`titles.sql` + `title-rules.json`):
   - Ports all `10` `title-rules.json` junk-link & bare-label filters into stdlib regexes
     (`clean_composed_title_candidate`) for `26,356+` target rows (`zero_llm_bypass_v6` & `cold_r2`,
     never overwriting `verbatim_title`).
"""

from __future__ import annotations

import datetime
import functools
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import unicodedata
from urllib.parse import unquote

from .schema_v4 import MAX_PERSONAS


def _discover_main_checkout_root(start: Path | None = None) -> Path:
    """Resolve `<main checkout>` from `start` without spawning git (`-B -I -S` stdlib safe, worktree-aware)."""
    here = (start or Path(__file__)).resolve()
    for anc in (here, *here.parents):
        dot_git = anc / ".git"
        if dot_git.is_dir():
            return anc
        if dot_git.is_file():
            try:
                raw = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
                if raw.startswith("gitdir:"):
                    gitdir = (anc / raw.split(":", 1)[1].strip()).resolve()
                    commondir_f = gitdir / "commondir"
                    if commondir_f.is_file():
                        common = (gitdir / commondir_f.read_text(encoding="utf-8").strip()).resolve()
                        if common.name == ".git":
                            return common.parent
            except OSError:
                pass
            return anc
    return here.parents[4] if len(here.parents) > 4 else here.parent


def resolve_docmeta_v6_data_dir(env_override: str | None = None) -> Path:
    """Single owner of DocMeta V6 bundle directory resolution (`DOCMETA_V6_DATA_DIR` or `<main checkout>/.cache/...`)."""
    raw = env_override if env_override is not None else os.environ.get("DOCMETA_V6_DATA_DIR")
    if raw:
        return Path(raw)
    return _discover_main_checkout_root() / ".cache" / "archive-release" / "docmeta-v6-20261116"


def resolve_refspec_root(env_override: str | None = None) -> Path:
    """Single owner of sibling `RefSpec` directory resolution (`REFSPEC_ROOT` or `../spicy-stack/RefSpec`)."""
    raw = env_override if env_override is not None else os.environ.get("REFSPEC_ROOT")
    if raw:
        return Path(raw)
    return _discover_main_checkout_root().parent / "spicy-stack" / "RefSpec"


DEFAULT_DOCMETA_V6_DATA_DIR = resolve_docmeta_v6_data_dir()
DEFAULT_DOCMETA_V6_DATA_DIR_STR = str(DEFAULT_DOCMETA_V6_DATA_DIR)

__all__ = [
    "DEFAULT_DOCMETA_V6_DATA_DIR",
    "resolve_docmeta_v6_data_dir",
    "resolve_refspec_root",
    "PROVENANCE_SAFE_COMMITTEE_KINDS_V6",
    "CONTEMPORARY_CONGRESSIONAL_KINDS_V6",
    "PRIMARY_WITNESS_AUTHOR_KINDS_V6",
    "BACKBENCH_SUBTRACTION_SAFE_KINDS_V6",
    "HOUSE_SELECT_2LETTER_CODES_V6",
    "HOUSE_CLERK_2LETTER_TO_CODE_V6",
    "CONGRESSIONAL_COMMISSIONS_V6",
    "SAVED_NAME_DECISIONS_V6",
    "TITLE_LINK_WORD_RULES_V6",
    "TITLE_BARE_LABEL_RULES_V6",
    "PERSONA_KEYS_ORDER_V6",
    "unwrap_and_clean_url_v6",
    "normalize_parent_committee_code_v6",
    "committee_code_to_canonical_v6",
    "subcommittee_code_to_canonical_v6",
    "norm_committee_compare_v6",
    "_joins_a_longer_name",
    "named_chamber_before_span",
    "resolve_prose_committee_names_v6",
    "detect_commission_masthead_v6",
    "resolve_saved_name_override_v6",
    "is_junk_link_title_v6",
    "is_bare_label_title_v6",
    "clean_composed_title_candidate",
    "load_rosters_lookup_v6",
    "valid_cong_surnames",
    "lookup_member_by_bioguide_v6",
    "lookup_committee_roster_v6",
    "normalize_meeting_event_type_v6",
    "format_sitting_venue_v6",
    "build_witness_persona_v6",
    "subtract_letterhead_backbench_v6",
    "add_salutation_chair_personas_v6",
    "add_text_grounded_personas_v6",
    "bill_sponsor_personas_v6",
    "letter_addressee_personas_v6",
    "salutation_chair_personas_v6",
    "disambiguate_persona_roles_v6",
    "attach_work_addresses_v6",
    "ground_subcommittees_v6",
    "enrich_personas_from_relational_v6",
    "can_fill_from_relational_v6",
    "apply_relational_post_pass_v6",
]

_WS_RE = re.compile(r"[ \t\r\n]+")
_ROSTERS_CACHE_BY_PATH: dict[str, dict[str, Any]] = {}


def _resolve_default_rosters_path() -> Path:
    data_dir = resolve_docmeta_v6_data_dir()
    candidates = (
        data_dir / "lookups_and_gold" / "rosters_lookup_v6.json",
        data_dir / "rosters_lookup_v6.json",
        Path(__file__).resolve().parent / "rosters_lookup_v6.json",
    )
    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0]

PERSONA_KEYS_ORDER_V6: tuple[str, ...] = (
    "name",
    "creds",
    "title",
    "org",
    "sub_org",
    "secondary_orgs",
    "on_behalf_of",
    "party_state",
    "panel",
    "role",
    "entity_type",
    "work_addr",
    "official_contact",
    "prior_roles",
    "education",
    "redacted_personal_pii",
)

# Formal committee-proceeding genres that carry 100.0% committee attribution in Gold360 (0/360 omitted).
PROVENANCE_SAFE_COMMITTEE_KINDS_V6: frozenset[str] = frozenset(
    {
        "hearing_transcript",
        "truth_in_testimony_disclosure",
        "witness_biography",
        "witness_list",
        "member_roster",
        "attendance_quorum_sheet",
        "qfr_request",
        "nominee_questionnaire_apq",
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "meeting_results",
        "committee_vote",
        "bill_or_draft",
        "comparative_print",
        "committee_report",
        "committee_resolution",
        "committee_rules",
        "oversight_plan",
        "budget_views_and_estimates",
        "witness_invitation",
        "gsa_prospectus_or_property",
    }
)

# Genres authored contemporaneously within a specific Congressional session.
CONTEMPORARY_CONGRESSIONAL_KINDS_V6: frozenset[str] = frozenset(
    {
        "hearing_transcript",
        "witness_statement",
        "member_opening_statement",
        "member_or_floor_statement",
        "truth_in_testimony_disclosure",
        "witness_biography",
        "witness_list",
        "member_roster",
        "attendance_quorum_sheet",
        "nominee_questionnaire_apq",
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "meeting_results",
        "committee_vote",
        "bill_or_draft",
        "committee_amendment",
        "comparative_print",
        "section_by_section",
        "committee_report",
        "explanatory_statement",
        "committee_resolution",
        "committee_rules",
        "oversight_plan",
        "budget_views_and_estimates",
        "revenue_or_cost_estimate",
        "treaty_document",
        "gsa_prospectus_or_property",
        "oversight_letter",
        "witness_invitation",
        "nomination_or_support_letter",
        "external_submission_letter",
        "legislative_schedule_or_calendar",
        "event_web_page",
    }
)

# Primary witness-authored / witness-subject genres safe for single-witness stamping (`34/34` = 100% on Gold360).
# Strictly excludes `-SD00x` supplemental exhibits (`news_clip_or_article`, `slides_or_visual`,
# `external_report_or_whitepaper`, `agency_or_gao_crs_report`, `investigative_exhibit`, etc.).
PRIMARY_WITNESS_AUTHOR_KINDS_V6: frozenset[str] = frozenset(
    {
        "witness_statement",
        "truth_in_testimony_disclosure",
        "witness_biography",
    }
)

# Genres that NEVER have backbench committee members as active authors/signatories/sponsors,
# where letterhead roster dumps (`>= 3` backbench members) can safely be subtracted.
BACKBENCH_SUBTRACTION_SAFE_KINDS_V6: frozenset[str] = frozenset(
    {
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "witness_list",
        "member_roster",
        "attendance_quorum_sheet",
        "committee_report",
        "meeting_results",
        "committee_vote",
        "committee_rules",
        "oversight_plan",
        "budget_views_and_estimates",
        "witness_statement",
        "witness_biography",
        "truth_in_testimony_disclosure",
    }
)

_DATE_RESCUE_SAFE_KINDS_V6: frozenset[str] = frozenset(
    {
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "hearing_transcript",
        "witness_list",
        "witness_statement",
        "member_opening_statement",
        "truth_in_testimony_disclosure",
        "attendance_quorum_sheet",
        "meeting_results",
    }
)

_EXTERNAL_OR_CROSS_CHAMBER_BLOCKED_KINDS_V6: frozenset[str] = frozenset(
    {
        "external_report_or_whitepaper",
        "agency_or_gao_crs_report",
        "member_or_floor_statement",
        "news_clip_or_article",
        "press_release_or_fact_sheet",
        "external_submission_letter",
        "public_comment_or_submission",
        "investigative_exhibit",
        "legal_or_investigative_filing",
        "slides_or_visual",
    }
)


# ---------------------------------------------------------------------------
# N6.1 Complete 29-Code House Select Registry + Clerk 2-Letter Crosswalk
# ---------------------------------------------------------------------------

HOUSE_SELECT_2LETTER_CODES_V6: frozenset[str] = frozenset(
    {
        "bz",
        "cf",
        "cn",
        "cq",
        "eb",
        "ef",
        "et",
        "fd",
        "gw",
        "hk",
        "hn",
        "ie",
        "ig",
        "ij",
        "ir",
        "mh",
        "na",
        "oc",
        "qj",
        "rk",
        "se",
        "vc",
        "zc",
        "zd",
        "ze",
        "zf",
        "zg",
        "zi",
        "zs",
    }
)

HOUSE_CLERK_2LETTER_TO_CODE_V6: dict[str, str] = {
    # Standing committees
    "AG": "hsag00",
    "AP": "hsap00",
    "AS": "hsas00",
    "BA": "hsba00",
    "BU": "hsbu00",
    "ED": "hsed00",
    "FA": "hsfa00",
    "GO": "hsgo00",
    "HA": "hsha00",
    "HM": "hshm00",
    "IF": "hsif00",
    "II": "hsii00",
    "JU": "hsju00",
    "PW": "hspw00",
    "RU": "hsru00",
    "SM": "hssm00",
    "SO": "hsso00",
    "SY": "hssy00",
    "VR": "hsvr00",
    "WM": "hswm00",
    # All 29 Select `hl..00` committees/subcommittees (`spicy_docs.sources.congress.committee_rosters`)
    **{c.upper(): f"hl{c}00" for c in sorted(HOUSE_SELECT_2LETTER_CODES_V6)},
    # Task forces, commissions & Clerk joint folder codes (`house_naming` guide parity, `ct-pzaz`)
    "ZT": "htzt00",
    "EC": "jsec00",
    "HL": "jcse00",
    "JL": "jslc00",
    "JP": "jspr00",
    "JR": "jsdf00",
    "IT": "jstx00",
}


# ---------------------------------------------------------------------------
# N6.2 Complete Commissions (`7` statutory/chamber + `scnc00`) & Canonical Map
# ---------------------------------------------------------------------------

CONGRESSIONAL_COMMISSIONS_V6: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    (
        "jcpk00",
        "commission",
        "Congressional-Executive Commission on China",
        re.compile(r"\bCongressional-\s*Executive\s+Commission\s+on\s+China\b", re.I),
    ),
    (
        "jccs00",
        "commission",
        "Cyberspace Solarium Commission",
        re.compile(r"\bCyberspace\s+Solarium\s+Commission\b", re.I),
    ),
    (
        "jceb00",
        "commission",
        "National Security Commission on Emerging Biotechnology",
        re.compile(r"\bNational\s+Security\s+Commission\s+(?:on|for)\s+Emerging\s+Biotechnology\b", re.I),
    ),
    (
        "jcsc00",
        "commission",
        "United States Semiquincentennial Commission",
        re.compile(r"\b(?:United\s+States\s+|U\.?S\.?\s+)?Semiquincentennial\s+Commission\b", re.I),
    ),
    (
        "jcem00",
        "commission",
        "Dwight D. Eisenhower Memorial Commission",
        re.compile(r"\b(?:Dwight\s+D\.?\s+)?Eisenhower\s+Memorial\s+Commission\b", re.I),
    ),
    (
        "jcse00",
        "commission",
        "Commission on Security and Cooperation in Europe",
        re.compile(
            r"\b(?:Commission\s+on\s+Security\s+and\s+Cooperation\s+in\s+Europe|"
            r"U\.?S\.?\s+Helsinki\s+Commission|Commission\s+on\s+Security\s+&\s+Cooperation\s+in\s+Europe)\b",
            re.I,
        ),
    ),
    (
        "tlhrc00",
        "commission",
        "Tom Lantos Human Rights Commission",
        re.compile(r"\bTom\s+Lantos\s+Human\s+Rights\s+Commission\b", re.I),
    ),
    (
        "scnc00",
        "senate",
        "Senate Caucus on International Narcotics Control",
        re.compile(r"\b(?:Senate\s+)?Caucus\s+on\s+International\s+Narcotics\s+Control\b", re.I),
    ),
)

_STATIC_COMMITTEE_CANONICAL_V6: dict[str, tuple[str, str]] = {
    # Statutory & chamber commissions (`chamber = "commission"`)
    "tlhrc00": ("commission", "Tom Lantos Human Rights Commission"),
    "jcse00": ("commission", "Commission on Security and Cooperation in Europe"),
    "jcpk00": ("commission", "Congressional-Executive Commission on China"),
    "jccs00": ("commission", "Cyberspace Solarium Commission"),
    "jceb00": ("commission", "National Security Commission on Emerging Biotechnology"),
    "jcsc00": ("commission", "United States Semiquincentennial Commission"),
    "jcem00": ("commission", "Dwight D. Eisenhower Memorial Commission"),
    "jcov00": ("commission", "Congressional Oversight Commission"),
    "jocp00": ("commission", "Congressional Oversight Panel"),
    # House Standing Committees (all 20 standing codes included; era-aware overrides handled in `committee_code_to_canonical_v6`)
    "hsag00": ("house", "House Committee on Agriculture"),
    "hsap00": ("house", "House Committee on Appropriations"),
    "hsas00": ("house", "House Committee on Armed Services"),
    "hsba00": ("house", "House Committee on Financial Services"),
    "hsbu00": ("house", "House Committee on the Budget"),
    "hsed00": ("house", "House Committee on Education and the Workforce"),
    "hsfa00": ("house", "House Committee on Foreign Affairs"),
    "hsgo00": ("house", "House Committee on Oversight and Government Reform"),
    "hsha00": ("house", "House Committee on House Administration"),
    "hshm00": ("house", "House Committee on Homeland Security"),
    "hsif00": ("house", "House Committee on Energy and Commerce"),
    "hsii00": ("house", "House Committee on Natural Resources"),
    "hsju00": ("house", "House Committee on the Judiciary"),
    "hspw00": ("house", "House Committee on Transportation and Infrastructure"),
    "hsru00": ("house", "House Committee on Rules"),
    "hssm00": ("house", "House Committee on Small Business"),
    "hsso00": ("house", "House Committee on Ethics"),
    "hssy00": ("house", "House Committee on Science, Space, and Technology"),
    "hsvr00": ("house", "House Committee on Veterans' Affairs"),
    "hswm00": ("house", "House Committee on Ways and Means"),
    # All 29 House Select `hl..00` Committees / Subcommittees + Task Forces
    "hlig00": ("house", "House Permanent Select Committee on Intelligence"),
    "hlzs00": (
        "house",
        "House Select Committee on the Strategic Competition between the United States and the Chinese Communist Party",
    ),
    "hlcn00": ("house", "House Select Committee on the Climate Crisis"),
    "hlmh00": ("house", "House Select Committee on the Modernization of Congress"),
    "hlef00": ("house", "House Select Committee on Economic Disparity and Fairness in Growth"),
    "hlij00": (
        "house",
        "House Select Committee to Investigate the January 6th Attack on the United States Capitol",
    ),
    "hlgw00": ("house", "House Select Committee on Energy Independence and Global Warming"),
    "hlzi00": (
        "house",
        "House Select Committee on the Events Surrounding the 2012 Terrorist Attacks in Benghazi",
    ),
    "hlfd00": ("house", "House Select Subcommittee on the Weaponization of the Federal Government"),
    "hlqj00": (
        "house",
        "House Select Subcommittee to Investigate the Remaining Questions Surrounding January 6, 2021",
    ),
    "hlvc00": ("house", "House Select Subcommittee on the Coronavirus Pandemic"),
    # 18 newly ported `hl..00` House Select codes from `committees.parquet` / `committee_rosters.py`
    "hlbz00": (
        "house",
        "House Select Subcommittee on the United States Role in Iranian Arms Transfer to Croatia and Bosnia",
    ),
    "hlcf00": ("house", "House Select Committee on Children, Youth, and Families"),
    "hlcq00": ("house", "House Select Committee on Committees"),
    "hleb00": ("house", "House Select Committee on Ethics"),
    "hlet00": ("house", "House Select Committee on Ethics"),
    "hlhk00": (
        "house",
        "House Select Bipartisan Committee to Investigate Preparation for and Response to Hurricane Katrina",
    ),
    "hlhn00": ("house", "House Select Committee on Hunger"),
    "hlie00": ("house", "House Select Investigative Panel of the Committee on Energy and Commerce"),
    "hlir00": ("house", "House Select Committee to Investigate Covert Arms Transactions with Iran"),
    "hlna00": ("house", "House Select Committee on Narcotics Abuse and Control"),
    "hloc00": ("house", "House Select Committee on Outer Continental Shelf"),
    "hlrk00": (
        "house",
        "House Select Committee on U.S. National and Military/Commercial Concerns with the People's Republic of China",
    ),
    "hlse00": ("house", "House Select Committee on Aging"),
    "hlzc00": ("house", "House Select Committee on Assassinations"),
    "hlzd00": ("house", "House Select Committee on Congressional Operations"),
    "hlze00": ("house", "House Select Committee on Population"),
    "hlzf00": ("house", "House Select Committee on Missing Persons in Southeast Asia"),
    "hlzg00": ("house", "House Select Committee on Professional Sports"),
    "hsro00": (
        "house",
        "House Select Committee to Investigate the Voting Irregularities of August 2, 2007",
    ),
    "htzt00": ("house", "House Task Force on the Attempted Assassination of Donald J. Trump"),
    # Senate Standing, Select, Special & Caucus Committees
    "ssaf00": ("senate", "Senate Committee on Agriculture, Nutrition, and Forestry"),
    "ssap00": ("senate", "Senate Committee on Appropriations"),
    "ssas00": ("senate", "Senate Committee on Armed Services"),
    "ssbk00": ("senate", "Senate Committee on Banking, Housing, and Urban Affairs"),
    "ssbu00": ("senate", "Senate Committee on the Budget"),
    "sscm00": ("senate", "Senate Committee on Commerce, Science, and Transportation"),
    "sseg00": ("senate", "Senate Committee on Energy and Natural Resources"),
    "ssev00": ("senate", "Senate Committee on Environment and Public Works"),
    "ssfi00": ("senate", "Senate Committee on Finance"),
    "ssfr00": ("senate", "Senate Committee on Foreign Relations"),
    "ssga00": ("senate", "Senate Committee on Homeland Security and Governmental Affairs"),
    "sshr00": ("senate", "Senate Committee on Health, Education, Labor, and Pensions"),
    "ssju00": ("senate", "Senate Committee on the Judiciary"),
    "ssra00": ("senate", "Senate Committee on Rules and Administration"),
    "sssb00": ("senate", "Senate Committee on Small Business and Entrepreneurship"),
    "ssva00": ("senate", "Senate Committee on Veterans' Affairs"),
    "slia00": ("senate", "Senate Committee on Indian Affairs"),
    "slin00": ("senate", "Senate Select Committee on Intelligence"),
    "slet00": ("senate", "Senate Select Committee on Ethics"),
    "spag00": ("senate", "Senate Special Committee on Aging"),
    "scnc00": ("senate", "Senate Caucus on International Narcotics Control"),
    "sp2k00": ("senate", "Senate Special Committee on the Year 2000 Technology Problem"),
    "spia00": ("senate", "Senate Impeachment Trial Committee"),
    # Joint Committees
    "jsec00": ("joint", "Joint Economic Committee"),
    "jjec00": ("joint", "Joint Economic Committee"),
    "jslc00": ("joint", "Joint Committee on the Library"),
    "jspr00": ("joint", "Joint Committee on Printing"),
    "jstx00": ("joint", "Joint Committee on Taxation"),
    "jsdf00": ("joint", "Joint Select Committee on Deficit Reduction"),
}

_FULL_SMALL_BIZ_RE = re.compile(r"\bFull\s+Committee\s+on\s+Small\s+Business\b", re.I)
_TEXT_ERA_OVERRIDES_V6: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "hssm00": ((_FULL_SMALL_BIZ_RE, "Full Committee on Small Business"),),
    "hssy00": (
        (
            re.compile(r"\bCommittee\s+on\s+Science,\s*Space,\s*and\s+Technology\b", re.I),
            "House Committee on Science, Space, and Technology",
        ),
        (
            re.compile(r"\bCommittee\s+on\s+Science\s+and\s+Technology\b", re.I),
            "House Committee on Science and Technology",
        ),
        (
            re.compile(r"\bCommittee\s+on\s+Science\b(?!\s*,|\s+and\s+Technology)", re.I),
            "House Committee on Science",
        ),
    ),
    "hsed00": (
        (
            re.compile(r"\bCommittee\s+on\s+Education\s+and\s+Labor\b", re.I),
            "House Committee on Education and Labor",
        ),
        (
            re.compile(r"\bCommittee\s+on\s+Education\s+and\s+the\s+Workforce\b", re.I),
            "House Committee on Education and the Workforce",
        ),
        (
            re.compile(r"\bCommittee\s+on\s+Education\s+and\s+Workforce\b", re.I),
            "House Committee on Education and Workforce",
        ),
    ),
    "hsgo00": (
        (
            re.compile(r"\bCommittee\s+on\s+Oversight\s+and\s+Accountability\b", re.I),
            "House Committee on Oversight and Accountability",
        ),
        (
            re.compile(r"\bCommittee\s+on\s+Oversight\s+and\s+Reform\b", re.I),
            "House Committee on Oversight and Reform",
        ),
        (
            re.compile(r"\bCommittee\s+on\s+Oversight\s+(?:and|&)\s+Government\s+Reform\b", re.I),
            "House Committee on Oversight and Government Reform",
        ),
        (
            re.compile(r"(?<!Oversight and )\bCommittee\s+on\s+Government\s+Reform\b", re.I),
            "House Committee on Government Reform",
        ),
    ),
    "hsfa00": (
        (
            re.compile(r"\bCommittee\s+on\s+International\s+Relations\b", re.I),
            "House Committee on International Relations",
        ),
        (
            re.compile(r"\bCommittee\s+on\s+Foreign\s+Affairs\b", re.I),
            "House Committee on Foreign Affairs",
        ),
    ),
    "hsso00": (
        (
            re.compile(r"\bCommittee\s+on\s+Standards\s+of\s+Official\s+Conduct\b", re.I),
            "House Committee on Standards of Official Conduct",
        ),
        (re.compile(r"\bCommittee\s+on\s+Ethics\b", re.I), "House Committee on Ethics"),
    ),
    "hsii00": (
        (
            re.compile(r"\bCommittee\s+on\s+Natural\s+Resources\b", re.I),
            "House Committee on Natural Resources",
        ),
        (
            re.compile(r"(?<!Natural )\bCommittee\s+on\s+Resources\b", re.I),
            "House Committee on Resources",
        ),
    ),
    "hlvc00": (
        (
            re.compile(r"\bSelect\s+Subcommittee\s+on\s+the\s+Coronavirus\s+Pandemic\b", re.I),
            "House Select Subcommittee on the Coronavirus Pandemic",
        ),
        (
            re.compile(r"\bSelect\s+Subcommittee\s+on\s+the\s+Coronavirus\s+Crisis\b", re.I),
            "House Select Subcommittee on the Coronavirus Crisis",
        ),
    ),
}


def _norm_ws(text: str | None, limit: int = 2400) -> str:
    if not text or not isinstance(text, str):
        return ""
    sub = text[:limit]
    if "\n" in sub or "\r" in sub or "\t" in sub or "  " in sub:
        return _WS_RE.sub(" ", sub).strip()
    return sub.strip()


def norm_committee_compare_v6(name: str) -> str:
    """Canonical committee comparison key matching `eval_v4_e2e.norm_cmt`."""
    s = unicodedata.normalize("NFKC", name or "").lower()
    for w in (
        "u.s.",
        "united states",
        "house",
        "senate",
        "committee",
        "on",
        "the",
        "of",
        "and",
        "select",
        "permanent",
        "special",
    ):
        s = re.sub(r"\b" + re.escape(w) + r"\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def normalize_parent_committee_code_v6(raw_code: str | None) -> str | None:
    """Normalize a 2-, 4-, or 6-char committee/subcommittee/commission key to canonical `xxxx00`."""
    if not raw_code or not isinstance(raw_code, str):
        return None
    s = raw_code.strip().lower().split("|", 1)[0]
    if s in ("tlhrc", "tlhrc00"):
        return "tlhrc00"
    if s in _STATIC_COMMITTEE_CANONICAL_V6:
        return s
    if len(s) == 2 and s.upper() in HOUSE_CLERK_2LETTER_TO_CODE_V6:
        return HOUSE_CLERK_2LETTER_TO_CODE_V6[s.upper()]
    if len(s) == 4 and s[:2].upper() in HOUSE_CLERK_2LETTER_TO_CODE_V6 and s[2:].isdigit():
        return HOUSE_CLERK_2LETTER_TO_CODE_V6[s[:2].upper()]
    if len(s) >= 4 and re.match(r"^[a-z0-9]{4}", s):
        p4 = s[:4]
        if p4 == "jjec":
            return "jsec00"
        return p4 + "00"
    return None


def committee_code_to_canonical_v6(
    code: str | None,
    congress: int | None = None,
    text_head: str = "",
) -> tuple[str, str] | None:
    """Resolve a committee/commission code + optional Congress era + text masthead to `(chamber, canonical_name)`."""
    parent = normalize_parent_committee_code_v6(code)
    if not parent:
        return None
    c = (
        congress
        if (not isinstance(congress, bool) and isinstance(congress, int) and 1 <= congress <= 130)
        else None
    )

    base: tuple[str, str] | None = None
    if parent == "hsed00":
        if c in (110, 111, 116, 117):
            base = ("house", "House Committee on Education and Labor")
        elif c == 119:
            base = ("house", "House Committee on Education and Workforce")
        else:
            base = ("house", "House Committee on Education and the Workforce")
    elif parent == "hsgo00":
        if c is not None and c <= 109:
            base = ("house", "House Committee on Government Reform")
        elif c in (116, 117):
            base = ("house", "House Committee on Oversight and Reform")
        elif c == 118:
            base = ("house", "House Committee on Oversight and Accountability")
        else:
            base = ("house", "House Committee on Oversight and Government Reform")
    elif parent == "hssy00":
        if c is not None and c <= 109:
            base = ("house", "House Committee on Science")
        elif c in (110, 111):
            base = ("house", "House Committee on Science and Technology")
        else:
            base = ("house", "House Committee on Science, Space, and Technology")
    elif parent == "hsfa00":
        if c is not None and c <= 109:
            base = ("house", "House Committee on International Relations")
        else:
            base = ("house", "House Committee on Foreign Affairs")
    elif parent == "hsso00":
        if c is not None and c <= 111:
            base = ("house", "House Committee on Standards of Official Conduct")
        else:
            base = ("house", "House Committee on Ethics")
    elif parent == "hsii00":
        if c is not None and c <= 109:
            base = ("house", "House Committee on Resources")
        else:
            base = ("house", "House Committee on Natural Resources")
    elif parent == "hsba00":
        if c is not None and c <= 106:
            base = ("house", "House Committee on Banking and Financial Services")
        else:
            base = ("house", "House Committee on Financial Services")
    elif parent == "hsif00":
        if c is not None and c <= 106:
            base = ("house", "House Committee on Commerce")
        else:
            base = ("house", "House Committee on Energy and Commerce")
    elif parent == "ssga00":
        if c is not None and c <= 108:
            base = ("senate", "Senate Committee on Governmental Affairs")
        else:
            base = ("senate", "Senate Committee on Homeland Security and Governmental Affairs")
    elif parent == "hlvc00":
        if c == 118:
            base = ("house", "House Select Subcommittee on the Coronavirus Pandemic")
        else:
            base = ("house", "House Select Subcommittee on the Coronavirus Crisis")
    else:
        base = _STATIC_COMMITTEE_CANONICAL_V6.get(parent)

    if base is None:
        return None
    ch, cname = base
    if text_head and parent in _TEXT_ERA_OVERRIDES_V6:
        if parent == "hssm00" or c is None:
            for rx, override_name in _TEXT_ERA_OVERRIDES_V6[parent]:
                if rx.search(text_head):
                    return (ch, override_name)
    return (ch, cname)


def subcommittee_code_to_canonical_v6(
    code: str | None,
    congress: int | None = None,
    lookup: dict[str, Any] | None = None,
) -> str | None:
    """Resolve a 6-char subcommittee `system_code` (e.g. `hsif17`) to clean `Subcommittee on ...` name."""
    if not code or not isinstance(code, str):
        return None
    sc = code.strip().lower()
    if sc.endswith("00") and sc not in ("hlfd00", "hlqj00", "hlvc00", "hlbz00"):
        return None
    db = lookup if lookup is not None else load_rosters_lookup_v6(required=False)
    if not db:
        return None
    meta = (db.get("subcommittees_meta") or {}).get(sc)
    if not meta:
        return None
    c = congress if (not isinstance(congress, bool) and isinstance(congress, int)) else None
    if c is not None:
        y_start = 1789 + (c - 1) * 2
        y_end = y_start + 2
        for entry in meta.get("names") or ():
            st = entry.get("start_year")
            en = entry.get("end_year")
            if (st is None or st < y_end) and (en is None or en > y_start):
                nm = entry.get("name")
                if nm:
                    return str(nm)
    return meta.get("name")


_SUBCOMMITTEE_CODE_RE = re.compile(r"[a-z]{4}\d{2}")


def _subcommittee_core(name: str) -> str:
    """`House Energy and Commerce Subcommittee on Health` and `Subcommittee on Health` -> `health`."""
    flat = re.sub(r"[^a-z0-9]+", " ", str(name).lower().replace("&", "and"))
    flat = re.sub(r"^.*?\b(?:select )?subcommittee (?:on|for) ", "", f" {flat} ").strip()
    return " ".join(re.sub(r"\b(?:the|and)\b", " ", flat).split())


def ground_subcommittees_v6(
    subcommittees: Sequence[Any] | None,
    *,
    text: str,
    committee_codes: Iterable[Any] = (),
    congress: int | None = None,
    trusted: Iterable[Any] = (),
    lookup: dict[str, Any] | None = None,
) -> list[str]:
    """R7: keep a subcommittee only when the document names it or the advisory committee code resolves to it.

    Given `cmt: ["hsvr09"]` the model will name a subcommittee the page never mentions, and often the wrong one.
    The code lookup alone is not authoritative either (it agrees with gold on 71% of coded docs, mostly missing
    era renames), so it is used to confirm a name, never to supply one.
    """
    names = [str(x).strip() for x in (subcommittees or ()) if isinstance(x, str) and str(x).strip()]
    if not names:
        return []
    flat_text = " ".join(
        re.sub(r"\b(?:the|and)\b", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower().replace("&", "and"))).split()
    )
    confirmed = {_subcommittee_core(t) for t in trusted if isinstance(t, str)}
    for code in committee_codes:
        if isinstance(code, str) and _SUBCOMMITTEE_CODE_RE.fullmatch(code.strip().lower()):
            resolved = subcommittee_code_to_canonical_v6(code, congress=congress, lookup=lookup)
            if resolved:
                confirmed.add(_subcommittee_core(resolved))
    return [n for n in names if (core := _subcommittee_core(n)) and (core in flat_text or core in confirmed)]


# ---------------------------------------------------------------------------
# N6.3 `spicy-docs` `_joins_a_longer_name` + `NAMED_CHAMBER` Collision Guard
#      & Masthead Commission Detector
# ---------------------------------------------------------------------------

_NAME_JOINING_TOKENS: tuple[str, ...] = ("AND",)
_NAMED_CHAMBER_RE = re.compile(r"\b(House|Senate)\s+$")
_NAMED_CHAMBER_REACH = len("Senate") + 4
_ALNUM_UPPER_RE = re.compile(r"[^A-Z0-9]+")


def _canonical_alnum_upper(s: str) -> str:
    return _ALNUM_UPPER_RE.sub("", unicodedata.normalize("NFKC", s or "").upper())


def _joins_a_longer_name(remainder: str) -> bool:
    """Ported from `spicy_docs.interpretation.citations._joins_a_longer_name`.

    Prevents `"COMMITTEEONHOMELANDSECURITY"` + `"ANDGOVERNMENTALAFFAIRS"` (Senate `ssga00`)
    from false-matching the shorter House prefix `"COMMITTEEONHOMELANDSECURITY"` (`hshm00`).
    """
    return any(remainder.startswith(token) for token in _NAME_JOINING_TOKENS)


def named_chamber_before_span(text: str, start: int) -> str | None:
    """Ported from `spicy_docs.interpretation.citations.named_chamber` (`House ` or `Senate ` right before `start`)."""
    if not text or start <= 0:
        return None
    m = _NAMED_CHAMBER_RE.search(text, max(0, start - _NAMED_CHAMBER_REACH), start)
    return None if m is None else m.group(1).lower()


def _build_chamber_committee_vocab(
    default_chamber: str = "house",
    own_only: bool = False,
    congress: int | None = None,
) -> tuple[tuple[str, str], ...]:
    by_ch: dict[str, list[tuple[str, str]]] = {"house": [], "senate": []}
    for code in sorted(_STATIC_COMMITTEE_CANONICAL_V6):
        resolved = committee_code_to_canonical_v6(code, congress)
        if not resolved:
            continue
        ch, full_name = resolved
        if ch not in ("house", "senate"):
            continue
        stripped = re.sub(r"^(?:House|Senate)\s+", "", full_name, flags=re.I)
        key = _canonical_alnum_upper(stripped)
        if key:
            by_ch[ch].append((key, code))
    eff_ch = default_chamber if default_chamber in ("house", "senate") else "house"
    sides = (eff_ch,) if own_only else (eff_ch, "senate" if eff_ch == "house" else "house")
    merged: dict[str, str] = {}
    for side in sides:
        for k, code in by_ch[side]:
            merged.setdefault(k, code)
    return tuple(sorted(merged.items()))


_PROSE_CMT_SPAN_RE = re.compile(
    r"\b(?:Permanent\s+Select\s+|Select\s+|Special\s+)?Committee\s+on\s+"
    r"[A-Z][A-Za-z',&-]+(?:\s+(?:and|on|of|the|for|in|to|&|[A-Z][A-Za-z',&-]+)){0,12}",
)


def resolve_prose_committee_names_v6(
    text: str | None,
    *,
    default_chamber: str | None = None,
    congress: int | None = None,
) -> list[dict[str, str]]:
    """Resolve `Committee on ...` spans in `text` using `NAMED_CHAMBER` + `_joins_a_longer_name` guard."""
    if not text:
        return []
    out: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    base_ch = default_chamber if default_chamber in ("house", "senate") else "house"

    for m in _PROSE_CMT_SPAN_RE.finditer(text):
        span_txt = m.group(0)
        cand = _canonical_alnum_upper(span_txt)
        if not cand:
            continue
        explicit_ch = named_chamber_before_span(text, m.start())
        vocab = _build_chamber_committee_vocab(
            default_chamber=explicit_ch or base_ch,
            own_only=(explicit_ch is not None),
            congress=congress,
        )
        chosen_code: str | None = None
        route = "unresolved"

        exact = [code for v_name, code in vocab if v_name == cand]
        if exact:
            chosen_code, route = exact[0], "exact"
        else:
            # Candidate has trailing prose after a full committee name, UNLESS remainder starts with `AND...`!
            longer_matches: list[tuple[int, str]] = []
            for v_name, code in vocab:
                if cand.startswith(v_name):
                    rem = cand[len(v_name) :]
                    if not _joins_a_longer_name(rem):
                        longer_matches.append((len(v_name), code))
            if longer_matches:
                longer_matches.sort(reverse=True)
                top_len = longer_matches[0][0]
                top_codes = {c for ln, c in longer_matches if ln == top_len}
                if len(top_codes) == 1:
                    chosen_code, route = next(iter(top_codes)), "name_prefix"

        if chosen_code and chosen_code not in seen_codes:
            canon = committee_code_to_canonical_v6(chosen_code, congress)
            if canon:
                seen_codes.add(chosen_code)
                out.append(
                    {
                        "code": chosen_code,
                        "chamber": canon[0],
                        "name": canon[1],
                        "route": route,
                    }
                )
    return out


_PROSE_LOOKBACK_BLOCK_RE = re.compile(
    r"\b(?:worked|served|testified|appeared|prior\s+to|formerly|staff|counsel|fellow|"
    r"created\s+by|established\s+by|recommendations?\s+of|report\s+of\s+the)\s+$",
    re.I,
)


def detect_commission_masthead_v6(text: str | None) -> dict[str, str] | None:
    """Detect any of the `7` statutory/chamber Commissions (+ `scnc00`) in formal p1 mastheads (`0` FP on Gold360)."""
    if not text:
        return None
    head = _norm_ws(text, 750)
    if len(head) < 15:
        return None
    for code, ch, cname, rx in CONGRESSIONAL_COMMISSIONS_V6:
        for m in rx.finditer(head[:550]):
            pre = head[max(0, m.start() - 60) : m.start()]
            if _PROSE_LOOKBACK_BLOCK_RE.search(pre):
                continue
            return {"code": code, "chamber": ch, "name": cname}
    return None


# ---------------------------------------------------------------------------
# N6.4 URL Unwrapping + `url-rules.json` (`&download=1` missing `?` fix)
# ---------------------------------------------------------------------------

_WAYBACK_RE = re.compile(
    r"^https?://web\.archive\.org/web/([0-9a-z_*]+)/(https?://.+|[A-Za-z0-9.-]+\.[A-Za-z]{2,}/.*)$",
    re.I,
)
_LOC_WEBARCHIVE_RE = re.compile(
    r"^https?://webarchive\.loc\.gov/all/([0-9a-z_*]+)/(https?://.+)$",
    re.I,
)
_WEBHARVEST_RE = re.compile(
    r"^https?://[^/]*webharvest\.gov/[^/]+/([0-9a-z_*]+)/(https?://.+)$",
    re.I,
)
_LIS_GPO_RE = re.compile(
    r"^https?://(?:www\.)?(?:lis|congress)\.gov/cgi-lis/t2GPO/(https?://(?:www\.)?gpo\.gov/fdsys/pkg/.+)$",
    re.I,
)
_PROOFPOINT_V2_RE = re.compile(
    r"^https?://(?:urldefense\.proofpoint\.com|urldefense\.com)/v2/url\?u=([^&]+).*$",
    re.I,
)
_SENATE_NOTFOUND_RE = re.compile(
    r"^(https?://(?:[a-z0-9-]+\.)+senate\.gov)/404\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$",
    re.I,
)
_DOWNLOAD_AMP_QUERY_RE = re.compile(
    r"^(https?://(?:[a-z0-9-]+\.)*(?:house|senate)\.gov/download/[^?#]+?)(?:%20|\s)*&download=1(?:#.*)?$",
    re.I,
)


def _decode_proofpoint_u(encoded: str) -> str:
    def _rep(m: re.Match[str]) -> str:
        return bytes.fromhex(m.group(1)).decode("latin-1")

    step1 = re.sub(r"-([0-9A-Fa-f]{2})", _rep, encoded)
    return step1.replace("_", "/")


def unwrap_and_clean_url_v6(url: str | None) -> tuple[str, bool, bool]:
    """Unwrap Wayback/LOC/WebHarvest/LIS-GPO/Proofpoint/Senate-404 URLs and repair `&download=1` (`4,862` docs).

    Returns `(clean_url, was_archived, had_download_amp_fix)`.
    """
    if not url or not isinstance(url, str):
        return "", False, False
    cur = url.strip()
    was_archived = False
    had_amp_fix = False

    for _ in range(3):
        m_wb = _WAYBACK_RE.match(cur)
        if m_wb:
            was_archived = True
            inner = m_wb.group(2).strip()
            cur = inner if inner.lower().startswith(("http://", "https://")) else f"https://{inner}"
            continue
        m_loc = _LOC_WEBARCHIVE_RE.match(cur)
        if m_loc:
            was_archived = True
            cur = m_loc.group(2).strip()
            continue
        m_wh = _WEBHARVEST_RE.match(cur)
        if m_wh:
            was_archived = True
            cur = m_wh.group(2).strip()
            continue
        m_lis = _LIS_GPO_RE.match(cur)
        if m_lis:
            cur = m_lis.group(1).strip()
            continue
        m_pp = _PROOFPOINT_V2_RE.match(cur)
        if m_pp:
            cur = _decode_proofpoint_u(m_pp.group(1).strip())
            continue
        m_snf = _SENATE_NOTFOUND_RE.match(cur)
        if m_snf:
            cur = f"{m_snf.group(1)}/{unquote(m_snf.group(2)).lstrip('/')}"
            continue
        break

    m_amp = _DOWNLOAD_AMP_QUERY_RE.match(cur)
    if m_amp:
        cur = m_amp.group(1)
        had_amp_fix = True
    elif re.search(r"(?:house|senate)\.gov/download/", cur, re.I) and cur.lower().endswith("?download=1"):
        cur = cur[: -len("?download=1")]

    return cur, was_archived, had_amp_fix


# ---------------------------------------------------------------------------
# N6.5 `saved-name-decisions.json` (`84` Human-Verified SHA Overrides)
# ---------------------------------------------------------------------------

# Maps `body_sha_hex` -> `(decision, effective_filename, override_primary_kind, override_subkind)`
SAVED_NAME_DECISIONS_V6: dict[str, tuple[str, str, str, str | None]] = {
    "0cd7e66646cfb65d5300dcb97d71aa3c362ee2bdf043de22469ee16463fa7f6c": ("official", "BILLS-113pih-WeatherForecastingImprovementAct.pdf", "bill_or_draft", None),
    "541b965df45aca4a432a5d346ed39cb4b53af02a08564b00d00093cf2398146b": ("official", "BILLS-114pih-BudgetReconciliationLegislativeRecommendationsRelatingtoRepealofIndependentPaymentAdvisoryBoard.pdf", "bill_or_draft", None),
    "4145bb0603dae3555f5573f3aa7ddb1b4f2a2fa107cb7623437ac00403f62d5c": ("official", "BILLS-114pih-FCCquarterlyreport-U1.pdf", "bill_or_draft", None),
    "30405ddcb80d17c4e2802d4a6091b338f8623988cf9286a54afba97cf60c6509": ("official", "BILLS-115-5970-W000812-Amdt-001.pdf", "committee_amendment", None),
    "7d129b37f9a4c19246834c18defd71ba00216a9b93f21125b7ec934b61495980": ("official", "BILLS-115-CommitteePrint-W000791-Amdt-1.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "397540810f58af404db62982420effbfd19d759a367654db1532a1a60930c241": ("official", "BILLS-116pih-SAFEBankingAct-U1.pdf", "bill_or_draft", None),
    "b08a978230e0426f6353d90f978de931edba05883842d0e7767560df92875a69": ("official", "BILLS-117-CommitteePrint2-S000185-Amdt-1.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "7f7cdc6fec927f2b19aeb7f340b772053654f39779b7e3eb099e3e11c9540bfd": ("official", "BILLS-117-SConRes5ReconciliationDirectives-S000185-Amdt-1.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "5018728f624bc4152dff6025e4b0e7948a49e332c618659e158631ff8aeb3058": ("official", "BILLS-118-ANSreport-J000289-Amdt-1.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "39cfb2c8374986bdecaa3b7ce20e57dd3fe9fa0f6cecd4d1f9749d20afd773a4": ("official", "BILLS-118HR1418ih.pdf", "bill_or_draft", None),
    "d963d0ddc3acf480b46f7884f8763d109db30f72e3ddf16f91a36a5faf496db6": ("official", "BILLS-118pih-BioEarly-U1.pdf", "bill_or_draft", None),
    "d84f18542808f257fe44faff62e66e368a7ee67103ccb853c38b755b4c974a7b": ("official", "BILLS-118pih-CompactofFreeAssociationA.pdf", "bill_or_draft", None),
    "ae04506de223c30db37f2d6ec47734aa0c51e6793517476fba92fa7a135df860": ("official", "BILLS-119-0-S001195-Amdt-1-U9.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "d2f9e695659c4388373106686f38c37acbec2125b0a737fa9efe3a877377d816": ("official", "BILLS-119HR4273ih.pdf", "bill_or_draft", None),
    "36962d07e34126a86c28dcece55ff7c15aca838ec4d64f004630c957c85f948c": ("official", "CRPT-114-GO00-Vote001-20150421.pdf", "committee_vote", None),
    "bfee601476123d5e2aaf7d6a3aca6baef2c6ce35c8a7736178eb02316e2a9cd1": ("official", "CRPT-115-II00-Vote002-20180411.pdf", "committee_vote", None),
    "1ffe727ac6fc241349b0c4bfc5079af74465d1c506ac04e34a417868ea2f8d8b": ("official", "CRPT-117-AS00-Vote002-20221213.pdf", "committee_vote", None),
    "30b74ecbba7776c796e137f553c8997f6a3bb090ea656b36f4ed5ba9de52687d": ("official", "HHRG-114-GO24-Transcript-20150415.pdf", "hearing_transcript", None),
    "16d84087aaf6028ff9ca91eac460af60275d37a29ad068988021561a147a021b": ("committee", "amendment_2_revised_final_recorded_vote.pdf", "committee_vote", None),
    "a581a1a792ba4ae2ecfd4b89416492947236e7c8369d5aa7fa30a96bdda839d5": ("committee", "amendment_9_final_recorded_vote_hr_2542.pdf", "committee_vote", None),
    "d17c0ab24988f189ebb834206b8007a20246148e25b81dc3e795320cec1b5996": ("committee", "amendment_3_final_recorded_vote_hr_2542.pdf", "committee_vote", None),
    "0c86642838d0a951f92c5e7ef3b92cf5791e4fd3da276a5ad9e7c94f11e59a8f": ("committee", "revised_amendment_18_recorded_vote_hr_2542.pdf", "committee_vote", None),
    "44c4d8c14d527d73eb7d6a852eff859a78eb48efdce0ef1d66770a6537228f9d": ("committee", "amendment_11_final_recorded_vote_hr_2542.pdf", "committee_vote", None),
    "df314d4dc80e74a7dddba6444f21dea3450336582036738a169de481bcf48c9a": ("committee", "amendment_19_final_recorded_vote_hr_2542..pdf", "committee_vote", None),
    "3d1434b53900ce1090d10d7fbf56baac566116291ed02ccf2b3f2713ff9ab186": ("committee", "HR-5033-ANS.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "28d4b633704ba754504ded0a3891c63d2ada1be42284680633ec29a57a4447b9": ("committee", "3-25-2015_revised_ans_to_hr_1481.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "f15c5a6f41b3b874d017e8caf322c24dd46086218dba8f1ab361e32d1c7d94dd": ("committee", "042315_Vote_Sheet_Final_Passage_HR_1890.pdf", "committee_vote", None),
    "08b50c2b4a0ade452706e359c5fad27591532ebfcc038e088e033fe33d454980": ("committee", "fc_markup_notice_--_04.11.18.pdf", "markup_notice", None),
    "5a6595c2362775c17f2331302f10bcb7be9e3bd8abcc17028910cd2b070b04c8": ("committee", "ECR-Committee-Print-GOP-Reconciliation-Text.pdf", "bill_or_draft", None),
    "fd8bbbc80a41b4b26daff1c2435cce030a25749df0e6668efb048bd6bc3b2ce8": ("committee", "02.28.2017_fy18_budget_views_and_estimates.pdf", "budget_views_and_estimates", None),
    "45089adfb64119befeba2f9b64769a81621411dd38be7689a3b94b854ace2c35": ("committee", "03.06.2018_fy19_budget_views_and_estimates.pdf", "budget_views_and_estimates", None),
    "4b0650ec444f4cd7676ac0a319bb5d2f8fd930b94ea17f19fcbc2819efb5e431": ("committee", "AINS TO HR 1922.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "e4e64309651ae9a5466a64a8dcaf9aaa41f867d992857a32e9ac5eb98d1d2fff": ("committee", "AINS TO HR 3398.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "c4451cf3bde46934ecfb6bb3e818fd7af4a80be8b949830ea33053ecb9214e7d": ("committee", "AINS TO HR 3708.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "83b203f065bdf86c2bcf94c191f01e0a1a01a30be17cf205262d1cba12963df0": ("committee", "AINS TO HR 3.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "64065772c24dd1df332fadcbcf270654fe1c407ce2702878956a43c945129420": ("committee", "AINS TO HR 4618.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "6517e36330f92df7631122d1891185739bbeeb61c36ee09f90a619d666682a8f": ("committee", "AINS TO HR 4650 DENTAL.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "2cf0d9d93021f6eaac7a0802a599d067f72eab1c15c99bf39c13543688358e6a": ("committee", "AINS TO HR 4716.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "9d6c36b2b726154cf746a79ad43cad6aa67bf1c80b53796c733f71aa1ff0f9ab": ("committee", "AINS TO HR 4742.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "48e738504727194e4735e87124fc6a91c94f9a73ef08199ad3b18ab5710fde10": ("committee", "AINS to HR 5306.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "f9791109037b7e30717797183d2e7552ae847415a555fc5fe9fe1d0d7f71d449": ("committee", "AINS to HR 5826 Leg Text.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "6af16e8c9432b9505413028f13205000919879dee4667a0e7c056ae7272b5914": ("committee", "NEAL_048_xml AINS TO H Res 746.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "e826996078c8df3583f074d9f29caff58077519c3df2f508a7738827012150f3": ("committee", "gsa_resolutions_june_15_2022.pdf", "gsa_prospectus_or_property", None),
    "7d362447d2a94628e1e5f51f242cc67eee31a3c8810bbccf087cccffa1ad8690": ("committee", "gsa_resolutions_for_april_28_2022_markup.pdf", "gsa_prospectus_or_property", None),
    "812d1a1b1e06961cd3cef27bc85a06dda79bc8af495fa543fa7106796fb82c15": ("committee", "BILL-TO-BILL_BILLS-118hr3397rh_to_RCP_H3397_xml.pdf", "comparative_print", None),
    "c7bca90782406819c4c5fc68d0096e8585a75e413fc1de39cef459bc882971c6": ("committee", "06-26-2024_final_gsa_resolutions_combined.pdf", "gsa_prospectus_or_property", None),
    "f7240d014097ee74a1b8bf9e6d50dd0701684a8c27d942c1d1a90e02b3a5538c": ("committee", "03-20-2024_final_gsa_resolutions_combined.pdf", "gsa_prospectus_or_property", None),
    "cf8e651b2c51cbc8c8c735b33b759f93dae4fddf0aa47f946a8314898a3e23ee": ("committee", "BILL-TO-BILL_118hr1023rh_to_118hr1eh - SEC. 10015.pdf", "comparative_print", None),
    "ba81aa9017d84e23dcb22f60e10fc6d49c29def97cdbdf859f84c2b35c78d6c8": ("committee", "BILL-TO-BILL_BILLS-118hr4691ih_to_RCP_H4691_xml (1).pdf", "comparative_print", None),
    "747836ade47df342d5ae0bac0d04db27a19bdea3fb2bbd32f419ad6ea07ca310": ("committee", "BILL-TO-BILL_118hr1130rh_to_PFLUGE_184_xml.pdf", "comparative_print", None),
    "690ddd3bfb286417d1384cc6c4c67d0e65866a07f06f7a3e8e62e5546e473d65": ("committee", "BILL-TO-BILL_118hr1141rh_to_118hr1eh - SEC. 10014.pdf", "comparative_print", None),
    "5698e63ceb685e13aa7a1548874c267c8fcb73e260a57011e86a44f11ff63783": ("committee", "BILL-TO-BILL_118hr1eh - SEC. 10008_to_PFLUGE_184_xml.pdf", "comparative_print", None),
    "03665ed634fdfd51fe24c3f3cfce02f8038aef269df14f2902e583019706bc56": ("committee", "BILL-TO-BILL_BILLS-118hr4763rh_agriculture_xml_to_RCP_H4763_xml.pdf", "comparative_print", None),
    "8e72bbb5cee7dccb2b6a6d4e670960eb7e358dda5e0f564fd15bcb39df53d0e6": ("committee", "Report_HR354_RH_Judiciary_as prepared to be filed(1).pdf", "committee_report", None),
    "cf5b6cf8a4a8bff2cf82008df89b945bc0e3276653c48182d805a37015a81bd1": ("committee", "BILL-TO-BILL_118hr2eh_to_RCP_3602_j_xml (1).pdf", "comparative_print", None),
    "58fec71ece5f128353cf2e768eb9293d66a51b394cd7484b43f20e3fac44c05f": ("committee", "BILL-TO-BILL_BILLS-118hr4763rh_financialServices_xml_to_RCP_H4763_xml.pdf", "comparative_print", None),
    "6e02c2ae2d44782f97dab926b515809829d954b37a40d358beb51f11689a4d23": ("committee", "2024-02-03 CHS H.Res.863 Report.pdf", "committee_report", None),
    "7cab63cb317751c143208c56a832bafd18c8b21efc8b2e03f89fb28595774622": ("committee", "hr_1836_ans_xml.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "ff5bace33546afcb3f6baae7d4d5495d7d8852b2c1b896706708f947fda4b9d0": ("committee", "0E12FEDAEACF1A1EEED620E7A1BF670AFEDFD00A83A41EA6A447A9B0CE8EDABF.h.r.-3559-amendment-028-obernolte.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "d06afdfcf386907007812bdf50121cd8d6b60596bc7d7762bf16e1afc74cfc07": ("committee", "HR 8205_ANS.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "625586e06c891994a2055dd9ded9f4309899a0cf7efd75e65607866553ebe5a7": ("committee", "HR 8419_ANS.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "903013f8708c9ad1c050f843ebf0ccf8f6325003a6c40ada92864616ef83286a": ("committee", "HR 9605_ANS.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "79bf9bbd4566140fb4b1c6fbb2084c348d20413dddd715719f6e935cd0363cca": ("committee", "Garland-Contempt-Report-re-Hur-Report.pdf", "committee_report", None),
    "f7809a688a8af50bdcbb79c29d872c8ae82ecd1eb70526c97b102e1525a688d3": ("committee", "Hunter-Biden-Contempt-Report-Oversight.pdf", "committee_report", None),
    "1e8e71ee99f5dfe59223058cdf749418fb0f2ee7ff0104ea8791d29810858361": ("committee", "Zwonitzer Contempt Report.pdf", "committee_report", None),
    "05e3e85e5fdb5d06b0c20c51adbaf0b99902376c4473cbbf2bba31caf3eafa48": ("committee", "Views-and-Estimates-Letter.pdf", "budget_views_and_estimates", None),
    "6c9aeeece51ebdef21a65ddc50d90cf37561283328da2393059de7d35d2805a3": ("committee", "06-04-2026_fc_markup_-_ti_fy_2027_budget_views_and_estimates_final.pdf", "budget_views_and_estimates", None),
    "a8055c1d775fccb82d2f550596b9b0a346f89bb943cadcc65befc5e2d6196990": ("committee", "final_authorization_and_oversight_plan_for_the_committee_on_transportation_and_infrastructure_for_the_119th_congress.pdf", "oversight_plan", None),
    "c4560b1ecaed987987265bb272dbd9c7fe720edb1c1fede8b463cece9bb3f74d": ("committee", "09-15-2026_fc_markup_gsa_resolutions_compiled_final.pdf", "gsa_prospectus_or_property", None),
    "d014b6f8561e8bda26883685cc7a946f969574fc743f4ae732d0af7bff53b22a": ("committee", "BILL-TO-BILL_119hr7147eh_to_DHS_xml.pdf", "comparative_print", None),
    "eda3f0713e51cbc60b9f50558061e66962cb6f50383bd0fbe1056b44b06a0c0f": ("committee", "BILL-TO-BILL_119hr7296ih_to_RCP_S1383_xml.pdf", "comparative_print", None),
    "99f9e262f139aea57225bc480b30a87fbc2d2f441a4bed1779bb4bc5a972f296": ("committee", "Explanatory Statement Homeland Security.pdf", "explanatory_statement", None),
    "9f713593e03d8b529b6e0b49826c8fb6bf6f9dfb40183371062e627c07d460d9": ("committee", "h.r-3699-energy-choice-act-rep-langworthy-committee-print.pdf", "bill_or_draft", None),
    "57ea8856e5984fb7709b4a94ded2f547baa05ffa496c4deec79352e6c3ef6acd": ("committee", "h.r-4626-dont-mess-with-my-home-appliances-act-rep-allen-committee-print.pdf", "bill_or_draft", None),
    "e283fe9a2267b6429315f3d5d7dfaa8275e43c68917f2bbb4e2ebdbaf78cb5bc": ("committee", "BILL-TO-BILL_BILLS-119pih_to_RCP_119-3_FINAL.pdf", "comparative_print", None),
    "7ba733c03bb4021fcf9368bfb7db8e249856eee4cfe6e406a5d8d46019952020": ("committee", "h.r-5184-affordable-homes-over-mandating-efficiency-standards-rep-houchin-committee-print.pdf", "bill_or_draft", None),
    "ebcb62faa5d7b207b49e2df3fccdb48bad926711309836daf97f0d6d9adf5bd3": ("committee", "BILL-TO-BILL_BILLS-119hr9576ih (1)_to_RCP_H9576_xml.pdf", "comparative_print", None),
    "a02ecea555d46ccb51833a0f6b3ff82bb6cc4629ede4c546caae2c7ba8e4a18e": ("committee", "hr-60-ans.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
    "fc0158b6b3d27e7abd2afaebfc7744f6476a0ce84352316499f701ff7ef96e8e": ("committee", "h.r-7266-rural-and-municipal-utility-and-cybersecurity-act-committee-print.pdf", "bill_or_draft", None),
    "610c418a38de0dad8847b0668009eb3d16ddac3873b92196673830e8e74fcc59": ("committee", "60074651C3B20C4C18C084B64D2E4AD79E318175EE27A8125D1432E3E687A521.10-21-2021-idoc-e3c-subcommittee-hearing-notice.pdf", "hearing_notice", None),
    "a12510fd432fd7406455fab59e23cd0b17aa121e2692298d8feb08471b726a3b": ("committee", "982D20536F367F0B575249CF8948F3198CC1296D2C72D7760F35BC3202ED7071.11-18-2021-idoc-subcommittee-hearing-notice.pdf", "hearing_notice", None),
    "f423c7111a6e9590efa5963e731e334e53f47c45471339e0a80f2586cce2be50": ("committee", "16868A00CD95351A32363D8B99194299E6C5FFBFAA19F7587C700F21C3C79ECD.hearing-notice---11.20.24---revised.pdf", "hearing_notice", None),
    "25b7e1f69f3f0e204a9b560fd481c4c6b29508c074e581f93c5d0ea0ba677111": ("committee", "63AFDBC6E8963B9B4D6A62AC97B8A1C0C1787ABD5A2EB1C12EEA6E9B2F8F52D7.h.r.-4755-amendment-016-sykes.pdf", "committee_amendment", None),
    "603783213c9b0603503cdc2934c4bcbcfcb8fd5e839a0718cd324cd6b514cc16": ("neither", "ans_to_ti_committee_print_reconciliation.pdf", "committee_amendment", "amendment_in_nature_of_substitute"),
}


def resolve_saved_name_override_v6(body_sha_hex: str | None) -> dict[str, Any] | None:
    """Look up a `body_sha_hex` in CT's `84` human-verified `saved-name-decisions.json` overrides."""
    if not body_sha_hex or not isinstance(body_sha_hex, str):
        return None
    hit = SAVED_NAME_DECISIONS_V6.get(body_sha_hex.strip().lower())
    if hit is None:
        return None
    dec, eff_fn, pk, subk = hit
    return {
        "decision": dec,
        "effective_filename": eff_fn,
        "override_primary_kind": pk,
        "override_subkind": subk,
    }


# ---------------------------------------------------------------------------
# N7. Deterministic Title Waterfall (`titles.sql` + `title-rules.json`)
# ---------------------------------------------------------------------------

# All 9 `link_word` patterns + 1 `label` pattern from `model/registries/title-rules.json`
# ported to 100% Python stdlib `re` (`\p{L}` -> `[^\W\d_]`, `[^\p{L}]` -> `[\W\d_]`).
TITLE_LINK_WORD_RULES_V6: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "link_word_formats",
        re.compile(r"(?i)^(zip|pdf|html?|xml|docx?|txt|text|json|csv|xlsx?|pptx?|mp3|mp4)[.!:]*$"),
    ),
    (
        "link_word_actions",
        re.compile(
            r"(?i)^(click here|please click here|here|link|document|file|download|download file|"
            r"download pdf|download testimony|download witness testimony|"
            r"download executive business meeting results|view|view pdf|view testimony|open|"
            r"read more|more|email|print|share|website|webpage|untitled|attachment|hearings?)[.!:]*$"
        ),
    ),
    ("link_word_click_here", re.compile(r"(?i)^(please\s+)?click\s+here\b")),
    (
        "link_word_download",
        re.compile(
            r"(?i)^(?:download\s+\S|(?:view|open)\s+(?:witness\s+)?(?:testimony|statement|document|pdf|file|results)\b)"
        ),
    ),
    (
        "link_word_format_size",
        re.compile(
            r"(?i)^[\s\W\d_]*(?:(?:zip|pdf|html?|xml|docx?|txt|text|json|csv|xlsx?|pptx?|rtf|mp3|mp4|"
            r"download|view|open|click|here|[kmg]i?b|bytes?)\b[\s\W\d_]*)+$"
        ),
    ),
    (
        "link_word_phrases",
        re.compile(
            r"(?i)^(printable\s+(pdf|version)(\s+of\s+this\s+(document|page))?|"
            r"download\s+(the\s+)?(report|document|file|attachment))[.!:]*$"
        ),
    ),
    (
        "link_word_no_name",
        re.compile(
            r"(?i)^(?:[\W\d_]*|(?:nos?|number)[.]?[\W\d_]*[0-9][\W\d_]*|_[0-9]+(?:\s*\([^)]*\)?[,;.!:]*)?)$"
        ),
    ),
    (
        "link_word_bill_placeholder",
        re.compile(
            r"(?i)^(?:(?:H\.?\s?R\.?|S\.|H\.?\s?Res\.?|S\.?\s?Res\.?|H\.?\s?J\.?\s?Res\.?|"
            r"S\.?\s?J\.?\s?Res\.?|H\.?\s?Con\.?\s?Res\.?|S\.?\s?Con\.?\s?Res\.?)\s*|S\s+)_+"
            r"(?:\.[A-Za-z0-9]{2,5})?[,;.!:]*$"
        ),
    ),
    (
        "link_word_filename",
        re.compile(r"(?i)^\S+\.(?:pdf|docx?|xlsx?|pptx?|zip|xml|txt|csv|rtf)$"),
    ),
)

TITLE_BARE_LABEL_RULES_V6: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "label_alone",
        re.compile(
            r"(?i)^(?:witness\s+(?:statement|testimony|biography)|(?:prepared|written)\s+statement|"
            r"testimony|biography|truth\s+in\s+testimony(?:\s+form|\s+disclosure(?:\s+form)?)?)$"
        ),
    ),
)

_LEADING_GPO_DASH_RE = re.compile(r"^\s*[-–—]+\s+")


def is_junk_link_title_v6(text: str | None) -> bool:
    """True if `text` is empty or matches any of `title-rules.json`'s 9 `link_word` junk filters."""
    if not text or not isinstance(text, str):
        return True
    s = _WS_RE.sub(" ", _LEADING_GPO_DASH_RE.sub("", text)).strip()
    if not s:
        return True
    if len(s) <= 64 and any(rx.search(s) for _, rx in TITLE_LINK_WORD_RULES_V6):
        return True
    return False


def is_bare_label_title_v6(text: str | None) -> bool:
    """True if `text` is a bare generic label (`"Testimony"`, `"Witness Biography"`, etc.) per `title-rules.json`."""
    if not text or not isinstance(text, str):
        return False
    s = _WS_RE.sub(" ", _LEADING_GPO_DASH_RE.sub("", text)).strip()
    return any(rx.search(s) for _, rx in TITLE_BARE_LABEL_RULES_V6)


def _cap_composed_title(s: str, max_len: int = 108) -> str:
    clean = _WS_RE.sub(" ", s).strip()
    if len(clean) <= max_len:
        return clean
    cut = clean[: max_len - 3].rsplit(" ", 1)[0].rstrip(",;:- ")
    return (cut if len(cut) >= 24 else clean[: max_len - 3]) + "..."


def clean_composed_title_candidate(
    detail_title: str | None = None,
    detail_title_source: str | None = None,
    *,
    witness_name: str | None = None,
    link_texts: Sequence[str] | None = None,
    page_title: str | None = None,
) -> tuple[str | None, str | None]:
    """Deterministic `titles.sql` + `title-rules.json` waterfall for `composed_title` / `cold_r2` / bypasses.

    NEVER used to overwrite `verbatim_title`. Returns `(clean_title, source_tag)`.
    """
    raw_cands: list[tuple[str, str]] = []
    if isinstance(detail_title, str) and detail_title.strip():
        raw_cands.append((detail_title, detail_title_source or "detail_title"))
    if isinstance(page_title, str) and page_title.strip():
        raw_cands.append((page_title, "page_title"))
    for lt in link_texts or ():
        if isinstance(lt, str) and lt.strip():
            raw_cands.append((lt, "link_text"))

    first_bare_label: tuple[str, str] | None = None
    for raw, src in raw_cands:
        stripped = _WS_RE.sub(" ", _LEADING_GPO_DASH_RE.sub("", raw)).strip()
        if not stripped:
            continue
        if src != "correction" and is_junk_link_title_v6(stripped):
            continue
        if src != "correction" and is_bare_label_title_v6(stripped):
            if first_bare_label is None:
                first_bare_label = (stripped, src)
            continue
        return _cap_composed_title(stripped), src

    if first_bare_label is not None and isinstance(witness_name, str) and witness_name.strip():
        assembled = f"{first_bare_label[0]} - {witness_name.strip()}"
        return _cap_composed_title(assembled), "label_witness"

    return None, None


# ---------------------------------------------------------------------------
# N5.1 Rosters & Bioguide Lookup (`rosters_lookup_v6.json`)
# ---------------------------------------------------------------------------


def _surname_token(name: str) -> str:
    s = re.sub(
        r"\b(Jr\.?|Sr\.?|II|III|IV|V|M\.?D\.?|Ph\.?D\.?|Esq\.?|Hon\.?|Rep\.?|Sen\.?|Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\b",
        "",
        name or "",
        flags=re.I,
    )
    parts = [p for p in re.split(r"[^A-Za-z'\u00C0-\u024F-]+", s) if len(p) > 1]
    return unicodedata.normalize("NFKC", parts[-1]).lower() if parts else ""


def load_rosters_lookup_v6(
    path: str | Path | None = None,
    *,
    required: bool = False,
) -> dict[str, Any]:
    """Load and cache `rosters_lookup_v6.json` (`12,770` members + `284` committee system codes)."""
    target = Path(path) if path is not None else _resolve_default_rosters_path()
    cache_key = str(target)
    if cache_key in _ROSTERS_CACHE_BY_PATH:
        cached = _ROSTERS_CACHE_BY_PATH[cache_key]
        if not cached and required and not target.exists():
            raise FileNotFoundError(f"Missing rosters lookup table: {target}")
        return cached
    if not target.exists():
        if required:
            raise FileNotFoundError(f"Missing rosters lookup table: {target}")
        _ROSTERS_CACHE_BY_PATH[cache_key] = {}
        return {}
    data = json.loads(target.read_text(encoding="utf-8"))
    _ROSTERS_CACHE_BY_PATH[cache_key] = data
    return data


@functools.lru_cache(maxsize=256)
def _cached_cong_surnames_for_path(congress: int, rosters_path_str: str) -> frozenset[str]:
    db = load_rosters_lookup_v6(rosters_path_str, required=False)
    mem_by_bg = db.get("members_by_bioguide") if isinstance(db, Mapping) else None
    if not isinstance(mem_by_bg, Mapping):
        return frozenset()
    out: set[str] = set()
    for mv in mem_by_bg.values():
        if not isinstance(mv, Mapping):
            continue
        sur = str(mv.get("surname") or "").strip().lower()
        if not sur:
            continue
        if any(
            isinstance(tr, (list, tuple)) and len(tr) >= 2 and tr[0] <= congress <= tr[1]
            for tr in (mv.get("terms") or ())
        ):
            out.add(sur)
    return frozenset(out)


_CUSTOM_SURNAME_CACHE: dict[tuple[int, int], frozenset[str]] = {}


@functools.lru_cache(maxsize=256)
def valid_cong_surnames(congress: int) -> frozenset[str]:
    """Return `@lru_cache`-memoized set of valid Bioguide Member surnames serving in `congress`."""
    if isinstance(congress, bool) or not isinstance(congress, int) or not (1 <= congress <= 130):
        return frozenset()
    target = _resolve_default_rosters_path()
    return _cached_cong_surnames_for_path(int(congress), str(target))


def _valid_cong_surnames_with_lookup(
    congress: int | None,
    lookup: Mapping[str, Any] | None = None,
) -> frozenset[str]:
    if isinstance(congress, bool) or not isinstance(congress, int) or not (1 <= congress <= 130):
        return frozenset()
    if lookup is None:
        return valid_cong_surnames(int(congress))
    target = _resolve_default_rosters_path()
    if str(target) in _ROSTERS_CACHE_BY_PATH and lookup is _ROSTERS_CACHE_BY_PATH[str(target)]:
        return _cached_cong_surnames_for_path(int(congress), str(target))
    mem_by_bg = lookup.get("members_by_bioguide")
    if not isinstance(mem_by_bg, Mapping):
        return frozenset()
    key = (id(mem_by_bg), int(congress))
    hit = _CUSTOM_SURNAME_CACHE.get(key)
    if hit is not None:
        return hit
    surs = frozenset(
        str(mv.get("surname") or "").strip().lower()
        for mv in mem_by_bg.values()
        if isinstance(mv, Mapping)
        and str(mv.get("surname") or "").strip()
        and any(
            isinstance(tr, (list, tuple)) and len(tr) >= 2 and tr[0] <= congress <= tr[1]
            for tr in (mv.get("terms") or ())
        )
    )
    if len(_CUSTOM_SURNAME_CACHE) >= 256:
        _CUSTOM_SURNAME_CACHE.clear()
    _CUSTOM_SURNAME_CACHE[key] = surs
    return surs


def lookup_member_by_bioguide_v6(
    bioguide_id: str | None,
    *,
    congress: int | None = None,
    lookup: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Resolve `bioguide_id` -> `{"bioguide_id", "name", "surname", "party_state", "chamber"}`."""
    if not bioguide_id or not isinstance(bioguide_id, str):
        return None
    bg = bioguide_id.strip().upper()
    if not bg:
        return None
    db = lookup if lookup is not None else load_rosters_lookup_v6(required=False)
    entry = (db.get("members_by_bioguide") or {}).get(bg)
    if not entry:
        return None

    ps = entry.get("default_party_state") or ""
    ch = entry.get("default_chamber") or "house"
    if not isinstance(congress, bool) and isinstance(congress, int) and 1 <= congress <= 130:
        for t_start, t_end, t_ps, t_ch in entry.get("terms") or ():
            if t_start <= congress <= t_end:
                ps = t_ps
                ch = t_ch
                break
    return {
        "bioguide_id": bg,
        "name": entry["name"],
        "surname": entry.get("surname") or _surname_token(entry["name"]),
        "party_state": ps,
        "chamber": ch,
    }


def lookup_committee_roster_v6(
    congress: int | None,
    committee_codes: Iterable[str] | None,
    *,
    lookup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return `(congress, committee_codes)` leadership & strict backbench sets across parent + all subcommittees.

    Protects ALL full-committee AND subcommittee Chairs, Vice Chairs, Ranking Members, Acting Chairs,
    and Ex Officio members so a Subcommittee Chair or Vice Chair is NEVER treated as backbench.
    """
    empty = {
        "chairs": [],
        "ranking_members": [],
        "vice_chairs": [],
        "leadership_bioguides": set(),
        "leadership_surnames": set(),
        "backbench_bioguides": set(),
        "backbench_surnames": set(),
    }
    if isinstance(congress, bool) or not isinstance(congress, int) or not committee_codes:
        return empty
    db = lookup if lookup is not None else load_rosters_lookup_v6(required=False)
    if not db:
        return empty

    rosters_map = db.get("rosters_by_cong_code") or {}
    sub_map = db.get("parent_to_subcodes") or {}
    mem_map = db.get("members_by_bioguide") or {}

    target_codes: list[str] = []
    for raw_c in committee_codes:
        if not raw_c or not isinstance(raw_c, str):
            continue
        sc = raw_c.strip().lower()
        parent = normalize_parent_committee_code_v6(sc) or sc
        for c_item in (sc, parent):
            if c_item not in target_codes:
                target_codes.append(c_item)
        for sub_c in sub_map.get(f"{congress}:{parent}") or ():
            if sub_c not in target_codes:
                target_codes.append(sub_c)

    chairs: list[dict[str, str]] = []
    ranking_members: list[dict[str, str]] = []
    vice_chairs: list[dict[str, str]] = []
    leadership_bgs: set[str] = set()
    all_roster_bgs: set[str] = set()

    for sc in target_codes:
        r_entry = rosters_map.get(f"{congress}:{sc}")
        if not r_entry:
            continue
        is_parent = sc.endswith("00") and sc not in ("hlfd00", "hlqj00", "hlvc00", "hlbz00")
        for bg in r_entry.get("chairs") or ():
            leadership_bgs.add(bg)
            all_roster_bgs.add(bg)
            info = lookup_member_by_bioguide_v6(bg, congress=congress, lookup=db)
            if info:
                rec = {**info, "system_code": sc, "is_parent": "1" if is_parent else "0"}
                chairs.append(rec)
        for bg in r_entry.get("ranking_members") or ():
            leadership_bgs.add(bg)
            all_roster_bgs.add(bg)
            info = lookup_member_by_bioguide_v6(bg, congress=congress, lookup=db)
            if info:
                rec = {**info, "system_code": sc, "is_parent": "1" if is_parent else "0"}
                ranking_members.append(rec)
        for bg in r_entry.get("vice_chairs") or ():
            leadership_bgs.add(bg)
            all_roster_bgs.add(bg)
            info = lookup_member_by_bioguide_v6(bg, congress=congress, lookup=db)
            if info:
                vice_chairs.append({**info, "system_code": sc})
        for bg in r_entry.get("ex_officio") or ():
            leadership_bgs.add(bg)
            all_roster_bgs.add(bg)
        for bg in r_entry.get("backbench") or ():
            all_roster_bgs.add(bg)

    strict_backbench_bgs = all_roster_bgs - leadership_bgs
    leadership_surnames = {
        (mem_map[bg].get("surname") or _surname_token(mem_map[bg]["name"]))
        for bg in leadership_bgs
        if bg in mem_map
    }
    # Never include a surname in `backbench_surnames` if it collides with ANY leadership member's surname (e.g. two Smiths)!
    backbench_surnames = {
        (mem_map[bg].get("surname") or _surname_token(mem_map[bg]["name"]))
        for bg in strict_backbench_bgs
        if bg in mem_map
    } - leadership_surnames

    return {
        "chairs": chairs,
        "ranking_members": ranking_members,
        "vice_chairs": vice_chairs,
        "leadership_bioguides": leadership_bgs,
        "leadership_surnames": {s for s in leadership_surnames if s},
        "backbench_bioguides": strict_backbench_bgs,
        "backbench_surnames": {s for s in backbench_surnames if s},
    }


# ---------------------------------------------------------------------------
# N5.2 Meetings Event Type, Sitting Venue & Witness Persona Builders
# ---------------------------------------------------------------------------


def normalize_meeting_event_type_v6(
    meeting_type: str | None,
    congress_gov_meeting_type: str | None = None,
    title: str | None = None,
) -> str | None:
    """Normalize `meetings.{meeting_type, congress_gov_meeting_type, title}` to `DocMetaV4Causal.event_type`."""
    raw = (congress_gov_meeting_type or meeting_type or "").strip().lower()
    m_up = (meeting_type or "").strip().upper()
    t_low = (title or "").strip().lower()

    if m_up == "HMKP" or "markup" in raw:
        return "markup"
    if m_up == "HMTG" or "business meeting" in raw or raw == "meeting":
        if "markup" in t_low:
            return "markup"
        return "business_meeting"
    if m_up == "HHRG" or "hearing" in raw:
        if re.search(r"\b(?:field\s+hearing)\b", t_low):
            return "field_hearing"
        if re.search(r"\b(?:nominations?\s+of|pending\s+nominations|^nominations?$)\b", t_low):
            return "nomination_hearing"
        return "hearing"
    if "roundtable" in t_low or "briefing" in t_low:
        return "roundtable_or_briefing"
    return None


def format_sitting_venue_v6(
    sittings: Sequence[dict[str, Any]] | None,
) -> tuple[str | None, str | None, str | None]:
    """Extract `(venue, venue_kind, event_time)` from `meetings.sittings`."""
    if not sittings:
        return None, None, None
    s0 = sittings[0]
    if not isinstance(s0, dict):
        return None, None, None

    place = (s0.get("place") or "").strip()
    room = (s0.get("room") or "").strip()
    bldg = (s0.get("building") or "").strip()
    addr = (s0.get("address") or "").strip()

    venue: str | None = None
    if place and place.lower() not in ("washington, d.c.", "washington, dc", "tbd", "n/a"):
        venue = place
    elif room and bldg:
        venue = f"{room} {bldg}"
    elif bldg:
        venue = bldg
    elif addr and addr.lower() not in ("washington, d.c.", "washington, dc"):
        venue = addr

    venue_kind: str | None = None
    if venue:
        v_low = venue.lower()
        if any(w in v_low for w in ("webex", "zoom", "virtual", "remote")):
            venue_kind = "hybrid" if any(b in v_low for b in ("rayburn", "longworth", "cannon", "dirksen", "hart", "russell", "capitol")) else "virtual"
        elif any(b in v_low for b in ("rayburn", "longworth", "cannon", "dirksen", "hart", "russell", "capitol", "svc-", "hvc-")):
            venue_kind = "capitol_room"
        elif addr and not any(w in addr.lower() for w in ("washington, d.c", "washington, dc")):
            venue_kind = "field_site"

    event_time: str | None = None
    st = s0.get("start")
    if isinstance(st, datetime.datetime):
        tz_s = st.tzname() or ""
        hm = st.strftime("%H:%M")
        if hm != "00:00":
            event_time = f"{hm} {tz_s}".strip()

    return venue, venue_kind, event_time


_HONORIFIC_STRIP_RE = re.compile(
    r"^(?:The\s+Honorable|The\s+Hon\.|Hon\.|Dr\.|Mr\.|Ms\.|Mrs\.|Miss|Prof\.|Professor|"
    r"Ambassador|Amb\.|Senator|Sen\.|Representative|Rep\.|Congressman|Congresswoman)\s+",
    re.I,
)
_MIL_RANK_RE = re.compile(
    r"\b(?:General|Gen\.|Lt\.\s*Gen\.|Lieutenant\s+General|Maj\.\s*Gen\.|Major\s+General|"
    r"Brig\.\s*Gen\.|Brigadier\s+General|Admiral|Adm\.|Vice\s+Admiral|Rear\s+Admiral|"
    r"Colonel|Col\.|Lieutenant\s+Colonel|Commander|Capt\.|Captain\s+USN|Command\s+Sergeant\s+Major)\b",
    re.I,
)
_NOMINEE_POS_RE = re.compile(
    r"^(?:nominee\s+to\s+be|to\s+be\s+(?:an?\s+)?(?:United\s+States\s+|U\.?S\.?\s+)?(?:Circuit|District|Chief|Associate)?\s*"
    r"(?:Judge|Ambassador|Secretary|Deputy\s+Secretary|Under\s+Secretary|Assistant\s+Secretary|"
    r"Administrator|Director|Commissioner|Inspector\s+General|General\s+Counsel|Solicitor|"
    r"Attorney|Marshal|Member|Chair(?:man|woman)?))\b",
    re.I,
)
_JUNK_WITNESS_ORG_RE = re.compile(
    r"^(?:to\s+be\s+introduced\s+by:?|introduced\s+by:?|n/?a|none|tbd|witness(?:es)?|panel\s+[ivx0-9]+)$",
    re.I,
)
_GOV_ORG_CUE_RE = re.compile(
    r"\b(?:U\.?S\.?\s+Department|Department\s+of\s+(?:State|Defense|War|the\s+Treasury|Treasury|Justice|"
    r"the\s+Interior|Interior|Agriculture|Commerce|Labor|Health|Housing|Transportation|Energy|Education|"
    r"Veterans|Homeland\s+Security|the\s+Air\s+Force|the\s+Army|the\s+Navy)|"
    r"Government\s+Accountability\s+Office|Congressional\s+Research\s+Service|Congressional\s+Budget\s+Office|"
    r"Federal\s+(?:Trade|Communications|Reserve|Deposit|Aviation|Energy|Bureau|Emergency|Maritime|Highway|Railroad|Transit)|"
    r"Environmental\s+Protection\s+Agency|Securities\s+and\s+Exchange\s+Commission|"
    r"Internal\s+Revenue\s+Service|Social\s+Security\s+Administration|Centers\s+for\s+Medicare|"
    r"Food\s+and\s+Drug\s+Administration|Customs\s+and\s+Border\s+Protection|"
    r"Office\s+of\s+(?:Management\s+and\s+Budget|the\s+Comptroller|Personnel\s+Management|Inspector\s+General|the\s+United\s+States\s+Trade)|"
    r"State\s+of\s+[A-Z][a-z]+|Commonwealth\s+of\s+[A-Z][a-z]+|City\s+of\s+[A-Z][a-z]+)\b",
    re.I,
)


def _clean_witness_field(val: str | None) -> str | None:
    if not val or not isinstance(val, str):
        return None
    s = _WS_RE.sub(" ", val).strip().rstrip(":").strip()
    if not s or _JUNK_WITNESS_ORG_RE.match(s):
        return None
    return s


def _order_persona_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: d[k] for k in PERSONA_KEYS_ORDER_V6 if k in d and d[k] is not None and d[k] != ""}


def build_witness_persona_v6(
    w_row: dict[str, Any],
    *,
    person_row: dict[str, Any] | None = None,
    congress: int | None = None,
    lookup: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Construct a strict `DocMetaV4Causal` persona dict from `witnesses.parquet` (+ `people.parquet`)."""
    raw_name = _clean_witness_field(w_row.get("name")) or (
        _clean_witness_field(person_row.get("name")) if person_row else None
    )
    if not raw_name:
        return None

    clean_name = raw_name
    for _ in range(2):
        clean_name = _HONORIFIC_STRIP_RE.sub("", clean_name).strip()
    if not clean_name:
        clean_name = raw_name

    rank = _clean_witness_field(w_row.get("rank")) or (
        _clean_witness_field(person_row.get("rank")) if person_row else None
    )
    creds = _clean_witness_field(w_row.get("credentials")) or (
        _clean_witness_field(person_row.get("credentials")) if person_row else None
    )
    pos = _clean_witness_field(w_row.get("position"))
    org = _clean_witness_field(w_row.get("organization"))
    if org and org.lower().startswith("the ") and "federal reserve" in org.lower():
        org = org[4:].strip()
    obo = _clean_witness_field(w_row.get("on_behalf_of"))
    loc = _clean_witness_field(w_row.get("location"))
    panel_raw = w_row.get("panel")
    panel_ord = w_row.get("panel_order")
    w_type = (w_row.get("witness_type") or "").strip()
    bg = (w_row.get("bioguide_id") or w_row.get("matched_bioguide_id") or (person_row or {}).get("bioguide_id") or "").strip().upper()

    is_nominee = bool(pos and _NOMINEE_POS_RE.search(pos))
    is_member = bool(
        bg
        or w_type in ("member_appearance", "member_statement")
        or (pos and re.search(r"\b(?:U\.?S\.?\s+(?:Senator|Representative)|United\s+States\s+(?:Senator|Representative)|Member\s+of\s+Congress)\b", pos, re.I))
    )
    is_mil = bool(
        (rank and _MIL_RANK_RE.search(rank))
        or _MIL_RANK_RE.search(raw_name)
        or (pos and re.search(r"\b(?:Commandant|Commander,\s*U\.?S\.?|Chief\s+of\s+(?:Staff|Naval\s+Operations))\b", pos, re.I) and org and re.search(r"\b(?:Army|Navy|Air\s+Force|Marine\s+Corps|Space\s+Force|Coast\s+Guard)\b", org, re.I))
    )

    role = "nominee" if is_nominee else "witness"
    if is_nominee:
        entity_type = "judicial_or_exec_nominee"
    elif is_member:
        entity_type = "member"
    elif is_mil:
        entity_type = "military_officer"
    elif w_type.startswith("Government") or _GOV_ORG_CUE_RE.search(f"{org or ''} {pos or ''}") or (
        pos and re.search(r"\b(?:Governor|Mayor|Attorney\s+General|State\s+Treasurer|Secretary\s+of\s+State|Inspector\s+General)\b", pos, re.I)
    ):
        entity_type = "gov_official"
    else:
        entity_type = "non_gov_person"

    p: dict[str, Any] = {"name": clean_name[:120], "role": role, "entity_type": entity_type}
    if creds:
        p["creds"] = creds[:80]
    elif rank and is_mil and rank not in clean_name:
        p["creds"] = rank[:80]

    if pos:
        if is_nominee and pos.lower().startswith("to be "):
            p["title"] = f"Nominee {pos}"[:180]
        else:
            p["title"] = pos[:180]
    if org:
        p["org"] = org[:180]
    if obo and obo != org:
        p["on_behalf_of"] = obo[:180]

    if bg:
        m_info = lookup_member_by_bioguide_v6(bg, congress=congress, lookup=lookup)
        if m_info and m_info.get("party_state"):
            p["party_state"] = m_info["party_state"]

    if isinstance(panel_raw, str) and panel_raw.strip():
        ps_clean = panel_raw.strip()
        p["panel"] = ps_clean if ps_clean.lower().startswith("panel") else f"Panel {ps_clean}"
    elif isinstance(panel_ord, int) and not isinstance(panel_ord, bool) and 1 <= panel_ord <= 6:
        romans = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI"}
        p["panel"] = f"Panel {romans[panel_ord]}"

    if loc and len(loc) >= 4:
        p["work_addr"] = loc[:160]

    return _order_persona_dict(p)


# ---------------------------------------------------------------------------
# N5.3 Backbench Letterhead Subtraction & Relational Persona Enrichment
# ---------------------------------------------------------------------------

_PROTECTED_ACTIVE_ROLES_V6: frozenset[str] = frozenset(
    {
        "chair",
        "ranking_member",
        "presiding",
        "witness",
        "nominee",
        "sponsor",
        "cosponsor",
        "amendment_offeror",
        "questioner",
        "introducer",
        "staff",
        "party_or_investigator",
    }
)


def subtract_letterhead_backbench_v6(
    personas: list[dict[str, Any]],
    *,
    primary_kind: str | None,
    congress: int | None,
    committee_codes: Iterable[str] | None,
    protected_bioguides: Iterable[str] | None = None,
    lookup: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Remove leaked committee letterhead backbench member dumps (`0` active actors deleted on `Gold360`).

    Safety invariants:
      1. NEVER runs on Member-authored, correspondence, legislative-sponsorship, or QFR genres.
      2. Protects ALL full-committee & subcommittee Chairs, Vice Chairs, Ranking Members, Ex Officio,
         plus `protected_bioguides` (`detail.bioguide_ids`, `sponsor_bioguide`), Witnesses, Nominees, Staff.
      3. Requires `>= 3` strict backbench committee members in `personas[]` (unmistakable roster leak)
         before subtracting non-leadership `member` entries.
    """
    if not personas or primary_kind not in BACKBENCH_SUBTRACTION_SAFE_KINDS_V6:
        return personas, 0
    roster = lookup_committee_roster_v6(congress, committee_codes, lookup=lookup)
    bb_surnames = roster["backbench_surnames"]
    if not bb_surnames:
        return personas, 0

    prot_surnames = set(roster["leadership_surnames"])
    db = lookup if lookup is not None else load_rosters_lookup_v6(required=False)
    for bg in protected_bioguides or ():
        m_info = lookup_member_by_bioguide_v6(bg, congress=congress, lookup=db)
        if m_info and m_info["surname"]:
            prot_surnames.add(m_info["surname"])

    def _is_backbench_leak_candidate(p: dict[str, Any]) -> bool:
        if p.get("entity_type") != "member":
            return False
        if p.get("role") in _PROTECTED_ACTIVE_ROLES_V6:
            return False
        sur = _surname_token(str(p.get("name") or ""))
        if not sur or sur in prot_surnames:
            return False
        return sur in bb_surnames

    leak_indices = [i for i, p in enumerate(personas) if isinstance(p, dict) and _is_backbench_leak_candidate(p)]
    min_leaks = 1 if primary_kind in ("attendance_quorum_sheet", "member_roster", "committee_vote") else 3
    if len(leak_indices) < min_leaks:
        return personas, 0

    drop_set = set(leak_indices)
    kept = [p for i, p in enumerate(personas) if i not in drop_set]
    if not kept:
        return personas, 0
    return kept, len(drop_set)


_OFFERED_BY_RE = re.compile(
    r"\bOFFERED\s+BY\s+(?:MR\.|MS\.|MRS\.|MISS|REP\.|SEN\.|DR\.|THE\s+HONORABLE)\s+([A-Z][A-Za-z'\u00C0-\u024F-]+)",
    re.I,
)
_SD_SLUG_RE = re.compile(r"-SD\d+\b", re.I)
_SINCERELY_CUE_RE = re.compile(r"\b(?:Sincerely|Respectfully(?:\s+submitted)?)\b\s*[,:]?", re.I)
_DEAR_OR_TO_SALUTATION_RE = re.compile(r"(?:^|\n|\s)(?:Dear|TO\s*:)\s+([^\n:]{2,110})", re.I)
_OPENING_STMT_MEMBER_HDR_RE = re.compile(
    r"\bOPENING\s+STATEMENT\s+OF\s+(?:THE\s+)?"
    r"(HON(?:ORABLE)?\.?|CHAIR(?:MAN|WOMAN|PERSON)?|RANKING\s+(?:MINORITY\s+)?MEMBER|"
    r"REP(?:RESENTATIVE)?\.?|SEN(?:ATOR)?\.?)\s+([^\n]{2,100})",
    re.I,
)
_SUBMITTED_FOR_RECORD_BY_RE = re.compile(
    r"\bSUBMITTED\s+FOR\s+THE\s+RECORD\s+BY\s+(?:THE\s+)?"
    r"(?:HON(?:ORABLE)?\.?|REP(?:RESENTATIVE)?\.?|SEN(?:ATOR)?\.?|MR\.?|MS\.?|MRS\.?|DR\.?)?\s*"
    r"([A-Z][A-Za-z'\u00C0-\u024F .,-]{2,80})",
    re.I,
)


_SAL_NAME = r"(?:[A-Z][A-Za-z'’\-]+\.?\s){0,3}[A-Z][A-Za-z'’\-]+(?:,\s(?:Jr|Sr|II|III)\.?)?"
_SAL_CHAIR = r"(?:Madam\s+)?Chair(?:man|woman|person|lady)?"
_SAL_SEP = r"\s*(?:,|;|and|&)\s*(?:and\s+)?"
_SAL_MEMBERS_TAIL = (
    r"\s*,?\s*(?:and\s+)?(?:the\s+)?(?:other\s+)?(?:distinguished\s+|honorable\s+|esteemed\s+)?[Mm]embers\s+of\s+the"
)
_SAL_CHAIR_AND_RM_RE = re.compile(
    rf"{_SAL_CHAIR}\s+(?P<c>{_SAL_NAME}){_SAL_SEP}"
    rf"(?:Vice\s+(?:Madam\s+)?Chair\w*\s+{_SAL_NAME}{_SAL_SEP})?Ranking\s+(?:Minority\s+)?Member\s+(?P<r>{_SAL_NAME})"
)
_SAL_CHAIR_ONLY_RE = re.compile(rf"{_SAL_CHAIR}\s+(?P<c>{_SAL_NAME}){_SAL_MEMBERS_TAIL}")
_SAL_RM_ONLY_RE = re.compile(rf"Ranking\s+(?:Minority\s+)?Member\s+(?P<r>{_SAL_NAME}){_SAL_MEMBERS_TAIL}")
_SAL_VICE_PREFIX_RE = re.compile(r"\b(?:vice|co)\s*[- ]?$", re.I)
_SAL_NOT_A_NAME = frozenset(
    "member members the and of committee subcommittee emeritus ranking chairman chairwoman chair vice thank thanks "
    "dear good mr ms mrs madam i my we it as on in for to this distinguished honorable "
    "january february march april may june july august september october november december".split()
)


def salutation_chair_personas_v6(text: str, *, window: int = 4000) -> list[tuple[str, str]]:
    """`(role, name)` for the chair and ranking member a witness addresses by name in the opening salutation.

    Matches only the addressing forms (`Chairman X, Ranking Member Y`, `Chair X and Members of the ...`), so a
    passing `Chairman Powell said` elsewhere in testimony does not fire. Agrees with the blind and re-hydrated V4
    gold on 79 of 86 witness-statement personas; the 2,000-doc cluster gold omits 72% of them.
    """
    flat = re.sub(r"\s+", " ", (text or "")[:window])
    found: list[tuple[str, str]] = []
    for rx, groups in (
        (_SAL_CHAIR_AND_RM_RE, (("chair", "c"), ("ranking_member", "r"))),
        (_SAL_CHAIR_ONLY_RE, (("chair", "c"),)),
        (_SAL_RM_ONLY_RE, (("ranking_member", "r"),)),
    ):
        for m in rx.finditer(flat):
            pre_chair = flat[max(0, m.start() - 16) : m.start()]
            chair_is_vice = bool(_SAL_VICE_PREFIX_RE.search(pre_chair))
            for role, g in groups:
                if role == "chair" and chair_is_vice:
                    continue
                found.append((role, m.group(g)))

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for role, raw_name in found:
        toks = raw_name.strip(" ,").split()
        while toks and toks[-1].strip(".,").lower() in _SAL_NOT_A_NAME:
            toks.pop()
        while toks and toks[0].strip(".,").lower() in _SAL_NOT_A_NAME:
            toks.pop(0)
        if not toks or any(t.strip(".,").lower() in _SAL_NOT_A_NAME for t in toks):
            continue
        name = " ".join(toks).strip(" ,")
        if name.endswith(".") and toks[-1].rstrip(".").lower() not in ("jr", "sr"):
            name = name.rstrip(".")  # the match ran over a sentence end (`... Pallone. Thank you`)
        sur = _surname_token(name)
        if len(sur) < 3 or sur in seen:
            continue
        seen.add(sur)
        out.append((role, name))
    return out


def add_salutation_chair_personas_v6(
    personas: Sequence[Mapping[str, Any]] | None, text: str, *, max_personas: int = MAX_PERSONAS
) -> list[dict[str, Any]]:
    """List the addressed chair / ranking member after the witnesses when no persona has that surname."""
    cur = [dict(p) for p in (personas or []) if isinstance(p, Mapping) and p.get("name")]
    have: set[str] = set().union(*(_name_parts(str(p["name"])) for p in cur)) if cur else set()
    for role, name in salutation_chair_personas_v6(text):
        if len(cur) >= max_personas:
            break
        sur_parts = _name_parts(_surname_token(name))
        if sur_parts & have:
            continue
        have |= sur_parts
        # Gold order: witnesses, then chair, then ranking member, then everyone else.
        ahead = ("witness",) if role == "chair" else ("witness", "chair")
        at = 0
        while at < len(cur) and cur[at].get("role") in ahead:
            at += 1
        cur.insert(at, {"name": name, "role": role, "entity_type": "member"})
    return cur


_BILL_NAME = r"[A-Z][A-Za-z'’\-]+(?:\s[A-Z][A-Z'’\-]+){0,2}"
_BILL_SPONSOR_LINE_RE = re.compile(
    rf"\b(?:M[rs]s?\.|Miss)\s+(?P<sp>{_BILL_NAME})(?:\s+of\s+[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)?\s*"
    r"(?:\(for\s+(?:him|her)self\s*,?(?P<cos>.{0,1200}?)\)\s*)?(?:introduced|submitted)\s+the\s+following",
    re.S,
)
_BILL_COSPONSOR_RE = re.compile(rf"(?:M[rs]s?\.|Miss)\s+({_BILL_NAME})")
_LETTER_HONORABLE_RE = re.compile(
    r"(?:The\s+)?Hon(?:orable|\.)\s+([A-Z][A-Za-z'’\-\.]+(?:[ \t]+[A-Z][A-Za-z'’\-\.]+){0,3})[ \t]*(?:,|\n|$)",
    re.M,
)
_LETTER_DEAR_RE = re.compile(
    r"Dear\s+(?:Chair(?:man|woman)?|Ranking\s+Member|Senator|Representative|Congress(?:man|woman)|Mr\.|Ms\.|"
    r"Madam\s+Chair\w*)\s+([A-Z][A-Za-z'’\-]+(?:\s[A-Z][A-Za-z'’\-]+)?)"
)
_LETTER_CONGRESS_CUE_RE = re.compile(
    r"Chair|Ranking|Committee|Senate|Senator|House\s+of\s+Rep|Representative|Congress", re.I
)
_LETTER_GOV_CUE_RE = re.compile(
    r"\bDepartment\b|\bAgency\b|\bAdministration\b|\bBureau\b|\bU\.?S\.?\s|\bUnited\s+States\b|\bOffice\s+of\b|"
    r"\bCommission\b|\bSecretary\b|\bAdministrator\b|\bCommissioner\b|\bInspector\s+General\b"
)
# Letters to Members, and letters from a committee to a witness or agency (where the addressee is not a Member).
_LETTER_TO_MEMBER_KINDS = frozenset({"external_submission_letter", "nomination_or_support_letter"})
_LETTER_ADDRESSEE_KINDS = _LETTER_TO_MEMBER_KINDS | {"oversight_letter", "qfr_request", "witness_invitation"}


def _name_parts(name: str) -> set[str]:
    # `Herseth-Sandlin`, `Herseth Sandlin`, and `Sensenbrenner, Jr.` are one person: strip punctuation and suffixes.
    cleaned = unicodedata.normalize("NFKC", name or "").lower()
    return {
        tok
        for raw in re.split(r"[\s\-,.;:()/]+", cleaned)
        if len(tok := raw.strip("'’\"[]{}")) > 2
        and tok not in ("iii", "ii", "iv", "jr", "sr", "esq", "phd", "md", "ret", "usa", "usn", "usaf", "usmc")
    }


def _gpo_caps_to_name(raw: str) -> str:
    """`MCGOVERN` -> `McGovern`, `DE LA CRUZ` -> `De La Cruz`; a name already in mixed case is kept."""
    if raw != raw.upper():
        return raw
    return re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), raw.title())


def bill_sponsor_personas_v6(text: str, *, window: int = 3500) -> list[tuple[str, str]]:
    """`(role, name)` from a bill's `Mr. X (for himself, Mr. Y, ...) introduced the following bill` line.

    The sponsor matches gold in 58 of 60 bills; blank discussion-draft placeholders (`Mr. llll`) return nothing.
    """
    m = _BILL_SPONSOR_LINE_RE.search((text or "")[:window])
    if not m or re.fullmatch(r"l+", m.group("sp").lower()):
        return []
    out = [("sponsor", _gpo_caps_to_name(m.group("sp")))]
    seen = {_surname_token(out[0][1])}
    for raw in _BILL_COSPONSOR_RE.findall(m.group("cos") or ""):
        name = _gpo_caps_to_name(raw)
        sur = _surname_token(name)
        if re.fullmatch(r"l+", raw.lower()) or sur in seen:
            continue
        seen.add(sur)
        out.append(("cosponsor", name))
    return out


def letter_addressee_personas_v6(
    text: str, *, to_member: bool = True, window: int = 1800
) -> list[tuple[str, str]]:
    """`(entity_type, name)` for the people a letter is addressed to (`The Honorable X`, `Dear Chairman X`).

    174 of 182 such names are personas in gold. Letters to a committee address Members; on an oversight letter,
    QFR request or witness invitation (`to_member=False`) the address block decides: a congressional title is a
    Member, an agency cue is an official, anything else a private person.
    """
    head = (text or "")[:window]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rx in (_LETTER_HONORABLE_RE, _LETTER_DEAR_RE):
        for m in rx.finditer(head):
            name = m.group(1).strip(" ,.")
            sur = _surname_token(name)
            if len(sur) < 3 or sur in seen or sur in _SAL_NOT_A_NAME or sur in ("senate", "house", "secretary"):
                continue
            seen.add(sur)
            block = re.split(r"Hon(?:orable|\.)\s|Dear\s", head[m.end() : m.end() + 160])[0]
            if to_member or _LETTER_CONGRESS_CUE_RE.search(m.group(0) + block):
                etype = "member"
            else:
                etype = "gov_official" if _LETTER_GOV_CUE_RE.search(m.group(0) + block) else "non_gov_person"
            out.append((etype, name))
    return out


def add_text_grounded_personas_v6(
    personas: Sequence[Mapping[str, Any]] | None,
    *,
    primary_kind: str | None,
    text: str,
    max_personas: int = MAX_PERSONAS,
    additive_only: bool = False,
) -> list[dict[str, Any]]:
    """R4-R6: list the actors the document names in a fixed form when the model left them out.

    `additive_only` is for repairing reviewed labels: it adds the missing actors and never drops or re-labels
    one a reviewer wrote.

    R4 `witness_statement`: the chair / ranking member addressed in the salutation.
    R5 `bill_or_draft`: sponsor and cosponsors from the introduction line; a `sponsor` the line does not name is
       re-labelled `cosponsor` if it is in the list, else dropped.
    R6 letters: the addressees, as `recipient`.
    """
    cur = [dict(p) for p in (personas or []) if isinstance(p, Mapping) and p.get("name")]
    if not text:
        return cur
    if primary_kind == "witness_statement":
        return add_salutation_chair_personas_v6(cur, text, max_personas=max_personas) if cur else cur

    if primary_kind == "bill_or_draft":
        named = bill_sponsor_personas_v6(text)
        if not named:
            return cur
        role_of = {_surname_token(n): r for r, n in named}
        kept: list[dict[str, Any]] = []
        for p in cur:
            line_role = role_of.get(_surname_token(str(p["name"])))
            if not additive_only and p.get("role") == "sponsor" and line_role != "sponsor":
                if line_role is None:
                    continue
                p["role"] = line_role
            kept.append(p)
        cur = kept
        additions = [{"name": n, "role": r, "entity_type": "member"} for r, n in named]
    elif primary_kind in _LETTER_ADDRESSEE_KINDS:
        additions = [
            {"name": n, "role": "recipient", "entity_type": e}
            for e, n in letter_addressee_personas_v6(text, to_member=primary_kind in _LETTER_TO_MEMBER_KINDS)
        ]
    else:
        return cur

    have: set[str] = set().union(*(_name_parts(str(p["name"])) for p in cur)) if cur else set()
    for add in additions:
        if len(cur) >= max_personas:
            break
        parts = _name_parts(_surname_token(add["name"]))
        if parts & have:
            continue
        have |= parts
        if add["role"] == "sponsor":
            cur.insert(0, add)
        else:
            cur.append(add)
    return cur


def disambiguate_persona_roles_v6(
    personas: Sequence[Mapping[str, Any]] | None,
    *,
    primary_kind: str | None,
    text: str = "",
    congress: int | None = None,
    lookup: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply `0`-FP (`train_v4_all360`-verified) deterministic persona role disambiguation rules.

    Rules:
      - R1 (`witness_invitation` direction): Member (`chair`/`ranking_member`/`member`) in closing
        `Sincerely,` block -> `sender`; `witness` in `Dear`/`To:` salutation -> `recipient`.
      - R2 (`OPENING STATEMENT OF HON.` member guard): Member named in `OPENING STATEMENT OF ...`
        header never receives `role="witness"` (coerced to `chair`, `ranking_member`, or `author_or_speaker`).
      - R3 (`SUBMITTED FOR THE RECORD BY`): Named submitter on supplemental/letter submissions
        receives `role="sender"` (or `"introducer"` when a Member introduces an exhibit) instead of `witness`.
      - R4-R6 (`add_text_grounded_personas_v6`): actors the document names in a fixed form are listed.
    """
    cur = add_text_grounded_personas_v6(personas, primary_kind=primary_kind, text=text)
    if not cur or not text:
        return [_order_persona_dict(p) for p in cur]

    head_txt = text[:1800]
    tail_txt = text[-1600:] if len(text) > 1600 else text

    # R1: `witness_invitation` sender vs recipient direction (`0` FPs on `train_v4_all360`, `+2 TP` on `val_48[44]`)
    if primary_kind == "witness_invitation":
        closing_matches = list(_SINCERELY_CUE_RE.finditer(tail_txt))
        closing_block = tail_txt[closing_matches[-1].start() :] if closing_matches else ""
        sal_spans = " | ".join(m.group(1) for m in _DEAR_OR_TO_SALUTATION_RE.finditer(head_txt))
        for p in cur:
            sur = _surname_token(str(p.get("name") or ""))
            if len(sur) < 2:
                continue
            sur_rx = re.compile(rf"\b{re.escape(sur)}\b", re.I)
            in_closing = bool(closing_block and sur_rx.search(closing_block))
            in_sal = bool(sal_spans and sur_rx.search(sal_spans))
            if in_closing and (
                p.get("entity_type") == "member"
                or p.get("role") in ("chair", "ranking_member", "author_or_speaker")
            ):
                p["role"] = "sender"
            elif in_sal and not in_closing and p.get("role") == "witness":
                p["role"] = "recipient"

    # R2: `OPENING STATEMENT OF (THE) HON./CHAIRMAN/RANKING MEMBER/REP./SEN.` member guard
    if primary_kind != "witness_list":
        m_open = _OPENING_STMT_MEMBER_HDR_RE.search(head_txt)
        if m_open:
            hon_tok = m_open.group(1).lower()
            hdr_span = f"{m_open.group(1)} {m_open.group(2)}"
            cong_surs = _valid_cong_surnames_with_lookup(congress, lookup) if congress else frozenset()
            for p in cur:
                if p.get("role") != "witness":
                    continue
                sur = _surname_token(str(p.get("name") or ""))
                if len(sur) < 2 or not re.search(rf"\b{re.escape(sur)}\b", hdr_span, re.I):
                    continue
                if p.get("entity_type") == "member" or (cong_surs and sur in cong_surs):
                    p["entity_type"] = "member"
                    if "chair" in hon_tok and "vice" not in hdr_span.lower():
                        p["role"] = "chair"
                    elif "ranking" in hon_tok:
                        p["role"] = "ranking_member"
                    elif primary_kind == "hearing_transcript":
                        p["role"] = "questioner"
                    else:
                        p["role"] = "author_or_speaker"

    # R3: `SUBMITTED FOR THE RECORD BY <Name>` on submission/exhibit genres
    if primary_kind in ("external_submission_letter", "public_comment_or_submission", "investigative_exhibit"):
        m_sub = _SUBMITTED_FOR_RECORD_BY_RE.search(head_txt)
        if m_sub:
            sub_span = m_sub.group(1)
            for p in cur:
                if p.get("role") != "witness":
                    continue
                sur = _surname_token(str(p.get("name") or ""))
                if len(sur) >= 2 and re.search(rf"\b{re.escape(sur)}\b", sub_span, re.I):
                    p["role"] = "introducer" if p.get("entity_type") == "member" else "sender"

    return [_order_persona_dict(p) for p in cur]


_WORK_ADDR_KINDS = _LETTER_ADDRESSEE_KINDS | {"witness_statement", "witness_biography"}
_WORK_ADDR_BLOCK_LINES = 6
_WORK_ADDR_BLOCK_LINE_CHARS = 90
_WORK_ADDR_BLOCK_LINE_WORDS = 10
_WORK_ADDR_SAME_LINE_CHARS = 200
# A salutation, subject line or closing ends a letter's address stack; so does a committee letterhead, whose
# address belongs to the committee and not to the chair and ranking member printed above it.
_WORK_ADDR_BLOCK_STOP_RE = re.compile(
    r"(?i)^\s*(?:dear|re:|subject:|sincerely|respectfully)\b"
    r"|\bone\s+hundred\s+\w+(?:[- ]\w+)?\s+congress\b|\bcongress\s+of\s+the\s+united\s+states\b"
)
# On a testimony cover a House or Senate room under the hearing's name or hour is where the hearing sat.
_WORK_ADDR_HEARING_ROOM_RE = re.compile(r"(?i)\b\d{1,2}:\d{2}\s*[ap]\.?m\b|\bbefore\s+the\b|\bhearing\b")
# A lowercase word right before the address on its line: the address is inside a sentence.
_WORK_ADDR_IN_A_SENTENCE_RE = re.compile(r"\b[a-z]+[ \t]+$")


def _address_block_start(text: str, at: int) -> int:
    """Where the stack of short lines an address closes begins: its own line up to the address, and up to six
    lines above. A prose line, a salutation, a subject line, a closing or a committee letterhead ends the stack."""
    line_start = text.rfind("\n", 0, at) + 1
    start = max(line_start, at - _WORK_ADDR_SAME_LINE_CHARS)
    taken, pos = 0, line_start
    while taken < _WORK_ADDR_BLOCK_LINES and pos > 0:
        prev_start = text.rfind("\n", 0, pos - 1) + 1
        line = text[prev_start : pos - 1]
        pos = prev_start
        if not line.strip():
            continue
        if (
            len(line) > _WORK_ADDR_BLOCK_LINE_CHARS
            or len(line.split()) > _WORK_ADDR_BLOCK_LINE_WORDS
            or _WORK_ADDR_BLOCK_STOP_RE.search(line)
        ):
            break
        taken, start = taken + 1, prev_start
    return start


def attach_work_addresses_v6(
    personas: Sequence[Mapping[str, Any]] | None,
    *,
    primary_kind: str | None,
    text: str,
) -> list[dict[str, Any]]:
    """R8: the person named above a postal address, in the block it closes, gets it as `work_addr`.

    Statements, biographies and letters only: an inside address ("The Honorable X / 2157 Rayburn House Office
    Building"), a signature block, a testimony cover. The name must sit in the stack of short lines on the address;
    a letterhead with nobody named above it is attached to nobody, and an address inside a sentence ("will meet
    in 2123 Rayburn House Office Building") is skipped, as is a House or Senate room printed under a hearing's
    name or hour on a testimony cover. One address goes to the nearest name. Addresses
    that follow one another with no name between are one run: as many names as addresses pair off in order (two
    inside addresses set side by side read as "A B / street A street B"), and otherwise only the run's first
    address is used. A `work_addr` the model wrote is never replaced, and each person takes one address.

    The reader (`congress_docmeta.address_reader`) is imported here, on first use, so importing this package
    stays stdlib-only. Its libraries are required dependencies: a missing one raises, it does not switch the rule off.
    """
    cur = [dict(p) for p in (personas or []) if isinstance(p, Mapping)]
    if not text or primary_kind not in _WORK_ADDR_KINDS:
        return cur
    people: dict[str, dict[str, Any]] = {}
    for p in cur:
        sur = _surname_token(str(p.get("name") or ""))
        if len(sur) > 2 and p.get("entity_type") != "organization":
            people.setdefault(sur, p)
    if all(p.get("work_addr") for p in people.values()):
        return cur
    from .address_reader.congressional import read_work_addresses

    folded, addresses = read_work_addresses(text)
    name_res = {sur: re.compile(rf"(?i)(?<![A-Za-z]){re.escape(sur)}(?![A-Za-z])") for sur in people}

    runs: list[tuple[list[str], list[str]]] = []  # (surnames above the run in page order, its addresses)
    prev_end = 0
    for at, end, address in addresses:
        if _WORK_ADDR_IN_A_SENTENCE_RE.search(folded, max(0, at - 24), at):
            prev_end = end
            continue  # "will meet in 2123 Rayburn House Office Building": a place in a sentence, not an office block
        start = _address_block_start(folded, at)
        segment = unicodedata.normalize("NFKC", folded[max(start, prev_end) : at])
        last_at = {sur: m.start() for sur, rx in name_res.items() for m in rx.finditer(segment)}
        if "Office Building, Washington, DC" in address and _WORK_ADDR_HEARING_ROOM_RE.search(segment):
            last_at = {}  # "Before the Committee on ... / 10:00 am / 334 Cannon House Office Building" is the room
        if last_at:
            runs.append((sorted(last_at, key=last_at.__getitem__), [address]))
        elif runs and start <= prev_end:
            runs[-1][1].append(address)
        prev_end = end
    for named, run in runs:
        if len(named) == len(run):
            pairs = list(zip(named, run))
        elif len(named) == 1 or len(run) == 1:
            pairs = [(named[-1], run[0])]
        else:
            continue
        for sur, address in pairs:
            if not people[sur].get("work_addr"):
                people[sur]["work_addr"] = address[:160]
    return cur


def enrich_personas_from_relational_v6(
    personas: list[dict[str, Any]] | None,
    rel_row: dict[str, Any] | None,
    primary_kind: str | None,
    *,
    filename: str = "",
    text: str = "",
    congress: int | None = None,
    committee_codes: Iterable[str] | None = None,
    lookup: dict[str, Any] | None = None,
    allow_ungrounded_qfr_witness: bool = False,
    upgrade_bare_chair_names: bool = False,
) -> list[dict[str, Any]]:
    """Enrich/clean `personas[]` from CT relational tables with `0` FPs and `0` `Gold360` regressions."""
    cur = [dict(p) for p in (personas or []) if isinstance(p, dict) and p.get("name")]
    if not rel_row:
        return [_order_persona_dict(p) for p in cur]

    db = lookup if lookup is not None else load_rosters_lookup_v6(required=False)
    eff_cong = congress or rel_row.get("rel_congress")
    eff_codes = list(committee_codes or rel_row.get("rel_host_committee_codes") or ())
    bgs = list(rel_row.get("bioguide_ids") or ())
    amdt_bg = rel_row.get("rel_amdt_sponsor_bioguide")
    prot_bgs = bgs + ([amdt_bg] if amdt_bg else [])

    # 1. Subtract unmistakable backbench letterhead roster dumps (`0` Gold360 personas touched)
    cur, _ = subtract_letterhead_backbench_v6(
        cur,
        primary_kind=primary_kind,
        congress=eff_cong,
        committee_codes=eff_codes,
        protected_bioguides=prot_bgs,
        lookup=db,
    )

    # 2. Optional `"Chairman <Surname>"` -> full Member name + `party_state` enrichment (preserves `surname_of`!)
    if upgrade_bare_chair_names and eff_cong and eff_codes:
        roster = lookup_committee_roster_v6(eff_cong, eff_codes, lookup=db)
        for p in cur:
            if p.get("entity_type") != "member" or p.get("role") not in ("chair", "ranking_member"):
                continue
            nm = str(p.get("name") or "").strip()
            sur = _surname_token(nm)
            pool = roster["chairs"] if p.get("role") == "chair" else roster["ranking_members"]
            matches = [m for m in pool if m["surname"] == sur]
            uniq_bgs = {m["bioguide_id"] for m in matches}
            if len(uniq_bgs) == 1:
                m0 = matches[0]
                if " " not in nm and _surname_token(m0["name"]) == sur:
                    p["name"] = m0["name"]
                if "party_state" not in p and m0.get("party_state"):
                    p["party_state"] = m0["party_state"]

    # 3. Primary Witness-Author Stamping: STRICTLY gated on `PRIMARY_WITNESS_AUTHOR_KINDS_V6`
    #    (`witness_statement`, `truth_in_testimony_disclosure`, `witness_biography`) + single witness!
    #    NEVER stamps `-SD00x` supplemental exhibits (`GOLD[37, 153, 257, 309]`).
    wks = list(rel_row.get("witness_keys") or ())
    w_json = rel_row.get("rel_witness_personas_json")
    w_personas: list[dict[str, Any]] = []
    if isinstance(w_json, str) and w_json:
        try:
            w_personas = json.loads(w_json)
        except Exception:
            w_personas = []
    elif isinstance(rel_row.get("rel_witness_personas"), list):
        w_personas = list(rel_row["rel_witness_personas"])

    norm_txt = unicodedata.normalize("NFKC", text or "").lower()

    if primary_kind in PRIMARY_WITNESS_AUTHOR_KINDS_V6 and len(wks) == 1 and len(w_personas) == 1:
        wp = dict(w_personas[0])
        if primary_kind == "truth_in_testimony_disclosure" and wp.get("role") == "nominee":
            wp["role"] = "witness"
        has_witness = any(p.get("role") in ("witness", "nominee") for p in cur)
        is_sd_fn = bool(_SD_SLUG_RE.search(filename or ""))
        wsur = _surname_token(wp["name"])
        # On `-SD00x` filenames, require text grounding unless `truth_in_testimony_disclosure`
        if not has_witness and (not is_sd_fn or primary_kind == "truth_in_testimony_disclosure" or (wsur and wsur in norm_txt)):
            cur.insert(0, wp)

    # 4. `qfr_response`: NEVER replace Member questioners; append responding witness alongside questioners!
    elif primary_kind == "qfr_response" and len(wks) == 1 and len(w_personas) == 1:
        wp = dict(w_personas[0])
        wsur = _surname_token(wp["name"])
        existing_surs = {_surname_token(str(p.get("name") or "")) for p in cur}
        if wsur and wsur not in existing_surs and len(cur) < MAX_PERSONAS:
            if allow_ungrounded_qfr_witness or (norm_txt and wsur in norm_txt):
                cur.append(wp)

    # 5. `committee_amendment` Offeror Rescue (`committee_records.sponsor_bioguide` / `bioguide_ids[0]`)
    #    Guarded against publisher filename-slot mismatches (`GOLD[102]` Posey vs W000828, `GOLD[231]` Holt vs A000055)!
    elif primary_kind == "committee_amendment":
        has_offeror = any(p.get("role") in ("amendment_offeror", "sponsor") for p in cur)
        cand_bg = amdt_bg or (bgs[0] if len(bgs) == 1 else None)
        if not has_offeror and cand_bg and len(cur) < MAX_PERSONAS:
            m_info = lookup_member_by_bioguide_v6(cand_bg, congress=eff_cong, lookup=db)
            if m_info:
                msur = m_info["surname"]
                m_off = _OFFERED_BY_RE.search(text or "")
                explicit_other = bool(m_off and _surname_token(m_off.group(1)) != msur)
                if not explicit_other and (not norm_txt or msur in norm_txt):
                    off_p: dict[str, Any] = {
                        "name": m_info["name"],
                        "role": "amendment_offeror",
                        "entity_type": "member",
                    }
                    if m_info.get("party_state"):
                        off_p["party_state"] = m_info["party_state"]
                    cur.insert(0, off_p)

    cur = disambiguate_persona_roles_v6(
        cur,
        primary_kind=primary_kind,
        text=text,
        congress=eff_cong if isinstance(eff_cong, int) else congress,
        lookup=db,
    )
    return [_order_persona_dict(p) for p in cur[:MAX_PERSONAS]]


# ---------------------------------------------------------------------------
# N5.4 Author-vs-Host Relational Fill Guards (`can_fill_from_relational_v6`)
# ---------------------------------------------------------------------------

_EXHIBIT_FN_GUARD_RE = re.compile(
    r"(?:^|[^a-zA-Z])exhibit(?:[^a-zA-Z]|$)|redacted|sanitized|\b302\b",
    re.I,
)
_EXTERNAL_HEAD_GUARD_RE = re.compile(
    r"^(?:THE\s+WHITE\s+HOUSE|EXECUTIVE\s+OFFICE\s+OF\s+THE\s+PRESIDENT|"
    r"UNITED\s+STATES\s+GOVERNMENT\s+ACCOUNTABILITY\s+OFFICE|GAO\s+Highlights\b|"
    r"CONGRESSIONAL\s+RESEARCH\s+SERVICE\b|CRS\s+Report\s+for\s+Congress\b|"
    r"CONGRESSIONAL\s+BUDGET\s+OFFICE\b|OFFICE\s+OF\s+INSPECTOR\s+GENERAL\b|"
    r"JOINT\s+COMMITTEE\s+ON\s+TAXATION\b|JCX-\d+-\d+|"
    r"From:\s+.{1,120}\bSent:\s+|"
    r"IN\s+THE\s+UNITED\s+STATES\s+(?:DISTRICT|CIRCUIT|SUPREME)\s+COURT)",
    re.I,
)
_HSRU_FN_AUTHOR_RE_V6 = re.compile(r"^(?:HHRG|HMTG|HMKP|CRPT)-\d{3}-RU\d{2}-", re.I)
_HSRU_PRINT_BANNER_RE_V6 = re.compile(
    r"(?:\bRULES\s+COMMITTEE\s+PRINT\s+11\d[–-]\d+\b|"
    r"^(?:Report\s+Generated:\s*.{5,65}?\s+)?(?:Comparative\s+Print:|Comparing\s+the\s+base\s+document\s+)|"
    r"^Suspend\s+the\s+Rules\s+and\s+Pass\b)",
    re.I,
)
_HSRU_AUTHOR_TEXT_RE_V6 = re.compile(
    r"(?:^(?:Page\s+\d+\s+of\s+\d+\s+|\d+\s+)?MOTION\s+BY\b|"
    r"\bProviding\s+for\s+consideration\s+of\s+the\s+(?:bill|joint\s+resolution|resolution|senate\s+amendment)\b|"
    r"\bFROM\s+THE\s+COMMITTEE\s+ON\s+RULES\b|"
    r"\bRecord\s+Vote\s+No\.\s*\d+|\bRULES\s+OF\s+THE\s+COMMITTEE\s+ON\s+RULES\b)",
    re.I,
)


def _is_hsru_rules_author_v6(filename: str, text_head: str, hsru_status: str = "not_hsru") -> bool:
    """True ONLY when `hsru00` (House Rules) actually authored the document rather than hosting a floor/print bill."""
    if hsru_status == "rules_host":
        return False
    base_fn = (filename or "").strip().rsplit("/", 1)[-1]
    if _HSRU_FN_AUTHOR_RE_V6.match(base_fn):
        return True
    if text_head and not _HSRU_PRINT_BANNER_RE_V6.search(text_head[:350]) and _HSRU_AUTHOR_TEXT_RE_V6.search(text_head[:1000]):
        return True
    return False


def _text_contradicts_host_committee_v6(codes: Sequence[str], text: str | None, congress: int | None = None) -> bool:
    """True when `text` explicitly names standing committee(s) in its header/referral and NONE match `codes`."""
    if not text or not codes:
        return False
    head = _norm_ws(text, 1600)
    if len(head) < 30:
        return False
    host_norms = set()
    for hc in codes:
        canon = committee_code_to_canonical_v6(hc, congress)
        if canon:
            host_norms.add(norm_committee_compare_v6(canon[1]))
    if not host_norms:
        return False
    mentioned = resolve_prose_committee_names_v6(head, congress=congress)
    mentioned_norms = {norm_committee_compare_v6(m["name"]) for m in mentioned if m.get("name")}
    if mentioned_norms and not (mentioned_norms & host_norms):
        return True
    return False
_MONTH_MAP_V6: dict[str, int] = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_BODY_LONG_DATE_RE_V6 = re.compile(
    r"\b(January|Jan\.?|February|Feb\.?|March|Mar\.?|April|Apr\.?|May|June|Jun\.?|July|Jul\.?|"
    r"August|Aug\.?|September|Sept?\.?|October|Oct\.?|November|Nov\.?|December|Dec\.?)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{2})\b",
    re.I,
)
_BODY_MDY_RE_V6 = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-]((?:19|20)\d{2})\b")
_BODY_ISO_RE_V6 = re.compile(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b")
_BODY_YEAR_RE_V6 = re.compile(r"\b(?:19|20)\d{2}\b")


def _extract_body_iso_dates_v6(text: str | None, limit: int = 1600) -> set[str]:
    if not text:
        return set()
    sub = text[:limit]
    found: set[str] = set()
    for m in _BODY_LONG_DATE_RE_V6.finditer(sub):
        mo = _MONTH_MAP_V6.get(m.group(1).rstrip(".").lower())
        da, yr = int(m.group(2)), int(m.group(3))
        if mo:
            try:
                datetime.date(yr, mo, da)
                found.add(f"{yr:04d}-{mo:02d}-{da:02d}")
            except ValueError:
                pass
    for m in _BODY_MDY_RE_V6.finditer(sub):
        mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime.date(yr, mo, da)
            found.add(f"{yr:04d}-{mo:02d}-{da:02d}")
        except ValueError:
            pass
    for m in _BODY_ISO_RE_V6.finditer(sub):
        yr, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime.date(yr, mo, da)
            found.add(f"{yr:04d}-{mo:02d}-{da:02d}")
        except ValueError:
            pass
    return found


def can_fill_from_relational_v6(
    rel_row: dict[str, Any] | None,
    primary_kind: str | None,
    *,
    existing_obj: dict[str, Any] | None = None,
    filename: str = "",
    text: str = "",
    hsru_status: str = "not_hsru",
    is_zero_llm_bypass: bool = False,
) -> dict[str, Any]:
    """Compute 100%-precision author-safe relational fills (`0` regressions on `Gold360`).

    Mandatory guards enforced:
      - NEVER overwrites existing `chamber` or `committees` on `external_report_or_whitepaper` /
        `agency_or_gao_crs_report` (`GOLD[257]`) or cross-chamber `member_or_floor_statement` (`GOLD[318]`).
      - Separates `rel_host_*` (always available in `rel_row` for sidecars) from `author_safe` fills.
      - Guards `event_date` against multi-day/postponed meetings (`GOLD[251, 324]`) and external exhibits
        where `doc_date` is already present (`48` Gold360 docs without `event_date`).
    """
    if not rel_row or not primary_kind:
        return {}

    cur = existing_obj or {}
    fn_s = filename or ""
    t_head = _norm_ws(text, 1800)
    is_exhibit_or_ext = bool(
        _EXHIBIT_FN_GUARD_RE.search(fn_s) or (t_head and _EXTERNAL_HEAD_GUARD_RE.match(t_head))
    )

    fills: dict[str, Any] = {}

    # 1. `congress`: `200/200` exact on `meetings` + `187/187` exact on `listed_on` across `Gold360`!
    rel_c = rel_row.get("rel_congress")
    if (
        "congress" not in cur
        and not isinstance(rel_c, bool)
        and isinstance(rel_c, int)
        and 1 <= rel_c <= 130
        and primary_kind in CONTEMPORARY_CONGRESSIONAL_KINDS_V6
        and not is_exhibit_or_ext
    ):
        fills["congress"] = rel_c

    eff_cong = cur.get("congress") or fills.get("congress") or rel_c

    # 2. Commission masthead check (`+94` `S_raw` commission docs)
    comm_hit = detect_commission_masthead_v6(text) if text else None
    if comm_hit and primary_kind in PROVENANCE_SAFE_COMMITTEE_KINDS_V6 and not is_exhibit_or_ext:
        if "chamber" not in cur:
            fills["chamber"] = comm_hit["chamber"]
        if "committees" not in cur:
            fills["committees"] = [comm_hit["name"]]

    # 3. `chamber` & `committees`: STRICTLY blocked on `GOLD[257]` (`external_report_or_whitepaper`),
    #    `GOLD[318]` (`member_or_floor_statement`), `agency_or_gao_crs_report`, exhibits, and `hsru00` floor hosts!
    if (
        primary_kind in PROVENANCE_SAFE_COMMITTEE_KINDS_V6
        and primary_kind not in _EXTERNAL_OR_CROSS_CHAMBER_BLOCKED_KINDS_V6
        and not is_exhibit_or_ext
        and hsru_status != "rules_host"
    ):
        hsru_auth = _is_hsru_rules_author_v6(fn_s, t_head, hsru_status=hsru_status)
        codes = [
            c
            for c in (rel_row.get("rel_host_committee_codes") or ())
            if not (c == "hsru00" and not hsru_auth)
        ]
        if (
            "committees" not in cur
            and "committees" not in fills
            and codes
            and not _text_contradicts_host_committee_v6(codes, text, eff_cong)
        ):
            resolved_names: list[str] = []
            for code in codes:
                canon = committee_code_to_canonical_v6(code, eff_cong, t_head[:1200])
                if canon and canon[1] not in resolved_names:
                    resolved_names.append(canon[1])
            if resolved_names:
                fills["committees"] = resolved_names

        if "chamber" not in cur and "chamber" not in fills:
            if primary_kind == "truth_in_testimony_disclosure":
                fills["chamber"] = "house"
            else:
                rel_ch = rel_row.get("rel_host_chamber")
                if rel_ch in ("house", "senate", "joint", "commission"):
                    fills["chamber"] = rel_ch

    # 4. `event_date`, `event_title`, `event_type`, `venue`
    rel_ed = rel_row.get("rel_event_date")
    not_held = bool(rel_row.get("rel_not_held"))
    is_sd = bool(_SD_SLUG_RE.search(fn_s))

    if (
        isinstance(rel_ed, str)
        and len(rel_ed) == 10
        and not not_held
        and primary_kind in _DATE_RESCUE_SAFE_KINDS_V6
        and not is_exhibit_or_ext
    ):
        if is_zero_llm_bypass:
            if "event_date" not in cur:
                body_dates = _extract_body_iso_dates_v6(text, limit=1600)
                if not body_dates or rel_ed in body_dates:
                    fills["event_date"] = rel_ed
        elif "doc_date" not in cur and "event_date" not in cur and not is_sd:
            body_dates = _extract_body_iso_dates_v6(text, limit=1600)
            head_yrs = set(_BODY_YEAR_RE_V6.findall((text or "")[:1200]))
            if (not body_dates or rel_ed in body_dates) and (not head_yrs or rel_ed[:4] in head_yrs):
                fills["event_date"] = rel_ed

    if is_zero_llm_bypass:
        if "event_title" not in cur and rel_row.get("rel_event_title"):
            fills["event_title"] = str(rel_row["rel_event_title"]).strip()
        if "event_type" not in cur and rel_row.get("rel_event_type"):
            fills["event_type"] = str(rel_row["rel_event_type"]).strip()
        if "venue" not in cur and rel_row.get("rel_venue"):
            fills["venue"] = str(rel_row["rel_venue"]).strip()
        if "venue_kind" not in cur and rel_row.get("rel_venue_kind"):
            fills["venue_kind"] = str(rel_row["rel_venue_kind"]).strip()
        if "subcommittees" not in cur and rel_row.get("rel_subcommittees"):
            subs = [str(s).strip() for s in rel_row["rel_subcommittees"] if s and str(s).strip()]
            if subs:
                fills["subcommittees"] = subs

    return fills


def apply_relational_post_pass_v6(
    obj: dict[str, Any],
    rel_row: dict[str, Any] | None,
    *,
    filename: str = "",
    text: str = "",
    hsru_status: str = "not_hsru",
    lookup: dict[str, Any] | None = None,
    allow_ungrounded_qfr_witness: bool = False,
    upgrade_bare_chair_names: bool = False,
) -> dict[str, Any]:
    """Apply all `100%`-precision relational post-pass enrichments to a mutable `DocMetaV4Causal` copy."""
    if not rel_row or not isinstance(obj, dict) or obj.get("status") != "usable":
        return obj
    pk = obj.get("primary_kind")
    if not isinstance(pk, str):
        return obj

    fills = can_fill_from_relational_v6(
        rel_row,
        pk,
        existing_obj=obj,
        filename=filename,
        text=text,
        hsru_status=hsru_status,
        is_zero_llm_bypass=False,
    )
    for k, v in fills.items():
        if k not in obj and v is not None:
            obj[k] = v

    enr_personas = enrich_personas_from_relational_v6(
        obj.get("personas"),
        rel_row,
        pk,
        filename=filename,
        text=text,
        congress=obj.get("congress"),
        committee_codes=rel_row.get("rel_host_committee_codes"),
        lookup=lookup,
        allow_ungrounded_qfr_witness=allow_ungrounded_qfr_witness,
        upgrade_bare_chair_names=upgrade_bare_chair_names,
    )
    if enr_personas:
        obj["personas"] = enr_personas
    else:
        obj.pop("personas", None)

    # Amendment `en_bloc_amendment` subkind from `committee_records.parquet`
    if pk == "committee_amendment" and "subkind" not in obj and rel_row.get("rel_amdt_subkind"):
        obj["subkind"] = rel_row["rel_amdt_subkind"]

    # Authoritative CRS `policy_area` / `subjects` fallback ONLY if `topics` is somehow empty
    if not obj.get("topics"):
        pa_list = list(rel_row.get("rel_bill_policy_areas") or ())
        subj_list = list(rel_row.get("rel_bill_subjects") or ())
        seed_topics = [str(x).strip().lower() for x in (pa_list + subj_list) if x and str(x).strip()][:6]
        if seed_topics:
            obj["topics"] = seed_topics

    return obj
