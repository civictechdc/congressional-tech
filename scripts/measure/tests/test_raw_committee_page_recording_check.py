"""Tests for scripts/measure/raw_committee_page_recording_check.py (ct-414r).

Verifies independent two-directional raw checking, unread page reporting, and planted fault detection.
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


def _store_html(mirror: Path, html_text: str) -> str:
    raw = html_text.encode('utf-8')
    digest = sha256(raw).hexdigest()
    path = mirror / 'bodies' / 'sha256' / digest[:2] / f'{digest}.gz'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw))
    return digest


def _fixture(tmp_path: Path):
    mirror = tmp_path / 'mirror'
    rel = tmp_path / 'release'
    rel.mkdir()

    # Clean true match: generic video title "Full Committee Business Meeting", raw HTML cites EventID=114799 and embeds vid114799AA.
    good_html = (
        '<html><head><title>Business Meeting | House Agriculture Committee</title></head>'
        '<body><h1>Business Meeting</h1>'
        '<a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=114799">Repository</a>'
        '<iframe src="https://www.youtube.com/embed/vid114799AA"></iframe>'
        '</body></html>'
    )
    good_sha = _store_html(mirror, good_html)

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
    ]
    videos = [
        dict(video_key='youtube:vid114799AA', title='Full Committee Business Meeting',
             source_description='', stated_event_ids=[], published_at='2022-05-17T15:00:00Z', video_published_at='2022-05-17T15:00:00Z'),
        dict(video_key='youtube:PYk8qVbLMfA', title='Roundtable on Reinvigorating the U.S.-Flag Fleet and Shipbuilding Industry',
             source_description='', stated_event_ids=[], published_at='2024-07-09T15:00:00Z', video_published_at='2024-07-09T15:00:00Z'),
        dict(video_key='youtube:Sm5K7WqgsDQ', title='The Fountain of Youth? The Quest for Aging Therapies (EventID=115115)',
             source_description='', stated_event_ids=[115115], published_at='2022-09-15T15:00:00Z', video_published_at='2022-09-15T15:00:00Z'),
        dict(video_key='youtube:B6weq9zOVQM', title='11.30.16. FL. 10:00 AM.',
             source_description='', stated_event_ids=[], published_at='2016-11-30T15:00:00Z', video_published_at='2016-11-30T15:00:00Z'),
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


def test_clean_generic_title_match_passes_both_directions(tmp_path):
    mirror, rel, meetings, videos, matches, _ = _fixture(tmp_path)
    report = _run(tmp_path, mirror, rel, meetings, videos, matches)
    assert report['committee_page_rows'] == 1
    assert report['raw_pages_read'] == 1
    assert report['raw_pages_unread'] == 0
    assert report['verdicts'] == {'raw_supports': 1}
    assert report['contradiction_counts'] == {}
    assert report['direction_b'] == {
        'explicit_raw_pairs_checked': 1,
        'missing_from_published_count': 0,
        'missing_from_published': [],
    }


def test_planted_false_links_and_provenance_gaps_are_flagged(tmp_path):
    mirror, rel, meetings, videos, matches, _ = _fixture(tmp_path)

    # Plant 1: Roundtable video on hearing date (ct-414r trigger), with raw HTML citing that video.
    rt_sha = _store_html(
        mirror,
        '<html><head><title>Roundtable on Reinvigorating the U.S.-Flag Fleet</title></head>'
        '<body><iframe src="https://www.youtube.com/embed/PYk8qVbLMfA"></iframe></body></html>',
    )
    # Plant 2: Video stating conflicting event 115115 linked to 115134, with raw HTML citing 115115 and missing note.
    conf_sha = _store_html(
        mirror,
        '<html><head><title>The Fountain of Youth?</title></head>'
        '<body><a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=115115">Event</a>'
        '<iframe src="https://www.youtube.com/embed/Sm5K7WqgsDQ"></iframe></body></html>',
    )
    # Plant 3: 2016 video date on 2014 hearing, whose raw HTML does NOT even embed the video ID.
    date_sha = _store_html(
        mirror,
        '<html><head><title>SRS Sequestration Hearing</title></head><body><p>No embed here</p></body></html>',
    )
    # Plant 4: Unread body SHA (not stored in mirror).
    missing_sha = 'ab' * 32

    matches.extend([
        dict(match_id='m_rt', event_id=117496, video_key='youtube:PYk8qVbLMfA', basis='committee_page',
             status='asserted', note='house_text_head_weak: board', source_ref=f'committee_page:{rt_sha}'),
        dict(match_id='m_conf', event_id=115134, video_key='youtube:Sm5K7WqgsDQ', basis='committee_page',
             status='asserted', note=None, source_ref=f'committee_page:{conf_sha}'),
        dict(match_id='m_date', event_id=101669, video_key='youtube:B6weq9zOVQM', basis='committee_page',
             status='asserted', note='house_title_words: obama, sequestration', source_ref=f'committee_page:{date_sha}'),
        dict(match_id='m_unread', event_id=114799, video_key='youtube:vid114799AA', basis='committee_page',
             status='asserted', note='house_title_words: 7764', source_ref=f'committee_page:{missing_sha}'),
    ])

    report = _run(tmp_path, mirror, rel, meetings, videos, matches)
    assert report['contradiction_counts']['roundtable_kind_conflict'] == 1
    assert report['contradiction_counts']['conflicting_stated_event_id'] == 1
    assert report['contradiction_counts']['raw_html_event_link_conflict'] == 1
    assert report['contradiction_counts']['missing_provenance_note'] == 1
    assert report['contradiction_counts']['video_date_contradiction'] == 1
    assert report['contradiction_counts']['video_not_in_raw_html'] == 1
    assert report['raw_pages_unread'] == 1
    assert report['unread_pages'] == [missing_sha]
    assert report['verdicts']['raw_contradicts'] == 3
    assert report['verdicts']['raw_supports'] == 1
    assert report['verdicts']['unread_body_no_metadata_contradiction'] == 1


def test_direction_b_flags_dropped_explicit_raw_match(tmp_path):
    mirror, rel, meetings, videos, matches, _ = _fixture(tmp_path)
    raw_dir = tmp_path / 'raw_pages'
    raw_dir.mkdir()
    (raw_dir / 'explicit_115115.html').write_text(
        '<html><head><title>The Fountain of Youth?</title></head>'
        '<body><a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=115115">Hearing</a>'
        '<iframe src="https://www.youtube.com/embed/Sm5K7WqgsDQ"></iframe></body></html>'
    )
    # Omit (115115, youtube:Sm5K7WqgsDQ) from recording_matches: Direction B must flag it.
    report = _run(tmp_path, mirror, rel, meetings, videos, matches, raw_pages=raw_dir)
    assert report['direction_b']['explicit_raw_pairs_checked'] == 1
    assert report['direction_b']['missing_from_published_count'] == 1
    assert report['direction_b']['missing_from_published'][0]['event_id'] == 115115
    assert report['direction_b']['missing_from_published'][0]['video_key'] == 'youtube:Sm5K7WqgsDQ'
