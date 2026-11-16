"""Tests for GPO p3..p8 witness-panel / CONTENTS extraction and stapled witness packets."""
from congress_api.parsers.gpo_hearings import (
    StapledPacketBoundary,
    detect_stapled_witness_packet,
    extract_gpo_p3_p8_witness_panels,
    is_gpo_cover_roster_only,
    is_steno_cover_roster_only,
    parse_gpo_contents_witnesses,
)


def test_gpo_p12_cover_roster_detection_and_p3_p8_witness_panel_extraction():
    p1 = """OVERSIGHT OF ARTIFICIAL INTELLIGENCE IN FINANCIAL SERVICES
    HEARING
    BEFORE THE
    COMMITTEE ON BANKING, HOUSING, AND URBAN AFFAIRS
    UNITED STATES SENATE
    ONE HUNDRED EIGHTEENTH CONGRESS
    SECOND SESSION
    MAY 22, 2024
    S. Hrg. 118-310
    Printed for the use of the Committee on Banking, Housing, and Urban Affairs
    U.S. GOVERNMENT PUBLISHING OFFICE
    WASHINGTON : 2024"""
    p2 = """COMMITTEE ON BANKING, HOUSING, AND URBAN AFFAIRS
    SHERROD BROWN, Ohio, Chairman
    TIM SCOTT, South Carolina, Ranking Member
    JACK REED, Rhode Island
    MIKE CRAPO, Idaho"""
    p3 = """C O N T E N T S
    WEDNESDAY, MAY 22, 2024
                                                                   Page
    Opening statement of Chairman Brown ..........................    1
    Opening statement of Senator Scott, a U.S. Senator from the
      State of South Carolina ....................................    3

                               WITNESSES
    Panel I
    Hon. Nellie Liang, Under Secretary for Domestic Finance, U.S.
      Department of the Treasury .................................    6
        Prepared statement .......................................   34
        Responses to written questions ...........................   68
    Panel II
    gensler_placeholder_ignored
    Dr. Simon Johnson, Ronald A. Kurtz Professor of Entrepreneur-
      ship, MIT Sloan School of Management .......................   18
    Ms. Miriam Vogel, President and CEO, EqualAI .................   21
    VerDate Sep 11 2014 14:22 Sep 09, 2024 Jkt 056120 PO 00000 Frm 00003 Fmt 5011 Sfmt 5011"""
    p4 = """OPENING STATEMENT OF HON. SHERROD BROWN
    The Chairman. The committee will come to order."""

    assert is_gpo_cover_roster_only([p1, p2]) is True
    assert is_gpo_cover_roster_only([p1, p3]) is False

    res = extract_gpo_p3_p8_witness_panels([p1, p2, p3, p4])
    assert res['cover_roster_only_p12'] is True
    assert res['rescue_pages'] == [3, 4]
    assert res['has_contents_header'] is True
    assert 'VerDate' not in res['contents_block']
    assert 'The committee will come to order' not in res['contents_block']

    witnesses = res['witnesses']
    assert [w['name'] for w in witnesses] == [
        'Hon. Nellie Liang',
        'Dr. Simon Johnson',
        'Ms. Miriam Vogel',
    ]
    assert witnesses[0]['panel'] == 'Panel I'
    assert witnesses[0]['page'] == 6
    assert witnesses[0]['organization'] == 'U.S. Department of the Treasury'
    assert witnesses[1]['panel'] == 'Panel II'
    assert witnesses[1]['page'] == 18
    assert witnesses[2]['position'] == 'President and CEO'
    assert witnesses[2]['organization'] == 'EqualAI'


def test_steno_cover_roster_only_and_surname_comma_given_contents():
    steno_p1 = """STENOGRAPHIC TRANSCRIPT OF PROCEEDINGS
    COMMITTEE ON ARMED SERVICES
    ALDERSON COURT REPORTING
    RPTS SMITH DCN 4412"""
    steno_p2 = """APPEARANCES:
    Senator Jack Reed, Chairman
    Senator Roger Wicker, Ranking Member"""
    assert is_steno_cover_roster_only([steno_p1, steno_p2]) is True
    assert is_steno_cover_roster_only([steno_p1, steno_p2 + '\n[Whereupon, at 9:30 a.m.]']) is False

    toc = """CONTENTS
    STATEMENTS
    Yellen, Hon. Janet L., Secretary, Department of the Treasury ........ 5
    Powell, Hon. Jerome H., Chair, Board of Governors of the Federal Reserve System .... 9"""
    parsed = parse_gpo_contents_witnesses(toc)
    assert [(w['name'], w['page']) for w in parsed['witnesses']] == [
        ('Hon. Janet L. Yellen', 5),
        ('Hon. Jerome H. Powell', 9),
    ]


def test_stapled_witness_packet_boundary_detection_and_single_artifact_guard():
    stmt_p1 = """Testimony of Dr. Sarah Jenkins
    Before the House Committee on Science, Space, and Technology
    Chairman Lucas, Ranking Member Lofgren, thank you for the opportunity to testify today."""
    stmt_p2 = """In conclusion, sustained federal investment in quantum sensing will strengthen national competitiveness.
    I look forward to your questions."""
    ttf_p3 = """Truth in Testimony Disclosure Form
    Witness Name: Dr. Sarah Jenkins
    1. Please list any nongovernmental entity for which you are a fiduciary.
    2. Please list any federal grants or contracts received."""
    ttf_p4 = """Truth in Testimony Disclosure Form
    Witness Name: Dr. Sarah Jenkins
    3. Please list any payments or contracts originating with a foreign government."""
    bio_p5 = """BIOGRAPHY OF DR. SARAH JENKINS
    Dr. Sarah Jenkins directs the Quantum Institute. She earned her Ph.D. in Physics in 2010."""
    qfr_p6 = """Questions for the Record
    Submitted by Representative Zoe Lofgren
    Question 1: What workforce bottlenecks affect national laboratories?
    Response: Graduate fellowship capacity remains the top constraint."""

    boundaries = detect_stapled_witness_packet([stmt_p1, stmt_p2, ttf_p3, ttf_p4, bio_p5, qfr_p6])
    assert boundaries == [
        StapledPacketBoundary(kind='witness-statement', start_page=1, end_page=2, marker='Prepared Witness Statement'),
        StapledPacketBoundary(kind='truth-in-testimony', start_page=3, end_page=4, marker='Truth in Testimony Disclosure Form'),
        StapledPacketBoundary(kind='witness-biography', start_page=5, end_page=5, marker='Witness Biography / CV'),
        StapledPacketBoundary(kind='questions-and-answers', start_page=6, end_page=6, marker='Questions for the Record'),
    ]

    # Single-artifact statement and standalone TTF must NOT split
    assert detect_stapled_witness_packet([stmt_p1, stmt_p2]) == []
    assert detect_stapled_witness_packet([ttf_p3, ttf_p4]) == []
