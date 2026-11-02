import pytest
from congress_api.matching.committees import codes_of
from congress_api.parsers.witness_names import is_name, witness
from congress_api.parsers.xml import parse_xml


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
