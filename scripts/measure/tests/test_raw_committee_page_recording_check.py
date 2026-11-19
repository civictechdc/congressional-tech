"""Tests for scripts/measure/raw_committee_page_recording_check.py (ct-414r).

Verifies independent two-directional raw checking, DOM chrome/nav separation, explicit
raw_inconclusive reporting, basis-specific Direction B, unread page naming, and planted fault detection.
"""
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location(
    'raw_committee_page_recording_check',
    ROOT / 'scripts/measure/raw_committee_page_recording_check.py',
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def _store_body(mirror: Path, text: str) -> str:
    raw = text.encode('utf-8')
    digest = sha256(raw).hexdigest()
    path = mirror / 'bodies' / 'sha256' / digest[:2] / f'{digest}.gz'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw))
    return digest


def _fixture(tmp_path: Path):
    mirror = tmp_path / 'mirror'
    rel = tmp_path / 'release'
    rel.mkdir()

    # Clean true match: generic video title "Full Committee Business Meeting", raw HTML cites EventID=114799 and embeds vid114799AA in editorial main.
    good_html = (
        '<html><head><title>Business Meeting | House Agriculture Committee</title></head>'
        '<body><main><h1>Business Meeting</h1>'
        '<a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=114799">Repository</a>'
        '<iframe src="https://www.youtube.com/embed/vid114799AA"></iframe>'
        '</main></body></html>'
    )
    good_sha = _store_body(mirror, good_html)

    meetings = [
        dict(event_id=114799, chamber='house', meeting_date='2022-05-17', meeting_type='HMKP',
             title='Markup of H.R. 7764, Agricultural Supply Chain Act', subject_keys=['117-hr-7764']),
        dict(event_id=117496, chamber='house', meeting_date='2024-07-09', meeting_type='Hearing',
             title='An Examination of the California Air Resources Board In Use Locomotive Regulation', subject_keys=[]),
        dict(event_id=115134, chamber='house', meeting_date='2022-09-21', meeting_type='Hearing',
             title='Looking Back to Predict the Future: The Next Generation of Weather Satellites', subject_keys=[]),
        dict(event_id=115115, chamber='house', meeting_date='2022-09-15', meeting_type='Hearing',
             title='The Fountain of Youth? The Quest for Aging Therapies', subject_keys=[]),
        dict(event_id=101669, chamber='house', meeting_date='2014-01-14', meeting_type='HHRG',
             title='Oversight of Sequestration and Secure Rural Schools Program', subject_keys=[]),
        dict(event_id=106253, chamber='house', meeting_date='2017-07-12', meeting_type='Hearing',
             title='Examining Legislative Proposals to Provide Targeted Regulatory Relief to Community Financial Institutions', subject_keys=[]),
        dict(event_id=108476, chamber='house', meeting_date='2018-06-20', meeting_type='Hearing',
             title='Illicit Use of Virtual Currency and the Law Enforcement Response', subject_keys=[]),
    ]
    videos = [
        dict(video_key='youtube:vid114799AA', title='Full Committee Business Meeting',
             source_description='', stated_event_ids=[], published_at='2022-05-17T15:00:00Z', video_published_at='2022-05-17T15:00:00Z'),
        dict(video_key='youtube:PYk8qVbLMfA', title='Round Table on Reinvigorating the U.S.-Flag Fleet and Shipbuilding Industry',
             source_description='', stated_event_ids=[], published_at='2024-07-09T15:00:00Z', video_published_at='2024-07-09T15:00:00Z'),
        dict(video_key='youtube:Sm5K7WqgsDQ', title='The Fountain of Youth? The Quest for Aging Therapies (EventID=115115)',
             source_description='', stated_event_ids=[115115], published_at='2022-09-15T15:00:00Z', video_published_at='2022-09-15T15:00:00Z'),
        dict(video_key='youtube:B6weq9zOVQM', title='11.30.16. FL. 10:00 AM.',
             source_description='', stated_event_ids=[], published_at='2016-11-30T15:00:00Z', video_published_at='2016-11-30T15:00:00Z'),
        dict(video_key='youtube:88nwbpiPKa0', title='Chairman Bishop opening statement HR 4680',
             source_description='', stated_event_ids=[], published_at='2016-05-18T15:00:00Z', video_published_at='2016-05-18T15:00:00Z'),
        dict(video_key='youtube:uy_DOU-Ldk4', title='Waters Warns of Economic Harm from Trump Policies, Commends Fed Chair - 07/12 2017',
             source_description='', stated_event_ids=[], published_at='2017-07-12T15:00:00Z', video_published_at='2017-07-12T15:00:00Z'),
        dict(video_key='youtube:IuvhLo3dz2U', title='Waters: GOP Tax Scam is a Giveaway to Wall Street at the Expense of Hardworking Americans',
             source_description='', stated_event_ids=[], published_at='2018-06-20T15:00:00Z', video_published_at='2018-06-20T15:00:00Z'),
        dict(video_key='youtube:genInconc01', title='Full Committee Hearing',
             source_description='', stated_event_ids=[], published_at='2022-09-21T15:00:00Z', video_published_at='2022-09-21T15:00:00Z'),
    ]
    matches = [
        dict(match_id='m_good', event_id=114799, video_key='youtube:vid114799AA', basis='committee_page',
             status='asserted', note='house_title_words: 7764, agricultural', source_ref=f'committee_page:{good_sha}'),
    ]
    return mirror, rel, meetings, videos, matches, good_sha


def _run(tmp_path, mirror, rel, meetings, videos, matches, *, raw_pages=None, require_provenance=True):
    (rel / 'meetings.json').write_text(json.dumps(meetings))
    (rel / 'videos.json').write_text(json.dumps(videos))
    (rel / 'recording_matches.json').write_text(json.dumps(matches))
    argv = ['--release', str(rel), '--mirror', str(mirror), '--output', str(tmp_path / 'out.json')]
    if raw_pages is not None:
        argv += ['--raw-pages', str(raw_pages)]
    if require_provenance:
        argv.append('--require-provenance')
    return check.main(argv)


def test_clean_generic_title_match_and_congress_json_pass_both_directions(tmp_path):
    mirror, rel, meetings, videos, matches, _ = _fixture(tmp_path)
    json_sha = _store_body(
        mirror,
        json.dumps({'committeeMeeting': {
            'eventId': '115134',
            'title': 'Looking Back to Predict the Future: The Next Generation of Weather Satellites',
            'videos': [{'url': 'https://www.youtube.com/watch?v=genInconc01'}],
        }}),
    )
    matches.append(dict(
        match_id='m_json', event_id=115134, video_key='youtube:genInconc01', basis='committee_page',
        status='asserted', note='page_named_meeting', source_ref=f'committee_page:{json_sha}',
    ))
    report = _run(tmp_path, mirror, rel, meetings, videos, matches)
    assert report['committee_page_rows'] == 2
    assert report['raw_pages_read'] == 2
    assert report['raw_pages_unread'] == 0
    assert report['verdicts'] == {'raw_supports': 2}
    assert report['contradiction_counts'] == {}
    assert report['direction_b'] == {
        'basis_checked': 'committee_page',
        'explicit_raw_pairs_checked': 2,
        'missing_from_published_count': 0,
        'missing_from_published': [],
    }


def test_planted_nav_bar_footer_carousel_and_ordinal_href_faults_are_flagged(tmp_path):
    """Reproduces the three Review #3 failures (106253, 108476, 101669) plus ordinal congress.gov href & roundtable plants."""
    mirror, rel, meetings, videos, matches, _ = _fixture(tmp_path)

    # Plant 1 (106253): Nav menu contains 'Financial Institutions' while editorial body is about Janet Yellen & monetary policy.
    nav_106253_sha = _store_body(
        mirror,
        '<html><head><title>At Yellen Hearing, Waters Warns of Economic Harm | U.S. House Committee on Financial Services Democrats</title></head>'
        '<body><nav><ul><li>Financial Institutions and Consumer Credit</li><li>Regulatory Relief</li></ul></nav>'
        '<main><div class="bodycopy"><p>Today at the semiannual Humphrey-Hawkins hearing on monetary policy with Chair Janet Yellen.</p>'
        '<iframe src="https://www.youtube.com/embed/uy_DOU-Ldk4"></iframe></div></main></body></html>',
    )
    # Plant 2 (108476): Nav menu contains 'Terrorism and Illicit Finance' while editorial body is about GOP Tax Scam (H.R. 1).
    nav_108476_sha = _store_body(
        mirror,
        '<html><head><title>Waters: GOP Tax Scam is a Giveaway to Wall Street | U.S. House Committee on Financial Services Democrats</title></head>'
        '<body><nav><ul><li>Terrorism and Illicit Finance</li><li>Laws</li></ul></nav>'
        '<main><div class="bodycopy"><p>Today at a hearing on the Republican tax scam legislation, H.R. 1.</p>'
        '<iframe src="https://www.youtube.com/embed/IuvhLo3dz2U"></iframe></div></main></body></html>',
    )
    # Plant 3 (101669/88nwbpiPKa0): Page is genuinely about SRS sequestration, but video is ONLY in footer carousel and names HR 4680.
    footer_101669_sha = _store_body(
        mirror,
        '<html><head><title>Obama Admin Sequestration of Secure Rural Schools - House Committee on Natural Resources</title></head>'
        '<body><main><p>Oversight of sequestration and the Secure Rural Schools program.</p>'
        '<section class="videos intfooter"><ul class="video-list"><li>'
        '<a href="https://www.youtube.com/watch?v=88nwbpiPKa0">HR 4680</a>'
        '</li></ul></section></main></body></html>',
    )
    # Plant 4: Labelled anchor pointing to ordinal zero-padded congress.gov/event/119th-congress/house-event/0115115.
    ordinal_href_sha = _store_body(
        mirror,
        '<html><head><title>Weather Satellites Hearing</title></head>'
        '<body><main><a href="https://www.congress.gov/event/119th-congress/house-event/0115115">Repository</a>'
        '<iframe src="https://www.youtube.com/embed/Sm5K7WqgsDQ"></iframe></main></body></html>',
    )
    # Plant 5: Roundtable variant ('Round Table') on hearing 117496.
    rt_sha = _store_body(
        mirror,
        '<html><head><title>Round-Table on Reinvigorating the U.S.-Flag Fleet</title></head>'
        '<body><main><iframe src="https://www.youtube.com/embed/PYk8qVbLMfA"></iframe></main></body></html>',
    )
    # Plant 6: 2016 video date on 2014 hearing, whose raw HTML does not embed the video ID.
    date_sha = _store_body(
        mirror,
        '<html><head><title>SRS Sequestration Hearing</title></head><body><main><p>No embed here</p></main></body></html>',
    )
    # Plant 7: Unread body SHA (not stored in mirror).
    missing_sha = 'ab' * 32

    matches.extend([
        dict(match_id='m_106253', event_id=106253, video_key='youtube:uy_DOU-Ldk4', basis='committee_page',
             status='asserted', note='house_text_head_weak: financial, institutions', source_ref=f'committee_page:{nav_106253_sha}'),
        dict(match_id='m_108476', event_id=108476, video_key='youtube:IuvhLo3dz2U', basis='committee_page',
             status='asserted', note='house_text_head_weak: illicit, law', source_ref=f'committee_page:{nav_108476_sha}'),
        dict(match_id='m_101669', event_id=101669, video_key='youtube:88nwbpiPKa0', basis='committee_page',
             status='asserted', note='house_title_words: obama, sequestration', source_ref=f'committee_page:{footer_101669_sha}'),
        dict(match_id='m_ord', event_id=115134, video_key='youtube:Sm5K7WqgsDQ', basis='committee_page',
             status='asserted', note=None, source_ref=f'committee_page:{ordinal_href_sha}'),
        dict(match_id='m_rt', event_id=117496, video_key='youtube:PYk8qVbLMfA', basis='committee_page',
             status='asserted', note='house_text_head_weak: board', source_ref=f'committee_page:{rt_sha}'),
        dict(match_id='m_date', event_id=101669, video_key='youtube:B6weq9zOVQM', basis='committee_page',
             status='asserted', note='house_title_words: obama, sequestration', source_ref=f'committee_page:{date_sha}'),
        dict(match_id='m_unread', event_id=114799, video_key='youtube:vid114799AA', basis='committee_page',
             status='asserted', note='house_title_words: 7764', source_ref=f'committee_page:{missing_sha}'),
    ])

    report = _run(tmp_path, mirror, rel, meetings, videos, matches)
    rv = report['_row_verdicts']
    assert rv['106253/youtube:uy_DOU-Ldk4']['verdict'] == 'raw_contradicts'
    assert 'editorial_body_topic_contradiction' in rv['106253/youtube:uy_DOU-Ldk4']['flags']
    assert rv['108476/youtube:IuvhLo3dz2U']['verdict'] == 'raw_contradicts'
    assert 'editorial_body_topic_contradiction' in rv['108476/youtube:IuvhLo3dz2U']['flags']
    assert rv['101669/youtube:88nwbpiPKa0']['verdict'] == 'raw_contradicts'
    assert 'chrome_only_video_embed' in rv['101669/youtube:88nwbpiPKa0']['flags']
    assert 'video_bill_contradiction' in rv['101669/youtube:88nwbpiPKa0']['flags']
    assert rv['115134/youtube:Sm5K7WqgsDQ']['verdict'] == 'raw_contradicts'
    assert 'raw_body_event_link_conflict' in rv['115134/youtube:Sm5K7WqgsDQ']['flags']
    assert 'conflicting_video_stated_event_id' in rv['115134/youtube:Sm5K7WqgsDQ']['flags']
    assert 'missing_provenance_note' in rv['115134/youtube:Sm5K7WqgsDQ']['flags']
    assert rv['117496/youtube:PYk8qVbLMfA']['verdict'] == 'raw_contradicts'
    assert 'proceeding_genre_conflict' in rv['117496/youtube:PYk8qVbLMfA']['flags']
    assert rv['101669/youtube:B6weq9zOVQM']['verdict'] == 'raw_contradicts'
    assert 'video_date_contradiction' in rv['101669/youtube:B6weq9zOVQM']['flags']
    assert 'video_not_in_raw_body' in rv['101669/youtube:B6weq9zOVQM']['flags']

    assert report['raw_pages_unread'] == 1
    assert report['unread_pages'] == [missing_sha]
    assert report['verdicts'] == {
        'raw_contradicts': 6,
        'raw_supports': 1,
        'unread_body_no_metadata_contradiction': 1,
    }


def test_uncorroborated_generic_read_reports_raw_inconclusive_never_raw_supports(tmp_path):
    """A read page with no contradiction and no affirmative corroboration must be reported raw_inconclusive."""
    mirror, rel, meetings, videos, matches, _ = _fixture(tmp_path)
    generic_sha = _store_body(
        mirror,
        '<html><head><title>Full Committee Hearing | House Science Committee</title></head>'
        '<body><main><h1>Full Committee Hearing</h1>'
        '<iframe src="https://www.youtube.com/embed/genInconc01"></iframe></main></body></html>',
    )
    matches = [dict(
        match_id='m_gen', event_id=115134, video_key='youtube:genInconc01', basis='committee_page',
        status='asserted', note='house_single_day_generic', source_ref=f'committee_page:{generic_sha}',
    )]
    report = _run(tmp_path, mirror, rel, meetings, videos, matches)
    assert report['contradiction_counts'] == {}
    assert report['verdicts'] == {'raw_inconclusive': 1}


def test_direction_b_flags_missing_committee_page_even_when_other_basis_exists(tmp_path):
    """Direction B checks basis='committee_page' specifically: video_states_event_id cannot hide a missing committee_page row."""
    mirror, rel, meetings, videos, matches, _ = _fixture(tmp_path)
    raw_dir = tmp_path / 'raw_pages'
    raw_dir.mkdir()
    (raw_dir / 'explicit_115115.html').write_text(
        '<html><head><title>The Fountain of Youth?</title></head>'
        '<body><main><a href="https://www.congress.gov/event/117th-congress/house-event/115115">Event</a>'
        '<iframe src="https://www.youtube.com/embed/Sm5K7WqgsDQ"></iframe></main></body></html>'
    )
    # Present under video_states_event_id ONLY (no committee_page row): Direction B must STILL flag it!
    matches.append(dict(
        match_id='m_other_basis', event_id=115115, video_key='youtube:Sm5K7WqgsDQ',
        basis='video_states_event_id', status='claimed', note=None, source_ref='video_records:' + '11' * 32,
    ))
    report = _run(tmp_path, mirror, rel, meetings, videos, matches, raw_pages=raw_dir)
    assert report['direction_b']['basis_checked'] == 'committee_page'
    assert report['direction_b']['explicit_raw_pairs_checked'] == 1
    assert report['direction_b']['missing_from_published_count'] == 1
    assert report['direction_b']['missing_from_published'][0]['event_id'] == 115115
    assert report['direction_b']['missing_from_published'][0]['video_key'] == 'youtube:Sm5K7WqgsDQ'
