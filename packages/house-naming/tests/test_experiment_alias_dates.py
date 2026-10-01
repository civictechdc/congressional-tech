"""Regression cases from real same-content aliases and date-field experiments."""
import pytest
from house_naming import Engine


@pytest.fixture(scope="module")
def engine():
    return Engine()


def checked(engine, filename, source_url=None):
    result = engine.extract(filename, source_url=source_url)
    for observation in result["observations"]:
        for field in observation["fields"]:
            assert filename[field["start"]:field["end"]] == field["raw"]
    return result["metadata"]


ALIASES = [('MGR_01.pdf', 'https://transportation.house.gov/UploadedFiles/MGR_01.pdf', 'amendment'),
 ('mgr_01.pdf', 'https://transportation.house.gov/uploadedfiles/mgr_01.pdf', 'amendment'),
 ('04292025-full-transcript_-nom',
  'https://www.armed-services.senate.gov/download/04292025-full-transcript_-nom',
  'transcript'),
 ('04292025fulltranscriptnom.pdf',
  'https://www.armed-services.senate.gov/imo/media/doc/04292025fulltranscriptnom.pdf',
  'transcript'),
 ('5132025-full-transcript-nom',
  'https://www.armed-services.senate.gov/download/5132025-full-transcript-nom',
  'transcript'),
 ('5132025fulltranscriptnom.pdf',
  'https://www.armed-services.senate.gov/imo/media/doc/5132025fulltranscriptnom.pdf',
  'transcript'),
 ('60525_-full---transcript1',
  'https://www.armed-services.senate.gov/download/60525_-full---transcript1',
  'transcript'),
 ('60525fulltranscript1.pdf',
  'https://www.armed-services.senate.gov/imo/media/doc/60525fulltranscript1.pdf',
  'transcript'),
 ('62625-transcript-nom',
  'https://www.armed-services.senate.gov/download/62625-transcript-nom',
  'transcript'),
 ('62625transcriptnom.pdf',
  'https://www.armed-services.senate.gov/imo/media/doc/62625transcriptnom.pdf',
  'transcript'),
 ('helpwrittenstatementcjh', 'https://www.help.senate.gov/download/helpwrittenstatementcjh', 'statement'),
 ('HELP.Written.Statement.CJH.pdf',
  'https://www.help.senate.gov/imo/media/doc/79536a31-d1cf-25b0-e526-52ba2193d900/HELP.Written.Statement.CJH.pdf',
  'statement'),
 ('mckeonbio_12-04-19', 'https://www.armed-services.senate.gov/download/mckeonbio_12-04-19', 'biography'),
 ('McKeon.Bio_12-04-19.pdf',
  'https://www.armed-services.senate.gov/imo/media/doc/McKeon.Bio_12-04-19.pdf',
  'biography'),
 ('statementmedeiros', 'https://www.armed-services.senate.gov/download/statementmedeiros', 'statement'),
 ('Statement.Medeiros.pdf',
  'https://www.armed-services.senate.gov/imo/media/doc/Statement.Medeiros.pdf',
  'statement'),
 ('mark-r-filip-and-brian-a-benczkowski-letter-of-support-for-john-eisenberg',
  'https://www.judiciary.senate.gov/download/mark-r-filip-and-brian-a-benczkowski-letter-of-support-for-john-eisenberg',
  'letter-of-support'),
 ('mark_r_filip_and_brian_abenczkowskiletterofsupportforjohneisenberg.pdf',
  'https://www.judiciary.senate.gov/imo/media/doc/mark_r_filip_and_brian_abenczkowskiletterofsupportforjohneisenberg.pdf',
  'letter-of-support'),
 ('CRPT-117hrpt261.pdf',
  'https://docs.house.gov/billsthisweek/20220307/CRPT-117hrpt261.pdf',
  'published-report'),
 ('CRPT-117hrpt-261.pdf',
  'https://docs.house.gov/billsthisweek/20220307/CRPT-117hrpt-261.pdf',
  'published-report'),
 ('CRPT-117-hrpt261.pdf',
  'https://docs.house.gov/billsthisweek/20220307/CRPT-117-hrpt261.pdf',
  'published-report'),
 ('CRPT117hrpt269.pdf',
  'https://docs.house.gov/billsthisweek/20220307/CRPT117hrpt269.pdf',
  'published-report'),
 ('CRPT-117hrpt-269.pdf',
  'https://docs.house.gov/billsthisweek/20220307/CRPT-117hrpt-269.pdf',
  'published-report'),
 ('CRPT-117-hrpt-269.pdf',
  'https://docs.house.gov/billsthisweek/20220307/CRPT-117-hrpt-269.pdf',
  'published-report'),
 ('CRPT-117hrpt269.pdf',
  'https://docs.house.gov/billsthisweek/20220307/CRPT-117hrpt269.pdf',
  'published-report')]


@pytest.mark.parametrize("filename,source_url,kind", ALIASES)
def test_close_body_aliases_preserve_explicit_kind(engine, filename, source_url, kind):
    assert kind in checked(engine, filename, source_url).get("document_kind", [])


@pytest.mark.parametrize("filename,candidates", [
    ("03202024subtranscript.pdf", ["2024-03-20"]),
    ("07222025fullnominationtranscript.pdf", ["2025-07-22"]),
    ("09182025nominationtranscript.pdf", ["2025-09-18"]),
    ("04292025fulltranscriptnom.pdf", ["2025-04-29"]),
    ("5132025fulltranscriptnom.pdf", ["2025-05-13"]),
    ("03042024fulltranscript.pdf", ["2024-03-04", "2024-04-03"]),
    ("20240229fulltranscript.pdf", ["2024-02-29"]),
])
def test_joined_transcripts_preserve_uncertain_calendar_candidates(engine, filename, candidates):
    row = checked(engine, filename)
    assert row["document_kind"] == ["transcript"]
    assert row["date_token_candidates"] == candidates
    assert row["date_or_number_token"] == row["date_token"]
    assert not {"meeting_date", "date", "timestamp"} & row.keys()


@pytest.mark.parametrize("filename,digits", [
    ("60525fulltranscript1.pdf", "60525"),
    ("62625transcriptnom.pdf", "62625"),
    ("022824personneltranscript.pdf", "022824"),
])
def test_joined_transcripts_preserve_short_date_uncertainty(engine, filename, digits):
    row = checked(engine, filename)
    assert row["document_kind"] == ["transcript"]
    assert row["date_or_number_token"] == [digits]
    assert row["short_date_token"] == [digits]
    assert not row.get("date_token_candidates")


@pytest.mark.parametrize("filename", [
    "02312024fulltranscript.pdf", "20230229fulltranscript.pdf",
    "00000000fulltranscript.pdf", "032020241fulltranscript.pdf",
    "HR111111.pdf", "H.R.12345.pdf", "H.R. 12345.pdf", "HR03202024.pdf",
    "AMDT03202024.pdf", "Exhibit03202024.pdf",
    "BILLS-119-HR03202024ih.pdf", "HR-5480.pdf", "HR-3320.pdf",
])
def test_invalid_dates_and_assigned_identifiers_never_gain_dates(engine, filename):
    assert not checked(engine, filename).get("date_token_candidates")


@pytest.mark.parametrize("filename,month", [
    ("202112xx.pdf", "2021-12"),
    ("Exhibit 20_202112xx_Insider_Risk_December_20211.pdf", "2021-12"),
    ("Exhibit B4_202112xx_Insider_Risk_December_20211.pdf", "2021-12"),
])
def test_unknown_day_does_not_gain_precision_or_repaired_year(engine, filename, month):
    row = checked(engine, filename)
    assert row["partial_date_token_candidates"] == [month]
    assert row["unknown_day_token"] == ["xx"]
    assert not row.get("date_token_candidates")


def test_ambiguous_compact_time_does_not_invent_calendar_date(engine):
    row = checked(engine, "transcript102022am")
    assert row["time_token"] == ["102022"]
    assert row["session_period"] == ["am"]
    assert not {"date_token_candidates", "meeting_date", "timestamp"} & row.keys()


def test_unassigned_generic_number_keeps_calendar_candidate_uncertain(engine):
    # "document" supplies no explicit identifier convention or event role.
    row = checked(engine, "document03202024.pdf")
    assert row["date_token_candidates"] == ["2024-03-20"]
    assert not {"meeting_date", "date", "timestamp"} & row.keys()


@pytest.mark.parametrize("filename,url,prohibited", [
    ("mgr_01.pdf", "https://example.org/mgr_01.pdf", "amendment"),
    ("mgr_01.pdf", "https://transportation.house.gov/unreviewed/mgr_01.pdf", "amendment"),
    ("MGR_02.pdf", "https://transportation.house.gov/UploadedFiles/MGR_02.pdf", "amendment"),
    ("statementary", "https://www.armed-services.senate.gov/download/statementary", "statement"),
    ("symbio_12-04-19", "https://www.armed-services.senate.gov/download/symbio_12-04-19", "biography"),
    ("helpwrittenstatementary", "https://example.org/helpwrittenstatementary", "statement"),
    ("04292025fulltranscriptase.pdf", None, "transcript"),
    ("04292025fulltranscriptnominee.pdf", None, "transcript"),
    ("HHRG-119-JU00-Wstate-TranscriptA-20250930.pdf", None, "transcript"),
    ("BILLS-119-HR1234-TranscriptAct.pdf", None, "transcript"),
    ("CRPT-117-hrpt-.pdf", None, "published-report"),
    ("CRPT-117-hrpt-HR261.pdf", None, "published-report"),
])
def test_alias_rules_do_not_escape_their_supported_context(engine, filename, url, prohibited):
    assert prohibited not in checked(engine, filename, url).get("document_kind", [])


def test_joined_subjects_remain_literal_without_person_roles(engine):
    statement = checked(engine, "statementmedeiros", "https://www.armed-services.senate.gov/download/statementmedeiros")
    assert statement["subject_token"] == ["medeiros"]
    bio = checked(engine, "mckeonbio_12-04-19", "https://www.armed-services.senate.gov/download/mckeonbio_12-04-19")
    assert bio["subject_token"] == ["mckeon"]
    assert bio["date_token"] == ["12-04-19"]
    assert not bio.get("date_token_candidates")
    written = checked(engine, "helpwrittenstatementcjh", "https://www.help.senate.gov/download/helpwrittenstatementcjh")
    assert written["subject_token"] == ["cjh"]
    assert written["context_token"] == ["help"]
    support = checked(engine, "mark_r_filip_and_brian_abenczkowskiletterofsupportforjohneisenberg.pdf")
    assert support["subject_token"] == ["mark_r_filip_and_brian_abenczkowski"]
    assert support["recipient_token"] == ["johneisenberg"]
    for row in [statement, bio, written, support]:
        assert not {"witness_id", "author", "person_id", "sponsor_bioguide_id"} & row.keys()


def test_report_separator_variants_preserve_components(engine):
    row = checked(engine, "CRPT-117-hrpt-269.pdf")
    assert row["congress"] == ["117"]
    assert row["report_number"] == ["269"]
    assert row["publication_type"] == ["hrpt"]


def test_case_is_not_the_manager_rule_qualification(engine):
    for filename in ["MGR_01.pdf", "mgr_01.pdf"]:
        for source_url in ["https://transportation.house.gov/UploadedFiles/MGR_01.pdf",
                           "https://transportation.house.gov/uploadedfiles/mgr_01.pdf"]:
            assert checked(engine, filename, source_url)["document_kind"] == ["amendment"]


@pytest.mark.parametrize("filename", [
    "Exhibits.pdf", "Attachments.pdf", "Exhibits_20240320.pdf", "Attachments-20240320.pdf",
])
def test_plural_reference_words_are_not_single_letter_items(engine, filename):
    row = checked(engine, filename)
    assert not row.get("item_token")
    assert not row.get("exhibit_marker")
