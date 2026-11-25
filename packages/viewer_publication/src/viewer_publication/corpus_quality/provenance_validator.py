"""Cross-table dataset provenance & conservation validator (`corpus_quality.provenance_validator`).

Implements deterministic product release-gate and regression checks across published
`congressional-tech` tables (`detail.parquet`, `list.parquet`, `sources.parquet`,
optional `witnesses.parquet`, `bills.parquet`, `committees.parquet`) and optional
`docmeta_v6_1` sidecars:

1. `<NONE>` (`committee_keys == []`) rates stratified by unwrapped congressional host/domain
   (plus optional `--base-tables` regression detection).
2. `hsru00` / `rules.house.gov` / `docs.house.gov/billsthisweek|floor` floor-host vs
   committee-author attribution leakage.
3. 14-digit Wayback/WebHarvest crawl-timestamp and WordPress/Drupal `/wp-content/uploads/`
   & `.senate.gov/download/MM/DD/YYYY/` retro-upload folder date-trap regressions.
4. `BILLS-` slug Congress validation and 20th-Amendment Noon-Jan-3 odd-year boundary
   checks (reusing `house_naming` directly — zero regex forks).
5. Legacy `docmeta` `link_key` conservation, `sha_dup_alias` canonical pointer integrity,
   `saved_body` custody match, and `strict_v4_valid` / zero-NULL invariants (using
   inlined required-column contracts).
6. `witnesses.parquet` vs `detail.witness_keys` orphan checks & `docmeta` `personas`
   shortfall anomalies on single-witness testimony/disclosure/biography genres.
7. `bills.parquet` vs `detail.measure_keys` orphan checks & `docmeta` `refs` coverage
   on `bill_or_draft` / `BILLS-` documents.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import duckdb
from house_naming import (
    date_to_congress_constitutional,
    is_valid_congress,
    split_bills_congress_and_number,
)
import pyarrow.parquet as pq
from viewer_publication.corpus_quality.core import (
    CorpusDocRow,
    QualityFinding,
    extract_url_host,
    load_corpus_rows,
    resolve_docmeta_paths,
    unwrap_archive_url,
)
REQUIRED_DIRECT_COLUMNS = frozenset({
    "link_key",
    "doc_key",
    "saved_body",
    "package_id",
    "disposition",
    "v6_route",
    "filename",
    "effective_format",
    "primary_kind",
    "status",
    "congress",
    "chamber",
    "committees",
    "docmeta_json",
    "strict_v4_valid",
})
REQUIRED_ALIAS_COLUMNS = frozenset({
    "link_key",
    "doc_key",
    "saved_body",
    "package_id",
    "disposition",
    "sub_disposition",
    "v6_route",
    "filename",
    "effective_format",
    "canonical_link_key",
    "canonical_doc_key",
    "canonical_partition_bucket",
    "canonical_v6_route",
})

# Canonical unambiguous congressional committee/commission web hosts -> 6-char system code
CONGRESSIONAL_HOST_TO_SYSTEM_CODE: dict[str, str] = {
    "agriculture.house.gov": "hsag00",
    "democrats-agriculture.house.gov": "hsag00",
    "appropriations.house.gov": "hsap00",
    "democrats-appropriations.house.gov": "hsap00",
    "armedservices.house.gov": "hsas00",
    "democrats-armedservices.house.gov": "hsas00",
    "financialservices.house.gov": "hsba00",
    "democrats-financialservices.house.gov": "hsba00",
    "budget.house.gov": "hsbu00",
    "democrats-budget.house.gov": "hsbu00",
    "edworkforce.house.gov": "hsed00",
    "edlabor.house.gov": "hsed00",
    "democrats-edworkforce.house.gov": "hsed00",
    "foreignaffairs.house.gov": "hsfa00",
    "democrats-foreignaffairs.house.gov": "hsfa00",
    "oversight.house.gov": "hsgo00",
    "oversightdemocrats.house.gov": "hsgo00",
    "cha.house.gov": "hsha00",
    "democrats-cha.house.gov": "hsha00",
    "homeland.house.gov": "hshm00",
    "democrats-homeland.house.gov": "hshm00",
    "intelligence.house.gov": "hlig00",
    "democrats-intelligence.house.gov": "hlig00",
    "energycommerce.house.gov": "hsif00",
    "democrats-energycommerce.house.gov": "hsif00",
    "naturalresources.house.gov": "hsii00",
    "democrats-naturalresources.house.gov": "hsii00",
    "judiciary.house.gov": "hsju00",
    "democrats-judiciary.house.gov": "hsju00",
    "transportation.house.gov": "hspw00",
    "democrats-transportation.house.gov": "hspw00",
    "rules.house.gov": "hsru00",
    "democrats-rules.house.gov": "hsru00",
    "smallbusiness.house.gov": "hssm00",
    "democrats-smallbusiness.house.gov": "hssm00",
    "ethics.house.gov": "hsso00",
    "science.house.gov": "hssy00",
    "democrats-science.house.gov": "hssy00",
    "veterans.house.gov": "hsvr00",
    "democrats-veterans.house.gov": "hsvr00",
    "waysandmeans.house.gov": "hswm00",
    "democrats-waysandmeans.house.gov": "hswm00",
    "chinaselectcommittee.house.gov": "hlzs00",
    "selectcommitteeontheccp.house.gov": "hlzs00",
    "coronavirus.house.gov": "hlvc00",
    "climatecrisis.house.gov": "hlcn00",
    "humanrightscommission.house.gov": "hlhr00",
    "www.csce.gov": "jcse00",
    "csce.gov": "jcse00",
    "www.jec.senate.gov": "jsec00",
    "jec.senate.gov": "jsec00",
    "www.jct.gov": "jstx00",
    "jct.gov": "jstx00",
    # Senate standing/select committees
    "www.agriculture.senate.gov": "ssaf00",
    "agriculture.senate.gov": "ssaf00",
    "www.appropriations.senate.gov": "ssap00",
    "appropriations.senate.gov": "ssap00",
    "www.armed-services.senate.gov": "ssas00",
    "armed-services.senate.gov": "ssas00",
    "www.banking.senate.gov": "ssbk00",
    "banking.senate.gov": "ssbk00",
    "www.budget.senate.gov": "ssbu00",
    "budget.senate.gov": "ssbu00",
    "www.commerce.senate.gov": "sscm00",
    "commerce.senate.gov": "sscm00",
    "www.energy.senate.gov": "sseg00",
    "energy.senate.gov": "sseg00",
    "www.epw.senate.gov": "ssev00",
    "epw.senate.gov": "ssev00",
    "www.finance.senate.gov": "ssfi00",
    "finance.senate.gov": "ssfi00",
    "www.foreign.senate.gov": "ssfr00",
    "foreign.senate.gov": "ssfr00",
    "www.hsgac.senate.gov": "ssga00",
    "hsgac.senate.gov": "ssga00",
    "www.help.senate.gov": "sshr00",
    "help.senate.gov": "sshr00",
    "www.indian.senate.gov": "slia00",
    "indian.senate.gov": "slia00",
    "www.intelligence.senate.gov": "slin00",
    "intelligence.senate.gov": "slin00",
    "www.judiciary.senate.gov": "ssju00",
    "judiciary.senate.gov": "ssju00",
    "www.rules.senate.gov": "ssra00",
    "rules.senate.gov": "ssra00",
    "www.sbc.senate.gov": "sssb00",
    "sbc.senate.gov": "sssb00",
    "www.veterans.senate.gov": "ssva00",
    "veterans.senate.gov": "ssva00",
    "www.aging.senate.gov": "spag00",
    "aging.senate.gov": "spag00",
    "www.ethics.senate.gov": "slet00",
    "ethics.senate.gov": "slet00",
}

HOUSE_CLERK_2LETTER_TO_CODE: dict[str, str] = {
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
    "IG": "hlig00",
    "II": "hsii00",
    "JU": "hsju00",
    "PW": "hspw00",
    "RU": "hsru00",
    "SM": "hssm00",
    "SO": "hsso00",
    "SY": "hssy00",
    "VR": "hsvr00",
    "WM": "hswm00",
    "ZS": "hlzs00",
    "VC": "hlvc00",
    "CN": "hlcn00",
}

_DOCS_HOUSE_MEETING_RE = re.compile(r"docs\.house\.gov/meetings/([A-Z]{2})/", re.I)
_DOCS_HOUSE_FLOOR_RE = re.compile(r"docs\.house\.gov/(?:floor|billsthisweek)(?:/|$|\?)", re.I)
_CLERK_CMT_SLUG_RE = re.compile(
    r"(?:^|/)(?:HHRG|HMTG|HMKP|CRPT)-(\d{3})-(?:(?:HHRG|HMTG|HMKP)-)?([A-Z]{2})\d{2}\b",
    re.I,
)
_CLERK_SLUG_DATE_RE = re.compile(
    r"(?:^|/)(?:HHRG|HMTG|HMKP|CRPT)-\d{3}-[A-Za-z0-9._-]*?-((?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?=$|[-._])",
    re.I,
)
_CMS_UPLOAD_TRAP_RE = re.compile(
    r"(?:/wp-content/uploads/((?:19|20)\d{2})/(\d{2})/|/uploads/((?:19|20)\d{2})/(\d{2})/|"
    r"/sites/[^/]+/files/((?:19|20)\d{2})-(\d{2})/)"
    ,
    re.I,
)
_SENATE_DOWNLOAD_TRAP_RE = re.compile(
    r"\.senate\.gov/download/(\d{2})/(\d{2})/((?:19|20)\d{2})/",
    re.I,
)
_RULES_PRINT_BANNER_RE = re.compile(
    r"\bRULES\s+COMMITTEE\s+PRINT\b|\bCOMMITTEE\s+ON\s+RULES\s+PRINT\b",
    re.I,
)
_HRES_SLUG_RE = re.compile(r"\bBILLS-\d{2,3}hres\d+", re.I)

_RULES_PROCEEDING_KINDS: frozenset[str] = frozenset(
    {
        "hearing_transcript",
        "committee_report",
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "committee_rules",
        "committee_resolution",
        "oversight_plan",
        "budget_views_and_estimates",
        "meeting_results",
        "committee_vote",
        "truth_in_testimony_disclosure",
        "witness_list",
        "witness_biography",
        "attendance_quorum_sheet",
        "member_roster",
    }
)

_SINGLE_WITNESS_PERSONA_KINDS: frozenset[str] = frozenset(
    {
        "truth_in_testimony_disclosure",
        "witness_statement",
        "witness_biography",
        "nominee_questionnaire_apq",
    }
)


@dataclass(frozen=True, slots=True)
class ProvenanceValidationReport:
    """Structured dataset provenance & cross-table conservation report."""

    total_rows: int
    has_docmeta: bool
    none_committee_summary: dict[str, Any]
    hsru00_summary: dict[str, Any]
    date_trap_summary: dict[str, Any]
    congress_boundary_summary: dict[str, Any]
    docmeta_conservation_summary: dict[str, Any] | None
    witness_persona_summary: dict[str, Any]
    bill_refs_summary: dict[str, Any]
    findings: tuple[QualityFinding, ...]

    @property
    def passed_gate(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "has_docmeta": self.has_docmeta,
            "passed_gate": self.passed_gate,
            "error_count": sum(1 for f in self.findings if f.severity == "error"),
            "warning_count": sum(1 for f in self.findings if f.severity == "warning"),
            "info_count": sum(1 for f in self.findings if f.severity == "info"),
            "none_committee_summary": self.none_committee_summary,
            "hsru00_summary": self.hsru00_summary,
            "date_trap_summary": self.date_trap_summary,
            "congress_boundary_summary": self.congress_boundary_summary,
            "docmeta_conservation_summary": self.docmeta_conservation_summary,
            "witness_persona_summary": self.witness_persona_summary,
            "bill_refs_summary": self.bill_refs_summary,
            "findings": [f.to_dict() for f in self.findings],
        }


def resolve_host_committee_code(
    host: str | None,
    url: str | None = None,
    *,
    extra_host_map: dict[str, str] | None = None,
) -> str | None:
    """Resolve an unambiguous congressional committee system code (`hsju00`, `ssju00`, etc.)."""
    cu = unwrap_archive_url(url)[0] if url else ""
    if cu:
        if _DOCS_HOUSE_FLOOR_RE.search(cu):
            return "hsru00"
        m_dh = _DOCS_HOUSE_MEETING_RE.search(cu)
        if m_dh:
            c2 = m_dh.group(1).upper()
            if c2 in HOUSE_CLERK_2LETTER_TO_CODE:
                return HOUSE_CLERK_2LETTER_TO_CODE[c2]
        m_sl = _CLERK_CMT_SLUG_RE.search(cu)
        if m_sl:
            c2 = m_sl.group(2).upper()
            if c2 in HOUSE_CLERK_2LETTER_TO_CODE:
                return HOUSE_CLERK_2LETTER_TO_CODE[c2]
    h = (host or extract_url_host(cu) or "").strip().lower()
    if not h:
        return None
    if h in CONGRESSIONAL_HOST_TO_SYSTEM_CODE:
        return CONGRESSIONAL_HOST_TO_SYSTEM_CODE[h]
    if extra_host_map and h in extra_host_map:
        return extra_host_map[h]
    return None


def _sql_quote(path: Path) -> str:
    return str(path).replace("'", "''")


def _load_committees_host_map(tables_dir: Path) -> dict[str, str]:
    cmt_path = tables_dir / "committees.parquet"
    if not cmt_path.is_file():
        return {}
    cols = set(pq.read_schema(cmt_path).names)
    if not {"system_code", "website"} <= cols:
        return {}
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT system_code, website FROM read_parquet('{_sql_quote(cmt_path)}') WHERE website IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    out: dict[str, str] = {}
    for code, web in rows:
        h = extract_url_host(str(web))
        if h and h not in ("www.house.gov", "house.gov", "www.senate.gov", "senate.gov") and code:
            out[h] = str(code).lower()
    return out


def _scan_raw_url_traps_and_pm(tables_dir: Path) -> dict[int, dict[str, Any]]:
    """Fast DuckDB projection over `sources.parquet` + `detail.parquet` (`page_metadata`) for trap URLs."""
    info_by_lr: dict[int, dict[str, Any]] = defaultdict(dict)
    sources_path = tables_dir / "sources.parquet"
    detail_path = tables_dir / "detail.parquet"
    con = duckdb.connect()
    try:
        if sources_path.is_file():
            scols = set(pq.read_schema(sources_path).names)
            if {"list_row", "url"} <= scols:
                lo_expr = "listed_on" if "listed_on" in scols else "CAST(NULL AS VARCHAR)"
                for lr, u, lo in con.execute(
                    f"SELECT list_row, url, {lo_expr} FROM read_parquet('{_sql_quote(sources_path)}')"
                ).fetchall():
                    rec = info_by_lr[int(lr)]
                    for raw in (u, lo):
                        if not raw:
                            continue
                        cu, wk, cts = unwrap_archive_url(raw)
                        if wk and cts and len(cts) >= 8:
                            rec["wayback_ymd"] = f"{cts[:4]}-{cts[4:6]}-{cts[6:8]}"
                            rec["wayback_raw"] = raw
                        m_up = _CMS_UPLOAD_TRAP_RE.search(cu)
                        if m_up:
                            yr = m_up.group(1) or m_up.group(3) or m_up.group(5)
                            mo = m_up.group(2) or m_up.group(4) or m_up.group(6)
                            rec["cms_upload_ym"] = f"{yr}-{mo}"
                            rec["cms_upload_url"] = cu
                        m_sd = _SENATE_DOWNLOAD_TRAP_RE.search(cu)
                        if m_sd:
                            mo, da, yr = m_sd.group(1), m_sd.group(2), m_sd.group(3)
                            rec["senate_dl_ymd"] = f"{yr}-{mo}-{da}"
                        if _DOCS_HOUSE_FLOOR_RE.search(cu):
                            rec["floor_week"] = True

        if detail_path.is_file():
            dcols = set(pq.read_schema(detail_path).names)
            if "page_metadata" in dcols:
                pm_rows = con.execute(
                    f"""
                    WITH d AS (
                        SELECT row_number() OVER () - 1 AS list_row, page_metadata
                        FROM read_parquet('{_sql_quote(detail_path)}')
                    )
                    SELECT list_row
                    FROM d
                    WHERE page_metadata IS NOT NULL
                      AND len(list_filter(page_metadata, x -> x.field LIKE '%published_time%')) > 0
                    """
                ).fetchall()
                for (lr,) in pm_rows:
                    info_by_lr[int(lr)]["pm_published_time"] = True
    finally:
        con.close()
    return info_by_lr


def _validate_docmeta_conservation(
    tables_dir: Path,
    docmeta_dir: Path,
    findings: list[QualityFinding],
) -> dict[str, Any]:
    """Verify 100% `link_key` conservation, alias resolution, `saved_body` custody, and `strict_v4_valid`."""
    detail_path = tables_dir / "detail.parquet"
    dm_paths = resolve_docmeta_paths(docmeta_dir)
    missing_cols_by_part: dict[str, list[str]] = {}

    if "completed_no_llm" in dm_paths:
        cols = set(pq.read_schema(dm_paths["completed_no_llm"]).names)
        miss = sorted(REQUIRED_DIRECT_COLUMNS - cols)
        if miss:
            missing_cols_by_part["completed_no_llm"] = miss
    if "llm_results" in dm_paths:
        cols = set(pq.read_schema(dm_paths["llm_results"]).names)
        miss = sorted(REQUIRED_DIRECT_COLUMNS - cols)
        if miss:
            missing_cols_by_part["llm_results"] = miss
    if "sha_dup_alias" in dm_paths:
        cols = set(pq.read_schema(dm_paths["sha_dup_alias"]).names)
        miss = sorted(REQUIRED_ALIAS_COLUMNS - cols)
        if miss:
            missing_cols_by_part["sha_dup_alias"] = miss

    for part_name, miss in missing_cols_by_part.items():
        findings.append(
            QualityFinding(
                code="docmeta_missing_required_columns",
                severity="error",
                category="docmeta_conservation",
                link_key_hex="corpus",
                filename=dm_paths[part_name].name,
                expected=sorted(
                    REQUIRED_ALIAS_COLUMNS if part_name == "sha_dup_alias" else REQUIRED_DIRECT_COLUMNS
                ),
                observed=miss,
                score=1.0,
                evidence={"part": part_name, "missing_columns": miss},
            )
        )

    con = duckdb.connect()
    try:
        detail_count = int(
            con.execute(f"SELECT count(*) FROM read_parquet('{_sql_quote(detail_path)}')").fetchone()[0]
        )
        comp_count = 0
        queue_count = 0
        llm_res_count = 0
        alias_count = 0

        part_Selects: list[str] = []
        direct_Selects: list[str] = []

        if "completed_no_llm" in dm_paths:
            p = dm_paths["completed_no_llm"]
            comp_count = int(con.execute(f"SELECT count(*) FROM read_parquet('{_sql_quote(p)}')").fetchone()[0])
            part_Selects.append(
                f"SELECT 'completed_no_llm' AS part, link_key, CAST(doc_key AS VARCHAR) AS doc_key, saved_body, CAST(filename AS VARCHAR) AS filename FROM read_parquet('{_sql_quote(p)}')"
            )
            direct_Selects.append(
                f"SELECT 'completed_no_llm' AS part, link_key, CAST(doc_key AS VARCHAR) AS doc_key, CAST(filename AS VARCHAR) AS filename, CAST(status AS VARCHAR) AS status, CAST(primary_kind AS VARCHAR) AS primary_kind, CAST(docmeta_json AS VARCHAR) AS docmeta_json, CAST(strict_v4_valid AS BOOLEAN) AS strict_v4_valid FROM read_parquet('{_sql_quote(p)}')"
            )

        if "llm_results" in dm_paths:
            p = dm_paths["llm_results"]
            llm_res_count = int(con.execute(f"SELECT count(*) FROM read_parquet('{_sql_quote(p)}')").fetchone()[0])
            part_Selects.append(
                f"SELECT 'llm_results' AS part, link_key, CAST(doc_key AS VARCHAR) AS doc_key, saved_body, CAST(filename AS VARCHAR) AS filename FROM read_parquet('{_sql_quote(p)}')"
            )
            direct_Selects.append(
                f"SELECT 'llm_results' AS part, link_key, CAST(doc_key AS VARCHAR) AS doc_key, CAST(filename AS VARCHAR) AS filename, CAST(status AS VARCHAR) AS status, CAST(primary_kind AS VARCHAR) AS primary_kind, CAST(docmeta_json AS VARCHAR) AS docmeta_json, CAST(strict_v4_valid AS BOOLEAN) AS strict_v4_valid FROM read_parquet('{_sql_quote(p)}')"
            )
        elif "llm_queue" in dm_paths:
            p = dm_paths["llm_queue"]
            queue_count = int(con.execute(f"SELECT count(*) FROM read_parquet('{_sql_quote(p)}')").fetchone()[0])
            part_Selects.append(
                f"SELECT 'llm_queue' AS part, link_key, CAST(doc_key AS VARCHAR) AS doc_key, saved_body, CAST(filename AS VARCHAR) AS filename FROM read_parquet('{_sql_quote(p)}')"
            )

        if "sha_dup_alias" in dm_paths:
            p = dm_paths["sha_dup_alias"]
            alias_count = int(con.execute(f"SELECT count(*) FROM read_parquet('{_sql_quote(p)}')").fetchone()[0])
            part_Selects.append(
                f"SELECT 'sha_dup_alias' AS part, link_key, CAST(doc_key AS VARCHAR) AS doc_key, saved_body, CAST(filename AS VARCHAR) AS filename FROM read_parquet('{_sql_quote(p)}')"
            )

        partition_sum = comp_count + (llm_res_count if "llm_results" in dm_paths else queue_count) + alias_count
        has_full_partition = (
            "completed_no_llm" in dm_paths
            and ("llm_results" in dm_paths or "llm_queue" in dm_paths)
            and "sha_dup_alias" in dm_paths
        )
        conserved_exact = (partition_sum == detail_count) if has_full_partition else None
        if has_full_partition and partition_sum != detail_count:
            findings.append(
                QualityFinding(
                    code="docmeta_partition_row_conservation_mismatch",
                    severity="error",
                    category="docmeta_conservation",
                    link_key_hex="corpus",
                    filename="docmeta_v6_1",
                    expected=detail_count,
                    observed=partition_sum,
                    score=1.0,
                    evidence={
                        "detail_rows": detail_count,
                        "completed_no_llm": comp_count,
                        "llm_queue": queue_count,
                        "llm_results": llm_res_count,
                        "sha_dup_alias": alias_count,
                    },
                )
            )

        dup_link_keys = 0
        dup_doc_keys = 0
        orphan_rows = 0
        saved_body_mismatches = 0
        if part_Selects:
            union_sql = " UNION ALL ".join(part_Selects)
            inv_row = con.execute(
                f"""
                WITH u AS ({union_sql}),
                d AS (SELECT link_key, saved_body FROM read_parquet('{_sql_quote(detail_path)}'))
                SELECT
                    (SELECT count(*) FROM (SELECT link_key FROM u GROUP BY link_key HAVING count(*) > 1)),
                    (SELECT count(*) FROM (SELECT doc_key FROM u WHERE doc_key IS NOT NULL AND doc_key <> '' GROUP BY doc_key HAVING count(*) > 1)),
                    (SELECT count(*) FROM u ANTI JOIN d ON u.link_key = d.link_key),
                    (SELECT count(*) FROM u JOIN d ON u.link_key = d.link_key WHERE u.saved_body IS DISTINCT FROM d.saved_body)
                """
            ).fetchone()
            dup_link_keys, dup_doc_keys, orphan_rows, saved_body_mismatches = (int(x) for x in inv_row)

            for code, cnt, desc in (
                ("docmeta_duplicate_link_key", dup_link_keys, "duplicate link_key across docmeta partitions"),
                ("docmeta_duplicate_doc_key", dup_doc_keys, "duplicate doc_key across docmeta partitions"),
                ("docmeta_orphan_link_key", orphan_rows, "docmeta link_key absent from detail.parquet"),
                ("docmeta_saved_body_mismatch", saved_body_mismatches, "docmeta saved_body differs from detail.saved_body"),
            ):
                if cnt > 0:
                    findings.append(
                        QualityFinding(
                            code=code,
                            severity="error",
                            category="docmeta_conservation",
                            link_key_hex="corpus",
                            filename="docmeta_v6_1",
                            expected=0,
                            observed=cnt,
                            score=1.0,
                            evidence={"description": desc, "count": cnt},
                        )
                    )

        broken_alias_targets = 0
        if "sha_dup_alias" in dm_paths and part_Selects:
            ap = dm_paths["sha_dup_alias"]
            non_alias_selects = [s for s in part_Selects if "'sha_dup_alias'" not in s]
            if non_alias_selects:
                non_alias_sql = " UNION ALL ".join(non_alias_selects)
                broken_alias_targets = int(
                    con.execute(
                        f"""
                        WITH canon AS ({non_alias_sql}),
                        a AS (SELECT link_key, canonical_link_key, filename FROM read_parquet('{_sql_quote(ap)}'))
                        SELECT count(*) FROM a ANTI JOIN canon c ON a.canonical_link_key = c.link_key
                        """
                    ).fetchone()[0]
                )
                if broken_alias_targets > 0:
                    findings.append(
                        QualityFinding(
                            code="docmeta_broken_sha_dup_alias_target",
                            severity="error",
                            category="docmeta_conservation",
                            link_key_hex="corpus",
                            filename=ap.name,
                            expected=0,
                            observed=broken_alias_targets,
                            score=1.0,
                            evidence={"broken_alias_targets": broken_alias_targets},
                        )
                    )

        invalid_strict_rows = 0
        null_usable_pk_rows = 0
        malformed_json_rows = 0
        if direct_Selects and not missing_cols_by_part:
            direct_sql = " UNION ALL ".join(direct_Selects)
            bad_rows = con.execute(
                f"""
                WITH dir AS ({direct_sql})
                SELECT lower(hex(link_key)) AS lk_hex,
                       filename,
                       status,
                       primary_kind,
                       docmeta_json,
                       strict_v4_valid
                FROM dir
                WHERE docmeta_json IS NULL
                   OR trim(docmeta_json) = ''
                   OR strict_v4_valid IS DISTINCT FROM true
                   OR status IS NULL
                   OR (status IN ('usable', 'catalog_xml', 'ok') AND (primary_kind IS NULL OR trim(primary_kind) = ''))
                LIMIT 50
                """
            ).fetchall()
            counts_row = con.execute(
                f"""
                WITH dir AS ({direct_sql})
                SELECT
                    count(*) FILTER (WHERE docmeta_json IS NULL OR trim(docmeta_json) = '' OR strict_v4_valid IS DISTINCT FROM true OR status IS NULL),
                    count(*) FILTER (WHERE status IN ('usable', 'catalog_xml', 'ok') AND (primary_kind IS NULL OR trim(primary_kind) = ''))
                FROM dir
                """
            ).fetchone()
            invalid_strict_rows = int(counts_row[0])
            null_usable_pk_rows = int(counts_row[1])

            for lk_hex, fn, st, pk, dm_j, sv in bad_rows[:20]:
                findings.append(
                    QualityFinding(
                        code="docmeta_invalid_or_null_record",
                        severity="error",
                        category="docmeta_conservation",
                        link_key_hex=lk_hex or "",
                        filename=fn or "",
                        expected="strict_v4_valid=True and non-null status/primary_kind",
                        observed={"strict_v4_valid": sv, "status": st, "primary_kind": pk, "has_json": bool(dm_j)},
                        score=1.0,
                    )
                )

            # Sample-check JSON parseability across direct rows via DuckDB json_valid
            malformed_json_rows = int(
                con.execute(
                    f"""
                    WITH dir AS ({direct_sql})
                    SELECT count(*) FROM dir WHERE docmeta_json IS NOT NULL AND NOT json_valid(docmeta_json)
                    """
                ).fetchone()[0]
            )
            if malformed_json_rows > 0:
                findings.append(
                    QualityFinding(
                        code="docmeta_malformed_json",
                        severity="error",
                        category="docmeta_conservation",
                        link_key_hex="corpus",
                        filename="docmeta_v6_1",
                        expected=0,
                        observed=malformed_json_rows,
                        score=1.0,
                    )
                )
    finally:
        con.close()

    return {
        "detail_rows": detail_count,
        "completed_no_llm_rows": comp_count,
        "llm_queue_rows": queue_count,
        "llm_results_rows": llm_res_count,
        "sha_dup_alias_rows": alias_count,
        "partition_sum": partition_sum,
        "conserved_exact": conserved_exact,
        "duplicate_link_keys": dup_link_keys,
        "duplicate_doc_keys": dup_doc_keys,
        "orphan_docmeta_rows": orphan_rows,
        "saved_body_mismatches": saved_body_mismatches,
        "broken_alias_targets": broken_alias_targets,
        "invalid_strict_v4_rows": invalid_strict_rows,
        "null_usable_primary_kind_rows": null_usable_pk_rows,
        "malformed_json_rows": malformed_json_rows,
        "missing_required_columns": missing_cols_by_part,
    }


def _load_valid_key_set(parquet_path: Path, key_col: str) -> set[str] | None:
    if not parquet_path.is_file():
        return None
    cols = set(pq.read_schema(parquet_path).names)
    if key_col not in cols:
        return None
    con = duckdb.connect()
    try:
        return {
            str(r[0])
            for r in con.execute(
                f"SELECT DISTINCT {key_col} FROM read_parquet('{_sql_quote(parquet_path)}') WHERE {key_col} IS NOT NULL"
            ).fetchall()
        }
    finally:
        con.close()


def validate_dataset_provenance(
    tables_dir: str | Path,
    *,
    docmeta_dir: str | Path | None = None,
    rows: Sequence[CorpusDocRow] | None = None,
    base_tables_dir: str | Path | None = None,
    baseline_rows: Sequence[CorpusDocRow] | None = None,
    max_row_findings_per_code: int = 50,
) -> ProvenanceValidationReport:
    """Run all cross-table provenance, date-trap, Congress-boundary, and conservation checks."""
    tdir = Path(tables_dir)
    corpus_rows = (
        list(rows)
        if rows is not None
        else load_corpus_rows(tdir, docmeta_dir=docmeta_dir, include_text=True)
    )
    findings: list[QualityFinding] = []
    per_code_emitted: Counter[str] = Counter()

    def _emit_row_finding(f: QualityFinding) -> None:
        if per_code_emitted[f.code] < max_row_findings_per_code:
            findings.append(f)
            per_code_emitted[f.code] += 1

    extra_host_map = _load_committees_host_map(tdir)
    raw_trap_by_lr = _scan_raw_url_traps_and_pm(tdir)

    # Optional `hsru_host_status` map from `deterministic_323k_v6_1.parquet` if available
    det_hsru_by_lk: dict[str, str] = {}
    if docmeta_dir is not None:
        dm_paths = resolve_docmeta_paths(docmeta_dir)
        if "deterministic" in dm_paths:
            dp = dm_paths["deterministic"]
            dp_cols = set(pq.read_schema(dp).names)
            if "hsru_host_status" in dp_cols:
                lk_col = "lower(hex(link_key))" if "link_key" in dp_cols else "link_key_hex"
                con = duckdb.connect()
                try:
                    for lk_h, h_st in con.execute(
                        f"SELECT {lk_col}, hsru_host_status FROM read_parquet('{_sql_quote(dp)}') WHERE hsru_host_status IS NOT NULL"
                    ).fetchall():
                        det_hsru_by_lk[str(lk_h)] = str(h_st)
                finally:
                    con.close()

    # Optional witness & bill reference universes when present in `tables_dir`
    valid_witness_keys = _load_valid_key_set(tdir / "witnesses.parquet", "witness_key")
    valid_bill_ids = _load_valid_key_set(tdir / "bills.parquet", "bill_id")

    # Accumulators
    none_total = 0
    none_with_source = 0
    none_resolvable_committee_host = 0
    host_totals: Counter[str] = Counter()
    host_none_counts: Counter[str] = Counter()
    host_resolved_code: dict[str, str] = {}

    pub_hsru_only = 0
    floor_repo_host_rows = 0
    docmeta_hsru_leaks = 0

    wayback_wrapped_rows = 0
    cms_uploads_rows = 0
    senate_dl_rows = 0
    floor_week_rows = 0
    pm_pub_time_rows = 0
    wayback_leaks = 0
    cms_upload_leaks = 0

    invalid_cong_rows = 0
    bills_slug_checked = 0
    bills_slug_mismatches = 0
    early_jan_checked = 0
    jan3_off_by_one_rows = 0

    rows_with_witness_keys = 0
    orphan_witness_rows = 0
    completed_witness_bearing_rows = 0
    persona_shortfall_rows = 0

    rows_with_measure_keys = 0
    orphan_measure_rows = 0
    completed_bill_measure_rows = 0
    bill_ref_shortfall_rows = 0

    for row in corpus_rows:
        u = row.source_url or row.listed_on or ""
        host = row.host or extract_url_host(u)
        resolved_code = resolve_host_committee_code(host, u, extra_host_map=extra_host_map)
        if host:
            host_totals[host] += 1
            if resolved_code and host not in host_resolved_code:
                host_resolved_code[host] = resolved_code

        # 1. `<NONE>` committee audit
        if not row.committee_keys:
            none_total += 1
            if u or row.member_path:
                none_with_source += 1
            if host:
                host_none_counts[host] += 1
            if resolved_code and resolved_code != "hsru00":
                none_resolvable_committee_host += 1

        # 2. `hsru00` floor-host attribution leakage audit
        is_floor_url = bool(
            host in ("rules.house.gov", "democrats-rules.house.gov")
            or (u and _DOCS_HOUSE_FLOOR_RE.search(u))
        )
        if is_floor_url:
            floor_repo_host_rows += 1
        if row.committee_keys == ("hsru00",):
            pub_hsru_only += 1

        if row.docmeta_committees and "House Committee on Rules" in row.docmeta_committees:
            eff_pk = row.docmeta_primary_kind or ""
            hsru_st = det_hsru_by_lk.get(row.link_key_hex)
            is_sole_rules = row.docmeta_committees == ("House Committee on Rules",)
            has_print_banner = bool(row.p12_text and _RULES_PRINT_BANNER_RE.search(row.p12_text[:600]))
            is_hres = bool(_HRES_SLUG_RE.search(row.filename) or any("hres" in mk.lower() for mk in row.measure_keys))
            if hsru_st == "rules_host" or (
                is_sole_rules
                and eff_pk not in _RULES_PROCEEDING_KINDS
                and not is_hres
                and (has_print_banner or is_floor_url)
            ):
                docmeta_hsru_leaks += 1
                _emit_row_finding(
                    QualityFinding(
                        code="prov_hsru00_floor_author_leak",
                        severity="error",
                        category="provenance",
                        link_key_hex=row.link_key_hex,
                        filename=row.filename,
                        expected="[] or originating legislative committee (not floor host hsru00)",
                        observed=list(row.docmeta_committees),
                        score=1.0,
                        evidence={
                            "primary_kind": eff_pk,
                            "host": host,
                            "hsru_host_status": hsru_st,
                            "has_rules_print_banner": has_print_banner,
                        },
                    )
                )

        # Parse `docmeta_json` once if present for date / persona / refs checks
        dm_obj: dict[str, Any] | None = None
        if row.docmeta_json:
            try:
                parsed = json.loads(row.docmeta_json)
                if isinstance(parsed, dict):
                    dm_obj = parsed
            except json.JSONDecodeError:
                dm_obj = None

        # 3. Date-trap regressions (Wayback 14-digit crawl ts & CMS `/uploads/` folder dates)
        trap = raw_trap_by_lr.get(row.list_row, {})
        if "wayback_ymd" in trap:
            wayback_wrapped_rows += 1
        if "cms_upload_ym" in trap:
            cms_uploads_rows += 1
        if "senate_dl_ymd" in trap:
            senate_dl_rows += 1
        if trap.get("floor_week"):
            floor_week_rows += 1
        if trap.get("pm_published_time"):
            pm_pub_time_rows += 1

        m_slug_dt = _CLERK_SLUG_DATE_RE.search(row.filename) or _CLERK_SLUG_DATE_RE.search(u)
        slug_iso_dt: str | None = None
        if m_slug_dt:
            ymd = m_slug_dt.group(1)
            slug_iso_dt = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"

        eff_cong = row.docmeta_congress if row.docmeta_congress is not None else row.congress
        dm_doc_date = dm_obj.get("doc_date") if dm_obj else None

        if "wayback_ymd" in trap:
            wb_ymd = trap["wayback_ymd"]
            wb_cong = date_to_congress_constitutional(wb_ymd)
            # Check docmeta doc_date or accepted URL-sourced published document_date
            for src_label, cand_dt, sev in (
                ("docmeta.doc_date", dm_doc_date, "error"),
                (
                    "detail.document_date",
                    row.document_date
                    if (row.date_kind == "captured" and row.document_date_status == "accepted" and row.document_date_source == "url")
                    else None,
                    "error",
                ),
            ):
                if cand_dt and cand_dt == wb_ymd:
                    contradicts_slug = bool(slug_iso_dt and slug_iso_dt != wb_ymd)
                    contradicts_cong = bool(eff_cong and wb_cong and wb_cong > eff_cong)
                    if contradicts_slug or contradicts_cong:
                        wayback_leaks += 1
                        _emit_row_finding(
                            QualityFinding(
                                code="prov_wayback_crawl_date_leak",
                                severity=sev,  # type: ignore[arg-type]
                                category="date_trap",
                                link_key_hex=row.link_key_hex,
                                filename=row.filename,
                                expected=slug_iso_dt or f"Congress {eff_cong} window",
                                observed=cand_dt,
                                score=1.0,
                                evidence={
                                    "field": src_label,
                                    "wayback_ymd": wb_ymd,
                                    "raw_url": trap.get("wayback_raw"),
                                    "congress": eff_cong,
                                },
                            )
                        )

        if "cms_upload_ym" in trap:
            up_ym = trap["cms_upload_ym"]
            for src_label, cand_dt, sev in (
                ("docmeta.doc_date", dm_doc_date, "error"),
                (
                    "detail.document_date",
                    row.document_date
                    if (row.date_kind == "captured" and row.document_date_status == "accepted" and row.document_date_source == "url")
                    else None,
                    "warning",
                ),
            ):
                if cand_dt and cand_dt.startswith(up_ym):
                    cand_cong = date_to_congress_constitutional(cand_dt)
                    contradicts_slug = bool(slug_iso_dt and not slug_iso_dt.startswith(up_ym))
                    contradicts_cong = bool(eff_cong and cand_cong and cand_cong > eff_cong)
                    if contradicts_slug or contradicts_cong:
                        cms_upload_leaks += 1
                        _emit_row_finding(
                            QualityFinding(
                                code="prov_cms_upload_folder_date_leak",
                                severity=sev,  # type: ignore[arg-type]
                                category="date_trap",
                                link_key_hex=row.link_key_hex,
                                filename=row.filename,
                                expected=slug_iso_dt or f"Congress {eff_cong} window",
                                observed=cand_dt,
                                score=0.95,
                                evidence={
                                    "field": src_label,
                                    "cms_upload_ym": up_ym,
                                    "upload_url": trap.get("cms_upload_url"),
                                    "congress": eff_cong,
                                },
                            )
                        )

        # 4. `BILLS-` slug Congress & Constitutional Noon-Jan-3 boundary checks (`house_naming`)
        for c_label, c_val in (("published", row.congress), ("docmeta", row.docmeta_congress)):
            if c_val is not None and not is_valid_congress(c_val):
                invalid_cong_rows += 1
                _emit_row_finding(
                    QualityFinding(
                        code="prov_invalid_congress_range",
                        severity="error",
                        category="congress_boundary",
                        link_key_hex=row.link_key_hex,
                        filename=row.filename,
                        expected="1..130",
                        observed=c_val,
                        score=1.0,
                        evidence={"source": c_label},
                    )
                )

        bills_info = split_bills_congress_and_number(row.filename)
        if bills_info is not None:
            bills_slug_checked += 1
            expected_cong = int(bills_info["congress"])
            if row.docmeta_congress is not None and row.docmeta_congress != expected_cong:
                bills_slug_mismatches += 1
                _emit_row_finding(
                    QualityFinding(
                        code="prov_bills_slug_congress_mismatch",
                        severity="error",
                        category="congress_boundary",
                        link_key_hex=row.link_key_hex,
                        filename=row.filename,
                        expected=expected_cong,
                        observed=row.docmeta_congress,
                        score=1.0,
                        evidence={"source": "docmeta", "bills_parsed": bills_info},
                    )
                )
            elif row.congress is not None and row.congress != expected_cong:
                bills_slug_mismatches += 1
                _emit_row_finding(
                    QualityFinding(
                        code="prov_bills_slug_congress_mismatch",
                        severity="warning",
                        category="congress_boundary",
                        link_key_hex=row.link_key_hex,
                        filename=row.filename,
                        expected=expected_cong,
                        observed=row.congress,
                        score=0.9,
                        evidence={"source": "published", "bills_parsed": bills_info},
                    )
                )

        # Noon-Jan-3 odd-year constitutional boundary check (`YYYY-01-01` & `YYYY-01-02` belong to outgoing Congress)
        check_dt = dm_doc_date or (
            row.document_date if (row.date_kind == "captured" and row.document_date_status == "accepted") else None
        )
        if check_dt and len(check_dt) >= 10:
            try:
                yr_i = int(check_dt[:4])
                mo_i = int(check_dt[5:7])
                da_i = int(check_dt[8:10])
            except ValueError:
                yr_i, mo_i, da_i = 0, 0, 0
            if yr_i >= 1935 and yr_i % 2 == 1 and mo_i == 1 and da_i in (1, 2):
                early_jan_checked += 1
                const_cong = date_to_congress_constitutional(check_dt[:10])
                obs_cong = row.docmeta_congress if dm_doc_date else row.congress
                if const_cong is not None and obs_cong == const_cong + 1:
                    jan3_off_by_one_rows += 1
                    _emit_row_finding(
                        QualityFinding(
                            code="prov_jan3_noon_boundary_off_by_one",
                            severity="error" if dm_doc_date else "warning",
                            category="congress_boundary",
                            link_key_hex=row.link_key_hex,
                            filename=row.filename,
                            expected=const_cong,
                            observed=obs_cong,
                            score=1.0,
                            evidence={"date": check_dt[:10], "source": "docmeta" if dm_doc_date else "published"},
                        )
                    )

        # 6. `witnesses.parquet` vs `detail.witness_keys` & `docmeta` `personas` shortfall
        if row.witness_keys:
            rows_with_witness_keys += 1
            if valid_witness_keys is not None:
                missing_wks = [wk for wk in row.witness_keys if wk not in valid_witness_keys]
                if missing_wks:
                    orphan_witness_rows += 1
                    _emit_row_finding(
                        QualityFinding(
                            code="prov_orphan_witness_key",
                            severity="error",
                            category="witness_consistency",
                            link_key_hex=row.link_key_hex,
                            filename=row.filename,
                            expected="all witness_keys present in witnesses.parquet",
                            observed=missing_wks,
                            score=1.0,
                        )
                    )
            if (
                dm_obj is not None
                and row.docmeta_status == "usable"
                and row.docmeta_primary_kind in _SINGLE_WITNESS_PERSONA_KINDS
            ):
                completed_witness_bearing_rows += 1
                personas = dm_obj.get("personas") or []
                if len(personas) == 0:
                    persona_shortfall_rows += 1
                    _emit_row_finding(
                        QualityFinding(
                            code="prov_witness_persona_shortfall",
                            severity="warning",
                            category="witness_consistency",
                            link_key_hex=row.link_key_hex,
                            filename=row.filename,
                            expected=f">=1 persona (relational witness_keys={len(row.witness_keys)})",
                            observed=0,
                            score=0.85,
                            evidence={
                                "primary_kind": row.docmeta_primary_kind,
                                "witness_keys": list(row.witness_keys[:5]),
                            },
                        )
                    )

        # 7. `bills.parquet` vs `detail.measure_keys` & `docmeta` `refs` coverage
        if row.measure_keys:
            rows_with_measure_keys += 1
            if valid_bill_ids is not None:
                missing_mks = [mk for mk in row.measure_keys if mk not in valid_bill_ids]
                if missing_mks:
                    orphan_measure_rows += 1
                    _emit_row_finding(
                        QualityFinding(
                            code="prov_orphan_measure_key",
                            severity="error",
                            category="bill_consistency",
                            link_key_hex=row.link_key_hex,
                            filename=row.filename,
                            expected="all measure_keys present in bills.parquet",
                            observed=missing_mks,
                            score=1.0,
                        )
                    )
            if (
                dm_obj is not None
                and row.docmeta_status == "usable"
                and row.docmeta_primary_kind in ("bill_or_draft", "comparative_print")
            ):
                completed_bill_measure_rows += 1
                refs = dm_obj.get("refs") or []
                if len(refs) == 0:
                    bill_ref_shortfall_rows += 1
                    _emit_row_finding(
                        QualityFinding(
                            code="prov_bill_measure_ref_shortfall",
                            severity="warning",
                            category="bill_consistency",
                            link_key_hex=row.link_key_hex,
                            filename=row.filename,
                            expected=list(row.measure_keys[:5]),
                            observed=[],
                            score=0.85,
                            evidence={"primary_kind": row.docmeta_primary_kind},
                        )
                    )

    # Summarize `<NONE>` committee rates by domain and emit domain-level notices / base->candidate spikes
    top_none_domains: list[dict[str, Any]] = []
    for host, none_cnt in host_none_counts.most_common(30):
        tot = host_totals[host]
        rate = round(none_cnt / max(1, tot), 4)
        sys_code = host_resolved_code.get(host)
        top_none_domains.append(
            {
                "host": host,
                "none_rows": none_cnt,
                "total_rows": tot,
                "none_rate": rate,
                "resolvable_committee_code": sys_code,
            }
        )
        if sys_code and sys_code != "hsru00" and tot >= 10 and rate >= 0.50:
            findings.append(
                QualityFinding(
                    code="prov_domain_high_none_committee_rate",
                    severity="info",
                    category="provenance",
                    link_key_hex="corpus",
                    filename=host,
                    expected=sys_code,
                    observed={"none_rows": none_cnt, "total_rows": tot, "none_rate": rate},
                    score=rate,
                    evidence={"host": host, "resolvable_committee_code": sys_code},
                )
            )

    base_none_delta: dict[str, Any] | None = None
    if baseline_rows is not None or (base_tables_dir is not None and Path(base_tables_dir).exists()):
        base_rows = (
            list(baseline_rows)
            if baseline_rows is not None
            else load_corpus_rows(Path(base_tables_dir), include_text=False)  # type: ignore[arg-type]
        )
        base_none = sum(1 for r in base_rows if not r.committee_keys)
        base_rate = base_none / max(1, len(base_rows))
        curr_rate = none_total / max(1, len(corpus_rows))
        delta_rate = round(curr_rate - base_rate, 6)
        base_none_delta = {
            "base_total_rows": len(base_rows),
            "base_none_rows": base_none,
            "base_none_rate": round(base_rate, 4),
            "candidate_none_rate": round(curr_rate, 4),
            "none_rate_delta": delta_rate,
        }
        if len(corpus_rows) >= 20 and delta_rate >= 0.05:
            findings.append(
                QualityFinding(
                    code="prov_none_committee_rate_regression",
                    severity="warning",
                    category="provenance",
                    link_key_hex="corpus",
                    filename="list.parquet",
                    expected=round(base_rate, 4),
                    observed=round(curr_rate, 4),
                    score=min(1.0, delta_rate * 5.0),
                    evidence=base_none_delta,
                )
            )

    # 5. `docmeta_v6_1` conservation & strict_v4_valid gate
    docmeta_conservation = (
        _validate_docmeta_conservation(tdir, Path(docmeta_dir), findings)
        if docmeta_dir is not None
        else None
    )

    total_n = len(corpus_rows)
    return ProvenanceValidationReport(
        total_rows=total_n,
        has_docmeta=docmeta_dir is not None,
        none_committee_summary={
            "total_rows": total_n,
            "none_committee_rows": none_total,
            "none_committee_rate": round(none_total / max(1, total_n), 4),
            "none_with_sources": none_with_source,
            "none_on_resolvable_committee_hosts": none_resolvable_committee_host,
            "top_none_domains": top_none_domains,
            "base_comparison": base_none_delta,
        },
        hsru00_summary={
            "published_hsru00_only_rows": pub_hsru_only,
            "floor_repo_host_rows": floor_repo_host_rows,
            "docmeta_hsru_floor_author_leaks": docmeta_hsru_leaks,
        },
        date_trap_summary={
            "wayback_or_webharvest_wrapped_rows": wayback_wrapped_rows,
            "cms_uploads_folder_rows": cms_uploads_rows,
            "senate_download_folder_rows": senate_dl_rows,
            "house_floor_week_rows": floor_week_rows,
            "page_metadata_published_time_rows": pm_pub_time_rows,
            "wayback_crawl_date_leaks": wayback_leaks,
            "cms_upload_folder_date_leaks": cms_upload_leaks,
        },
        congress_boundary_summary={
            "invalid_congress_range_rows": invalid_cong_rows,
            "bills_slug_rows_checked": bills_slug_checked,
            "bills_slug_congress_mismatches": bills_slug_mismatches,
            "odd_year_jan1_jan2_rows_checked": early_jan_checked,
            "jan3_noon_boundary_off_by_one_rows": jan3_off_by_one_rows,
        },
        docmeta_conservation_summary=docmeta_conservation,
        witness_persona_summary={
            "witnesses_table_present": valid_witness_keys is not None,
            "rows_with_witness_keys": rows_with_witness_keys,
            "orphan_witness_key_rows": orphan_witness_rows,
            "completed_single_witness_rows": completed_witness_bearing_rows,
            "persona_shortfall_rows": persona_shortfall_rows,
        },
        bill_refs_summary={
            "bills_table_present": valid_bill_ids is not None,
            "rows_with_measure_keys": rows_with_measure_keys,
            "orphan_measure_key_rows": orphan_measure_rows,
            "completed_bill_rows_with_measures": completed_bill_measure_rows,
            "bill_ref_shortfall_rows": bill_ref_shortfall_rows,
        },
        findings=tuple(findings),
    )
