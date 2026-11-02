import pytest
from congress_api.matching.committees import codes_of
from congress_api.parsers.witness_names import is_name, witness
from congress_api.parsers.xml import parse_xml


FOOTNOTE_TEXT_LINES = [
    # GPO's footnote text runs into the next witness's line; the name follows its last sentence (green-f4).
    ("Prepared statement \\2\\ \\1\\ The information has been retained in committee files and also is available at "
     "http://docs.house.gov/meetings/IF/IF03/20150603/103551/ BILLS-114pih-SubtitleA-EnergyEfficiency.pdf. \\2\\ Ms. Kelly's "
     "statement has been retained in committee files and also is available at http://docs.house.gov/meetings/IF/IF03/20150603/ "
     "103551/HHRG-114-IF03-Wstate-KellyS-20150603.pdf. John E. Shelk, President and Chief Executive Officer, Electric Power "
     "Supply Association", "John E. Shelk"),
    ("Science, Changing the Culture'' and the accompanying slide presentation have been retained in committee records and also are "
     "available at http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=101897. Gerard A. Gioia, Chief, Division of "
     "Pediatric Neuropsychology, Children's National Health System", "Gerard A. Gioia"),
    ("and also is available at https://docs.house.gov/meetings/IF/IF14/ 20191210/110313/HHRG-116-IF14-Wstate-RossJ-20191210.pdf. "
     "Scott W. Atlas, M.D., David and Joan Traitel Senior Fellow, Hoover Institution, Stanford University", "Scott W. Atlas"),
    ("is available at https://docs.house.gov/meetings/IF/IF14/ 20200129/110423/HHRG-116-IF14-Wstate-ChuaK-20200129.pdf. \\2\\ "
     "Nancy Perry, did not answer the question by the time of publication. Melanie Benesh, Legislative Attorney, Environmental "
     "Working Group", "Melanie Benesh"),
    ("is available at https://docs.house.gov/meetings/IF/IF03/ 20200205/110468/HHRG-116-IF03-Wstate-McMahonM-20200205.pdf. \\2\\ "
     "Mr. Peress did not answer submitted questions for the record by the time of publication. \\3\\ The information has been "
     "retained in committee files and also is available at https://docs.house.gov/meetings/IF/IF03/ 20200205/110468/"
     "HHRG-116-IF03-Wstate-vanRossumM-20200205.pdf. David Mallino, Legislative and Political Director, Laborers International "
     "Union of North America", "David Mallino"),
    ("time of printing. \\2\\ Additional material submitted for the record has been retained in committee files and also is "
     "available at http://docs.house.gov/ Committee/Calendar/ByEvent.aspx?EventID=104765. Mae C. Wu, Senior Attorney, Health and "
     "Environment Program, Natural Resources Defense Council", "Mae C. Wu"),
    ("Attatchments to Lt. General Semonite's responses to Questions for the Record are retained in the files of the Committee "
     "Corbett, Hon. Ron, Mayor, Cedar Rapids, Iowa", "Ron Corbett"),
    # A line that is footnote text to its end names no one.
    ("Investing in Racial Diversity in Tech\" has been retained in committee files and also is available as part of Ms. Kim's "
     "written testimony at https://docs.house.gov/meetings/IF/IF17/ 20190306/108901/HHRG-116-IF17-Wstate-KimJ-20190306.pdf. \\2\\ "
     "Ms. Oliverio did not answer submitted questions for the record by the time of publication. \\3\\ A report entitled \"The "
     "2018 Disability Equality Index: A Record Year for Corporate Disability Inclusion and Leadership\" has been retained in "
     "committee files and", ""),
    # A contents label followed directly by a name, with no marker (green-f4).
    ("Prepared statement Erik D. Olson, Senior Strategic Director for Health And Food, Natural Resources Defense Counsel", "Erik D. Olson"),
    ("Submitted questions: Avalos, Hon. Edward M", "Edward M Avalos"),
    ("Submitted questions \\2\\...................................... Mark Johnson, Senior Environmental Health Scientist, Agency "
     "for Toxic Substances and Disease Registry--Region 5", "Mark Johnson"),
    ("Submitted questions.......................................... Beachy, Ph.D., Roger N., President Emeritus, Donald Danforth "
     "Plant Science Center", "Roger N. Beachy"),
    ("Additional information \\1\\ Kevin Sunday, Director, Government Affairs, Pennsylvania Chamber of Business and Industry", "Kevin Sunday"),
    ("Additional information from Michael R. Lemov, Winston & Strawn", "Michael R. Lemov"),
    ("Additional materials supplied: Pautzke, Dr. Clarence, Executive Director, North Pacific Research Board, Statement "
     "submitted for the record", "Clarence Pautzke"),
    ("Additional materials supplied: Lingle, Hon. Linda, Governor, State of Hawaii, Letter submitted for the record", "Linda Lingle"),
    ("Prepared statements: Weber, Peter", "Peter Weber"),
    ("Prepared statements:..................................... LaMura, Marianne", "Marianne LaMura"),
    ("Prepared statement and attachments..........................124-136 Paperiello, Carl, Deputy Executive Director for "
     "Materials, Research and State Programs, Nuclear Regulatory Commission", "Carl Paperiello"),
    ("Prepared Statement 4........................................... David S. McClimon, President, Conway Freight Inc.", "David S. McClimon"),
    # A label followed by what is not a name stays as GPO wrote it.
    ("Prepared statement on H.R. 841, H.R. 931, and H.R. 1410", "Prepared statement on H.R. 841"),
    ("Prepared statements: April 5, 2001", "Prepared statements: April 5"),
    ("Prepared statement dated July 30, 2020 before the Senate Committee on Commerce, Science and Transportation", "Prepared statement dated July 30"),
]


LEADER_LINES = [
    # A dot leader inside a line separates two items: a name and its position, or a contents entry (and its
    # pages) and the next witness's line. Neither side is dropped wholesale (D4 gate, witnesses).
    ("Kay E. Brown..................................................... Director, Education, Workforce, and Income Security, "
     "U.S. Government Accountability Office Testimony", "Kay E. Brown", "Director", "Education, Workforce, and Income Security, "
     "U.S. Government Accountability Office Testimony"),
    ("Slides....................................................... 62-75 Hines, William H., past chairman and board member, "
     "Greater New Orleans, Inc.", "William H. Hines", "past chairman and board member", "Greater New Orleans, Inc."),
    ("Letters to Hon. Arthur Levitt................................ 39,40 Metzenbaum, Hon. Howard M., (Retired Senator), "
     "Chairman, Consumer Federation of America", "Howard M. Metzenbaum", "(Retired Senator)", "Chairman, Consumer Federation of America"),
    ("Statements, Association of State and Interstate Water Pollution Control Administrators.................102-115, 115-123 "
     "Nielsen, William, council president, Eau Claire, WI, on Behalf of the National League of Cities", "William Nielsen",
     "council president", "Eau Claire, WI, on Behalf of the National League of Cities"),
    ("Steve Chalk, Chief Financial Officer, Energy Efficiency and Renewable Energy, Department of Energy \\1\\..................... "
     "Insert for the record", "Steve Chalk", "Chief Financial Officer", "Energy Efficiency and Renewable Energy, Department of Energy"),
    # Contents entries with no one's line after them stay entries; a bare Member's name between them is not a witness line.
    ("Response to request arising during the hearing by: Hon. Patty Murray.......................................... 13,14 Hon. "
     "Jon Tester............................................ 22,27 Response to posthearing questions submitted by Hon. Jerry Moran",
     "Response to request arising during the hearing by: Hon. Patty Murray", "", ""),
    ("Charts.........................................49-51, 53, 54, 58-62 Letters: Several Governors........................................ "
     "38-47 Environmental Council of the States", "Charts", "", ""),
]


@pytest.mark.parametrize("line,name,position,organization", LEADER_LINES)
def test_dot_leaders_separate_items(line, name, position, organization):
    parsed = witness(line)
    assert (parsed["name"], parsed["position"], parsed["organization"]) == (name, position, organization)


@pytest.mark.parametrize("line,name", FOOTNOTE_TEXT_LINES)
def test_footnote_text_and_unmarked_labels_leave_the_name(line, name):
    assert witness(line)["name"] == name


@pytest.mark.parametrize("line,name,position,organization", [
    ("Mr. Nels Leader, Vice President, Bread Alone Bakery", "Nels Leader", "Vice President", "Bread Alone Bakery"),
    ("Richard J. Powell, Executive Director, ClearPath", "Richard J. Powell", "Executive Director", "ClearPath"),
    ("Campbell, Jr., J.H., President and CEO, Associated Grocers", "J.H. Campbell Jr.", "President and CEO", "Associated Grocers"),
    ("The Honorable Jay Bhattacharya, M.D., Ph.D.", "Jay Bhattacharya", "", ""),
    ("Lieutenant General Brian S. Eifler USA (Ret.)", "Brian S. Eifler", "", ""),
    ("Woodruff, Ph.D., MPH, Tracey", "Tracey Woodruff", "", ""),
    ("Campbell, Jr.", "Campbell Jr.", "", ""),
    # GPO's contents labels carry footnote markers (\1\) that run into the next name (CHRG-113hhrg..., red-f3):
    ("Prepared statement \\1\\ George Apostolakis, Commissioner, Nuclear Regulatory Commission",
     "George Apostolakis", "Commissioner", "Nuclear Regulatory Commission"),
    ("Supplement to prepared statement \\1\\ Mel Coleman, Chief Executive Officer, Northern Arkansas Electric Cooperative",
     "Mel Coleman", "Chief Executive Officer", "Northern Arkansas Electric Cooperative"),
    ("Prepared statement\\1\\ Answers to submitted questions\\2\\ John Bozzella, President and CEO, Alliance for Automotive Innovation",
     "John Bozzella", "President and CEO", "Alliance for Automotive Innovation"),
    ("Prepared statement \\2\\ William M. Lear, Jr., Vice Chairman, The Jockey Club", "William M. Lear Jr.", "Vice Chairman", "The Jockey Club"),
    ("Answers to submitted questions \\1\\ Rochelle P. Walensky", "Rochelle P. Walensky", "", ""),
    # A marker after a name or position is a footnote on it, not part of it.
    ("Matthew F. Wood\\1\\, Vice President of Policy, Free Press", "Matthew F. Wood", "Vice President of Policy", "Free Press"),
    # A contents line's dot leader and page number end the label.
    ("Prepared Statement........................................... 22' Mr. Shane L. Liermann, Assistant National Legislative Director",
     "Shane L. Liermann", "Assistant National Legislative Director", ""),
    ("Prepared statement of.................................... 126- Scott-Chandler, Sharon, JD, Policy Director",
     "Sharon Scott-Chandler", "Policy Director", ""),
    ("Answers to submitted questions \\1\\........................... Greg Abbott", "Greg Abbott", "", ""),
    ("Answer to submitted questions \\1\\ Jolina Cuaresma, Senior Counsel, Common Sense Media", "Jolina Cuaresma", "Senior Counsel", "Common Sense Media"),
    ("Additional information for the record \\1\\ Vednita Carter, Founder and Executive Director, Breaking Free",
     "Vednita Carter", "Founder and Executive Director", "Breaking Free"),
    ("Prepared Statement......................................60<greek-l> Mr. Daniel R. Levine, Legal Correspondent, Thomson Reuters",
     "Daniel R. Levine", "Legal Correspondent", "Thomson Reuters"),
    ("Prepared Statement..........................................00 deg. Ms. Jodi M. Schebel, Co-Managing Partner, Bowman and Brooke",
     "Jodi M. Schebel", "Co-Managing Partner", "Bowman and Brooke"),
    ("Hon. Deb Fischer, a United States Senator from the State of Nebraska \\1\\.......................... Prepared statement",
     "Deb Fischer", "a United States Senator from the State of Nebraska", ""),
])
def test_witness(line, name, position, organization):
    parsed = witness(line)
    assert (parsed["name"], parsed["position"], parsed["organization"]) == (name, position, organization)


@pytest.mark.parametrize("line", ["State Director", "Printed Hearing Record", "Security Officer and Security Services Administrator", "Panel 1"])
def test_non_names(line):
    assert not is_name(line)


def test_bom_and_committee_aliases():
    assert parse_xml(b'\xef\xbb\xbf<?xml version="1.0"?><committee-meeting/>').tag == "committee-meeting"
    assert codes_of({"committees": [{"systemCode": "hlvc00"}, {"systemCode": "hsgo12"}, {"systemCode": "jjec00"}]}) == ["hsgo00", "jsec00"]


def test_http_retries_and_paces_house(monkeypatch):
    import requests
    from congress_api.transport import http
    at, calls = [0.0], []
    monkeypatch.setattr(http.time, "monotonic", lambda: at[0])
    monkeypatch.setattr(http.time, "sleep", lambda seconds: at.__setitem__(0, at[0] + seconds))
    monkeypatch.setattr(http, "_next", __import__("collections").defaultdict(float))
    statuses = iter([403, 200, 200])
    class Session:
        def request(self, *args, **kwargs):
            calls.append(at[0])
            r = requests.Response()
            r.status_code = next(statuses)
            return r
    session = Session()
    http.get_with_retry(session, "https://docs.house.gov/first")
    http.get_with_retry(session, "https://docs.house.gov/second")
    assert calls == [0, 60, 61.2]


def test_transient_failure_is_not_absence(monkeypatch):
    import requests
    from congress_api.transport import http
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    class Session:
        def request(self, *args, **kwargs):
            raise requests.ConnectionError("sensitive query string")
    with pytest.raises(RuntimeError, match="request error") as error:
        http.get_with_retry(Session(), "https://example.org/item?api_key=secret", allowed=(200, 404))
    assert "secret" not in str(error.value)


def test_http_same_host_requests_overlap_and_keep_start_spacing(monkeypatch):
    import time
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import requests
    from congress_api.transport import http

    monkeypatch.setattr(http, "_next", defaultdict(float))
    first_started, second_started = Event(), Event()
    starts = []

    class Session:
        def request(self, method, url, **kwargs):
            starts.append(time.monotonic())
            if url.endswith('/first'):
                first_started.set()
                assert second_started.wait(3), 'First response blocked the second request'
            else:
                second_started.set()
            response = requests.Response()
            response.status_code = 200
            return response

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(http.get_with_retry, Session(), 'https://parallel.test/first')
        assert first_started.wait(3)
        second = pool.submit(http.get_with_retry, Session(), 'https://parallel.test/second')
        assert first.result(timeout=4).status_code == 200
        assert second.result(timeout=4).status_code == 200
    assert starts[1] - starts[0] >= .19
