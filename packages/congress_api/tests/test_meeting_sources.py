"""gpo-match and congress-committees read meetings from the archive release and refuse without it (ct-0mqc)."""
import hashlib
import io
import json
import sys
from datetime import date, datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from congress_api.acquisition.public_release import release_meetings
from congress_api.cli import committees as committees_cli
from congress_api.cli import gpo_match
from congress_api.matching.meetings import scheduled_or_rescheduled
from congress_api.retention.meetings import all_meetings

MEETING = dict(
    event_id=118000, congress=119, title='Oversight of the Federal Reserve', meeting_date=date(2025, 3, 4),
    status='Scheduled', congress_gov_updated=datetime(2025, 3, 5, 1, tzinfo=timezone.utc),
    committees=[dict(system_code='hsba00', role='host'), dict(system_code='hsba20', role='subcommittee')],
    videos=[dict(name='Hearing', url='https://www.youtube.com/watch?v=abcdefghijk', video_key='youtube:abcdefghijk'),
            dict(name='Senate', url='https://www.senate.gov/isvp/?comm=banking&filename=banking030425', video_key=None)])
CANCELED = dict(MEETING, event_id=118001, congress=118, status='Canceled')
COMMITTEES = [
    dict(system_code='hsba00', name='Financial Services Committee', names=[]),
    dict(system_code='hsba20', name='Financial Institutions Subcommittee', names=[
        dict(name='House Subcommittee on Financial Institutions', start=date(2025, 1, 3), end=None),
        dict(name='House Subcommittee on Monetary Policy', start=date(2013, 1, 3), end=date(2025, 1, 3))])]
MEETING_TYPE = pa.schema([
    ('event_id', pa.int64()), ('congress', pa.int16()), ('title', pa.string()), ('meeting_date', pa.date32()),
    ('status', pa.string()), ('congress_gov_updated', pa.timestamp('us', tz='UTC')),
    ('committees', pa.list_(pa.struct([('system_code', pa.string()), ('role', pa.string())]))),
    ('videos', pa.list_(pa.struct([('name', pa.string()), ('url', pa.string()), ('video_key', pa.string())])))])
COMMITTEE_TYPE = pa.schema([
    ('system_code', pa.string()), ('name', pa.string()),
    ('names', pa.list_(pa.struct([('name', pa.string()), ('start', pa.date32()), ('end', pa.date32())])))])


def release(root, meetings=(MEETING, CANCELED)):
    """A local release directory whose manifest identity is computed as the publisher does."""
    root.mkdir()
    pq.write_table(pa.Table.from_pylist(list(meetings), schema=MEETING_TYPE), root / 'meetings.parquet')
    pq.write_table(pa.Table.from_pylist(COMMITTEES, schema=COMMITTEE_TYPE), root / 'committees.parquet')
    files = []
    for name, rows in (('meetings.parquet', len(meetings)), ('committees.parquet', len(COMMITTEES))):
        body = (root / name).read_bytes()
        files.append(dict(name=name, sha256=hashlib.sha256(body).hexdigest(), size=len(body), rows=rows))
    release_id = hashlib.sha256(json.dumps([1, [[row[k] for k in ('name', 'sha256', 'size', 'rows')] for row in files]],
                                           ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(dict(schema_version=1, release_id=release_id, files=files)))
    return root


def test_gpo_match_refuses_a_missing_meeting_source(tmp_path):
    # Was a warning that returned no meetings and silently dropped all Congress.gov evidence.
    with pytest.raises(ValueError, match='No usable meetings source'):
        gpo_match.load_meetings(tmp_path / 'absent', work=tmp_path / 'work')


def test_gpo_match_command_exits_non_zero_without_a_release(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gpo_match, 'main', lambda *args, **kwargs: pytest.fail('matched without meetings'))
    monkeypatch.setattr(gpo_match, 'configure_logging', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['gpo-match', '--release', str(tmp_path / 'absent')])
    with pytest.raises(SystemExit) as stopped:
        gpo_match.parse_args_and_run()
    assert stopped.value.code == 2
    assert 'gpo-match: No usable meetings source' in capsys.readouterr().err


def test_committees_command_exits_non_zero_without_a_release(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(committees_cli, 'collect', lambda *args, **kwargs: pytest.fail('refreshed without meetings'))
    monkeypatch.setattr(committees_cli, 'load_congress_api_key', lambda: 'key')
    monkeypatch.setattr(sys, 'argv', ['congress-committees', '--release', str(tmp_path / 'absent'),
                                      '--output-path', str(tmp_path / 'out.jsonl.gz')])
    with pytest.raises(SystemExit) as stopped:
        committees_cli.main()
    assert stopped.value.code == 2
    assert 'congress-committees: No usable meetings source' in capsys.readouterr().err


def test_release_refuses_altered_bytes_and_an_empty_scope(tmp_path):
    root = release(tmp_path / 'altered')
    pq.write_table(pa.Table.from_pylist([CANCELED], schema=MEETING_TYPE), root / 'meetings.parquet')
    with pytest.raises(ValueError, match='identity or size differs'):
        release_meetings(root, work=tmp_path / 'w1', scope=all_meetings)
    with pytest.raises(ValueError, match='no meetings in scope'):
        release_meetings(release(tmp_path / 'canceled', [CANCELED]), work=tmp_path / 'w2', scope=scheduled_or_rescheduled)


def test_release_meetings_give_gpo_match_its_evidence(tmp_path):
    loaded = gpo_match.load_meetings(release(tmp_path / 'release'), work=tmp_path / 'work')
    assert {code: dict(days) for code, days in loaded.items()} == {'hsba00': {'2025-03-04': [{
        'eventId': '118000', 'title': 'Oversight of the Federal Reserve',
        'words': gpo_match.words('Oversight of the Federal Reserve'),
        # the subcommittee's name in force on the meeting date
        'subcommittees': ['House Subcommittee on Financial Institutions'],
        'videos': ['abcdefghijk'],
        'offsite': ['https://www.senate.gov/isvp/?comm=banking&filename=banking030425']}]}}


def test_committees_take_every_release_congress(tmp_path):
    rows = release_meetings(release(tmp_path / 'release'), work=tmp_path / 'work', scope=all_meetings)
    assert sorted(row['congress'] for row in rows) == [118, 119]


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.status_code = 200

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        return iter(lambda: self.read(chunk_size), b'')

    def __exit__(self, *exc):
        self.close()


class PublicSession:
    """Serves one release at https://public.fixture/viewer-publications/."""

    def __init__(self, root):
        self.root = root
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if url.endswith('/viewer-publications/manifest.json'):
            release_id = json.loads((self.root / 'manifest.json').read_text())['release_id']
            return Response(json.dumps(dict(release_id=release_id)).encode())
        return Response((self.root / url.rsplit('/', 1)[1]).read_bytes())


def test_public_pointer_selects_the_release_and_verifies_its_files(tmp_path, monkeypatch):
    from congress_api.acquisition import public_release
    session = PublicSession(release(tmp_path / 'release'))
    real_open = public_release.open_release
    monkeypatch.setattr(public_release, 'open_release', lambda **kwargs: real_open(**kwargs, session=session))
    rows = release_meetings('https://public.fixture/viewer-publications/manifest.json', work=tmp_path / 'work',
                            scope=scheduled_or_rescheduled)
    assert [row['eventId'] for row in rows] == ['118000']
    assert [url.rsplit('/', 1)[1] for url in session.urls] == [
        'manifest.json', 'manifest.json', 'meetings.parquet', 'committees.parquet']
