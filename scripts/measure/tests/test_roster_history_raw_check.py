"""The historical roster raw check sees a wrong chair, a missing seat and an extra seat, in both directions."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('roster_history_raw_check', ROOT / 'scripts/measure/roster_history_raw_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

MEMBERDATA = """<?xml version="1.0"?><MemberData publish-date="November 1, 2022"><title-info><congress-num>117</congress-num>
</title-info><members>
<member><member-info><bioguideID>S001157</bioguideID></member-info><committee-assignments>
 <committee comcode="AG00" rank="1" leadership="Chairman"/><subcommittee subcomcode="AG14" rank="2"/></committee-assignments></member>
<member><member-info><bioguideID>T000467</bioguideID></member-info><committee-assignments>
 <committee comcode="AG00" rank="1"/></committee-assignments></member>
<member><member-info><bioguideID>P000610</bioguideID></member-info><committee-assignments>
 <committee comcode="AG00" rank="3"/><subcommittee subcomcode="AG14" rank="1" leadership="Chair"/></committee-assignments></member>
<member><member-info><bioguideID/></member-info></member>
</members></MemberData>"""
CVC = """<senators><lastUpdate><date>Tuesday, September 20, 2022</date></lastUpdate>
<senator><bioguideId>S000770</bioguideId><committees><committee code="SSAF00" position="Chairman">Agriculture</committee>
</committees></senator></senators>"""
YAML = """HSAG:
- {name: A, party: majority, rank: 1, title: Chair, bioguide: S001157}
- {name: B, party: minority, rank: 1, title: Ranking Member, bioguide: T000467}
HSAG14:
- {name: C, party: majority, rank: 1, title: Chair, bioguide: P000610}
JSEC:
- {name: D, party: majority, rank: 1, bioguide: B001248}
"""
SEATS = [
    {'congress': 117, 'system_code': 'hsag00', 'bioguide_id': 'S001157', 'title': 'Chair'},
    {'congress': 117, 'system_code': 'hsag00', 'bioguide_id': 'T000467', 'title': 'Ranking Member'},
    {'congress': 117, 'system_code': 'hsag00', 'bioguide_id': 'P000610', 'title': None},
    {'congress': 117, 'system_code': 'hsag14', 'bioguide_id': 'P000610', 'title': 'Chair'},
    {'congress': 117, 'system_code': 'hsag14', 'bioguide_id': 'S001157', 'title': None},
    {'congress': 117, 'system_code': 'ssaf00', 'bioguide_id': 'S000770', 'title': 'Chair'},
    {'congress': 119, 'system_code': 'hsag00', 'bioguide_id': 'X000001', 'title': 'Chair'},  # another Congress: not read
]


def run(tmp_path, seats, **sources):
    (tmp_path / 'seats.json').write_text(json.dumps(seats))
    paths = {'house_memberdata': ('MemberData.xml', MEMBERDATA), 'senate_cvc': ('cvc.xml', CVC),
             'legislators_yaml': ('membership.yaml', YAML)}
    argv = ['--seats', str(tmp_path / 'seats.json'), '--congress', '117', '--output', str(tmp_path / 'out.json')]
    for name in sources:
        filename, body = paths[name]
        (tmp_path / filename).write_text(body)
        argv += [f"--{name.replace('_', '-')}", str(tmp_path / filename)]
    return {r['publisher'].split()[0]: r for r in check.main(argv)['results']}


def test_agreeing_seats_pass_in_both_directions(tmp_path):
    results = run(tmp_path, SEATS, house_memberdata=True, senate_cvc=True)
    house, senate = results['House'], results['Senate']
    assert (house['committees_compared'], house['agreement'], house['chair_mismatches'], house['seat_differences']) == (2, 1.0, [], [])
    assert (senate['chairs_compared'], senate['chair_mismatches'], senate['seat_differences']) == (1, [], [])


def test_planted_wrong_chair_missing_and_extra_seats_are_flagged(tmp_path):
    planted = [dict(row) for row in SEATS]
    planted[0]['title'], planted[1]['title'] = 'Ranking Member', 'Chair'  # the chair moved to the wrong member
    planted = [row for row in planted if not (row['system_code'] == 'hsag14' and row['bioguide_id'] == 'S001157')]
    planted.append({'congress': 117, 'system_code': 'hsag14', 'bioguide_id': 'T000467', 'title': None})
    house = run(tmp_path, planted, house_memberdata=True)['House']
    assert house['chair_mismatches'] == [{'committee': 'h:ag00', 'under_test': 'T000467', 'independent': 'S001157'}]
    assert house['seat_differences'] == [{'committee': 'h:ag14', 'only_under_test': ['T000467'], 'only_independent': ['S001157']}]


def test_unseen_committees_are_listed_and_codes_compare_by_suffix(tmp_path):
    result = run(tmp_path, SEATS, legislators_yaml=True)['congress-legislators']
    assert result['committees_compared'] == 2 and result['chair_mismatches'] == []
    assert result['committees_only_independent'] == ['j:ec00']
    assert result['committees_only_under_test'] == ['s:af00']
    assert result['seat_differences'] == [
        {'committee': 'h:ag00', 'only_under_test': ['P000610'], 'only_independent': []},
        {'committee': 'h:ag14', 'only_under_test': ['S001157'], 'only_independent': []}]


def test_a_file_stating_another_congress_is_refused(tmp_path):
    (tmp_path / 'seats.json').write_text(json.dumps(SEATS))
    (tmp_path / 'm.xml').write_text(MEMBERDATA)
    try:
        check.main(['--seats', str(tmp_path / 'seats.json'), '--congress', '116', '--house-memberdata',
                    str(tmp_path / 'm.xml'), '--output', str(tmp_path / 'o.json')])
    except SystemExit as stop:
        assert 'states Congress 117' in str(stop)
    else:
        raise AssertionError('a Congress 117 file judged Congress 116 seats')
