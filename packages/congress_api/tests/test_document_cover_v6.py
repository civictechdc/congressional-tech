"""Tests for V5/V6 Tier-1 document covers and SFRC nominee / embargo / Member opening guards."""
from io import BytesIO
import json
from pathlib import Path

from pypdf import PdfReader
import pytest

from congress_api.parsers.document_cover import (
    COVER_FIELDS,
    document_cover,
    document_page_fields,
)

FIXTURES = Path(__file__).parent / 'fixtures'


def test_all_existing_document_cover_fixtures_stay_pinned():
    expected_pdfs = {
        'document-covers/house-amendment.pdf': {'content_document_kind': ['amendment']},
        'document-covers/house-hearing.pdf': {'content_document_kind': ['published-hearing']},
        'document-covers/house-vote.pdf': {'content_document_kind': ['committee-vote']},
        'meeting_inventory/document-covers/bill.pdf': {
            'content_document_kind': ['legislative-text'],
            'content_citation': ['S. 2599'],
            'content_congress': ['117'],
        },
        'meeting_inventory/document-covers/coverless.pdf': {'content_document_kind': ['transcript']},
        'meeting_inventory/document-covers/email.pdf': {},
        'meeting_inventory/document-covers/letter.pdf': {},
        'meeting_inventory/document-covers/opening.pdf': {'content_document_kind': ['opening-statement']},
        'meeting_inventory/document-covers/paper-questions.pdf': {'content_document_kind': ['questions-and-answers']},
        'meeting_inventory/document-covers/stenographic.pdf': {'content_document_kind': ['transcript']},
        'meeting_inventory/document-covers/substitute-original.pdf': {
            'content_document_kind': ['amendment'],
            'content_amendment_type': ['substitute'],
            'content_citation': ['S. 3235'],
            'content_congress': ['116'],
        },
        'meeting_inventory/document-covers/substitute.pdf': {
            'content_document_kind': ['amendment'],
            'content_amendment_type': ['substitute'],
            'content_citation': ['S. 3235'],
            'content_congress': ['116'],
        },
        'meeting_inventory/document-covers/testimony.pdf': {'content_document_kind': ['witness-statement']},
    }
    for rel, exp in expected_pdfs.items():
        data = (FIXTURES / rel).read_bytes()
        got = document_cover(data, lambda raw, idx: PdfReader(BytesIO(raw)).pages[idx].extract_text())
        assert got == exp, rel
        assert set(got) <= COVER_FIELDS

    dev = json.loads((FIXTURES / 'document-covers/development-forms.json').read_text())
    for rec in dev['records']:
        got_kind = document_page_fields(rec['assisted_text']).get('content_document_kind', [None])[0]
        assert got_kind == rec['expected_assisted'], rec['review_id']

    rem = json.loads((FIXTURES / 'meeting_inventory/document-covers/remaining-legislative-text.json').read_text())
    for rec in rem:
        assert document_page_fields(rec['text']) == rec['expected'], rec['filename']


def test_tier1_testimony_disclosure_and_witness_list_and_cv_covers():
    ttf = """118th Congress
    Truth in Testimony Disclosure Form
    Instructions for Completing the Truth in Testimony Disclosure Form
    Witness Name: Dr. Jane R. Doe
    Position/Title: Senior Fellow
    1. Please list any nongovernmental entity for which you are a fiduciary.
    2. Please list any federal grants or contracts received since October 1, 2021."""
    res_ttf = document_page_fields(ttf)
    assert res_ttf == {'content_document_kind': ['testimony-disclosure'], 'content_congress': ['118']}

    wlist = """Committee on Energy and Commerce
    Subcommittee on Health
    118th Congress
    WITNESS LIST
    Hearing on Strengthening Primary Care
    Panel I
    The Honorable Chiquita Brooks-LaSure, Administrator, Centers for Medicare & Medicaid Services
    Panel II
    Dr. Marcus Welby, President, Family Medicine Association"""
    assert document_page_fields(wlist) == {
        'content_document_kind': ['witness-list'],
        'content_congress': ['118'],
    }

    cv = """CURRICULUM VITAE
    Jane R. Doe, Ph.D.
    EDUCATION
    2008 - 2013  Ph.D. in Economics, Massachusetts Institute of Technology
    PROFESSIONAL EXPERIENCE
    2018 - Present  Senior Fellow, Brookings Institution
    2013 - 2018  Assistant Professor, University of Michigan
    SELECTED PUBLICATIONS"""
    assert document_page_fields(cv) == {'content_document_kind': ['witness-biography']}


@pytest.mark.parametrize('crs_code', ['R47812', 'RL33614', 'IF12455', 'IN12301', 'LSB11092'])
def test_crs_gao_cbo_and_federal_register_covers_and_adversarial_negatives(crs_code):
    crs = f"""Congressional Research Service
    Informing the legislative debate since 1914
    Federal Disaster Assistance After Hurricanes
    Updated October 14, 2024
    Congressional Research Service
    https://crsreports.congress.gov
    {crs_code}"""
    assert document_page_fields(crs) == {
        'content_document_kind': ['crs-report'],
        'content_citation': [crs_code],
    }

    # CRS Memorandum must NOT classify as crs-report
    crs_memo = f"""Congressional Research Service
    MEMORANDUM
    To: Honorable Committee Member
    Subject: Confidential Distribution Analysis ({crs_code})"""
    assert document_page_fields(crs_memo) == {}


def test_gao_report_excludes_testimony_and_cbo_at_a_glance_and_federal_register():
    gao_report = """United States Government Accountability Office
    GAO
    Report to Congressional Requesters
    May 2024
    CYBERSECURITY
    Agencies Need to Strengthen Cloud Incident Response
    GAO-24-106214"""
    assert document_page_fields(gao_report) == {
        'content_document_kind': ['gao-report'],
        'content_citation': ['GAO-24-106214'],
    }

    # GAO-YY-NNNT is witness testimony, NEVER gao-report
    gao_testimony = """Statement of Gene L. Dodaro, Comptroller General of the United States
    Testimony
    Before the Special Committee on Aging, U.S. Senate
    GAO-24-107111T
    United States Government Accountability Office"""
    assert document_page_fields(gao_testimony) == {'content_document_kind': ['witness-statement']}

    cbo = """At a Glance
    H.R. 4366, Military Construction, Veterans Affairs, and Related Agencies Appropriations Act
    As ordered reported by the House Committee on Appropriations on June 15, 2023
    By Fiscal Year, Millions of Dollars
    Pay-As-You-Go Considerations: None
    CONGRESSIONAL BUDGET OFFICE | WWW.CBO.GOV"""
    assert document_page_fields(cbo) == {
        'content_document_kind': ['cost-estimate'],
        'content_citation': ['H.R. 4366'],
    }

    fr = """54321 Federal Register / Vol. 89, No. 126 / Monday, July 1, 2024 / Notices
    DEPARTMENT OF COMMERCE
    National Institute of Standards and Technology
    ACTION: Notice of public meeting.
    SUMMARY: NIST announces a workshop on AI safety.
    Billing Code 3510-13-P"""
    assert document_page_fields(fr) == {
        'content_document_kind': ['federal-register-notice'],
        'content_citation': ['89 FR 54321'],
    }


def test_subpoena_attendance_meeting_notice_staff_report_and_adversarial_traps():
    subpoena = """SUBPOENA
    BY AUTHORITY OF THE HOUSE OF REPRESENTATIVES OF THE CONGRESS OF THE UNITED STATES OF AMERICA
    118th Congress
    To: John Doe, Chief Executive Officer
    You are hereby commanded to be and appear before the Committee on the Judiciary of the House of Representatives
    and produce the things specified in the attached schedule."""
    assert document_page_fields(subpoena) == {
        'content_document_kind': ['subpoena'],
        'content_congress': ['118'],
    }

    # Notice of Intent to Issue a Subpoena memo must NEVER fire subpoena or meeting-notice
    subpoena_memo = """MEMORANDUM
    To: Members of the Committee on Oversight and Reform
    Fr: Chairwoman Carolyn B. Maloney
    Re: Notice of Intent to Issue a Subpoena to AbbVie Inc."""
    assert document_page_fields(subpoena_memo) == {}

    attendance = """COMMITTEE ON FINANCIAL SERVICES
    118th Congress
    COMMITTEE ATTENDANCE SHEET
    Full Committee Hearing - June 12, 2024
    Present:
    Mr. McHenry
    Ms. Waters
    Mr. Lucas
    Mr. Sherman"""
    assert document_page_fields(attendance) == {
        'content_document_kind': ['attendance-sheet'],
        'content_congress': ['118'],
    }

    markup_notice = """Committee on Transportation and Infrastructure
    118th Congress
    NOTICE OF FULL COMMITTEE MARKUP
    Date: Wednesday, May 15, 2024
    Time: 10:00 a.m.
    Place: 2167 Rayburn House Office Building
    The Committee on Transportation and Infrastructure will meet to consider the following measures:"""
    assert document_page_fields(markup_notice) == {
        'content_document_kind': ['meeting-notice'],
        'content_congress': ['118'],
    }

    staff_report = """MAJORITY STAFF REPORT
    Prepared for the Committee on Homeland Security and Governmental Affairs
    United States Senate
    118th Congress
    Failures in Federal Emergency Contracting"""
    assert document_page_fields(staff_report) == {
        'content_document_kind': ['staff-report'],
        'content_congress': ['118'],
    }


def test_sfrc_nominee_opening_statement_and_member_honorable_guard_and_questionnaire():
    # Adversarial Trap 1: SFRC Nominee "Opening Statement" -> witness-statement, NEVER opening-statement
    sfrc_nominee_opening = """OPENING STATEMENT OF HON. KURT M. CAMPBELL
    NOMINEE TO BE DEPUTY SECRETARY OF STATE
    BEFORE THE SENATE COMMITTEE ON FOREIGN RELATIONS
    UNITED STATES SENATE
    DECEMBER 7, 2023
    Chairman Cardin, Ranking Member Risch, and Members of the Committee, I am honored to appear before you today as President Biden's nominee."""
    assert document_page_fields(sfrc_nominee_opening) == {'content_document_kind': ['witness-statement']}

    # Agency official witness "Opening Statement" -> witness-statement
    agency_witness_opening = """OPENING STATEMENT OF THE HONORABLE CHIQUITA BROOKS-LASURE
    ADMINISTRATOR, CENTERS FOR MEDICARE & MEDICAID SERVICES
    BEFORE THE SUBCOMMITTEE ON HEALTH"""
    assert document_page_fields(agency_witness_opening) == {'content_document_kind': ['witness-statement']}

    # Member Opening Statement with "THE HONORABLE" (F11) MUST remain opening-statement, NEVER witness-statement!
    member_honorable_opening = """OPENING STATEMENT OF THE HONORABLE FRANK PALLONE
    BEFORE THE SUBCOMMITTEE ON HEALTH
    COMMITTEE ON ENERGY AND COMMERCE
    Good morning. Today the Subcommittee meets to examine prescription drug pricing."""
    assert document_page_fields(member_honorable_opening) == {'content_document_kind': ['opening-statement']}

    # Physician Member Opening Statement with "THE HONORABLE ..., M.D." MUST remain opening-statement!
    physician_member_opening = """OPENING STATEMENT OF THE HONORABLE RAUL RUIZ, M.D.
    BEFORE THE SUBCOMMITTEE ON OVERSIGHT AND INVESTIGATIONS"""
    assert document_page_fields(physician_member_opening) == {'content_document_kind': ['opening-statement']}

    # Member Opening Statement at a nomination hearing MUST remain opening-statement
    chair_opening_at_nomination = """OPENING STATEMENT OF SENATOR BENJAMIN L. CARDIN
    CHAIRMAN, SENATE COMMITTEE ON FOREIGN RELATIONS
    To conduct a nomination hearing for Kurt M. Campbell to be Deputy Secretary of State
    Good morning. The Committee meets today to consider this nomination."""
    assert document_page_fields(chair_opening_at_nomination) == {'content_document_kind': ['opening-statement']}

    # Adversarial Trap 2: SFRC Nominee Questionnaire -> questionnaire, NEVER questions-and-answers (QFR)
    sfrc_questionnaire = """118th Congress
    NOMINEE QUESTIONNAIRE FOR THE COMMITTEE ON FOREIGN RELATIONS
    UNITED STATES SENATE
    BIOGRAPHICAL AND FINANCIAL INFORMATION REQUESTED OF NOMINEES
    1. Name: Kurt Michael Campbell
    2. Position to which nominated: Deputy Secretary of State"""
    assert document_page_fields(sfrc_questionnaire) == {
        'content_document_kind': ['questionnaire'],
        'content_congress': ['118'],
    }

    # Genuine QFR -> questions-and-answers
    qfr = """118th Congress
    QUESTIONS FOR THE RECORD
    Submitted by Senator James E. Risch
    Committee on Foreign Relations
    Question 1: How will the Department prioritize Indo-Pacific deterrence?
    Response: We will align security assistance with allies."""
    assert document_page_fields(qfr) == {
        'content_document_kind': ['questions-and-answers'],
        'content_congress': ['118'],
    }

    # Adversarial Trap 3: Embargoed Witness Testimony -> witness-statement, NEVER QFR or opening-statement
    embargoed_testimony = """EMBARGOED UNTIL DELIVERY
    PLEASE CHECK AGAINST DELIVERY
    Statement of Dr. Elena Martinez
    Before the Committee on Commerce, Science, and Transportation
    United States Senate
    Thank you for inviting me. I look forward to answering your questions for the record or today."""
    assert document_page_fields(embargoed_testimony) == {'content_document_kind': ['witness-statement']}
