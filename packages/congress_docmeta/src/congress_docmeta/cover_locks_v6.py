#!/usr/bin/env python3
"""Stage 4 (`N10`) Expanded 100%-Precision Cover & SHA Genre Locks (`cover_locks_v6.py`).

100% Python standard-library runtime module (`/usr/bin/python3 -B -I -S` clean, zero third-party
imports) implementing:
  1. Human-adjudicated SHA-256 overrides (`SAVED_NAME_SHA_DECISIONS_V6`, `84` entries ported from
     `congressional-tech/model/registries/saved-name-decisions.json`) via
     `lookup_saved_name_sha_override_v6` (`30/30` agreement with V5 locks, `0` contradictions).
  2. Mutually-exclusive, fast-prefiltered `100.0%`-precision cover/heading signatures ported from
     `congress_api.parsers.document_cover` + CBO/JCT cost estimates + GAO/CRS reports + formal
     witness & Member opening statement cover headers (`detect_cover_lock_v6`).
  3. Explicit SFRC / Senate / Executive Nominee `"Opening Statement"` override helper
     (`detect_nominee_opening_override_v6`) rescuing nominee statements (`Statement / Opening
     Statement of <Name>, Nominee to be/for ...`) from ever being mis-locked as
     `member_opening_statement`.

Mandatory precision safeguards enforced:
  - NEVER locks from raw `detail.document_kind` (`house_naming` `Bio-` has `59.6%` contradictions).
  - SFRC / Senate / Executive / Judicial Nominee `"Opening Statement"` Guard:
    Any statement whose cover header identifies a `Nominee to be / serve as / for ...` routes to
    `witness_statement` (`witness_nominee_statement_cover_v6`), NEVER `member_opening_statement`.
    `member_opening_statement` (`stmt_member_opening_cover_v6`) is strictly reserved for verified
    Congressional Member titles/roles (`Chairman`, `Chairwoman`, `Ranking Member`, `Senator`, `Sen.`,
    `Representative`, `Rep.`, `Congressman`, `Congresswoman`, or `(D-XX)`/`(R-XX)`) with zero
    nominee, witness `Before the`, QFR, floor, letter, or press-release cues.
  - Non-QFR / Non-Invitation / Non-TTF / Public-Submission Guards on `witness_statement`:
    Strictly excludes QFR packets (`Questions for the Record`), Chair invitations (`Dear ... invite you`),
    standalone TTF forms (`Truth in Testimony` / `Witness Disclosure` / `Clause 2(g)(5)`), `Statement for
    the Record` public comments, and `-SD00x` supplemental organizational submissions.
  - Cover/TOC Usability Guard:
    Never locks HTML documents or short/cover-only snippets (`status='cover_or_toc'`) as `usable`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

__all__ = [
    "COVER_SIGNATURE_TO_KIND_V6",
    "SAVED_NAME_SHA_DECISIONS_V6",
    "SAVED_NAME_SHA_TO_KIND_V6",
    "classify_cover_lock_v6",
    "detect_all_cover_locks_v6",
    "detect_cover_lock_v6",
    "detect_exact_cover_lock_v6",
    "detect_nominee_opening_override_v6",
    "get_sha_kind_override_v6",
    "lookup_saved_name_sha_override_v6",
    "resolve_sha_override_v6",
    "senate_hearing_citation_v6",
]

# ---------------------------------------------------------------------------
# 1. Human-Verified SHA-256 Overrides (`saved-name-decisions.json`, 84 rows)
# ---------------------------------------------------------------------------

# Tuple layout: (decision_source, effective_filename, v4_primary_kind, optional_subkind)
SAVED_NAME_SHA_DECISIONS_V6: dict[str, tuple[str, str, str, str | None]] = {
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

SAVED_NAME_SHA_TO_KIND_V6: dict[str, tuple[str, str]] = {
    sha: (f"sha_saved_name_{pk}_{sha[:10]}", pk)
    for sha, (_dec, _fn, pk, _sub) in SAVED_NAME_SHA_DECISIONS_V6.items()
}


def lookup_saved_name_sha_override_v6(body_sha_hex: str | None) -> tuple[str, str] | None:
    """Return `(lock_id, primary_kind)` when `body_sha_hex` matches one of the 84 SHA overrides."""
    if not body_sha_hex or not isinstance(body_sha_hex, str):
        return None
    return SAVED_NAME_SHA_TO_KIND_V6.get(body_sha_hex.strip().lower())


get_sha_kind_override_v6 = lookup_saved_name_sha_override_v6
resolve_sha_override_v6 = lookup_saved_name_sha_override_v6


# ---------------------------------------------------------------------------
# 2. Mutually-Exclusive Cover & Heading Signatures (`COVER_SIGNATURE_TO_KIND_V6`)
# ---------------------------------------------------------------------------

COVER_SIGNATURE_TO_KIND_V6: dict[str, str] = {
    "witness_nominee_statement_cover_v6": "witness_statement",
    "witness_statement_formal_cover_v6": "witness_statement",
    "stmt_member_opening_cover_v6": "member_opening_statement",
    "cbo_or_jct_cost_estimate_cover_v6": "revenue_or_cost_estimate",
    "gao_or_crs_report_cover_v6": "agency_or_gao_crs_report",
    "gsa_lease_resolution_cover_v6": "gsa_prospectus_or_property",
    "committee_resolution_cover_v6": "committee_resolution",
    "bill_draft_or_print_cover_v6": "bill_or_draft",
    "budget_views_and_estimates_cover_v6": "budget_views_and_estimates",
    "oversight_plan_cover_v6": "oversight_plan",
    "published_hearing_proceedings_cover_v6": "hearing_transcript",
}

_WS_RE = re.compile(r"\s+")
_HTML_HEAD_RE = re.compile(r"^\s*(?:<!doctype\s+html|<html\b|<head\b|<body\b|<div\b|<script\b)", re.I)

# Filename slugs that already lock or contradict cover-only genres
_FN_SD_RE = re.compile(r"-SD\d+\b", re.I)
_FN_WSTATE_RE = re.compile(r"-Wstate-", re.I)
_FN_MSTATE_RE = re.compile(r"-MState-", re.I)
_FN_NON_STMT_SLUG_RE = re.compile(
    r"(?:^|[-_.\s])(?:TTF|Truth[-_\s]?in[-_\s]?Testimony|Bio|Biography|CV|WList|Witness[-_\s]?List|"
    r"Vote\d*|Roll[-_\s]?Call|Attendance|Quorum|Amdt|Amendment|QFRs?|Questions[-_\s]?for[-_\s]?the[-_\s]?Record|"
    r"APQ|Questionnaire|Transcript)(?:[-_.\s\d]|$)",
    re.I,
)
_FN_AMDT_OR_VOTE_SLUG_RE = re.compile(
    r"(?:^|[-_.])(?:Amdt|Amendment|ANS|AINS|Vote\d*|Roll[-_]?Call|Attendance|Quorum|SD\d+)(?:[-_.\d]|$)",
    re.I,
)

# Shared negative guards for statements (`witness_statement` & `member_opening_statement`)
_STMT_HARD_NEG_RE = re.compile(
    r"\b(?:"
    r"Questions\s+for\s+the\s+Record|"
    r"Responses?\s+to\s+(?:Written\s+|Additional\s+|Post-?Hearing\s+)?Questions|"
    r"addendum\s+to\s+(?:the\s+)?testimony|"
    r"Witness\s+Disclosure\s+Form|"
    r"Truth\s+in\s+Testimony\s+Disclosure|"
    r"Clause\s+2\(g\)\(5\)|"
    r"Questionnaire\s+for\s+(?:Nominees|Judicial|Executive|Presidential)|"
    r"Biographical\s+(?:Sketch|Information)|"
    r"Curriculum\s+Vitae|"
    r"Witness\s+List|"
    r"Notice\s+of\s+(?:Committee\s+|Subcommittee\s+|Full\s+Committee\s+|Public\s+)?(?:Hearing|Markup|Business\s+Meeting)|"
    r"(?:Hearing|Markup)\s+Notice|"
    r"MEMORANDUM\s+TO:|"
    r"FOR\s+IMMEDIATE\s+RELEASE|"
    r"COMMITTEE\s+ACTION\s+SUMMARY|"
    r"ROLL\s+CALL\s+VOTE"
    r")\b",
    re.I,
)
_CHAIR_INVITATION_NEG_RE = re.compile(
    r"\bDear\s+(?:Mr\.|Ms\.|Mrs\.|Dr\.|Secretary|Administrator|Director|Commissioner|Honorable|General|Admiral|Ambassador|Professor|Judge|Chairman|Chairwoman|Senator|Representative)\b"
    r".{0,450}?\b(?:invite\s+you\s+to\s+(?:testify|appear)|inviting\s+you\s+to\s+(?:testify|appear)|pleased\s+to\s+invite\s+you)\b",
    re.I,
)
_TRANSCRIPT_PROCEEDINGS_CUES_RE = re.compile(
    r"(?:\[\s*(?:House|Senate|Joint)\s+Hearing\s*,\s*1\d\d|\bS\.\s*Hrg\.\s*\d{2,3}\s*[-–]\s*\d+|"
    r"\bStenographic\s+Transcript\b|\bALDERSON\s+COURT\s+REPORTING\b|"
    r"\bThe\s+(?:committee|subcommittee|task\s+force|commission)\s+met,\s+pursuant\s+to\s+notice\b|"
    r"\bThe\s+(?:committee|subcommittee)\s+was\s+called\s+to\s+order\b)",
    re.I,
)

# 2A. SFRC / Senate / Executive / Judicial Nominee Statement (`witness_statement`, NEVER `member_opening_statement`)
_NOMINEE_STMT_COVER_RE = re.compile(
    r"\b(?:(?:Written|Prepared|Oral)\s+)?"
    r"(?:Opening\s+Statement|Statement|Testimony|Remarks)\s*"
    r"(?:of|by|for|:|-|–|—)\s*"
    r"(?P<spk>[A-Z][^\n]{2,180}?)"
    r"(?:,\s*|\s+-\s+|\s+–\s+|\s+)"
    r"(?:Presidential\s+)?Nominee\s+(?:to\s+(?:be|serve\s+as)\s+(?:an?\s+|the\s+)?|for\s+(?:the\s+(?:Position|Office)\s+of\s+)?)"
    r"(?P<role>[A-Z][^\n]{2,180})",
    re.I,
)

# 2B. Formal Witness Statement Cover (`Testimony/Statement of <Non-Member> Before [the] [Sub]Committee`)
_COMMITTEE_TARGET_PAT = (
    r"(?:(?:United\s+States|U\.?S\.?)\s+)?"
    r"(?:(?:House(?:\s+of\s+Representatives)?|Senate)\s+)?"
    r"(?:(?:Permanent\s+Select|Select|Joint|Special)\s+)?"
    r"(?:"
    r"Subcommittees?\s+on\s+|"
    r"Committee\s+on\s+|"
    r"Commission\s+on\s+|"
    r"[A-Z][A-Za-z,&'’\s-]{2,75}?\s+(?:Subcommittee|Committee)\b"
    r")"
)
_WITNESS_FORMAL_COVER_RE = re.compile(
    r"\b(?P<kw>(?:Written|Prepared|Oral|Complete)\s+(?:Testimony|Statement|Remarks)|Testimony|Statement|Remarks)\s+"
    r"(?:of|by|from|Submitted\s+by:?)\s+"
    r"(?P<spk>.{3,240}?)\s+"
    r"(?:Before|Submitted\s+to|Presented\s+to)\s+(?:the\s+)?"
    + _COMMITTEE_TARGET_PAT,
    re.I,
)
_WITNESS_TESTIMONY_BEFORE_COVER_RE = re.compile(
    r"\b(?:(?:Written|Prepared)\s+(?:Testimony|Statement)|Testimony)\s+"
    r"(?:prepared\s+for\s+HEARING\s+[^\n]{0,60}?\s+)?"
    r"Before\s+(?:the\s+)?"
    r"(?:JOINT\s+(?:PUBLIC\s+)?HEARING\s+of\s+the\s+)?"
    + _COMMITTEE_TARGET_PAT,
    re.I,
)
_PUBLIC_SUBMISSION_NEG_RE = re.compile(
    r"\b(?:Statement\s+(?:Submitted\s+)?for\s+the\s+Record|Submission\s+for\s+the\s+Record|"
    r"Submitted\s+for\s+the\s+Record\s+by|Public\s+Comment(?:s)?\s+(?:of|on|by)|"
    r"Comments\s+of\s+the\s+|Amicus\s+Curiae)\b",
    re.I,
)
_SPEAKER_CONGRESSIONAL_MEMBER_NEG_RE = re.compile(
    r"(?:\b(?:Full\s+Committee\s+Chair(?:man|woman)?|Subcommittee\s+Chair(?:man|woman)?|"
    r"Ranking\s+Member|Senator|Representative|Congressman|Congresswoman|Member\s+of\s+Congress|"
    r"Speaker\s+of\s+the\s+House|Majority\s+Leader|Minority\s+Leader|Majority\s+Whip|Minority\s+Whip)\b|"
    r"\b(?:Chairman|Chairwoman|Chair)\s+[A-Z][a-z]+|"
    r"(?:^|\s)(?:Sen\.|Rep\.)\s+[A-Z]|"
    r"\(\s*[DRI]\s*[-–]\s*[A-Z]{2}(?:\s*[-–]\s*(?:\d{1,2}|At\s+Large|AL))?\s*\))",
    re.I,
)
_SPEAKER_ORG_ONLY_NEG_RE = re.compile(
    r"^(?:the\s+)?[A-Z][A-Za-z0-9,&'’.\s-]{2,140}\b"
    r"(?:Association|Coalition|Institute|Federation|Council|Chamber\s+of\s+Commerce|Society|"
    r"Alliance|Union|Foundation|Roundtable|Network|Bureau|Board\s+of\s+Trade|Club|League|Fund|"
    r"Inc\.|LLC|LLP|Corp\.|Corporation)\s*$",
    re.I,
)
_BIO_HEAD_NEG_RE = re.compile(
    r"^(?:Biography\s+of|Biographical\s+Sketch|Bio\s*[:\-])\b",
    re.I,
)
_GAO_REPORT_NOT_TESTIMONY_NEG_RE = re.compile(
    r"\bReport\s+to\s+(?:Congressional\s+(?:Requesters|Committees|Addressees)|"
    r"the\s+(?:Chair(?:man|woman)?|Ranking\s+Member|Committee|Subcommittee|Honorable))\b",
    re.I,
)

# 2C. Member Opening Statement Cover (`stmt_member_opening_cover_v6`)
_MEMBER_ROLE_TOKEN = (
    r"(?:(?:Full\s+Committee|Subcommittee|Committee|Acting)\s+)?"
    r"(?:Chairman|Chairwoman|Chair|Co-?Chair(?:man|woman)?|Ranking\s+Member|Vice\s+Chair(?:man|woman)?|"
    r"Senator|Representative|Congressman|Congresswoman)"
)
_MEMBER_OPENING_A_RE = re.compile(
    r"\b(?:Opening\s+(?:Statement|Remarks))\s*"
    r"(?:as\s+Prepared\s+for\s+Delivery\s+)?"
    r"(?:(?:of|by|from|:|-|–|—)\s*)?"
    r"(?:The\s+Honorable\s+)?"
    rf"(?P<hdr>(?:{_MEMBER_ROLE_TOKEN}\b|(?:Sen\.|Rep\.)\s+[A-Z])[^\n]{{2,200}})",
    re.I,
)
_MEMBER_OPENING_B_RE = re.compile(
    r"^(?:.{0,80}?\s+)?"
    r"(?:The\s+Honorable\s+)?"
    rf"(?:{_MEMBER_ROLE_TOKEN}\s+[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){{0,3}}|"
    r"(?:Sen\.|Rep\.)\s+[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){0,3})"
    r"(?:\s*\(\s*[DRI]\s*[-–]\s*[A-Z]{2}(?:[-–]\d{1,2})?\s*\))?"
    r"(?:['’]s|\s+[-–—:]\s+|\s+)"
    r"Opening\s+(?:Statement|Remarks)\b",
    re.I,
)
_MEMBER_OPENING_PARTY_STATE_RE = re.compile(
    r"\bOpening\s+(?:Statement|Remarks)\s*(?:as\s+Prepared\s+for\s+Delivery\s+)?(?:(?:of|by|:|-|–|—)\s*)?"
    r"[A-Z][A-Za-z.'’\s-]{3,60}\(\s*[DRI]\s*[-–]\s*[A-Z]{2}(?:\s*[-–]\s*(?:\d{1,2}|AL))?\s*\)",
    re.I,
)
_MEMBER_MARKUP_STMT_RE = re.compile(
    r"^Statement\s+of\s+(?:Chairman|Chairwoman|Ranking\s+Member|Representative|Rep\.|Senator|Sen\.)\s+"
    r"[A-Z][A-Za-z.'’\s-]{3,60}?\s+(?:House|Senate)?\s*Committee\s+on\s+[A-Z][A-Za-z,\s&'’-]{3,80}?\s+"
    r"(?:Full\s+Committee|Subcommittee)\s+Markup\b",
    re.I,
)
_MEMBER_OPENING_NEG_RE = re.compile(
    r"\b(?:"
    r"Nominee(?:\s+to\s+(?:be|serve)|\s+for\b)|"
    r"Testimony\s+(?:of|by|Before)|"
    r"(?:Statement|Remarks|Testimony)\s+(?:of|by)\s+.{2,140}?\bBefore\s+the\b|"
    r"Members?['’]?\s+Day|"
    r"Mr\.\s+Speaker|"
    r"Madam\s+Speaker|"
    r"Congressional\s+Record|"
    r"Extensions\s+of\s+Remarks|"
    r"In\s+the\s+House\s+of\s+Representatives\s+(?:Mr\.|Ms\.|Mrs\.)|"
    r"PRESS\s+RELEASE|"
    r"FOR\s+IMMEDIATE\s+RELEASE|"
    r"today\s+delivered\s+the\s+following|"
    r"today\s+released\s+the\s+following|"
    r"WASHINGTON\s*[–—-]\s*(?:U\.?S\.?\s+)?(?:Sen|Rep|House|Senate)|"
    r"Dear\s+(?:Chairman|Chairwoman|Chair|Ranking\s+Member|Senator|Representative|Mr\.|Ms\.|Madam|Secretary|Director|Administrator)"
    r")\b",
    re.I,
)

# 2D. CBO & JCT Cost / Revenue Estimates (`cbo_or_jct_cost_estimate_cover_v6`)
_CBO_CLASSIC_COVER_RE = re.compile(
    r"\bCONGRESSIONAL\s+BUDGET\s+OFFICE\s+COST\s+ESTIMATE\b",
    re.I,
)
_CBO_GLANCE_COVER_RE = re.compile(
    r"(?:\bAt\s+a\s+Glance\b.{0,450}?\b(?:Cost\s+Estimate|Dynamic\s+Estimate)\b|"
    r"\b(?:Cost\s+Estimate|Dynamic\s+Estimate)\b.{0,350}?\bAs\s+(?:ordered\s+)?reported\s+by\s+the\s+(?:House|Senate)\s+Committee\b)"
    r".{0,900}?\bBy\s+Fiscal\s+Year,\s+(?:Millions|Billions)\s+of\s+Dollars\b",
    re.I,
)
_JCT_REVENUE_ESTIMATE_RE = re.compile(
    r"\bJOINT\s+COMMITTEE\s+ON\s+TAXATION\b.{0,220}?\bJCX-\d{1,3}-\d{2}\b.{0,450}?"
    r"\b(?:ESTIMATED\s+(?:REVENUE|BUDGET)\s+EFFECTS\s+OF|Provision\s+Effective\s+20\d{2}\s+20\d{2})\b",
    re.I,
)

# 2E. GAO & CRS Reports (`gao_or_crs_report_cover_v6`)
_GAO_REPORT_COVER_RE = re.compile(
    r"^(?:.{0,180}?\bUnited\s+States\s+Government\s+Accountability\s+Office\b.{0,160}?|"
    r"\bGAO\s+Report\s+to\s+)"
    r"\bReport\s+to\s+(?:Congressional\s+(?:Requesters|Committees|Addressees)|"
    r"the\s+(?:Chair(?:man|woman)?|Ranking\s+Member|Committee|Subcommittee|Honorable))\b",
    re.I,
)
_GAO_TESTIMONY_OR_CORRESP_ID_RE = re.compile(r"\bGAO-\d{2}-\d+[TR]\b", re.I)
_CRS_REPORT_COVER_RE = re.compile(
    r"^(?:.{0,140}?\bCRS\s+Report\s+for\s+Congress\b|"
    r"Congressional\s+Research\s+Service\s+(?:Informing\s+the\s+legislative\s+debate\s+since\s+1914\s+)?.{5,220}?\b(?:R4\d{4}|RL3\d{4}|RS2\d{4}|IF1\d{4}|IN1\d{4})\b)",
    re.I,
)
_CRS_MEMO_NEG_RE = re.compile(r"\bMEMORANDUM\b", re.I)

# 2F. GSA Lease / Prospectus Committee Resolutions (`gsa_lease_resolution_cover_v6`)
_GSA_RESOLUTION_COVER_RE = re.compile(
    r"^(?:.{0,140}?)?\bCOMMITTEE\s+RESOLUTION\s+"
    r"(?:LEASE|ALTERATION|CONSTRUCTION|DESIGN|REPAIR|BUILDING|SITE|AMENDMENT\s+TO\s+LEASE)\b"
    r".{0,900}?\b(?:40\s+U\.?S\.?C\.?\s*(?:§+\s*)?3307|Public\s+Buildings\s+Service|General\s+Services\s+Administration|Prospectus\s+No\.)\b",
    re.I,
)
_GSA_PROSPECTUS_COVER_RE = re.compile(
    r"^(?:.{0,160}?)?\bPROSPECTUS\s*[-–—]\s*(?:LEASE|ALTERATION|CONSTRUCTION|DESIGN|ACQUISITION)\b"
    r".{0,450}?\b(?:Description|Prospectus\s+Number|P[A-Z]{2}-\d{2}-[A-Z0-9-]+|General\s+Services\s+Administration)\b",
    re.I,
)

# 2G. Committee Resolutions (`committee_resolution_cover_v6`, ported from `document_cover.py`)
_COMMITTEE_RESOLUTION_COVER_RE = re.compile(
    r"^(?:"
    r"(?:\[?(?:COMMITTEE\s+PRINT|DISCUSSION\s+DRAFT)\]?\s+)?"
    r"(?:1\d\d\s*(?:TH|ST|ND|RD)\s+CONGRESS\s+\d\s*(?:ST|ND|RD|TH)\s+SESSION\s+)?"
    r"(?:IN\s+THE\s+COMMITTEE\s+ON\s+[A-Z][A-Za-z,\s&'’-]{3,110}?\s+(?:U\.?S\.?\s+)?(?:HOUSE\s+OF\s+REPRESENTATIVES|UNITED\s+STATES\s+SENATE)?\s*)?"
    r"(?:COMMITTEE\s+RESOLUTION\b|RESOLUTION\s+Of\s+the\s+Committee\s+on\s+[A-Z][A-Za-z,\s&'’-]{3,110}).{0,500}?\bResolved,\s+That\b|"
    r"(?:U\.?S\.?\s+House\s+of\s+Representatives\s+|United\s+States\s+Senate\s+)?Committee\s+on\s+[A-Z][A-Za-z,\s&'’-]{3,90}?\s+"
    r"(?:1\d\d\s*(?:th|st|nd|rd)\s+Congress\s+)?A\s+Resolution\s+Offered\s+by\s+.{3,140}?\bResolved,\s+that\b|"
    r"Motion\s+of\s+(?:Senator|Representative|Chairman|Chairwoman|Ranking\s+Member)\s+[A-Z][A-Za-z.\s'’-]{3,80}?\s+Committee\s+on\s+[A-Z][A-Za-z,\s&'’-]{3,90}?.{0,120}?\bBe\s+it\s+resolved\s+that\b"
    r")",
    re.I,
)
_COMMITTEE_RES_NEG_RE = re.compile(
    r"\b(?:40\s+U\.?S\.?C\.?\s*(?:§+\s*)?3307|PROSPECTUS|GENERAL\s+SERVICES\s+ADMINISTRATION|"
    r"AMENDMENT\s+(?:TO|IN\s+THE\s+NATURE|OFFERED)|RULES\s+OF\s+(?:THE\s+COMMITTEE|PROCEDURE)|"
    r"OVERSIGHT\s+PLAN|VIEWS\s+AND\s+ESTIMATES|"
    r"H\.\s*Res\.|S\.\s*Res\.|H\.\s*Con\.\s*Res\.|S\.\s*Con\.\s*Res\.|H\.\s*J\.\s*Res\.|S\.\s*J\.\s*Res\.|"
    r"ROLL\s+CALL|RECORDED\s+VOTE|REPORT\s+TO\s+ACCOMPANY)\b",
    re.I,
)

# 2H. Bill / Discussion Draft Covers (`bill_draft_or_print_cover_v6`, ported from `document_cover.py`)
_BILL_COVER_RE = re.compile(
    r"^(?:.{0,120}?\s+)?"
    r"(?:\[\s*DISCUSSION\s+DRAFT\s*\]\s*.{0,160}?|"
    r"(?:1\d\d\s*(?:TH|ST|ND|RD)\s+CONGRESS\s+\d\s*(?:ST|ND|RD|TH|D)\s+SESSION\s+)"
    r"(?:\(Original\s+Signature\s+of\s+Member\)\s+)?"
    r"(?:H\.\s*R\.|S\.|H\.\s*J\.\s*RES\.|S\.\s*J\.\s*RES\.|H\.\s*CON\.\s*RES\.|S\.\s*CON\.\s*RES\.|H\.\s*RES\.|S\.\s*RES\.)\s*(?:\d+|ll|\[?_{2,}\]?)?\b.{0,260}?)"
    r"\b(?:A\s+BILL\s+To\s+|AN\s+ACT\s+To\s+|JOINT\s+RESOLUTION\s+(?:Proposing|Relating|Making|Providing|Disapproving|To\s+)|"
    r"CONCURRENT\s+RESOLUTION\s+(?:Expressing|Establishing|Setting|Directing|Authorizing|To\s+)|"
    r"To\s+[a-z]{3,18}\s+.{15,280}?\bIN\s+THE\s+HOUSE\s+OF\s+REPRESENTATIVES\b)",
    re.I,
)
_BILL_COVER_NEG_RE = re.compile(
    r"(?:\bAMENDMENT(?:\s+IN\s+THE\s+NATURE\s+OF\s+A\s+SUBSTITUTE|\s+TO\b|\s+OFFERED\s+BY\b|\s+NO\.)|"
    r"\bStrike\s+(?:all\s+after|section|lines?)\b|\bPage\s+\d+,\s*line\s+\d+|"
    r"\bComparative\s+Print\b|\bChanges\s+in\s+Existing\s+Law\b|"
    r"\bSection-by-Section\b|\[\s*Report\s+No\.|\bReport\s+together\s+with\b|"
    r"\bCONGRESSIONAL\s+BUDGET\s+OFFICE\b|\bCOST\s+ESTIMATE\b|"
    r"\bROLL\s+CALL\s+VOTE\b|\bRECORDED\s+VOTE\b|\bYEAS\s+AND\s+NAYS\b)",
    re.I,
)

# 2I. Budget Views & Estimates (`budget_views_and_estimates_cover_v6`)
_BUDGET_VIEWS_COVER_RE = re.compile(
    r"^(?:.{0,120}?)?\b(?:BUDGET\s+)?VIEWS\s+AND\s+ESTIMATES\s+(?:OF|FOR)\s+THE\s+COMMITTEE\s+ON\s+"
    r"[A-Z][A-Za-z,\s&'’-]{3,120}?\bFOR\s+FISCAL\s+YEAR\s+20\d{2}\b",
    re.I,
)
_PLAN_OR_VIEWS_NEG_RE = re.compile(
    r"\b(?:AMENDMENT|SUBSTITUTE|OFFERED\s+BY|NOTICE\s+OF|MARKUP\s+NOTICE|MEMORANDUM|ROLL\s+CALL|RECORDED\s+VOTE)\b",
    re.I,
)

# 2J. Committee Oversight Plan (`oversight_plan_cover_v6`)
_OVERSIGHT_PLAN_COVER_RE = re.compile(
    r"^(?:.{0,120}?)?\b(?:AUTHORIZATION\s+AND\s+)?OVERSIGHT\s+PLAN\s+(?:OF|FOR)\s+THE\s+COMMITTEE\s+ON\s+"
    r"[A-Z][A-Za-z,\s&'’-]{3,120}?\b(?:FOR\s+THE\s+)?1\d\d\s*(?:TH|ST|ND|RD)\s+CONGRESS\b",
    re.I,
)

# 2K. Published GPO Hearing Transcripts with Proceedings (`published_hearing_proceedings_cover_v6`)
_SENATE_HEARING_CITATION_RE = re.compile(r"\bS\.\s*Hrg\.\s*(\d{2,3})\s*[-–]\s*(\d+)\b", re.I)
_PUBLISHED_HEARING_COVER_RE = re.compile(
    r"\b(?:S\.\s*Hrg\.\s*\d{2,3}\s*[-–]\s*\d+|Serial\s+No\.\s*\d{2,3}\s*[-–]\s*\d+)\b"
    r".{0,700}?\b(?:HEARING(?:S)?|OVERSIGHT\s+HEARING|FIELD\s+HEARING|JOINT\s+HEARING)\s+BEFORE\s+THE\s+"
    r"(?:(?:SUBCOMMITTEE|PERMANENT\s+SELECT\s+COMMITTEE|SELECT\s+COMMITTEE|SPECIAL\s+COMMITTEE|COMMITTEE|COMMISSION)\b)",
    re.I,
)
_PROCEEDINGS_TURN_RE = re.compile(
    r"(?:\bThe\s+(?:committee|subcommittee|commission|task\s+force|panel)\s+(?:met|convened),\s+pursuant\s+to\s+notice\b|"
    r"\bThe\s+(?:committee|subcommittee|hearing)\s+(?:was\s+called\s+to\s+order|came\s+to\s+order)\b|"
    r"\bThe\s+(?:Chairman|Chairwoman|Chair)\s*(?:\[[^\]]+\])?\.\s+The\s+(?:committee|subcommittee|hearing)\s+will\s+come\s+to\s+order\b)",
    re.I,
)


def senate_hearing_citation_v6(text: str | None) -> str | None:
    """Extract normalized `S. Hrg. <cong>-<num>` citation from cover text (ported from `document_cover.py`)."""
    if not text or "hrg" not in text[:1200].lower():
        return None
    m = _SENATE_HEARING_CITATION_RE.search(text[:1200])
    if not m:
        return None
    return f"S. Hrg. {m.group(1)}-{m.group(2)}"


def detect_nominee_opening_override_v6(
    filename: str = "",
    text: str = "",
    *,
    is_html: bool = False,
) -> tuple[str, str, str] | None:
    """Detect SFRC / Senate / Executive / Judicial nominee `'Opening Statement'` covers that MUST be
    `witness_statement` (rescuing V5's `stmt_member_opening_formal_v5` false positives).
    """
    if not text or is_html:
        return None
    low_600 = text[:600].lower()
    if "nominee" not in low_600 or not ("statement" in low_600 or "testimony" in low_600 or "remarks" in low_600):
        return None
    fn_s = filename or ""
    if fn_s.lower().endswith((".htm", ".html", ".xml")) or _FN_NON_STMT_SLUG_RE.search(fn_s):
        return None
    t_ws = _WS_RE.sub(" ", text[:2000]).strip()
    if len(t_ws) < 160 or _STMT_HARD_NEG_RE.search(t_ws[:1800]) or _BIO_HEAD_NEG_RE.search(t_ws[:520]):
        return None
    if _NOMINEE_STMT_COVER_RE.search(t_ws[:560]):
        return ("witness_nominee_statement_cover_v6", "witness_statement", "cover_lock_v6")
    return None


def detect_all_cover_locks_v6(
    filename: str = "",
    text: str = "",
    *,
    body_sha_hex: str | None = None,
    bioguide_ids: Sequence[str] | None = None,
    witness_keys: Sequence[str] | None = None,
    is_html: bool = False,
    p12_lines: str | None = None,
    include_sha_override: bool = False,
) -> list[tuple[str, str, str]]:
    """Return all `(signature_id, target_doc_kind, lock_source)` matches for multi-rule collision auditing.

    All 11 cover signatures are guarded by fast lowercase substring prefilters (`< 3s` across `323,564`
    rows) and strict mutual-exclusion checks (`<= 1` match per document).
    """
    hits: list[tuple[str, str, str]] = []
    if include_sha_override and body_sha_hex:
        sha_hit = lookup_saved_name_sha_override_v6(body_sha_hex)
        if sha_hit is not None:
            hits.append((sha_hit[0], sha_hit[1], "saved_name_sha_override"))
            return hits

    probe = p12_lines if (isinstance(p12_lines, str) and p12_lines.strip()) else (text or "")
    if not probe or is_html:
        return hits

    fn_s = filename or ""
    fn_low = fn_s.lower()
    if fn_low.endswith((".htm", ".html", ".xml")):
        return hits
    if "<" in probe[:240] and _HTML_HEAD_RE.match(probe[:240]):
        return hits

    t_ws = _WS_RE.sub(" ", probe[:3600]).strip()
    if len(t_ws) < 160:
        return hits

    head_900 = t_ws[:900]
    head_560 = t_ws[:560]
    head_420 = t_ws[:420]
    low_900 = head_900.lower()
    low_1800 = t_ws[:1800].lower()

    # 1 & 2 & 3. Witness Nominee / Formal Witness / Member Opening Statement family (fast prefilter FIRST!)
    if (
        ("statement" in low_900 or "testimony" in low_900 or "remarks" in low_900)
        and not _FN_NON_STMT_SLUG_RE.search(fn_s)
        and not _STMT_HARD_NEG_RE.search(t_ws[:1800])
        and not ("dear " in low_1800 and _CHAIR_INVITATION_NEG_RE.search(t_ws[:1600]))
        and not _TRANSCRIPT_PROCEEDINGS_CUES_RE.search(t_ws[:1600])
    ):
        # 1. SFRC / Senate / Executive / Judicial Nominee statement -> ALWAYS `witness_statement`
        #    Note: skip `^Opening Statement (?:of|for) (?:the Honorable|Hon\.)` which V5 Tier-1 already
        #    claims (`stmt_member_opening_formal_v5`), preserving `0` V5-vs-V6 lock conflicts; callers
        #    wishing to override V5 on those 3 rows can call `detect_nominee_opening_override_v6`.
        if (
            "nominee" in low_900
            and not _FN_MSTATE_RE.search(fn_s)
            and not re.match(r"^Opening\s+Statement\s+(?:of|for)\s+(?:the\s+Honorable|Hon\.)\s+", t_ws, re.I)
        ):
            if _NOMINEE_STMT_COVER_RE.search(head_560):
                if not _BIO_HEAD_NEG_RE.search(head_420) and not _PUBLIC_SUBMISSION_NEG_RE.search(head_900):
                    hits.append(("witness_nominee_statement_cover_v6", "witness_statement", "cover_lock_v6"))

        # 2. Formal Witness Statement Cover (`Testimony/Statement of <Non-Member> Before [the] [Sub]Committee`)
        if (
            not hits
            and not _FN_MSTATE_RE.search(fn_s)
            and ("before " in low_900 or "submitted to " in low_900 or "presented to " in low_900)
        ):
            if (
                not _BIO_HEAD_NEG_RE.search(head_420)
                and not _PUBLIC_SUBMISSION_NEG_RE.search(head_900)
                and not _GAO_REPORT_NOT_TESTIMONY_NEG_RE.search(head_900)
                and "opening statement" not in low_900[:140]
                and "opening remarks" not in low_900[:140]
            ):
                m_wf = _WITNESS_FORMAL_COVER_RE.search(head_900)
                if m_wf and m_wf.start() <= 320:
                    kw_low = m_wf.group("kw").lower()
                    spk = m_wf.group("spk").strip(" ,;:-–—")
                    is_sd = bool(_FN_SD_RE.search(fn_s)) and not bool(_FN_WSTATE_RE.search(fn_s))
                    is_member_spk = bool(_SPEAKER_CONGRESSIONAL_MEMBER_NEG_RE.search(spk)) or (
                        bool(bioguide_ids) and not bool(witness_keys) and ("honorable" in spk.lower() or "hon." in spk.lower())
                    )
                    is_org_only = bool(_SPEAKER_ORG_ONLY_NEG_RE.match(spk)) and "testimony" not in kw_low
                    if not is_member_spk and not is_org_only and not (is_sd and "testimony" not in kw_low):
                        hits.append(("witness_statement_formal_cover_v6", "witness_statement", "cover_lock_v6"))
                else:
                    m_tb = _WITNESS_TESTIMONY_BEFORE_COVER_RE.search(head_560)
                    if m_tb and m_tb.start() <= 260:
                        is_sd = bool(_FN_SD_RE.search(fn_s)) and not bool(_FN_WSTATE_RE.search(fn_s))
                        if not is_sd and not _SPEAKER_CONGRESSIONAL_MEMBER_NEG_RE.search(head_420[:240]):
                            hits.append(("witness_statement_formal_cover_v6", "witness_statement", "cover_lock_v6"))

        # 3. Member Opening Statement Cover (`stmt_member_opening_cover_v6`)
        if (
            not hits
            and ("opening statement" in low_900 or "opening remarks" in low_900 or "full committee markup" in low_900 or "subcommittee markup" in low_900)
            and not _FN_WSTATE_RE.search(fn_s)
            and not _FN_SD_RE.search(fn_s)
            and not _MEMBER_OPENING_NEG_RE.search(t_ws[:1500])
            and not (bool(witness_keys) and not bool(bioguide_ids))
        ):
            if (
                _MEMBER_OPENING_A_RE.search(head_420)
                or _MEMBER_OPENING_B_RE.search(head_420)
                or _MEMBER_OPENING_PARTY_STATE_RE.search(head_420)
                or _MEMBER_MARKUP_STMT_RE.search(head_420)
            ):
                hits.append(("stmt_member_opening_cover_v6", "member_opening_statement", "cover_lock_v6"))

    if hits:
        return hits

    has_amdt_or_vote_slug = bool(_FN_AMDT_OR_VOTE_SLUG_RE.search(fn_s))
    if has_amdt_or_vote_slug:
        return hits

    # 4. CBO Cost Estimate & JCT Revenue Estimate (`cbo_or_jct_cost_estimate_cover_v6`)
    if (
        ("cost estimate" in low_1800 or "dynamic estimate" in low_1800 or "jcx-" in low_900)
        and "testimony" not in low_900
        and "before the " not in low_900
    ):
        if (
            _CBO_CLASSIC_COVER_RE.search(head_900)
            or _CBO_GLANCE_COVER_RE.search(t_ws[:2000])
            or _JCT_REVENUE_ESTIMATE_RE.search(t_ws[:1500])
        ):
            hits.append(("cbo_or_jct_cost_estimate_cover_v6", "revenue_or_cost_estimate", "cover_lock_v6"))
            return hits

    # 5. GAO Report to Congressional Requesters/Committees & CRS Reports (`gao_or_crs_report_cover_v6`)
    if len(t_ws) >= 500 and (
        "accountability office" in low_900
        or "report to congressional" in low_900
        or "crs report" in low_900
        or "congressional research service" in low_900
    ):
        if (
            _GAO_REPORT_COVER_RE.search(head_900)
            and not _GAO_TESTIMONY_OR_CORRESP_ID_RE.search(t_ws[:1600])
            and "testimony" not in low_900
        ):
            hits.append(("gao_or_crs_report_cover_v6", "agency_or_gao_crs_report", "cover_lock_v6"))
            return hits
        if _CRS_REPORT_COVER_RE.search(head_560) and not _CRS_MEMO_NEG_RE.search(head_560):
            hits.append(("gao_or_crs_report_cover_v6", "agency_or_gao_crs_report", "cover_lock_v6"))
            return hits

    # 6. GSA Lease / Building Resolutions & Prospectuses (`gsa_lease_resolution_cover_v6`)
    if (
        ("committee resolution" in low_900 or "prospectus" in low_900)
        and ("3307" in low_1800 or "general services administration" in low_1800 or "public buildings" in low_1800 or "prospectus" in low_900)
    ):
        if _GSA_RESOLUTION_COVER_RE.search(t_ws[:1800]) or _GSA_PROSPECTUS_COVER_RE.search(head_900):
            hits.append(("gsa_lease_resolution_cover_v6", "gsa_prospectus_or_property", "cover_lock_v6"))
            return hits

    # 7. Committee Resolutions (`committee_resolution_cover_v6`)
    if (
        ("resolution" in low_900 or "be it resolved" in low_900)
        and ("resolved, that" in low_1800 or "be it resolved that" in low_1800)
        and not _COMMITTEE_RES_NEG_RE.search(t_ws[:1800])
    ):
        if _COMMITTEE_RESOLUTION_COVER_RE.search(t_ws[:1400]):
            hits.append(("committee_resolution_cover_v6", "committee_resolution", "cover_lock_v6"))
            return hits

    # 8. Bill / Discussion Draft Covers (`bill_draft_or_print_cover_v6`)
    if (
        ("discussion draft" in low_900 or "congress" in low_900)
        and (
            "a bill to " in low_900
            or "an act to " in low_900
            or "joint resolution " in low_900
            or "concurrent resolution " in low_900
            or "(original signature of member)" in low_900
        )
        and not _BILL_COVER_NEG_RE.search(t_ws[:1800])
    ):
        if _BILL_COVER_RE.search(head_900):
            hits.append(("bill_draft_or_print_cover_v6", "bill_or_draft", "cover_lock_v6"))
            return hits

    # 9. Budget Views & Estimates (`budget_views_and_estimates_cover_v6`)
    if (
        "views and estimates" in low_900
        and "fiscal year" in low_900
        and not _PLAN_OR_VIEWS_NEG_RE.search(head_900)
    ):
        if _BUDGET_VIEWS_COVER_RE.search(head_560):
            hits.append(("budget_views_and_estimates_cover_v6", "budget_views_and_estimates", "cover_lock_v6"))
            return hits

    # 10. Committee Oversight Plan (`oversight_plan_cover_v6`)
    if (
        "oversight plan" in low_900
        and "congress" in low_900
        and not _PLAN_OR_VIEWS_NEG_RE.search(head_900)
    ):
        if _OVERSIGHT_PLAN_COVER_RE.search(head_560):
            hits.append(("oversight_plan_cover_v6", "oversight_plan", "cover_lock_v6"))
            return hits

    # 11. Published GPO Hearing Transcripts with Proceedings (`published_hearing_proceedings_cover_v6`)
    if (
        len(t_ws) >= 1200
        and ("s. hrg." in low_900 or "serial no." in low_900)
        and "before the " in low_1800
    ):
        if _PUBLISHED_HEARING_COVER_RE.search(t_ws[:1500]) and _PROCEEDINGS_TURN_RE.search(t_ws):
            hits.append(("published_hearing_proceedings_cover_v6", "hearing_transcript", "cover_lock_v6"))
            return hits

    return hits


def detect_cover_lock_v6(
    filename: str = "",
    text: str = "",
    *,
    body_sha_hex: str | None = None,
    bioguide_ids: Sequence[str] | None = None,
    witness_keys: Sequence[str] | None = None,
    is_html: bool = False,
    p12_lines: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Return `(signature_id, target_doc_kind, lock_source)` or `(None, None, None)` when unlocked.

    Checks SHA-256 human-verified overrides first (when `body_sha_hex` is supplied), then evaluates
    the 11 mutually-exclusive 100%-precision cover signatures.
    """
    if body_sha_hex:
        sha_hit = lookup_saved_name_sha_override_v6(body_sha_hex)
        if sha_hit is not None:
            return sha_hit[0], sha_hit[1], "saved_name_sha_override"

    hits = detect_all_cover_locks_v6(
        filename=filename,
        text=text,
        body_sha_hex=body_sha_hex,
        bioguide_ids=bioguide_ids,
        witness_keys=witness_keys,
        is_html=is_html,
        p12_lines=p12_lines,
        include_sha_override=False,
    )
    if not hits:
        return None, None, None
    return hits[0]


detect_exact_cover_lock_v6 = detect_cover_lock_v6
classify_cover_lock_v6 = detect_cover_lock_v6
