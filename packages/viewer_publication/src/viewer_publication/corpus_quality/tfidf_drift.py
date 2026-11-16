"""DRY Label-Contradiction & Host Boilerplate-Drift Validator (`corpus_quality.tfidf_drift`).

Repurposes empirical TF-IDF and Monroe et al. (2008) Dirichlet-smoothed log-odds
n-gram mining into three product-grade dataset QA capabilities with zero heavy ML
dependencies (`scipy`/`sklearn`-free; pure Python + `numpy`):

1. `compute_log_odds_signatures`: Reusable discriminative 1..3-gram phrase scorer
   over `core.py`'s shared header/footer/body windows and n-gram stream, shared DRY
   with `tail_clusters.py`.
2. `detect_label_contradictions`: Hybrid class-conditional log-odds + structural
   cover validator (`congress_api.parsers.document_cover`, `house_naming`) that flags
   high-margin document-kind mislabels (e.g. `-Bio-` / `-Wstate-` upload-slot
   inversions, `opening-statement` <-> `witness-statement` swaps, vote sheets tagged
   `amendment`), masthead `congress` contradictions (guarded against the HTML CMS
   Time-Travel Trap), and `committee_keys` / `hsru00` floor-host contradictions.
3. `detect_host_boilerplate_drift`: Per-host header/footer n-gram radar catching
   emerging CMS Congress navigation chrome (`"120th Congress"`), WAF / soft-refusal
   challenge walls (aligned with `model/registries/page-signals.json`), and newly
   spiked template wrappers between `--base` and `--candidate` releases.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Literal

import numpy as np

from congress_api.parsers.document_cover import document_page_fields
from congress_api.parsers.main_content import infer_document_congress, strip_cms_time_travel_lines
from house_naming import is_slot_kind_ambiguous, parse_bills_slug
from viewer_publication.corpus_quality.core import (
    DEFAULT_STOPWORDS,
    CorpusDocRow,
    QualityFinding,
    Severity,
    extract_header_footer_windows,
    extract_url_host,
    iter_word_ngrams,
)

WindowMode = Literal["full", "header", "header_footer"]
LabelSource = Literal["auto", "published", "docmeta"]

_MAX_FULL_WINDOW_CHARS = 8_000
_MAX_TRAIN_DOCS_PER_GENRE = 1_500
_MAX_DOCS_PER_HOST_SIGNATURE = 400

# Jurisdiction / calendar tokens excluded when fitting cross-committee genre log-odds
# so a single committee's topical workload never masquerades as a document genre cue.
_JURISDICTION_NOISE_TOKENS: frozenset[str] = frozenset(
    {
        "energy",
        "commerce",
        "homeland",
        "security",
        "appropriations",
        "judiciary",
        "natural",
        "resources",
        "ways",
        "means",
        "veterans",
        "affairs",
        "financial",
        "services",
        "foreign",
        "relations",
        "armed",
        "agriculture",
        "science",
        "space",
        "technology",
        "transportation",
        "infrastructure",
        "education",
        "workforce",
        "labor",
        "oversight",
        "accountability",
        "reform",
        "small",
        "business",
        "budget",
        "banking",
        "housing",
        "urban",
        "environment",
        "indian",
        "aging",
        "intelligence",
        "rayburn",
        "longworth",
        "cannon",
        "dirksen",
        "hart",
        "russell",
        "capitol",
        "washington",
    }
)

# Generic / opaque slot labels that do not assert a specific positive genre claim on their own
_GENERIC_OPAQUE_PUBLISHED_KINDS: frozenset[str] = frozenset(
    {
        "",
        "<empty>",
        "meeting-support",
        "witness-support",
        "support-document",
        "committee-document",
        "committee-document-numbered",
        "attachment",
        "appendix",
        "exhibit",
        "exhibit-collection",
        "other",
        "multi_doc_packet",
    }
)

# Canonical genre family mapping across both published (hyphenated) and docmeta_v6_1 (underscore) vocabularies
_KIND_TO_CANONICAL_FAMILY: dict[str, str] = {
    # Truth in Testimony
    "testimony-disclosure": "truth_in_testimony_disclosure",
    "truth_in_testimony_disclosure": "truth_in_testimony_disclosure",
    # Biography / CV
    "witness-biography": "witness_biography",
    "biography": "witness_biography",
    "cv-resume": "witness_biography",
    "witness_biography": "witness_biography",
    # Witness testimony
    "witness-statement": "witness_statement",
    "testimony": "witness_statement",
    "witness_statement": "witness_statement",
    # Member opening / floor statement
    "opening-statement": "member_opening_statement",
    "member-statement": "member_opening_statement",
    "opening-remarks": "member_opening_statement",
    "member_opening_statement": "member_opening_statement",
    "member_or_floor_statement": "member_opening_statement",
    # Roll-call votes
    "committee-vote": "committee_vote",
    "tally-sheet": "committee_vote",
    "committee_vote": "committee_vote",
    # Quorum / attendance sheets & rosters
    "attendance-sheet": "attendance_quorum_sheet",
    "attendance_quorum_sheet": "attendance_quorum_sheet",
    "member-roster": "member_roster",
    "member_roster": "member_roster",
    # Amendments
    "committee-amendment": "committee_amendment",
    "amendment": "committee_amendment",
    "bill-house-amendment": "committee_amendment",
    "floor-amendment": "committee_amendment",
    "interchamber-amendment": "committee_amendment",
    "committee-amendment-described": "committee_amendment",
    "committee-enbloc-described": "committee_amendment",
    "committee-enbloc-numbered": "committee_amendment",
    "amendment-collection": "committee_amendment",
    "mark-modification": "committee_amendment",
    "committee_amendment": "committee_amendment",
    # Staff memoranda & hearing charters
    "committee-memorandum": "hearing_memo_or_charter",
    "rules-memorandum": "hearing_memo_or_charter",
    "hearing-charter": "hearing_memo_or_charter",
    "hearing_memo_or_charter": "hearing_memo_or_charter",
    # Hearing & markup notices
    "meeting-notice": "meeting_notice",
    "weekly-meeting-notice": "meeting_notice",
    "hearing_notice": "hearing_notice",
    "markup_notice": "markup_notice",
    # QFRs & questionnaires
    "questions-for-record": "qfr",
    "questions-for-record-response": "qfr",
    "questions-and-answers": "qfr",
    "qfr_request": "qfr_request",
    "qfr_response": "qfr_response",
    "questionnaire": "nominee_questionnaire_apq",
    "nominee_questionnaire_apq": "nominee_questionnaire_apq",
    # Transcripts & published hearings
    "committee-transcript": "hearing_transcript",
    "transcript": "hearing_transcript",
    "published-hearing": "hearing_transcript",
    "hearing_transcript": "hearing_transcript",
    # Witness lists
    "witness-list": "witness_list",
    "panelist-list": "witness_list",
    "participant-list": "witness_list",
    "witness_list": "witness_list",
    # Bills, drafts & legislative text
    "legislative-text": "bill_or_draft",
    "public-law": "bill_or_draft",
    "bill-numbered": "bill_or_draft",
    "bill-untyped-numbered": "bill_or_draft",
    "bill-untyped-draft": "bill_or_draft",
    "bill-suspension-numbered": "bill_or_draft",
    "bill-unnumbered": "bill_or_draft",
    "bill-named-draft": "bill_or_draft",
    "bill-titled-draft": "bill_or_draft",
    "bill-preintroduced": "bill_or_draft",
    "bill-numbered-described": "bill_or_draft",
    "committee-print": "bill_or_draft",
    "published-print": "bill_or_draft",
    "chair-mark": "bill_or_draft",
    "bill_or_draft": "bill_or_draft",
    # Comparative prints
    "bill-comparison": "comparative_print",
    "comparative_print": "comparative_print",
    # Committee / agency / CBO reports
    "committee-report": "committee_report",
    "committee-report-part": "committee_report",
    "committee-report-unnumbered": "committee_report",
    "conference-report": "committee_report",
    "published-report": "committee_report",
    "report": "committee_report",
    "staff-report": "committee_report",
    "activity-report": "committee_report",
    "committee_report": "committee_report",
    "crs-report": "agency_or_gao_crs_report",
    "gao-report": "agency_or_gao_crs_report",
    "agency_or_gao_crs_report": "agency_or_gao_crs_report",
    "cost-estimate": "revenue_or_cost_estimate",
    "revenue_or_cost_estimate": "revenue_or_cost_estimate",
    # Resolutions & rules
    "committee-resolution": "committee_resolution",
    "committee_resolution": "committee_resolution",
    "committee-rules": "committee_rules",
    "committee_rules": "committee_rules",
    # Letters & invitations
    "witness_invitation": "witness_invitation",
    "letter": "letter",
    "letter-of-support": "letter",
    "oversight_letter": "letter",
    "external_submission_letter": "letter",
    "nomination_or_support_letter": "letter",
    # Filings & schedules
    "subpoena": "legal_or_investigative_filing",
    "legal_or_investigative_filing": "legal_or_investigative_filing",
    "legislative_schedule_or_calendar": "legislative_schedule_or_calendar",
    "federal-register-notice": "agency_or_gao_crs_report",
}

_CANONICAL_TO_PUBLISHED_KIND: dict[str, str] = {
    "truth_in_testimony_disclosure": "testimony-disclosure",
    "witness_biography": "witness-biography",
    "witness_statement": "witness-statement",
    "member_opening_statement": "opening-statement",
    "committee_vote": "committee-vote",
    "attendance_quorum_sheet": "attendance-sheet",
    "member_roster": "member-roster",
    "committee_amendment": "committee-amendment",
    "hearing_memo_or_charter": "committee-memorandum",
    "meeting_notice": "meeting-notice",
    "hearing_notice": "meeting-notice",
    "markup_notice": "meeting-notice",
    "qfr": "questions-for-record",
    "qfr_request": "questions-for-record",
    "qfr_response": "questions-for-record-response",
    "nominee_questionnaire_apq": "questionnaire",
    "hearing_transcript": "committee-transcript",
    "witness_list": "witness-list",
    "bill_or_draft": "legislative-text",
    "comparative_print": "bill-comparison",
    "committee_report": "committee-report",
    "agency_or_gao_crs_report": "report",
    "revenue_or_cost_estimate": "cost-estimate",
    "committee_resolution": "committee-resolution",
    "committee_rules": "committee-rules",
    "witness_invitation": "letter",
    "letter": "letter",
    "legal_or_investigative_filing": "subpoena",
    "legislative_schedule_or_calendar": "meeting-notice",
}

# Compatible family pairs that reflect vocabulary granularity rather than genuine mislabeling
_COMPATIBLE_FAMILY_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("meeting_notice", "hearing_notice"),
        ("meeting_notice", "markup_notice"),
        ("qfr", "qfr_request"),
        ("qfr", "qfr_response"),
        ("letter", "witness_invitation"),
        ("letter", "qfr_request"),
        ("member_roster", "attendance_quorum_sheet"),
        ("bill_or_draft", "comparative_print"),
        ("committee_report", "agency_or_gao_crs_report"),
    }
)

# Structural boundary-trap & Tier-1 anchor regexes (validated at 100.0% precision on S_raw / gold360)
_RX_LETTER_SALUTATION = re.compile(
    r"\b(?:Dear\s+(?:Chair|Chairman|Chairwoman|Ranking|Senator|Representative|Congressman|"
    r"Congresswoman|Member|Members|Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.|Professor|Secretary|Director|"
    r"Administrator|Commissioner|General|Admiral|Judge|Honorable|Colleague)|"
    r"Sincerely,?|Respectfully\s+submitted)\b",
    re.I,
)
_RX_STMT_OR_BIO_OPENING = re.compile(
    r"^\s*(?:\d+\s+)?(?:(?:Prepared|Written|Oral)\s+)?(?:Statement|Testimony|Remarks|Biography|Curriculum\s+Vitae|R[eé]sum[eé])\s+(?:of|by)\b",
    re.I,
)
_RX_TTF_CLERK_OR_BESPOKE = re.compile(
    r"(?:Truth\s+in\s+Testimony\s+Disclosure\s+Form|"
    r"[WV]itness\s+Disclosure\s+Requirement\s*[-–—:]?\s*[\"“«']?Truth\s+in\s+Testimony|"
    r"[\"“«']?Truth\s+in\s+Testimony[\"”»']?\s+Disclosure\s+Form|"
    r"Required\s+Witness\s+Disclosure\s+Form\s+House\s+Rules|"
    r"Disclosure\s+Form\s+As\s+required\s+by\s+and\s+provided\s+for\s+in\s+House\s+Rule\s+XI)",
    re.I,
)
_RX_TTF_FORM_SLOTS = re.compile(
    r"(?:Witness\s+Name\s*:|1\.\s*(?:Your\s+)?Name\s*:|Your\s+Name\s*:|"
    r"Position/Title\s*:.*?Witness\s+Type\s*:|filling\s+in\s+the\s+provided\s+blanks|"
    r"Organization(?:s|\(s\))?\s+you\s+(?:are\s+)?represent)",
    re.I | re.S,
)
_RX_TTF_NEG_HEADERS = re.compile(
    r"\b(?:NOTICE\s+OF|MEMORANDUM|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|HEARING\s+CHARTER|"
    r"RULES\s+OF\s+THE\s+COMMITTEE|Thank\s+you\s+for\s+(?:agreeing|appearing|testifying))\b",
    re.I,
)
_RX_HSWM_VOTES = re.compile(
    r"^\s*(?:\d+\s+)?VOTES\s+OF\s+THE\s+COMMITTEE\s+In\s+compliance\s+with\s+the\s+Rules\s+of\s+the\s+House\s+of\s+Representatives",
    re.I,
)
_RX_VOTE_HEAD = re.compile(
    r"(?:FULL\s+COMMITTEE\s+(?:ROSTER\s+)?ROLL\s+CALL|SUBCOMMITTEE\s+ROLL\s+CALL|COMMITTEE\s+ROLL\s+CALL\s+VOTE|"
    r"Roll\s+Call\s+Vote(?:\s+No\.|\s*#|\s+on\b)|RECORD\s+VOTE\s+NO\.\s*\d+|\bROLL\s+CALL\s*:\s*\d+|"
    r"\bROLL\s+CALL\s+NO\.\s*_*\d+|\bRoll\s+Call\s+#\s*\d+)",
    re.I,
)
_RX_VOTE_TALLY = re.compile(
    r"(?:\b(?:YEAS?|AYES?)\s+(?:X*\s*)?(?:NAYS?|NOES?)(?:\s+PRESENT)?\b|"
    r"\(AYE\)\s*\d+\s*\(NO\)\s*\d+|"
    r"\b(?:Yeas?|Ayes?)\s*[:=-]?\s*\d+\s*[,;/]?\s*(?:Nays?|Noes?)\s*[:=-]?\s*\d+|"
    r"\bYEA/AYE\s+NAY/NO\b)",
    re.I,
)
_RX_VOTE_ANY_TALLY = re.compile(r"\b(?:YEAS?|NAYS?|AYES?|NOES?|ROLL\s+CALL\s+NO\.|ROLL\s+CALL\s+VOTE)\b", re.I)
_RX_VOTE_NEG = re.compile(
    r"ROLL\s+CALL\s+ATTENDANCE/QUORUM\s+CALL|\[To\s+accompany\b|Calendar\s+No\.|SUMMARY\s+OF\s+ACTION",
    re.I,
)
_RX_WITNESS_INVITATION = re.compile(
    r"\bDear\s+[^:\n]{2,70}[:,]\s+(?:Thank\s+you\s+for\s+agreeing\s+to\s+testify|"
    r"(?:On\s+behalf\s+of\s+.{5,90}?,\s*)?I\s+(?:am\s+writing\s+to\s+|would\s+like\s+to\s+|cordially\s+)?invite\s+you\s+to\s+testify)\b",
    re.I,
)
_RX_QFR_TRANSMITTAL_DEAR = re.compile(
    r"\bDear\s+[^:\n]{2,70}[:,]\s+(?:I\s+am\s+writing\s+to\s+thank\s+you|Thank\s+you)\s+for\s+(?:appearing|testifying)\s+before\s+the\b",
    re.I,
)
_RX_QFR_TRANSMITTAL_BODY = re.compile(
    r"(?:submit|submitted|enclosed|attached|respond\s+to)\s+(?:additional\s+|written\s+)?questions\s+for\s+the\s+(?:hearing\s+)?record\b",
    re.I,
)
_RX_QFR_RESPONSE_MARKERS = re.compile(
    r"(?:\bI\s+am\s+(?:attaching|submitting|enclosing)\s+my\s+(?:answers|responses)|"
    r"\bplease\s+find\s+(?:attached|enclosed|below)\s+(?:my|our)\s+(?:answers|responses)|"
    r"\b(?:Answer|Response)\s*:\s+[A-Z])",
    re.I,
)
_RX_NOTICE_BANNER = re.compile(
    r"(?:\b(?:HEARING|MARKUP|BUSINESS\s+MEETING)\s+NOTICE\b|"
    r"\bNOTICE\s+OF\s+(?:REVISED\s+)?(?:OVERSIGHT\s+|LEGISLATIVE\s+|FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+|HYBRID\s+|REMOTE\s+)*(?:HEARING|MARKUP|BUSINESS\s+MEETING)\b)")
_RX_STAFF_MEMO_HEAD = re.compile(
    r"(?:\bMEMORANDUM\b|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|Mark-?Up\s+Memorandum|Hearing\s+Memorandum)",
    re.I,
)
_RX_STAFF_MEMO_TO = re.compile(r"\b(?:To|TO)\s*:\s*(?:Re:\s*)?(?:All\s+)?(?:[A-Za-z ,&']+\s+)?Members\b")
_RX_STAFF_MEMO_FROM = re.compile(r"\b(?:From|FROM|Fr|FR)\s*:\s*(?:[A-Za-z ,&'–-]{0,75}?)\bStaff\b")
_RX_CHAIR_OPENING_HEAD = re.compile(
    r"^\s*(?:FOR\s+IMMEDIATE\s+RELEASE\s+|EMBARGOED[^\n]*\n+)?(?:OPENING\s+)?(?:STATEMENT|REMARKS)\s+(?:OF|BY)\s+"
    r"(?:THE\s+HONORABLE\s+)?(?:CHAIRMAN|CHAIRWOMAN|CHAIR\b|RANKING\s+MEMBER|SUBCOMMITTEE\s+CHAIR(?:MAN|WOMAN)?)\b",
    re.I,
)
_RX_MEMBER_GUEST_WITNESS_CUE = re.compile(
    r"\b(?:thank\s+you\s+(?:chair|chairman|chairwoman)[^\n.]{0,60}for\s+inviting\s+me\s+to\s+testify|"
    r"appear(?:ing)?\s+before\s+(?:your|the)\s+(?:sub)?committee\s+today\s+to\s+testify)\b",
    re.I,
)
_RX_NONMEMBER_WITNESS_OPENING = re.compile(
    r"^\s*(?:(?:PREPARED|WRITTEN|ORAL|OPENING)\s+)?(?:TESTIMONY|STATEMENT)\s+(?:OF|BY)\s+[^\n]{2,120}?"
    r"\b(?:PH\.?D\.|M\.?D\.|PROFESSOR|PRESIDENT|VICE\s+PRESIDENT|CHIEF\s+EXECUTIVE\s+OFFICER|CEO\b|"
    r"EXECUTIVE\s+DIRECTOR|MANAGING\s+DIRECTOR|FELLOW\b|GENERAL\s+COUNSEL|INSPECTOR\s+GENERAL|"
    r"COMPTROLLER\s+GENERAL|NOMINEE\s+TO\s+BE)\b",
    re.I,
)
_RX_MEMBER_TITLE_GUARD = re.compile(
    r"\b(?:SENATOR|SEN\.|REPRESENTATIVE|REP\.|CONGRESSMAN|CONGRESSWOMAN|CHAIRMAN|CHAIRWOMAN|RANKING\s+MEMBER)\b",
    re.I,
)

# Congress masthead extraction (PDF / non-HTML)
_ORDINAL_WORDS_TO_CONGRESS: dict[str, int] = {
    "HUNDREDTH": 100,
    "FIRST": 101,
    "SECOND": 102,
    "THIRD": 103,
    "FOURTH": 104,
    "FIFTH": 105,
    "SIXTH": 106,
    "SEVENTH": 107,
    "EIGHTH": 108,
    "NINTH": 109,
    "TENTH": 110,
    "ELEVENTH": 111,
    "TWELFTH": 112,
    "THIRTEENTH": 113,
    "FOURTEENTH": 114,
    "FIFTEENTH": 115,
    "SIXTEENTH": 116,
    "SEVENTEENTH": 117,
    "EIGHTEENTH": 118,
    "NINETEENTH": 119,
    "TWENTIETH": 120,
    "TWENTY-FIRST": 121,
    "TWENTY FIRST": 121,
}
_RX_MASTHEAD_CONGRESS = re.compile(
    r"\b(?:ONE\s+HUNDRED\s+(?:AND\s+)?"
    r"(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
    r"ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH|"
    r"SEVENTEENTH|EIGHTEENTH|NINETEENTH|TWENTIETH|TWENTY[- ]FIRST)\s+CONGRESS|"
    r"(1[0-2]\d)(?:ST|ND|RD|TH)\s+CONGRESS)\b",
    re.I,
)
_RX_PROSE_CONGRESS_CITATION = re.compile(
    r"(?:\(\s*1[0-2]\d(?:st|nd|rd|th)\s+Congress\s*\)|"
    r"\b(?:in|during|since|from|of|for|under|passed\s+in|enacted\s+in|introduced\s+in|prior)\s+the\s+"
    r"(?:1[0-2]\d(?:st|nd|rd|th)|One\s+Hundred\s+[A-Za-z -]+)\s+Congress\b|"
    r"\b(?:P\.L\.|Public\s+Law)\s+1[0-2]\d-\d+)",
    re.I,
)

# Committee masthead patterns for unambiguous standing-committee & hsru00 host-vs-author verification
_STANDING_COMMITTEE_MASTHEADS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("hsif", "House Energy and Commerce", re.compile(r"\bCommittee\s+on\s+Energy\s+(?:and|&)\s+Commerce\b", re.I)),
    ("hsii", "House Natural Resources", re.compile(r"\bCommittee\s+on\s+Natural\s+Resources\b", re.I)),
    ("hsba", "House Financial Services", re.compile(r"\bCommittee\s+on\s+Financial\s+Services\b", re.I)),
    ("hsfa", "House Foreign Affairs", re.compile(r"\bCommittee\s+on\s+Foreign\s+Affairs\b", re.I)),
    ("hshm", "House Homeland Security", re.compile(r"\b(?:House\s+[^\n]{0,40}?Committee\s+on\s+Homeland\s+Security|Committee\s+on\s+Homeland\s+Security\s*,?\s*(?:U\.S\.\s+)?House)\b", re.I)),
    ("hsap", "House Appropriations", re.compile(r"\b(?:House\s+[^\n]{0,30}?Committee\s+on\s+Appropriations|Committee\s+on\s+Appropriations\s*,?\s*(?:U\.S\.\s+)?House)\b", re.I)),
    ("hswm", "House Ways and Means", re.compile(r"\bCommittee\s+on\s+Ways\s+and\s+Means\b", re.I)),
    ("hssy", "House Science, Space, and Technology", re.compile(r"\bCommittee\s+on\s+Science,\s*Space,\s*and\s+Technology\b", re.I)),
    ("hsed", "House Education and the Workforce", re.compile(r"\bCommittee\s+on\s+Education\s+and\s+(?:the\s+)?(?:Workforce|Labor)\b", re.I)),
    ("hspw", "House Transportation and Infrastructure", re.compile(r"\bCommittee\s+on\s+Transportation\s+and\s+Infrastructure\b", re.I)),
    ("hsgo", "House Oversight", re.compile(r"\bCommittee\s+on\s+Oversight\s+and\s+(?:Government\s+Reform|Reform|Accountability)\b", re.I)),
    ("hssm", "House Small Business", re.compile(r"\b(?:House\s+[^\n]{0,30}?Committee\s+on\s+Small\s+Business|Committee\s+on\s+Small\s+Business\s*,?\s*(?:U\.S\.\s+)?House)\b", re.I)),
    ("hsha", "House Administration", re.compile(r"\bCommittee\s+on\s+House\s+Administration\b", re.I)),
    ("hsag", "House Agriculture", re.compile(r"\b(?:House\s+[^\n]{0,30}?Committee\s+on\s+Agriculture|Committee\s+on\s+Agriculture\s*,?\s*(?:U\.S\.\s+)?House)(?!\s*,\s*Nutrition)", re.I)),
    ("hsbu", "House Budget", re.compile(r"\b(?:House\s+[^\n]{0,30}?Committee\s+on\s+the\s+Budget|Committee\s+on\s+the\s+Budget\s*,?\s*(?:U\.S\.\s+)?House)\b", re.I)),
    ("hsju", "House Judiciary", re.compile(r"\b(?:House\s+of\s+Representatives[^\n]{0,60}?Committee\s+on\s+the\s+Judiciary|House\s+Committee\s+on\s+the\s+Judiciary|Committee\s+on\s+the\s+Judiciary\s*,?\s*(?:U\.S\.\s+)?House)\b", re.I)),
    ("hsvr", "House Veterans' Affairs", re.compile(r"\b(?:House\s+[^\n]{0,40}?Committee\s+on\s+Veterans'?\s*Affairs|Committee\s+on\s+Veterans'?\s*Affairs\s*,?\s*(?:U\.S\.\s+)?House)\b", re.I)),
    ("ssju", "Senate Judiciary", re.compile(r"\b(?:United\s+States\s+Senate[^\n]{0,60}?Committee\s+on\s+the\s+Judiciary|Senate\s+Committee\s+on\s+the\s+Judiciary)\b", re.I)),
    ("ssva", "Senate Veterans' Affairs", re.compile(r"\b(?:United\s+States\s+Senate[^\n]{0,60}?Committee\s+on\s+Veterans'?\s*Affairs|Senate\s+Committee\s+on\s+Veterans'?\s*Affairs)\b", re.I)),
    ("ssfr", "Senate Foreign Relations", re.compile(r"\bCommittee\s+on\s+Foreign\s+Relations\b", re.I)),
    ("ssfi", "Senate Finance", re.compile(r"\bCommittee\s+on\s+Finance\b", re.I)),
    ("ssbk", "Senate Banking, Housing, and Urban Affairs", re.compile(r"\bCommittee\s+on\s+Banking,\s*Housing,\s*and\s+Urban\s+Affairs\b", re.I)),
    ("sscm", "Senate Commerce, Science, and Transportation", re.compile(r"\bCommittee\s+on\s+Commerce,\s*Science,\s*and\s+Transportation\b", re.I)),
    ("ssev", "Senate Environment and Public Works", re.compile(r"\bCommittee\s+on\s+Environment\s+and\s+Public\s+Works\b", re.I)),
    ("sshr", "Senate Health, Education, Labor, and Pensions", re.compile(r"\bCommittee\s+on\s+Health,\s*Education,\s*Labor,\s*and\s+Pensions\b", re.I)),
    ("sseg", "Senate Energy and Natural Resources", re.compile(r"\bCommittee\s+on\s+Energy\s+and\s+Natural\s+Resources\b", re.I)),
    ("ssaf", "Senate Agriculture, Nutrition, and Forestry", re.compile(r"\bCommittee\s+on\s+Agriculture,\s*Nutrition,\s*and\s+Forestry\b", re.I)),
)

_RX_HSRU_AUTHORED = re.compile(
    r"(?:^\s*(?:\d+\s+)?MOTION\s+BY\s+(?:MR\.|MS\.|MRS\.|M_?\.)[^\n]{1,80}?\bTO\s+(?:MAKE\s+IN\s+ORDER|STRIKE|WAIVE|POSTPONE)|"
    r"\bI\s+have\s+an\s+amendment\s+to\s+the\s+rule\b|"
    r"\bPROVIDING\s+FOR\s+CONSIDERATION\s+OF\b|"
    r"\bFROM\s+THE\s+COMMITTEE\s+ON\s+RULES\b|"
    r"\bCOMMITTEE\s+ON\s+RULES\b[^\n]{0,120}\b(?:ROLL\s+CALL|HEARING|NOTICE)\b)",
    re.I,
)
_RX_HSRU_HOSTED_PACKAGE = re.compile(
    r"(?:^\s*(?:[A-Z]+\s+\d{1,2},\s*20\d\d\s+)?RULES\s+COMMITTEE\s+PRINT\s+1[0-2]\d[–-]\d+|"
    r"^\s*(?:Comparative\s+Print:|Comparing\s+the\s+base\s+document\s+))",
    re.I,
)

# Load canonical WAF / soft-refusal patterns from model/registries/page-signals.json (100% DRY!)
_PAGE_SIGNALS_PATH = Path(__file__).resolve().parents[5] / "model/registries/page-signals.json"


def _load_canonical_refusal_signals() -> tuple[tuple[str, re.Pattern[str]], ...]:
    signals: list[tuple[str, re.Pattern[str]]] = []
    if _PAGE_SIGNALS_PATH.is_file():
        try:
            entries = json.loads(_PAGE_SIGNALS_PATH.read_text())
            for entry in entries:
                sid = entry.get("id", "")
                kind = entry.get("kind", "")
                pat = entry.get("pattern")
                if pat and sid in {"visible_challenge", "senate_waf_block", "download_wrapper"}:
                    signals.append((sid, re.compile(pat)))
                elif pat and kind == "error_word" and sid == "generic_error":
                    # Tighten generic_error for full-text heads so topical prose with "error" never false-fires
                    signals.append(
                        (
                            "generic_error_banner",
                            re.compile(
                                r"^\s*(?:403\s+forbidden|404\s+(?:page\s+)?not\s+found|access\s+denied|"
                                r"service\s+unavailable|just\s+a\s+moment\.{0,3}|attention\s+required\s*[|!-]|"
                                r"checking\s+your\s+browser|client\s+challenge)\b",
                                re.I | re.M,
                            ),
                        )
                    )
        except (OSError, ValueError, TypeError):
            pass
    signals.extend(
        [
            (
                "cloudflare_or_akamai_waf",
                re.compile(
                    r"(?:cloudflare\s+ray\s+id|performance\s+&\s+security\s+by\s+cloudflare|"
                    r"you\s+don['’]t\s+have\s+permission\s+to\s+access\s+.{1,80}\s+on\s+this\s+server|"
                    r"akamaighost|reference\s*#\s*\d+\.\w+\.\d+)",
                    re.I,
                ),
            ),
            (
                "js_analytics_stub",
                re.compile(
                    r"^\s*(?:\(window\.NREUM|<!--//--><!\[CDATA\[//><!--\s*jQuery\.extend\(Drupal\.settings)",
                    re.I,
                ),
            ),
        ]
    )
    return tuple(signals)


_CANONICAL_REFUSAL_SIGNALS = _load_canonical_refusal_signals()

_RX_CMS_CHROME_WRAPPER = re.compile(
    r"(?:Skip\s+to\s+(?:main\s+)?content|Skip\s+to\s+primary\s+navigation|"
    r"Report\s+Waste,\s*Fraud,\s*and\s+Abuse|"
    r"Subcommittees\s+Press\s+Releases\s+Opening\s+Statements|"
    r"Toggle\s+navigation\s+Main\s+menu)",
    re.I,
)
_RX_NAV_CONGRESS_BANNER = re.compile(r"\b(1[12]\d)(?:st|nd|rd|th)\s+Congress\b", re.I)

# Boilerplate indicator words distinguishing broken template/CMS chrome from normal committee mastheads
_BOILERPLATE_CHROME_CUES: frozenset[str] = frozenset(
    {
        "skip",
        "navigation",
        "menu",
        "waste",
        "fraud",
        "javascript",
        "cookies",
        "cookie",
        "browser",
        "cloudflare",
        "denied",
        "forbidden",
        "unavailable",
        "subscribe",
        "newsletter",
        "drupal",
        "nreum",
        "cdata",
        "jquery",
        "search",
        "sidebar",
        "footer",
        "privacy",
        "accessibility",
        "human",
        "challenge",
        "captcha",
        "error",
        "403",
        "404",
    }
)


@dataclass(frozen=True, slots=True)
class PhraseSignature:
    """Discriminative phrase statistics scored via Monroe Dirichlet log-odds and cross-group TF-IDF."""

    phrase: str
    z_score: float
    log_odds: float
    tfidf_score: float
    within_df: float
    background_df: float
    doc_count: int
    group_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase": self.phrase,
            "z_score": round(float(self.z_score), 4),
            "log_odds": round(float(self.log_odds), 4),
            "tfidf_score": round(float(self.tfidf_score), 4),
            "within_df": round(float(self.within_df), 4),
            "background_df": round(float(self.background_df), 4),
            "doc_count": int(self.doc_count),
            "group_size": int(self.group_size),
        }


def _slice_window(text: str | None, window: WindowMode) -> str:
    if not text:
        return ""
    if window == "full":
        return text[:_MAX_FULL_WINDOW_CHARS]
    win = extract_header_footer_windows(text)
    if window == "header":
        return win.header
    return f"{win.header}\n{win.footer}".strip() if win.footer else win.header


def _deterministic_stride(items: Sequence[Any], max_items: int) -> Sequence[Any]:
    if len(items) <= max_items or max_items <= 0:
        return items
    step = len(items) / float(max_items)
    return [items[int(i * step)] for i in range(max_items)]


def compute_log_odds_signatures(
    groups_to_texts: Mapping[str, Sequence[str]],
    *,
    background_texts: Sequence[str] | None = None,
    ngram_range: tuple[int, int] = (1, 3),
    top_k: int = 10,
    alpha_total: float = 500.0,
    min_df: int = 2,
    max_df_ratio: float = 0.90,
    min_group_docs: int = 2,
    binary_per_doc: bool = True,
    window: WindowMode = "full",
    exclude_terms: Collection[str] = (),
) -> dict[str, list[PhraseSignature]]:
    """Compute Dirichlet-smoothed log-odds (`Fightin' Words`) & cross-group TF-IDF phrase signatures.

    Shared DRY across `tfidf_drift` and `tail_clusters`: uses `core.extract_header_footer_windows`
    and `core.iter_word_ngrams` directly with zero `scipy`/`sklearn` dependencies.
    """
    if top_k <= 0 or not groups_to_texts:
        return {}

    excluded = {t.strip().lower() for t in exclude_terms if t and t.strip()}
    eligible_groups: list[tuple[str, Sequence[str]]] = [
        (str(g), texts)
        for g, texts in groups_to_texts.items()
        if texts is not None and len(texts) >= max(1, min_group_docs)
    ]
    if not eligible_groups:
        return {}

    group_doc_counts: dict[str, Counter[str]] = {}
    group_term_counts: dict[str, Counter[str]] = {}
    group_sizes: dict[str, int] = {}
    global_df: Counter[str] = Counter()

    def _count_texts(texts: Sequence[str]) -> tuple[Counter[str], Counter[str], int]:
        df_c: Counter[str] = Counter()
        tf_c: Counter[str] = Counter()
        n_docs = len(texts)
        for raw in texts:
            sliced = _slice_window(raw, window)
            if not sliced:
                continue
            gen = iter_word_ngrams(
                sliced,
                ngram_range=ngram_range,
                lowercase=True,
                drop_pure_digits=True,
                stopwords=DEFAULT_STOPWORDS,
            )
            if binary_per_doc:
                seen = {ng for ng in gen if ng not in excluded and not _has_excluded_token(ng, excluded)}
                df_c.update(seen)
                tf_c.update(seen)
            else:
                doc_tf: Counter[str] = Counter(
                    ng for ng in gen if ng not in excluded and not _has_excluded_token(ng, excluded)
                )
                df_c.update(doc_tf.keys())
                tf_c.update(doc_tf)
        return df_c, tf_c, n_docs

    for g_name, texts in eligible_groups:
        df_c, tf_c, n_docs = _count_texts(texts)
        group_doc_counts[g_name] = df_c
        group_term_counts[g_name] = tf_c
        group_sizes[g_name] = n_docs
        global_df.update(df_c)

    bg_df_explicit: Counter[str] | None = None
    bg_tf_explicit: Counter[str] | None = None
    bg_n_docs = 0
    if background_texts is not None and len(background_texts) > 0:
        bg_df_explicit, bg_tf_explicit, bg_n_docs = _count_texts(background_texts)
        global_df.update(bg_df_explicit)

    has_contrast = len(eligible_groups) >= 2 or (bg_df_explicit is not None and bg_n_docs > 0)

    # Filter vocabulary by min_df and cross-group ubiquity (never dropping dominant-group signatures!)
    vocab: list[str] = []
    for phrase, tot_df in global_df.items():
        if tot_df < max(1, min_df):
            continue
        if has_contrast and max_df_ratio < 1.0:
            # Drop only true corpus-wide boilerplate present above max_df_ratio in EVERY group (and background)
            all_ubiquitous = all(
                (group_doc_counts[g].get(phrase, 0) / max(group_sizes[g], 1)) > max_df_ratio
                for g, _ in eligible_groups
            )
            if bg_df_explicit is not None and bg_n_docs > 0:
                all_ubiquitous = all_ubiquitous and ((bg_df_explicit.get(phrase, 0) / bg_n_docs) > max_df_ratio)
            if all_ubiquitous:
                continue
        vocab.append(phrase)

    vocab.sort()
    if not vocab:
        return {g: [] for g, _ in eligible_groups}

    v_len = len(vocab)
    phrase_to_idx = {p: idx for idx, p in enumerate(vocab)}

    # Build dense [G, V] matrices (V is compact after min_df filtering, fast vectorized numpy math)
    g_names = [g for g, _ in eligible_groups]
    n_groups = len(g_names)
    mat_tf = np.zeros((n_groups, v_len), dtype=np.float64)
    mat_df = np.zeros((n_groups, v_len), dtype=np.int32)
    sizes_arr = np.array([group_sizes[g] for g in g_names], dtype=np.float64)

    for row_i, g in enumerate(g_names):
        df_c = group_doc_counts[g]
        tf_c = group_term_counts[g]
        for p, d_cnt in df_c.items():
            col_j = phrase_to_idx.get(p)
            if col_j is not None:
                mat_df[row_i, col_j] = d_cnt
                mat_tf[row_i, col_j] = float(tf_c[p])

    bg_tf_vec = np.zeros(v_len, dtype=np.float64)
    bg_df_vec = np.zeros(v_len, dtype=np.int32)
    if bg_df_explicit is not None and bg_n_docs > 0:
        for p, d_cnt in bg_df_explicit.items():
            col_j = phrase_to_idx.get(p)
            if col_j is not None:
                bg_df_vec[col_j] = d_cnt
                bg_tf_vec[col_j] = float(bg_tf_explicit[p])  # type: ignore[index]

    # Cross-group IDF: log((1 + total_groups) / (1 + active_groups))
    total_contrast_groups = n_groups + (1 if bg_n_docs > 0 else 0)
    group_df_rates = mat_df / np.maximum(sizes_arr[:, None], 1.0)
    active_groups = (group_df_rates >= 0.02).sum(axis=0).astype(np.float64)
    if bg_n_docs > 0:
        active_groups += ((bg_df_vec / float(bg_n_docs)) >= 0.02).astype(np.float64)
    cross_group_idf = (
        np.log((1.0 + total_contrast_groups) / (1.0 + np.minimum(active_groups, total_contrast_groups - 0.5)))
        if has_contrast
        else np.ones(v_len, dtype=np.float64)
    )

    total_tf_all = mat_tf.sum(axis=0) + bg_tf_vec
    total_tokens_all = float(total_tf_all.sum())
    total_docs_all = int(sizes_arr.sum()) + bg_n_docs

    alpha_0 = max(float(alpha_total), 1.0)
    if has_contrast and total_tokens_all > 0:
        # Scale prior concentration on small corpora so pseudocounts never overwhelm observed counts
        eff_alpha_0 = min(alpha_0, max(2.0, 0.20 * total_tokens_all))
        alpha_vec = eff_alpha_0 * (total_tf_all / total_tokens_all)
        alpha_vec = np.maximum(alpha_vec, 1e-6)
        alpha_sum = float(alpha_vec.sum())
    else:
        # Single-group fallback with no external background: contrast against a broad virtual vocabulary V0
        virtual_vocab = max(1000.0, 20.0 * v_len)
        eff_alpha_0 = min(alpha_0, max(5.0, 0.50 * max(total_tokens_all, 1.0)))
        alpha_vec = np.full(v_len, eff_alpha_0 / virtual_vocab, dtype=np.float64)
        alpha_sum = eff_alpha_0

    out: dict[str, list[PhraseSignature]] = {}
    for row_i, g in enumerate(g_names):
        yi = mat_tf[row_i]
        ni = float(yi.sum())
        g_size = int(sizes_arr[row_i])
        df_i_counts = mat_df[row_i]
        df_i_float = df_i_counts.astype(np.float64)
        within_df = df_i_float / max(g_size, 1)

        if not has_contrast:
            # Single-group fallback: contrast group incidence against sparse virtual background prior
            y_not = np.zeros(v_len, dtype=np.float64)
            n_not = 0.0
            other_docs = max(g_size * 10, 20)
            other_df_float = np.zeros(v_len, dtype=np.float64)
            bg_df_rate = np.zeros(v_len, dtype=np.float64)
        elif bg_n_docs > 0 and n_groups == 1:
            y_not = bg_tf_vec
            n_not = float(y_not.sum())
            other_docs = max(bg_n_docs, 1)
            other_df_float = bg_df_vec.astype(np.float64)
            bg_df_rate = other_df_float / float(other_docs)
        else:
            y_not = np.maximum(total_tf_all - yi, 0.0)
            n_not = max(total_tokens_all - ni, 0.0)
            other_docs = max(total_docs_all - g_size, 1)
            other_df_float = np.maximum((mat_df.sum(axis=0) + bg_df_vec) - df_i_counts, 0).astype(np.float64)
            bg_df_rate = other_df_float / float(other_docs)

        if binary_per_doc:
            # Exact document-incidence Beta/Dirichlet log-odds (length- & ngram_range-invariant!)
            # Prior pseudocounts (a_pos, a_neg) blend informative corpus DF rate with Haldane 0.5 floor.
            if has_contrast:
                pooled_rate = (df_i_float + other_df_float + 0.5) / float(g_size + other_docs + 1.0)
                tau = min(max(alpha_0 / 250.0, 1.0), 2.0)
                a_pos = np.maximum(0.5 * tau * pooled_rate + 0.25, 0.35)
                a_neg = np.maximum(0.5 * tau * (1.0 - pooled_rate) + 0.25, 0.35)
            else:
                a_pos = np.full(v_len, 0.25, dtype=np.float64)
                a_neg = np.full(v_len, 2.0, dtype=np.float64)

            pos_i = df_i_float + a_pos
            neg_i = np.maximum(float(g_size) - df_i_float, 0.0) + a_neg
            pos_not = other_df_float + a_pos
            neg_not = np.maximum(float(other_docs) - other_df_float, 0.0) + a_neg

            delta = np.log(pos_i / neg_i) - np.log(pos_not / neg_not)
            se = np.sqrt(1.0 / pos_i + 1.0 / neg_i + 1.0 / pos_not + 1.0 / neg_not)
            z_scores = delta / se
        else:
            denom_i = np.maximum((ni + alpha_sum) - (yi + alpha_vec), 1e-9)
            denom_not = np.maximum((n_not + alpha_sum) - (y_not + alpha_vec), 1e-9)
            delta = np.log((yi + alpha_vec) / denom_i) - np.log((y_not + alpha_vec) / denom_not)
            se = np.sqrt(1.0 / (yi + alpha_vec) + 1.0 / (y_not + alpha_vec))
            z_scores = delta / se

        tfidf_scores = within_df * np.maximum(cross_group_idf, 0.05)

        # Keep only phrases actually present in this group above min_df (or >=1 if group itself is small)
        group_min = min(max(1, min_df), g_size)
        cand_indices = [
            j
            for j in range(v_len)
            if int(df_i_counts[j]) >= group_min and z_scores[j] > 0.0
        ]
        # On exact statistical ties, prefer multi-word structural phrases (3-grams > 2-grams > 1-grams)
        cand_indices.sort(
            key=lambda j: (
                -round(float(z_scores[j]), 6),
                -round(float(tfidf_scores[j]), 6),
                -int(df_i_counts[j]),
                -len(vocab[j].split()),
                vocab[j],
            )
        )
        out[g] = [
            PhraseSignature(
                phrase=vocab[j],
                z_score=float(z_scores[j]),
                log_odds=float(delta[j]),
                tfidf_score=float(tfidf_scores[j]),
                within_df=float(within_df[j]),
                background_df=float(bg_df_rate[j]),
                doc_count=int(df_i_counts[j]),
                group_size=g_size,
            )
            for j in cand_indices[:top_k]
        ]
    return out


def _has_excluded_token(ngram: str, excluded: set[str]) -> bool:
    if not excluded:
        return False
    return any(tok in excluded for tok in ngram.split())


def _canonicalize_kind(kind: str | None) -> str | None:
    if not kind:
        return None
    low = kind.strip().lower()
    if low in _GENERIC_OPAQUE_PUBLISHED_KINDS:
        return None
    return _KIND_TO_CANONICAL_FAMILY.get(low)


def _families_compatible(fam_a: str, fam_b: str, *, source_mode: str) -> bool:
    if fam_a == fam_b:
        return True
    if (fam_a, fam_b) in _COMPATIBLE_FAMILY_PAIRS or (fam_b, fam_a) in _COMPATIBLE_FAMILY_PAIRS:
        # In published mode, hearing_notice/markup_notice both collapse to meeting-notice and
        # qfr_request/qfr_response both collapse to questions-for-record.
        if source_mode == "published":
            return True
        # In docmeta mode, keep hearing_notice != markup_notice and qfr_request != qfr_response distinct
        if {fam_a, fam_b} in ({"hearing_notice", "markup_notice"}, {"qfr_request", "qfr_response"}):
            return False
        return True
    return False


def _format_expected_kind(canonical_family: str, *, source_mode: str) -> str:
    if source_mode == "published":
        return _CANONICAL_TO_PUBLISHED_KIND.get(canonical_family, canonical_family)
    return canonical_family


_RX_FAST_COVER_PREFILTER = re.compile(
    r"(?:SERIAL\s+NO\.|S\.\s*H\s*RG\.|STENOGRAPHIC|PURSUANT\s+TO\s+NOTICE|"
    r"OPENING\s+STATEMENT|(?:PREPARED\s+|WRITTEN\s+|ORAL\s+)?(?:TESTIMONY|STATEMENT)\s+(?:OF|BY|BEFORE)|"
    r"TRUTH\s+IN\s+TESTIMONY|DISCLOSURE\s+FORM|QUESTIONNAIRE|QUESTIONS?\s+FOR\s+THE\s+RECORD|"
    r"SUBPOENA|ATTENDANCE|QUORUM|MARKUP\s+NOTICE|NOTICE\s+OF\s+(?:FULL\s+|SUBCOMMITTEE\s+|REVISED\s+)?MARKUP|"
    r"WITNESS\s+LIST|LIST\s+OF\s+WITNESSES|CURRICULUM\s+VITAE|R[EÉ]SUM[EÉ]|BIOGRAPHY\s+OF|BIOGRAPHICAL\s+SKETCH|"
    r"^\s*EDUCATION\s*$|FEDERAL\s+REGISTER|CONGRESSIONAL\s+RESEARCH\s+SERVICE|CRS\s+(?:REPORT|IN\s+FOCUS|INSIGHT|LEGAL)|"
    r"GOVERNMENT\s+ACCOUNTABILITY\s+OFFICE|GAO-\d{2}|COST\s+ESTIMATE|AT\s+A\s+GLANCE|"
    r"STAFF\s+REPORT|A\s?MENDMENT|ROLL\s+CALL|VOTES\s+OF\s+THE\s+COMMITTEE|"
    r"IN\s+THE\s+COMMITTEE\s+ON|IN\s+THE\s+(?:HOUSE|SENATE)\s+OF)",
    re.I | re.M,
)
_STRUCTURAL_BODY_CACHE: dict[str, tuple[str | None, str | None]] = {}


def _structural_body_family(
    text: str,
    *,
    file_ext: str,
    cache_key: str = "",
) -> tuple[str | None, str | None]:
    """Return `(canonical_family, anchor_source)` when opening pages carry a 100%-precision structural form."""
    if not text or len(text.strip()) < 40:
        return None, None
    if cache_key:
        cached = _STRUCTURAL_BODY_CACHE.get(cache_key)
        if cached is not None:
            return cached

    head1600 = text[:1600]
    head950 = text[:950]
    flat600 = " ".join(text[:600].split())

    is_html = file_ext in {"html", "htm", "aspx"}
    if is_html:
        res: tuple[str | None, str | None] = (None, None)
        if flat600.startswith(
            "Committee Repository Clerk of the House Majority Leader Committee on Rules "
            "U.S. House of Representatives Bills to be Considered on the House Floor"
        ):
            res = ("legislative_schedule_or_calendar", "tier1:docs_house_floor_weekly")
        if cache_key and len(_STRUCTURAL_BODY_CACHE) < 400_000:
            _STRUCTURAL_BODY_CACHE[cache_key] = res
        return res

    # Guard against stapled multi-doc packets where page 1 opens as a witness statement or biography
    opens_as_stmt_or_bio = bool(_RX_STMT_OR_BIO_OPENING.match(flat600[:180]))
    has_letter_salutation = bool(_RX_LETTER_SALUTATION.search(head950[:800]))

    res = (None, None)
    # 1. Truth-in-Testimony forms (Clerk AcroForm v1/v2 + committee-bespoke Rule XI forms)
    if (
        not opens_as_stmt_or_bio
        and not has_letter_salutation
        and not _RX_TTF_NEG_HEADERS.search(flat600)
        and _RX_TTF_CLERK_OR_BESPOKE.search(flat600[:420])
        and _RX_TTF_FORM_SLOTS.search(head950)
    ):
        res = ("truth_in_testimony_disclosure", "tier1:truth_in_testimony_form")
    # 2. Chair Witness Invitation letters & Chair QFR Transmittal letters (frequently misfiled in -Bio- / -Wstate-)
    elif (
        not opens_as_stmt_or_bio
        and _RX_WITNESS_INVITATION.search(head1600[:1150])
        and re.search(r"Truth[- ]in[- ]Testimony|written\s+testimony|hearing\s+entitled", head1600, re.I)
    ):
        res = ("witness_invitation", "tier1:witness_invitation_chair_letter")
    elif (
        not opens_as_stmt_or_bio
        and _RX_QFR_TRANSMITTAL_DEAR.search(head1600[:1150])
        and _RX_QFR_TRANSMITTAL_BODY.search(head1600)
        and not _RX_QFR_RESPONSE_MARKERS.search(text[:2500])
    ):
        res = ("qfr_request", "tier1:qfr_request_chair_transmittal")
    # 3. Ways & Means & multi-committee roll-call vote tally sheets (frequently misfiled as amendment)
    elif _RX_HSWM_VOTES.match(flat600[:260]) and _RX_VOTE_ANY_TALLY.search(head1600):
        res = ("committee_vote", "tier1:vote_hswm_votes_of_committee")
    elif (
        not _RX_VOTE_NEG.search(flat600)
        and _RX_VOTE_HEAD.search(flat600[:420])
        and _RX_VOTE_TALLY.search(head1600)
    ):
        res = ("committee_vote", "tier1:vote_committee_roll_call_tally")
    # 4. Staff Memoranda (`To: Members ... From: Staff`, excluding hsii Chairman Hearing/Markup Notices)
    elif (
        not _RX_NOTICE_BANNER.search(head950[:450])
        and _RX_STAFF_MEMO_HEAD.search(head950[:550])
        and _RX_STAFF_MEMO_TO.search(head950[:750])
        and _RX_STAFF_MEMO_FROM.search(head950)
    ):
        res = ("hearing_memo_or_charter", "tier1:memo_committee_staff_to_members")
    # 5. Opening-statement vs Witness-statement explicit speaker-role inversions
    elif _RX_CHAIR_OPENING_HEAD.search(head950[:450]) and not _RX_MEMBER_GUEST_WITNESS_CUE.search(head1600):
        res = ("member_opening_statement", "tier1:chair_or_ranking_opening_statement")
    elif _RX_NONMEMBER_WITNESS_OPENING.search(head950[:450]) and not _RX_MEMBER_TITLE_GUARD.search(flat600[:260]):
        res = ("witness_statement", "tier1:nonmember_witness_testimony_header")
    # 6. Delegate DRY to congress_api.parsers.document_cover.document_page_fields (behind fast C-regex prefilter)
    elif _RX_FAST_COVER_PREFILTER.search(head1600):
        cover = document_page_fields(text[:2600])
        if cover_kinds := cover.get("content_document_kind"):
            ck = cover_kinds[0]
            mapped = _canonicalize_kind(ck)
            if mapped is not None and not (
                opens_as_stmt_or_bio
                and mapped not in {"witness_statement", "witness_biography", "member_opening_statement"}
            ):
                res = (mapped, f"document_cover:{ck}")

    if cache_key and len(_STRUCTURAL_BODY_CACHE) < 400_000:
        _STRUCTURAL_BODY_CACHE[cache_key] = res
    return res


def _violates_boundary_guard(predicted_family: str, text: str) -> bool:
    """Block known lexical boundary traps when evaluating statistical log-odds predictions."""
    head950 = text[:950]
    flat600 = " ".join(text[:600].split())
    if predicted_family == "truth_in_testimony_disclosure":
        if _RX_LETTER_SALUTATION.search(head950) or _RX_STMT_OR_BIO_OPENING.match(flat600[:180]):
            return True
        if _RX_TTF_NEG_HEADERS.search(flat600):
            return True
    elif predicted_family == "hearing_memo_or_charter":
        if _RX_NOTICE_BANNER.search(head950[:500]) or not _RX_STAFF_MEMO_FROM.search(head950):
            return True
    elif predicted_family == "hearing_notice":
        if re.search(r"\b(?:MARKUP|BUSINESS\s+MEETING)\b", head950, re.I):
            return True
    elif predicted_family == "markup_notice":
        if re.search(r"\bHEARING\s+NOTICE\b|\bNOTICE\s+OF\s+[^\n]{0,40}HEARING\b", head950, re.I) and not re.search(
            r"\bMARKUP\b", head950, re.I
        ):
            return True
    elif predicted_family in {"letter", "witness_invitation", "qfr_request"}:
        if not _RX_LETTER_SALUTATION.search(head950) or _RX_STMT_OR_BIO_OPENING.match(flat600[:180]):
            return True
    elif predicted_family == "attendance_quorum_sheet":
        if _RX_VOTE_ANY_TALLY.search(text):
            return True
    elif predicted_family == "committee_amendment":
        if _RX_VOTE_ANY_TALLY.search(head950) or _RX_LETTER_SALUTATION.search(flat600):
            return True
    elif predicted_family == "member_opening_statement":
        if _RX_MEMBER_GUEST_WITNESS_CUE.search(text[:1600]) or _RX_NONMEMBER_WITNESS_OPENING.search(head950[:450]):
            return True
    elif predicted_family == "witness_statement":
        if _RX_CHAIR_OPENING_HEAD.search(head950[:450]):
            return True
    return False


def _resolve_row_assigned_kinds(
    row: CorpusDocRow,
    label_source: LabelSource,
) -> tuple[str | None, tuple[str, ...], str]:
    """Return `(primary_raw_kind, all_canonical_families, effective_source_mode)`."""
    if label_source == "docmeta" or (label_source == "auto" and row.docmeta_primary_kind):
        raw = row.docmeta_primary_kind
        fam = _canonicalize_kind(raw)
        return raw, ((fam,) if fam else ()), "docmeta"

    if label_source == "docmeta":
        return None, (), "docmeta"

    raw_list = tuple(k for k in row.document_kind if k)
    if not raw_list:
        return None, (), "published"

    primary_raw = raw_list[0]
    fams = tuple(dict.fromkeys(f for k in raw_list if (f := _canonicalize_kind(k)) is not None))
    # Published generic `statement` umbrella covers both witness_statement and member_opening_statement
    if any(k.lower() == "statement" for k in raw_list):
        fams = tuple(dict.fromkeys((*fams, "witness_statement", "member_opening_statement")))
    return primary_raw, fams, "published"


def _is_ambiguous_upload_slot(row: CorpusDocRow, primary_raw_kind: str | None) -> bool:
    fn_low = (row.filename or "").lower()
    if any(tok in fn_low for tok in ("-bio-", "_bio_", "-wstate-", "-sd0", "-mstate-")):
        return True
    return is_slot_kind_ambiguous(primary_raw_kind)


def _extract_unambiguous_pdf_masthead_congress(text: str) -> int | None:
    """Extract opening PDF masthead Congress only when every masthead mention agrees and is non-citational."""
    head = text[:700]
    found: set[int] = set()
    for line in head.splitlines()[:10]:
        stripped = line.strip()
        if not stripped or len(stripped) > 160:
            continue
        if _RX_PROSE_CONGRESS_CITATION.search(stripped):
            continue
        for m in _RX_MASTHEAD_CONGRESS.finditer(stripped):
            if m.group(1):
                word_key = re.sub(r"\s+", " ", m.group(1).upper()).strip()
                c_val = _ORDINAL_WORDS_TO_CONGRESS.get(word_key)
            else:
                c_val = int(m.group(2))
            if c_val is not None and 100 <= c_val <= 125:
                found.add(c_val)
    return next(iter(found)) if len(found) == 1 else None


def _check_congress_contradiction(
    row: CorpusDocRow,
    *,
    source_mode: str,
) -> QualityFinding | None:
    assigned_cong = row.docmeta_congress if (source_mode == "docmeta" and row.docmeta_congress is not None) else row.congress
    if assigned_cong is None or not row.p12_text:
        return None

    ext = row.file_ext
    is_html = ext in {"html", "htm", "aspx"} or (row.effective_format or "").lower() == "html"
    if is_html:
        # Strip live CMS time-travel banners before checking HTML Congress so nav chrome never misleads
        declared = (row.document_date,) if row.document_date else ()
        cleaned = strip_cms_time_travel_lines(row.p12_text, declared_dates=declared)
        # Only flag HTML if explicit post-nav date AND body Congress both contradict by >= 2 Congresses
        if row.document_date:
            inferred = infer_document_congress(cleaned, declared_dates=(row.document_date,))
            if inferred is not None and abs(inferred - assigned_cong) >= 2:
                return QualityFinding(
                    code="congress_body_contradiction",
                    severity="warning",
                    category="label_contradiction",
                    link_key_hex=row.link_key_hex,
                    filename=row.filename,
                    expected=inferred,
                    observed=assigned_cong,
                    score=float(abs(inferred - assigned_cong)),
                    evidence={
                        "source": "html_date_and_body_congress",
                        "document_date": row.document_date,
                        "inferred_congress": inferred,
                    },
                )
        return None

    # Exclude historical quotes across the entire opening 900 chars if they mention another Congress in prose
    if _RX_PROSE_CONGRESS_CITATION.search(row.p12_text[:900]):
        return None

    masthead_cong = _extract_unambiguous_pdf_masthead_congress(row.p12_text)
    if masthead_cong is None or masthead_cong == assigned_cong:
        return None

    slug_info = parse_bills_slug(row.filename) if row.filename.upper().startswith("BILLS-") else None
    slug_cong = getattr(slug_info, "congress", None) if slug_info is not None else None
    score = 5.0 if (slug_cong == masthead_cong) else 3.5

    return QualityFinding(
        code="congress_body_contradiction",
        severity="warning",
        category="label_contradiction",
        link_key_hex=row.link_key_hex,
        filename=row.filename,
        expected=masthead_cong,
        observed=assigned_cong,
        score=score,
        evidence={
            "source": "pdf_opening_masthead",
            "masthead_congress": masthead_cong,
            "assigned_congress": assigned_cong,
            "bills_slug_congress": slug_cong,
        },
    )


_RX_COMMITTEE_CODE_TOKEN = re.compile(r"^([a-z]{4})(?:\d{2})?$", re.I)


def _normalize_assigned_parent_committees(raw_cmts: Sequence[str]) -> set[str]:
    """Normalize either 4/6-char system codes (`hsif00`) or full committee names (`House Committee on ...`)."""
    parents: set[str] = set()
    for raw in raw_cmts:
        if not raw:
            continue
        cleaned = raw.strip()
        if m := _RX_COMMITTEE_CODE_TOKEN.match(cleaned):
            parents.add(m.group(1).lower())
            continue
        low = cleaned.lower()
        if "committee on rules" in low or low in {"house rules", "rules committee"}:
            parents.add("hsru")
            continue
        matched_any = False
        for code, label, rx in _STANDING_COMMITTEE_MASTHEADS:
            if rx.search(cleaned) or label.lower() in low:
                parents.add(code)
                matched_any = True
        if not matched_any:
            # Unknown / select / joint / Senate Armed Services etc. — mark sentinel so we never false-flag!
            parents.add(f"other:{low[:24]}")
    return parents


def _check_committee_contradiction(
    row: CorpusDocRow,
    *,
    source_mode: str,
) -> QualityFinding | None:
    if not row.p12_text:
        return None
    ext = row.file_ext
    if ext in {"html", "htm", "aspx"} or (row.effective_format or "").lower() == "html":
        return None

    raw_cmts = row.docmeta_committees if (source_mode == "docmeta" and row.docmeta_committees) else row.committee_keys
    if not raw_cmts:
        return None

    parent_codes = _normalize_assigned_parent_committees(raw_cmts)
    if not parent_codes:
        return None

    head1000 = row.p12_text[:1000]
    flat500 = " ".join(row.p12_text[:500].split())

    # 1. House Rules (`hsru` / `hsru00`) floor-gatekeeper host vs originating committee author
    if parent_codes == {"hsru"}:
        if _RX_HSRU_AUTHORED.search(head1000) or "-RU" in (row.filename or "").upper():
            return None
        other_hits = [code for code, _, rx in _STANDING_COMMITTEE_MASTHEADS if rx.search(head1000)]
        is_hosted_pkg = bool(_RX_HSRU_HOSTED_PACKAGE.match(flat500))
        if other_hits or is_hosted_pkg:
            expected_cmt = other_hits[0] if other_hits else "floor_or_originating_committee"
            return QualityFinding(
                code="committee_body_contradiction",
                severity="warning",
                category="label_contradiction",
                link_key_hex=row.link_key_hex,
                filename=row.filename,
                expected=expected_cmt,
                observed=list(raw_cmts),
                score=4.0 if other_hits else 3.0,
                evidence={
                    "mechanism": "hsru00_floor_host_attribution_leakage",
                    "originating_committees_in_p12": other_hits,
                    "is_hosted_print_or_diff": is_hosted_pkg,
                },
            )
        return None

    # 2. Single-committee assignment contradicted by an unambiguous non-joint opening committee masthead
    if len(parent_codes) != 1:
        return None
    assigned_parent = next(iter(parent_codes))
    # Skip joint hearings, multi-committee bill referrals, and witness/member testimonies citing other committees
    if re.search(r"\b(?:Joint\s+Hearing|and\s+in\s+addition\s+to\s+the\s+Committee|referred\s+to\s+the\s+Committee)\b", head1000, re.I):
        return None
    if _RX_STMT_OR_BIO_OPENING.match(flat500[:180]) or _RX_LETTER_SALUTATION.search(head1000[:700]):
        return None

    masthead_window = "\n".join(row.p12_text.splitlines()[:8])[:450]
    matched_parents = [code for code, _, rx in _STANDING_COMMITTEE_MASTHEADS if rx.search(masthead_window)]
    if len(matched_parents) == 1 and matched_parents[0] != assigned_parent:
        # Confirm assigned committee does not appear anywhere in the opening 1,000 chars
        assigned_mentioned = any(
            rx.search(head1000) for code, _, rx in _STANDING_COMMITTEE_MASTHEADS if code == assigned_parent
        )
        if not assigned_mentioned:
            return QualityFinding(
                code="committee_body_contradiction",
                severity="warning",
                category="label_contradiction",
                link_key_hex=row.link_key_hex,
                filename=row.filename,
                expected=matched_parents[0],
                observed=list(raw_cmts),
                score=3.8,
                evidence={
                    "mechanism": "opening_masthead_committee_mismatch",
                    "masthead_committee": matched_parents[0],
                    "assigned_committees": list(raw_cmts),
                },
            )
    return None


def detect_label_contradictions(
    rows: Sequence[CorpusDocRow],
    *,
    label_source: LabelSource = "auto",
    min_class_docs: int = 5,
    min_margin: float = 2.5,
    min_confidence: float = 0.80,
    check_congress_contradictions: bool = True,
    check_committee_contradictions: bool = True,
    max_findings: int | None = None,
) -> list[QualityFinding]:
    """Detect high-margin contradictions between assigned metadata labels and opening-page text.

    Combines a corpus-fitted Dirichlet log-odds multinomial genre scorer (stripped of
    committee/jurisdiction topic leakage) with deterministic Tier-1 cover/form anchors
    (`congress_api.parsers.document_cover` + upload-slot boundary guards).
    """
    if not rows:
        return []

    # Step 1: Resolve assigned labels & index candidate training rows lazily (avoiding 323K upfront window splits)
    resolved_meta: list[tuple[str | None, tuple[str, ...], str]] = []
    genre_train_all_idxs: dict[str, list[int]] = defaultdict(list)
    genre_train_clean_idxs: dict[str, list[int]] = defaultdict(list)

    for idx, row in enumerate(rows):
        raw_k, fams, src_mode = _resolve_row_assigned_kinds(row, label_source)
        resolved_meta.append((raw_k, fams, src_mode))
        if row.is_alias or len(row.p12_text) < 30 or len(fams) != 1:
            continue
        fam = fams[0]
        genre_train_all_idxs[fam].append(idx)
        if not _is_ambiguous_upload_slot(row, raw_k):
            genre_train_clean_idxs[fam].append(idx)

    # Prefer non-ambiguous slot exemplars when >= min_class_docs exist so contaminated -Bio- slots
    # do not poison the `witness_biography` prototype!
    genre_corpora: dict[str, Sequence[str]] = {}
    for fam, all_idxs in genre_train_all_idxs.items():
        clean_idxs = genre_train_clean_idxs.get(fam, ())
        chosen_idxs = clean_idxs if len(clean_idxs) >= min_class_docs else all_idxs
        if len(chosen_idxs) >= max(2, min_class_docs):
            sampled_idxs = _deterministic_stride(chosen_idxs, _MAX_TRAIN_DOCS_PER_GENRE)
            hdrs = [
                extract_header_footer_windows(rows[i].p12_text, max_header_lines=20, max_header_chars=1200).header
                for i in sampled_idxs
            ]
            hdrs = [h for h in hdrs if len(h) >= 30]
            if len(hdrs) >= max(2, min_class_docs):
                genre_corpora[fam] = hdrs

    # Fit discriminative 1..3-gram log-odds signatures across genres
    phrase_weights: dict[str, list[tuple[str, float]]] = defaultdict(list)
    if len(genre_corpora) >= 2:
        eff_min_df = max(2, min(4, min_class_docs // 2))
        sigs_by_genre = compute_log_odds_signatures(
            genre_corpora,
            ngram_range=(1, 3),
            top_k=50,
            alpha_total=400.0,
            min_df=eff_min_df,
            max_df_ratio=0.85,
            min_group_docs=max(2, min_class_docs),
            binary_per_doc=True,
            window="full",
            exclude_terms=_JURISDICTION_NOISE_TOKENS,
        )
        for fam, sigs in sigs_by_genre.items():
            for sig in sigs:
                if sig.z_score >= 1.5 and sig.log_odds > 0.25:
                    weight = float(sig.log_odds) * max(float(sig.tfidf_score), 0.25)
                    phrase_weights[sig.phrase].append((fam, weight))

    findings: list[QualityFinding] = []

    # Step 2: Evaluate each non-alias row for kind, congress, and committee contradictions
    for row, (raw_kind, assigned_fams, src_mode) in zip(rows, resolved_meta):
        if row.is_alias or not row.p12_text:
            continue

        # 2a. Document-kind vs body contradiction check
        if raw_kind and assigned_fams:
            ext = row.file_ext
            ckey = f"{ext}:{row.effective_body_sha_hex or row.link_key_hex}:{hash(row.p12_text[:512])}"
            struct_fam, struct_source = _structural_body_family(
                row.p12_text,
                file_ext=ext,
                cache_key=ckey,
            )

            # Statistical log-odds scoring over opening 1,200-char header slice
            scores_by_fam: dict[str, float] = defaultdict(float)
            matched_by_fam: dict[str, list[str]] = defaultdict(list)
            if phrase_weights:
                hdr_slice = row.p12_text[:1200]
                seen_ngrams = set(
                    iter_word_ngrams(
                        hdr_slice,
                        ngram_range=(1, 3),
                        lowercase=True,
                        drop_pure_digits=True,
                        stopwords=DEFAULT_STOPWORDS,
                    )
                )
                for ng in seen_ngrams:
                    entries = phrase_weights.get(ng)
                    if entries is not None:
                        for fam, w in entries:
                            scores_by_fam[fam] += w
                            matched_by_fam[fam].append(ng)

            assigned_score = max((scores_by_fam.get(f, 0.0) for f in assigned_fams), default=0.0)
            best_stat_fam: str | None = None
            best_stat_score = 0.0
            for fam, sc in sorted(scores_by_fam.items(), key=lambda kv: (-kv[1], kv[0])):
                if any(_families_compatible(fam, af, source_mode=src_mode) for af in assigned_fams):
                    continue
                if _violates_boundary_guard(fam, row.p12_text):
                    continue
                best_stat_fam = fam
                best_stat_score = sc
                break

            stat_margin = best_stat_score - assigned_score
            stat_conf = best_stat_score / (best_stat_score + assigned_score + 0.75) if best_stat_score > 0 else 0.0
            stat_hits = len(matched_by_fam.get(best_stat_fam, ())) if best_stat_fam else 0

            ambiguous_slot = _is_ambiguous_upload_slot(row, raw_kind)

            # Decision rule:
            # (A) Deterministic Tier-1 / document_cover structural anchor contradicts all assigned families
            # (B) High-margin statistical log-odds contradiction (>=2 distinct signature phrases, low assigned support)
            chosen_fam: str | None = None
            chosen_score = 0.0
            detection_basis = ""

            if struct_fam is not None and not any(
                _families_compatible(struct_fam, af, source_mode=src_mode) for af in assigned_fams
            ):
                chosen_fam = struct_fam
                chosen_score = round(max(stat_margin, 4.0) + (1.0 if best_stat_fam == struct_fam else 0.0), 4)
                detection_basis = (
                    f"{struct_source}+log_odds" if best_stat_fam == struct_fam and stat_margin > 0 else str(struct_source)
                )
            elif (
                best_stat_fam is not None
                and stat_margin >= min_margin
                and stat_conf >= min_confidence
                and stat_hits >= 2
                and (assigned_score <= 0.35 * best_stat_score)
            ):
                chosen_fam = best_stat_fam
                chosen_score = round(stat_margin, 4)
                detection_basis = "statistical_log_odds"

            if chosen_fam is not None:
                expected_label = _format_expected_kind(chosen_fam, source_mode=src_mode)
                matched_phrases = sorted(matched_by_fam.get(chosen_fam, ()))[:6]
                findings.append(
                    QualityFinding(
                        code="kind_body_contradiction",
                        severity="warning",
                        category="label_contradiction",
                        link_key_hex=row.link_key_hex,
                        filename=row.filename,
                        expected=expected_label,
                        observed=raw_kind,
                        score=chosen_score,
                        evidence={
                            "label_source": src_mode,
                            "detection_basis": detection_basis,
                            "assigned_families": list(assigned_fams),
                            "predicted_family": chosen_fam,
                            "log_odds_margin": round(stat_margin, 4),
                            "confidence": round(stat_conf, 4),
                            "matched_phrases": matched_phrases,
                            "structural_anchor": struct_source,
                            "ambiguous_upload_slot": ambiguous_slot,
                        },
                    )
                )

        # 2b. Congress vs opening-masthead contradiction check
        if check_congress_contradictions:
            cong_finding = _check_congress_contradiction(row, source_mode=src_mode)
            if cong_finding is not None:
                findings.append(cong_finding)

        # 2c. Committee / hsru00 host-vs-author contradiction check
        if check_committee_contradictions:
            cmt_finding = _check_committee_contradiction(row, source_mode=src_mode)
            if cmt_finding is not None:
                findings.append(cmt_finding)

    findings.sort(key=lambda f: (-f.score, f.code, f.link_key_hex))
    if max_findings is not None and max_findings >= 0:
        return findings[:max_findings]
    return findings


def _row_host(row: CorpusDocRow) -> str:
    if row.host:
        return row.host.strip().lower()
    if row.source_url:
        h = extract_url_host(row.source_url)
        if h:
            return h
    return ""


def _match_refusal_signal(row: CorpusDocRow) -> str | None:
    text = row.p12_text or ""
    if not text or text.lstrip().startswith("%PDF-"):
        return None
    head = text[:1400]
    for sig_id, rx in _CANONICAL_REFUSAL_SIGNALS:
        if sig_id == "js_analytics_stub" and len(text.strip()) > 220:
            continue
        if rx.search(head):
            return sig_id
    return None


def _doc_contains_ngram(text: str, phrase: str, *, ngram_range: tuple[int, int] = (2, 3)) -> bool:
    return phrase in set(
        iter_word_ngrams(
            _slice_window(text, "header_footer"),
            ngram_range=ngram_range,
            lowercase=True,
            drop_pure_digits=True,
            stopwords=DEFAULT_STOPWORDS,
        )
    )


def _is_chrome_boilerplate_phrase(phrase: str) -> bool:
    return any(tok in _BOILERPLATE_CHROME_CUES for tok in phrase.split())


def detect_host_boilerplate_drift(
    current_rows: Sequence[CorpusDocRow],
    *,
    baseline_rows: Sequence[CorpusDocRow] | None = None,
    min_host_docs: int = 5,
    min_phrase_df: float = 0.30,
    min_delta_df: float = 0.25,
    min_z_score: float = 3.0,
) -> list[QualityFinding]:
    """Detect per-host CMS navigation chrome, WAF/soft-refusal walls, and header/footer boilerplate drift.

    Supports both release-comparison mode (`baseline_rows` supplied, flagging newly spiked
    host header/footer n-grams, new Congress nav banners like `"120th Congress"`, or WAF
    blockades) and single-snapshot dataset audit mode (`baseline_rows=None`).
    """
    if not current_rows:
        return []

    cur_by_host: dict[str, list[CorpusDocRow]] = defaultdict(list)
    for r in current_rows:
        if r.is_alias or not r.p12_text:
            continue
        h = _row_host(r)
        if h:
            cur_by_host[h].append(r)

    base_by_host: dict[str, list[CorpusDocRow]] = defaultdict(list)
    has_baseline = baseline_rows is not None and len(baseline_rows) > 0
    if baseline_rows:
        for r in baseline_rows:
            if r.is_alias or not r.p12_text:
                continue
            h = _row_host(r)
            if h:
                base_by_host[h].append(r)

    findings: list[QualityFinding] = []

    # ------------------------------------------------------------------
    # 1. Soft-Refusal / WAF Challenge Wall & CMS Nav Congress Drift per host
    # ------------------------------------------------------------------
    for host in sorted(cur_by_host):
        h_rows = cur_by_host[host]
        n_cur = len(h_rows)
        if n_cur < max(2, min_host_docs):
            continue

        b_rows = base_by_host.get(host, [])
        n_base = len(b_rows)

        # 1a. Canonical WAF / challenge / JS-stub soft-refusal check
        cur_refusals: list[tuple[CorpusDocRow, str]] = []
        for r in h_rows:
            if sig := _match_refusal_signal(r):
                cur_refusals.append((r, sig))
        cur_ref_rate = len(cur_refusals) / float(n_cur)

        base_ref_count = sum(1 for r in b_rows if _match_refusal_signal(r) is not None) if n_base > 0 else 0
        base_ref_rate = (base_ref_count / float(n_base)) if n_base > 0 else 0.0
        ref_delta = cur_ref_rate - base_ref_rate

        if len(cur_refusals) >= 2 and (
            (has_baseline and ref_delta >= 0.10)
            or (not has_baseline and (cur_ref_rate >= 0.10 or len(cur_refusals) >= 5))
        ):
            sig_counts = Counter(sig for _, sig in cur_refusals)
            exemplars = [r.link_key_hex for r, _ in cur_refusals[:5] if r.link_key_hex]
            is_severe_blockade = cur_ref_rate >= 0.50 and (not has_baseline or ref_delta >= 0.25)
            severity: Severity = "error" if is_severe_blockade else "warning"
            findings.append(
                QualityFinding(
                    code="soft_refusal_or_waf_wall",
                    severity=severity,
                    category="boilerplate_drift",
                    link_key_hex=exemplars[0] if exemplars else "",
                    filename=cur_refusals[0][0].filename,
                    expected="clean_document_body",
                    observed=sig_counts.most_common(1)[0][0],
                    score=round(cur_ref_rate * 10.0, 4),
                    evidence={
                        "host": host,
                        "affected_docs": len(cur_refusals),
                        "host_total_docs": n_cur,
                        "current_refusal_rate": round(cur_ref_rate, 4),
                        "baseline_refusal_rate": round(base_ref_rate, 4) if has_baseline else None,
                        "signal_breakdown": dict(sig_counts),
                        "exemplar_link_keys": exemplars,
                    },
                )
            )

        # 1b. HTML CMS Navigation Chrome & Time-Travel Congress Banner Drift (`"119th/120th Congress"` in nav)
        html_cur = [
            r
            for r in h_rows
            if r.file_ext in {"html", "htm", "aspx"} or (r.effective_format or "").lower() == "html"
        ]
        if len(html_cur) >= max(2, min(min_host_docs, 5)):
            html_base = [
                r
                for r in b_rows
                if r.file_ext in {"html", "htm", "aspx"} or (r.effective_format or "").lower() == "html"
            ]
            base_nav_congs: set[int] = set()
            for r in html_base:
                hdr = extract_header_footer_windows(r.p12_text, max_header_lines=10, max_header_chars=650).header
                for m in _RX_NAV_CONGRESS_BANNER.finditer(hdr):
                    base_nav_congs.add(int(m.group(1)))

            time_travel_rows: list[tuple[CorpusDocRow, int, int]] = []
            emergent_cong_rows: list[tuple[CorpusDocRow, int]] = []
            chrome_wrapper_rows: list[CorpusDocRow] = []
            cur_nav_cong_counts: Counter[int] = Counter()

            for r in html_cur:
                hdr = extract_header_footer_windows(r.p12_text, max_header_lines=10, max_header_chars=650).header
                has_chrome = bool(_RX_CMS_CHROME_WRAPPER.search(hdr))
                if has_chrome:
                    chrome_wrapper_rows.append(r)
                nav_congs = [int(m.group(1)) for m in _RX_NAV_CONGRESS_BANNER.finditer(hdr)]
                for nc in set(nav_congs):
                    cur_nav_cong_counts[nc] += 1
                if nav_congs:
                    top_nc = max(nav_congs)
                    row_cong = r.docmeta_congress or r.congress
                    if row_cong is not None and top_nc != row_cong:
                        time_travel_rows.append((r, row_cong, top_nc))
                    elif has_baseline and top_nc not in base_nav_congs:
                        emergent_cong_rows.append((r, top_nc))

            base_chrome_rate = (
                sum(
                    1
                    for r in html_base
                    if _RX_CMS_CHROME_WRAPPER.search(
                        extract_header_footer_windows(r.p12_text, max_header_lines=10, max_header_chars=650).header
                    )
                )
                / float(len(html_base))
                if html_base
                else 0.0
            )
            cur_chrome_rate = len(chrome_wrapper_rows) / float(len(html_cur))

            has_time_travel = len(time_travel_rows) >= 2 and (len(time_travel_rows) / float(len(html_cur))) >= 0.15
            has_emergent_banner = (
                has_baseline
                and len(emergent_cong_rows) >= 2
                and (len(emergent_cong_rows) / float(len(html_cur))) >= min_phrase_df
            )
            has_chrome_spike = (
                has_baseline
                and cur_chrome_rate >= min_phrase_df
                and (cur_chrome_rate - base_chrome_rate) >= min_delta_df
            )

            if has_time_travel or has_emergent_banner or has_chrome_spike:
                if time_travel_rows:
                    ex_row = time_travel_rows[0][0]
                    exemplars = [r.link_key_hex for r, _, _ in time_travel_rows[:5] if r.link_key_hex]
                    dominant_banner = Counter(nc for _, _, nc in time_travel_rows).most_common(1)[0][0]
                    expected_desc: Any = f"post_nav_article_congress (e.g. {time_travel_rows[0][1]})"
                    observed_desc: Any = f"{dominant_banner}th Congress CMS nav banner"
                    drift_rate = len(time_travel_rows) / float(len(html_cur))
                elif emergent_cong_rows:
                    ex_row = emergent_cong_rows[0][0]
                    exemplars = [r.link_key_hex for r, _ in emergent_cong_rows[:5] if r.link_key_hex]
                    dominant_banner = Counter(nc for _, nc in emergent_cong_rows).most_common(1)[0][0]
                    expected_desc = sorted(base_nav_congs) if base_nav_congs else "baseline_cms_header"
                    observed_desc = f"new {dominant_banner}th Congress CMS nav banner"
                    drift_rate = len(emergent_cong_rows) / float(len(html_cur))
                else:
                    ex_row = chrome_wrapper_rows[0]
                    exemplars = [r.link_key_hex for r in chrome_wrapper_rows[:5] if r.link_key_hex]
                    expected_desc = f"baseline_chrome_rate={base_chrome_rate:.2f}"
                    observed_desc = f"unstripped_cms_chrome_rate={cur_chrome_rate:.2f}"
                    drift_rate = cur_chrome_rate

                findings.append(
                    QualityFinding(
                        code="cms_nav_congress_drift",
                        severity="warning",
                        category="boilerplate_drift",
                        link_key_hex=exemplars[0] if exemplars else "",
                        filename=ex_row.filename,
                        expected=expected_desc,
                        observed=observed_desc,
                        score=round(drift_rate * 10.0, 4),
                        evidence={
                            "host": host,
                            "html_docs": len(html_cur),
                            "time_travel_docs": len(time_travel_rows),
                            "emergent_congress_banner_docs": len(emergent_cong_rows),
                            "current_chrome_wrapper_rate": round(cur_chrome_rate, 4),
                            "baseline_chrome_wrapper_rate": round(base_chrome_rate, 4) if has_baseline else None,
                            "nav_congress_counts": {str(k): v for k, v in sorted(cur_nav_cong_counts.items())},
                            "exemplar_link_keys": exemplars,
                        },
                    )
                )

    # ------------------------------------------------------------------
    # 2. Statistical Log-Odds Header/Footer Boilerplate Spike Radar
    # ------------------------------------------------------------------
    if has_baseline:
        # Compare each host's candidate header/footer windows directly against its baseline windows
        all_base_hf = [
            _slice_window(r.p12_text, "header_footer")
            for h_list in base_by_host.values()
            for r in _deterministic_stride(h_list, 100)
        ]
        for host in sorted(cur_by_host):
            c_rows = cur_by_host[host]
            if len(c_rows) < max(2, min_host_docs):
                continue
            c_sampled = _deterministic_stride(c_rows, _MAX_DOCS_PER_HOST_SIGNATURE)
            c_texts = [_slice_window(r.p12_text, "header_footer") for r in c_sampled]

            b_rows = base_by_host.get(host, [])
            if len(b_rows) >= 2:
                b_sampled = _deterministic_stride(b_rows, _MAX_DOCS_PER_HOST_SIGNATURE)
                b_texts: Sequence[str] = [_slice_window(r.p12_text, "header_footer") for r in b_sampled]
            else:
                b_texts = all_base_hf

            if not b_texts:
                continue

            sigs = compute_log_odds_signatures(
                {"current": c_texts},
                background_texts=b_texts,
                ngram_range=(2, 3),
                top_k=12,
                alpha_total=200.0,
                min_df=max(2, int(math.ceil(len(c_texts) * min_phrase_df * 0.5))),
                max_df_ratio=1.0,
                min_group_docs=max(2, min_host_docs),
                binary_per_doc=True,
                window="full",
            ).get("current", [])

            spiked = [
                s
                for s in sigs
                if s.within_df >= min_phrase_df
                and (s.within_df - s.background_df) >= min_delta_df
                and s.z_score >= min(min_z_score, max(1.25, 0.75 * math.log(max(s.doc_count, 2) + 1.0)))
            ]
            if spiked:
                top_sig = spiked[0]
                exemplars = [
                    r.link_key_hex
                    for r in c_sampled
                    if r.link_key_hex and _doc_contains_ngram(r.p12_text, top_sig.phrase)
                ][:5]
                ex_fn = next(
                    (r.filename for r in c_sampled if _doc_contains_ngram(r.p12_text, top_sig.phrase)),
                    c_sampled[0].filename,
                )
                findings.append(
                    QualityFinding(
                        code="host_boilerplate_spike",
                        severity="warning",
                        category="boilerplate_drift",
                        link_key_hex=exemplars[0] if exemplars else c_sampled[0].link_key_hex,
                        filename=ex_fn,
                        expected=f"baseline_df={top_sig.background_df:.2f}",
                        observed=f"{top_sig.phrase!r} (within_df={top_sig.within_df:.2f}, z={top_sig.z_score:.2f})",
                        score=round(float(top_sig.z_score), 4),
                        evidence={
                            "host": host,
                            "host_docs_evaluated": len(c_sampled),
                            "spiked_phrases": [s.to_dict() for s in spiked[:6]],
                            "exemplar_link_keys": exemplars,
                        },
                    )
                )
    else:
        # Single-snapshot mode: compare hosts against each other and surface high-DF non-masthead CMS/chrome wrappers
        host_hf_groups: dict[str, Sequence[str]] = {}
        host_sampled_rows: dict[str, Sequence[CorpusDocRow]] = {}
        for host, h_rows in sorted(cur_by_host.items()):
            if len(h_rows) >= max(2, min_host_docs):
                sampled = _deterministic_stride(h_rows, _MAX_DOCS_PER_HOST_SIGNATURE)
                host_sampled_rows[host] = sampled
                host_hf_groups[host] = [_slice_window(r.p12_text, "header_footer") for r in sampled]

        if host_hf_groups:
            sigs_by_host = compute_log_odds_signatures(
                host_hf_groups,
                ngram_range=(2, 3),
                top_k=12,
                alpha_total=300.0,
                min_df=2,
                max_df_ratio=0.95,
                min_group_docs=max(2, min_host_docs),
                binary_per_doc=True,
                window="full",
            )
            for host, sigs in sorted(sigs_by_host.items()):
                chrome_sigs = [
                    s
                    for s in sigs
                    if s.within_df >= min_phrase_df
                    and s.z_score >= min(min_z_score, max(1.25, 0.75 * math.log(max(s.doc_count, 2) + 1.0)))
                    and _is_chrome_boilerplate_phrase(s.phrase)
                ]
                if not chrome_sigs:
                    continue
                top_sig = chrome_sigs[0]
                sampled = host_sampled_rows[host]
                exemplars = [
                    r.link_key_hex
                    for r in sampled
                    if r.link_key_hex and _doc_contains_ngram(r.p12_text, top_sig.phrase)
                ][:5]
                ex_fn = next(
                    (r.filename for r in sampled if _doc_contains_ngram(r.p12_text, top_sig.phrase)),
                    sampled[0].filename,
                )
                findings.append(
                    QualityFinding(
                        code="host_boilerplate_spike",
                        severity="warning",
                        category="boilerplate_drift",
                        link_key_hex=exemplars[0] if exemplars else sampled[0].link_key_hex,
                        filename=ex_fn,
                        expected="clean_body_without_cms_chrome",
                        observed=f"{top_sig.phrase!r} (within_df={top_sig.within_df:.2f}, z={top_sig.z_score:.2f})",
                        score=round(float(top_sig.z_score), 4),
                        evidence={
                            "host": host,
                            "host_docs_evaluated": len(sampled),
                            "spiked_phrases": [s.to_dict() for s in chrome_sigs[:6]],
                            "exemplar_link_keys": exemplars,
                        },
                    )
                )

    findings.sort(key=lambda f: (0 if f.severity == "error" else 1, -f.score, f.code, f.link_key_hex))
    return findings


__all__ = [
    "LabelSource",
    "PhraseSignature",
    "WindowMode",
    "compute_log_odds_signatures",
    "detect_host_boilerplate_drift",
    "detect_label_contradictions",
]
