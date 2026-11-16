"""Offline unit tests for `viewer_publication.corpus_quality.tfidf_drift`."""
from __future__ import annotations

from viewer_publication.corpus_quality.core import CorpusDocRow
from viewer_publication.corpus_quality.tfidf_drift import (
    PhraseSignature,
    compute_log_odds_signatures,
    detect_host_boilerplate_drift,
    detect_label_contradictions,
)


def _make_row(
    link_idx: int,
    *,
    filename: str = "doc.pdf",
    fmt: str = "pdf",
    host: str = "docs.house.gov",
    document_kind: tuple[str, ...] = (),
    docmeta_primary_kind: str | None = None,
    congress: int | None = 118,
    docmeta_congress: int | None = None,
    committee_keys: tuple[str, ...] = ("hsif00",),
    docmeta_committees: tuple[str, ...] = (),
    document_date: str | None = "2023-06-14",
    p12_text: str = "",
) -> CorpusDocRow:
    hex_id = f"{link_idx:016x}"
    return CorpusDocRow(
        link_key_hex=hex_id,
        list_row=link_idx,
        doc_key=f"doc-{link_idx}",
        saved_body_hex=f"{link_idx:064x}",
        effective_body_sha_hex=f"{link_idx:064x}",
        filename=filename,
        format=fmt,
        effective_format=fmt,
        source_url=f"https://{host}/files/{filename}",
        host=host,
        document_kind=document_kind,
        docmeta_primary_kind=docmeta_primary_kind,
        congress=congress,
        docmeta_congress=docmeta_congress,
        committee_keys=committee_keys,
        docmeta_committees=docmeta_committees,
        document_date=document_date,
        p12_text=p12_text,
    )


def test_compute_log_odds_signatures_ranks_group_templates_and_preserves_large_group() -> None:
    # Dominant group (25 docs) vs small group (4 docs): global DF of "truth in testimony" is 25/29 = 0.862,
    # or even at 40/44 = 0.909 (> max_df_ratio=0.90) it must NOT be dropped because group B has 0% DF!
    ttf_texts = [
        (
            "Truth in Testimony Disclosure Form\n"
            "In accordance with Rule XI, clause 2(g)(5), witnesses disclose federal grants.\n"
            f"Witness Name: Researcher {i}\n"
        )
        for i in range(40)
    ]
    vote_texts = [
        (
            "COMMITTEE ON ENERGY AND COMMERCE -- 118TH CONGRESS\n"
            f"ROLL CALL VOTE NO. {i + 1}\n"
            "YEAS 28 NAYS 21 PRESENT 0\n"
        )
        for i in range(4)
    ]

    sigs = compute_log_odds_signatures(
        {"ttf": ttf_texts, "vote": vote_texts},
        ngram_range=(1, 3),
        top_k=8,
        min_df=2,
        max_df_ratio=0.90,
        window="header",
    )

    assert set(sigs) == {"ttf", "vote"}
    ttf_phrases = [s.phrase for s in sigs["ttf"]]
    vote_phrases = [s.phrase for s in sigs["vote"]]

    assert any("truth in testimony" in p or "disclosure form" in p for p in ttf_phrases)
    assert any("roll call" in p or "yeas" in p for p in vote_phrases)

    top_ttf = sigs["ttf"][0]
    assert isinstance(top_ttf, PhraseSignature)
    assert top_ttf.within_df == 1.0
    assert top_ttf.background_df == 0.0
    assert top_ttf.z_score > 3.0
    serialized = top_ttf.to_dict()
    assert serialized["doc_count"] == 40
    assert serialized["group_size"] == 40


def test_compute_log_odds_signatures_single_cluster_with_and_without_background() -> None:
    cluster_texts = [
        "SENATE JUDICIARY COMMITTEE QUESTIONNAIRE FOR JUDICIAL NOMINEES\n1. Full Name: Candidate A",
        "SENATE JUDICIARY COMMITTEE QUESTIONNAIRE FOR JUDICIAL NOMINEES\n1. Full Name: Candidate B",
        "SENATE JUDICIARY COMMITTEE QUESTIONNAIRE FOR JUDICIAL NOMINEES\n1. Full Name: Candidate C",
    ]
    # Degenerate single-cluster call without background_texts (used when tail clustering yields 1 cluster)
    solo = compute_log_odds_signatures({"tail-001": cluster_texts}, top_k=5, window="header")
    assert len(solo["tail-001"]) == 5
    assert solo["tail-001"][0].within_df == 1.0
    assert solo["tail-001"][0].z_score > 0.0

    # Single-cluster call contrasted against explicit background_texts
    bg = [
        "Prepared Statement of Jane Doe Before the Subcommittee on Health",
        "Testimony of John Roe Before the Committee on Finance",
        "Written Testimony of Alice Smith on Infrastructure Investment",
    ]
    contrasted = compute_log_odds_signatures(
        {"tail-001": cluster_texts},
        background_texts=bg,
        top_k=5,
        window="header",
        exclude_terms={"judiciary"},
    )
    phrases = [s.phrase for s in contrasted["tail-001"]]
    assert all("judiciary" not in p.split() for p in phrases)
    assert any("questionnaire" in p or "judicial nominees" in p for p in phrases)


def test_detect_label_contradictions_catches_bio_slot_ttf_and_respects_docmeta_resolution() -> None:
    rows: list[CorpusDocRow] = []
    # Clean biographies
    for i in range(1, 7):
        rows.append(
            _make_row(
                i,
                filename=f"witness_cv_{i}.pdf",
                document_kind=("witness-biography",),
                docmeta_primary_kind="witness_biography",
                p12_text=(
                    f"BIOGRAPHY OF DR. WITNESS {i}\n"
                    "EDUCATION\n2005 - 2010 Ph.D. in Physics, MIT\n"
                    "PROFESSIONAL EXPERIENCE\n2010 - Present Senior Scientist\n"
                    "SELECTED PUBLICATIONS\nJournal of Energy Systems\n"
                ),
            )
        )
    # Clean TTF disclosures
    for i in range(10, 16):
        rows.append(
            _make_row(
                i,
                filename=f"HHRG-118-IF14-TTF-Witness{i}-20230614.pdf",
                document_kind=("testimony-disclosure",),
                docmeta_primary_kind="truth_in_testimony_disclosure",
                p12_text=(
                    "Truth in Testimony Disclosure Form\n"
                    "Witness Name: Jane Doe\nPosition/Title: Director\n"
                    "Witness Type: Governmental Non-governmental\n"
                    "In accordance with Rule XI, clause 2(g)(5), list federal grants.\n"
                ),
            )
        )
    # Misfiled -Bio- upload slot containing a TTF form (fixed in docmeta_v6_1, broken in raw published)
    rows.append(
        _make_row(
            99,
            filename="HHRG-118-IF14-Bio-MisfiledW-20230614.pdf",
            document_kind=("witness-biography",),
            docmeta_primary_kind="truth_in_testimony_disclosure",
            p12_text=(
                "Truth in Testimony Disclosure Form\n"
                "In accordance with Rule XI, clause 2(g)(5)*, of the Rules of the House of Representatives, "
                "witnesses are asked to disclose the following information by filling in the provided blanks.\n"
                "Witness Name: Dr. Misfiled Witness\n"
            ),
        )
    )

    pub_findings = detect_label_contradictions(rows, label_source="published")
    assert [f.link_key_hex for f in pub_findings] == [f"{99:016x}"]
    assert pub_findings[0].code == "kind_body_contradiction"
    assert pub_findings[0].observed == "witness-biography"
    assert pub_findings[0].expected == "testimony-disclosure"
    assert pub_findings[0].evidence["ambiguous_upload_slot"] is True

    # In docmeta mode (and auto mode), docmeta_primary_kind already fixed the -Bio- slot -> 0 contradictions!
    docmeta_findings = detect_label_contradictions(rows, label_source="docmeta")
    assert docmeta_findings == []
    assert detect_label_contradictions(rows, label_source="auto") == []


def test_detect_label_contradictions_statement_inversions_and_boundary_trap_guards() -> None:
    rows = [
        # 1. Chair presiding opening statement mislabeled as witness-statement -> FLAG
        _make_row(
            1,
            filename="HHRG-118-IF14-Wstate-RodgersC-20230614.pdf",
            document_kind=("witness-statement",),
            p12_text=(
                "Opening Statement of Chairwoman Cathy McMorris Rodgers\n"
                "Subcommittee on Health Hearing on Modernizing Health Care\n"
                "June 14, 2023\n"
                "Today the Committee convenes to examine bipartisan solutions.\n"
            ),
        ),
        # 2. Non-Member CEO witness testimony mislabeled as opening-statement -> FLAG
        _make_row(
            2,
            filename="SFRC-Nominee-Or-Witness-Opening.pdf",
            document_kind=("opening-statement",),
            p12_text=(
                "Opening Statement of Dr. Elena Rostova, Ph.D., Chief Executive Officer, GridTech Labs\n"
                "Before the Committee on Energy and Natural Resources\n"
                "United States Senate\n"
                "Thank you for the opportunity to testify on battery supply chains.\n"
            ),
        ),
        # 3. Ways & Means roll-call vote sheet named 02-AMENDMENT-Brady.pdf -> FLAG
        _make_row(
            3,
            filename="02-AMENDMENT-Brady-1.pdf",
            document_kind=("amendment",),
            committee_keys=("hswm00",),
            p12_text=(
                "VOTES OF THE COMMITTEE\n"
                "In compliance with the Rules of the House of Representatives, the following statement is made "
                "concerning the vote of the Committee on Ways and Means.\n"
                "Yeas 24, Nays 17.\n"
            ),
        ),
        # 4. Chair QFR transmittal letter uploaded under -Wstate- -> FLAG
        _make_row(
            4,
            filename="HHRG-118-IF14-Wstate-SmithA-20230614-SD002.pdf",
            document_kind=("witness-statement",),
            p12_text=(
                "Dear Dr. Smith: Thank you for appearing before the Subcommittee on Health on June 14, 2023. "
                "Members of the Subcommittee have submitted additional questions for the hearing record "
                "attached to this letter. Please provide your responses by July 14, 2023.\nSincerely,\n"
            ),
        ),
        # --- ADVERSARIAL NEGATIVE GUARDS (MUST PRODUCE ZERO FALSE POSITIVES) ---
        # 5. Member of Congress testifying as a guest witness before another committee -> VALID witness-statement
        _make_row(
            5,
            filename="HHRG-118-II00-Wstate-CassidyB-20230614.pdf",
            document_kind=("witness-statement",),
            committee_keys=("hsii00",),
            p12_text=(
                "Statement of Senator Bill Cassidy\n"
                "Thank you, Chairman Westerman, for inviting me to testify before your committee today "
                "regarding coastal energy revenue sharing.\n"
            ),
        ),
        # 6. Stapled multi-doc packet opening with Witness Statement on p1 + TTF on p2 -> VALID witness-statement
        _make_row(
            6,
            filename="HHRG-118-IF14-Wstate-DoeJ-20230614.pdf",
            document_kind=("witness-statement",),
            p12_text=(
                "Testimony of Jane Doe, Executive Director, Clean Water Coalition\n"
                "Before the Committee on Energy and Commerce\n"
                "Thank you for inviting me.\n\n"
                "Truth in Testimony Disclosure Form\nWitness Name: Jane Doe\n"
                "In accordance with Rule XI, clause 2(g)(5), filling in the provided blanks.\n"
            ),
        ),
        # 7. hsii Hearing Notice formatted with `MEMORANDUM From: Chairman` -> VALID meeting-notice (NOT staff memo)
        _make_row(
            7,
            filename="HHRG-114-II13-Notice-20150507.pdf",
            document_kind=("meeting-notice",),
            committee_keys=("hsii13",),
            congress=114,
            p12_text=(
                "* * * HEARING NOTICE * * *\n"
                "MEMORANDUM\n"
                "To: Members, Subcommittee on Water, Power and Oceans\n"
                "From: The Honorable John Fleming, Chairman\n"
                "Subject: Oversight Hearing on May 7, 2015\n"
            ),
        ),
        # 8. Chair witness invitation letter citing Truth-in-Testimony -> MUST NOT fire as testimony-disclosure
        _make_row(
            8,
            filename="HHRG-118-IF14-Invite-20230601.pdf",
            document_kind=("letter",),
            p12_text=(
                "Dear Mr. Roe: Thank you for agreeing to testify at the hearing entitled 'Grid Reliability'. "
                "Please complete the enclosed Truth-in-Testimony Disclosure Form under Rule XI, clause 2(g)(5).\n"
                "Sincerely,\n"
            ),
        ),
    ]

    findings = detect_label_contradictions(
        rows,
        label_source="published",
        check_congress_contradictions=False,
        check_committee_contradictions=False,
    )
    flagged = {f.link_key_hex: (f.observed, f.expected) for f in findings}
    assert flagged == {
        f"{1:016x}": ("witness-statement", "opening-statement"),
        f"{2:016x}": ("opening-statement", "witness-statement"),
        f"{3:016x}": ("amendment", "committee-vote"),
        f"{4:016x}": ("witness-statement", "questions-for-record"),
    }


def test_detect_label_contradictions_pure_statistical_log_odds_without_cover_regex() -> None:
    rows: list[CorpusDocRow] = []
    # Two synthetic genres that do not trigger any hardcoded cover rule
    for i in range(1, 8):
        rows.append(
            _make_row(
                i,
                filename=f"cost_item_{i}.pdf",
                document_kind=("cost-estimate",),
                p12_text=(
                    "PAYGO SCOREKEEPING WORKSHEET\n"
                    "Direct spending outlays deficit impact ten year budget window scorekeeping baseline.\n"
                    f"Estimate table item {i}.\n"
                ),
            )
        )
    for i in range(20, 27):
        rows.append(
            _make_row(
                i,
                filename=f"rules_item_{i}.pdf",
                document_kind=("committee-rules",),
                p12_text=(
                    "STANDING SUBCOMMITTEE JURISDICTIONS AND QUORUM PROCEDURES\n"
                    "Proxy voting prohibition subpoena deposition authority clerk parliamentarian calendar.\n"
                    f"Rule clause {i}.\n"
                ),
            )
        )
    # Mislabel a clear scorekeeping worksheet as committee-rules
    rows.append(
        _make_row(
            77,
            filename="misfiled_worksheet.pdf",
            document_kind=("committee-rules",),
            p12_text=(
                "PAYGO SCOREKEEPING WORKSHEET\n"
                "Direct spending outlays deficit impact ten year budget window scorekeeping baseline.\n"
            ),
        )
    )

    findings = detect_label_contradictions(
        rows,
        label_source="published",
        min_class_docs=5,
        min_margin=2.0,
        min_confidence=0.75,
        check_congress_contradictions=False,
        check_committee_contradictions=False,
    )
    assert len(findings) == 1
    assert findings[0].link_key_hex == f"{77:016x}"
    assert findings[0].expected == "cost-estimate"
    assert findings[0].evidence["detection_basis"] == "statistical_log_odds"


def test_congress_and_committee_contradictions_respect_cms_time_travel_and_hsru_authorship() -> None:
    rows = [
        # 1. PDF masthead explicitly says ONE HUNDRED FOURTEENTH CONGRESS (114) while assigned congress=118 -> FLAG
        _make_row(
            1,
            filename="BILLS-114hr1234ih.pdf",
            fmt="pdf",
            congress=118,
            committee_keys=("hsif00",),
            p12_text=(
                "ONE HUNDRED FOURTEENTH CONGRESS\n"
                "Congress of the United States\n"
                "House of Representatives\n"
                "COMMITTEE ON ENERGY AND COMMERCE\n"
            ),
        ),
        # 2. Archived 114th Congress HTML page with live "119th Congress" CMS nav chrome -> NO congress contradiction!
        _make_row(
            2,
            filename="2015-press-release.html",
            fmt="html",
            host="budget.house.gov",
            congress=114,
            document_date="2015-04-15",
            committee_keys=("hsbu00",),
            p12_text=(
                "Skip to main content\n"
                "119th Congress\n"
                "April 15, 2015 — Committee on the Budget Releases FY2016 Concurrent Resolution.\n"
            ),
        ),
        # 3. 117th Congress PDF citing "(116th Congress)" in prose -> NO congress contradiction!
        _make_row(
            3,
            filename="HHRG-117-JU08-Notice.pdf",
            fmt="pdf",
            congress=117,
            committee_keys=("hsju08",),
            p12_text=(
                "117TH CONGRESS\n"
                "House Committee on the Judiciary\n"
                "Pursuant to section 1(a) of H. Res. 965 (116th Congress), Members may participate remotely.\n"
            ),
        ),
        # 4. hsru00 hosting a Rules Committee Print naming Energy and Commerce -> FLAG committee contradiction!
        _make_row(
            4,
            filename="BILLS-118HR2-RCP118-10.pdf",
            fmt="pdf",
            congress=118,
            committee_keys=("hsru00",),
            p12_text=(
                "RULES COMMITTEE PRINT 118-10\n"
                "TEXT OF H.R. 2, REPORTED BY THE COMMITTEE ON ENERGY AND COMMERCE\n"
                "SECTION 1. SHORT TITLE.\n"
            ),
        ),
        # 5. Genuine hsru00 floor-rule motion ("MOTION BY MR. COLE TO MAKE IN ORDER") -> NO committee contradiction!
        _make_row(
            5,
            filename="Cole-Motion-HR2.pdf",
            fmt="pdf",
            congress=118,
            committee_keys=("hsru00",),
            p12_text=(
                "MOTION BY MR. COLE OF OKLAHOMA TO MAKE IN ORDER\n"
                "I move that the Committee make in order amendment #12 to H.R. 2.\n"
                "I have an amendment to the rule.\n"
            ),
        ),
        # 6. Single-committee assignment (hsag00) whose opening masthead is House Natural Resources -> FLAG!
        _make_row(
            6,
            filename="misattributed_masthead.pdf",
            fmt="pdf",
            congress=118,
            committee_keys=("hsag00",),
            p12_text=(
                "ONE HUNDRED EIGHTEENTH CONGRESS\n"
                "U.S. House of Representatives\n"
                "Committee on Natural Resources\n"
                "Markup Memorandum\n"
            ),
        ),
    ]

    findings = detect_label_contradictions(rows, label_source="published")
    by_key = {(f.link_key_hex, f.code): f for f in findings}

    assert (f"{1:016x}", "congress_body_contradiction") in by_key
    assert by_key[(f"{1:016x}", "congress_body_contradiction")].expected == 114
    assert (f"{2:016x}", "congress_body_contradiction") not in by_key
    assert (f"{3:016x}", "congress_body_contradiction") not in by_key

    assert (f"{4:016x}", "committee_body_contradiction") in by_key
    assert by_key[(f"{4:016x}", "committee_body_contradiction")].expected == "hsif"
    assert (f"{5:016x}", "committee_body_contradiction") not in by_key

    assert (f"{6:016x}", "committee_body_contradiction") in by_key
    assert by_key[(f"{6:016x}", "committee_body_contradiction")].expected == "hsii"


def test_detect_host_boilerplate_drift_catches_waf_blockade_new_congress_nav_and_wrapper_spikes() -> None:
    baseline_rows: list[CorpusDocRow] = []
    current_rows: list[CorpusDocRow] = []

    # Host 1 (`veterans.senate.gov`): clean in baseline, hit by Senate WAF blockade in candidate (5/6 docs = 83%)
    for i in range(1, 7):
        baseline_rows.append(
            _make_row(
                100 + i,
                filename=f"hearing_{i}.html",
                fmt="html",
                host="veterans.senate.gov",
                congress=119,
                committee_keys=("ssva00",),
                p12_text=f"Senate Committee on Veterans' Affairs Hearing #{i} on VA Health Modernization.",
            )
        )
        current_rows.append(
            _make_row(
                200 + i,
                filename=f"hearing_{i}.html",
                fmt="html",
                host="veterans.senate.gov",
                congress=119,
                committee_keys=("ssva00",),
                p12_text=(
                    "Request Not Accepted - Security Risk Detected\nPlease contact support."
                    if i <= 5
                    else "Senate Committee on Veterans' Affairs Hearing #6 on VA Health."
                ),
            )
        )

    # Host 2 (`energycommerce.house.gov`): transitions from "119th Congress" in baseline to new "120th Congress"
    # CMS wrapper banner + newly spiked boilerplate footer in candidate!
    for i in range(1, 7):
        baseline_rows.append(
            _make_row(
                300 + i,
                filename=f"post_{i}.html",
                fmt="html",
                host="energycommerce.house.gov",
                congress=119,
                p12_text=f"119th Congress\nPress Release #{i}: Bipartisan Spectrum Legislation Advances.",
            )
        )
        current_rows.append(
            _make_row(
                400 + i,
                filename=f"post_{i}.html",
                fmt="html",
                host="energycommerce.house.gov",
                congress=None,
                p12_text=(
                    "Skip to main content Report Waste, Fraud, and Abuse 120th Congress\n"
                    f"Press Release #{i}: Bipartisan Legislation Advances.\n"
                    "Subscribe to committee newsletter cookie privacy notice\n"
                ),
            )
        )

    # Host 3 (`docs.house.gov`): normal PDF committee mastheads — must NOT false-fire in single-snapshot mode!
    for i in range(1, 7):
        pdf_row = _make_row(
            500 + i,
            filename=f"HHRG-118-IF14-Wstate-{i}.pdf",
            fmt="pdf",
            host="docs.house.gov",
            congress=118,
            p12_text=(
                "ONE HUNDRED EIGHTEENTH CONGRESS\n"
                "COMMITTEE ON ENERGY AND COMMERCE\n"
                "2125 Rayburn House Office Building, Washington, DC 20515\n"
                f"Prepared witness testimony #{i} on grid reliability.\n"
            ),
        )
        baseline_rows.append(pdf_row)
        current_rows.append(pdf_row)

    drift_vs_base = detect_host_boilerplate_drift(current_rows, baseline_rows=baseline_rows, min_host_docs=5)
    codes_by_host = {(f.evidence["host"], f.code): f for f in drift_vs_base}

    # Host 1 WAF blockade caught as severity="error" (>50% blocked & spiked over baseline)
    waf_finding = codes_by_host[("veterans.senate.gov", "soft_refusal_or_waf_wall")]
    assert waf_finding.severity == "error"
    assert waf_finding.observed == "senate_waf_block"
    assert waf_finding.link_key_hex != ""

    # Host 2 new "120th Congress" CMS nav + newly spiked header/footer wrapper caught
    assert ("energycommerce.house.gov", "cms_nav_congress_drift") in codes_by_host
    assert "120th Congress" in str(codes_by_host[("energycommerce.house.gov", "cms_nav_congress_drift")].observed)
    assert ("energycommerce.house.gov", "host_boilerplate_spike") in codes_by_host

    # Host 3 unchanged clean PDFs produce zero drift findings
    assert not any(f.evidence.get("host") == "docs.house.gov" for f in drift_vs_base)

    # Single-snapshot mode (baseline_rows=None): normal PDF letterheads on docs.house.gov STILL produce zero noise!
    single_snapshot = detect_host_boilerplate_drift(current_rows, baseline_rows=None, min_host_docs=5)
    assert not any(f.evidence.get("host") == "docs.house.gov" for f in single_snapshot)
    assert any(f.code == "soft_refusal_or_waf_wall" for f in single_snapshot)
    assert any(f.code == "host_boilerplate_spike" and f.evidence["host"] == "energycommerce.house.gov" for f in single_snapshot)


def test_multinomial_token_mode_and_header_footer_window() -> None:
    hdr1 = "Header Alpha Masthead\n" * 25
    hdr2 = "Header Beta Masthead\n" * 25
    mid_lines = "Exclusive Middle Body Prose\n" * 20
    g1 = [
        f"{hdr1}{mid_lines}Footer Copyright Portal Chrome Wrapper Chrome Wrapper"
        for _ in range(3)
    ]
    g2 = [
        f"{hdr2}{mid_lines}Clean Page End"
        for _ in range(3)
    ]
    sigs = compute_log_odds_signatures(
        {"g1": g1, "g2": g2},
        ngram_range=(2, 3),
        top_k=5,
        binary_per_doc=False,
        window="header_footer",
    )
    g1_phrases = [s.phrase for s in sigs["g1"]]
    assert any("chrome wrapper" in p or "header alpha" in p for p in g1_phrases)
    assert all("middle body" not in p for p in g1_phrases)


def test_alias_rows_skipped_and_docmeta_fine_grained_qfr_and_notice_splits() -> None:
    rows = [
        # Docmeta asserts qfr_response, but body is an unambiguous Chair QFR transmittal request -> FLAG in docmeta mode
        _make_row(
            1,
            filename="HHRG-118-IF14-QFR-Smith-20230614.pdf",
            document_kind=("questions-for-record",),
            docmeta_primary_kind="qfr_response",
            p12_text=(
                "Dear Dr. Smith: Thank you for testifying before the Committee on Energy and Commerce. "
                "Please respond to additional questions for the hearing record enclosed with this letter.\n"
            ),
        ),
        # Alias duplicate of the same document -> MUST BE SKIPPED (`is_alias=True`)
        CorpusDocRow(
            link_key_hex=f"{2:016x}",
            list_row=2,
            doc_key="doc-alias",
            saved_body_hex=f"{1:064x}",
            effective_body_sha_hex=f"{1:064x}",
            filename="HHRG-118-IF14-QFR-Smith-dup.pdf",
            format="pdf",
            effective_format="pdf",
            document_kind=("witness-biography",),
            docmeta_primary_kind="witness_biography",
            is_alias=True,
            p12_text=(
                "Truth in Testimony Disclosure Form\nWitness Name: Jane Doe\n"
                "In accordance with Rule XI, clause 2(g)(5), filling in the provided blanks.\n"
            ),
        ),
    ]

    # In published mode, `questions-for-record` is compatible with `qfr_request` -> 0 findings (and alias skipped!)
    assert detect_label_contradictions(rows, label_source="published", check_congress_contradictions=False, check_committee_contradictions=False) == []

    # In docmeta mode, `qfr_response` != `qfr_request` -> flags link 1, still skips alias link 2!
    dm_findings = detect_label_contradictions(
        rows,
        label_source="docmeta",
        check_congress_contradictions=False,
        check_committee_contradictions=False,
        max_findings=1,
    )
    assert len(dm_findings) == 1
    assert dm_findings[0].link_key_hex == f"{1:016x}"
    assert dm_findings[0].observed == "qfr_response"
    assert dm_findings[0].expected == "qfr_request"


def test_human_readable_docmeta_committees_do_not_false_positive() -> None:
    rows = [
        _make_row(
            1,
            filename="HHRG-118-IF14-Memo.pdf",
            document_kind=("committee-memorandum",),
            docmeta_primary_kind="hearing_memo_or_charter",
            committee_keys=("hsif14",),
            docmeta_committees=("House Committee on Energy and Commerce",),
            p12_text=(
                "ONE HUNDRED EIGHTEENTH CONGRESS\n"
                "House of Representatives\n"
                "COMMITTEE ON ENERGY AND COMMERCE\n"
                "MEMORANDUM\nTo: Subcommittee Members\nFrom: Majority Committee Staff\n"
            ),
        ),
    ]
    assert detect_label_contradictions(rows, label_source="docmeta") == []


