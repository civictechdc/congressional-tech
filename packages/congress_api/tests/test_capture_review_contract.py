"""F2 review: durable bytes precede inspection; bounded discovery drains its queue."""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.acquisition.fetcher import Fetcher
from congress_api.models.raw_fetch import Transfer
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.retention.sniff import read_sniff_file, SniffReadError, SniffResourceError
from test_capture_scheduler import release, run_fixture
from test_receipt_writer_contract import WRITER


URL = 'https://fixture.test/source'
PDF = b'%PDF-1.7\nreader unavailable after completed transfer\n'


class Adapter:
    def __init__(self, data):
        self.data, self.paths, self.calls = data, [], []

    def hop(self, url, destination, **options):
        self.calls.append(url)
        self.paths.append(destination)
        destination.write_bytes(self.data)
        return Transfer(destination, url, 200, {}, True,
                        sha256=hashlib.sha256(self.data).hexdigest(), size=len(self.data))


def fetch(adapter, directory, *, provider=None):
    return Fetcher(scope=lambda url: url == URL, direct=adapter, provider=provider,
        pace=lambda *_: None, directory=directory, spool_limit=10000).fetch(URL)


@contextmanager
def inspection_reads(adapter, inspect):
    """Observe or fail only the maintained inspector's source open, without patching it."""
    active = [True]
    def audit(event, args):
        if not active[0] or event != 'open' or not isinstance(args[0], (str, bytes)):
            return
        if Path(os.fsdecode(args[0])) not in adapter.paths:
            return
        frame = sys._getframe()
        while frame is not None:
            if frame.f_code is read_sniff_file.__code__:
                inspect(Path(os.fsdecode(args[0])))
                return
            frame = frame.f_back
    sys.addaudithook(audit)
    try:
        yield
    finally:
        active[0] = False


def body_key(data):
    digest = hashlib.sha256(data).hexdigest()
    return f'bodies/sha256/{digest[:2]}/{digest}'


def writer(root, *, adapter=None, archive_limits=None):
    return ReceiptWriter(BodyStore(adapter or LocalAdapter(root)), identity=WRITER,
        run_id='durable-before-inspection', write_date='2026-10-27', archive_limits=archive_limits)


def test_fetcher_returns_transfer_facts_without_inspection(tmp_path):
    result = fetch(Adapter(b'<html><p>source</p></html>'), tmp_path/'spool')
    body = result.final.body
    assert result.final.complete and result.final.error is None
    assert body.path.read_bytes() == b'<html><p>source</p></html>'
    assert (body.sniffed_format, body.sniff_version, body.intact, body.sniff_error) == (None,)*4


@pytest.mark.parametrize('failure', [SniffReadError('private path must not be recorded'),
                                   SniffResourceError('PdfToolError')])
def test_inspection_failure_retains_exact_body_receipt_and_transfer_facts(tmp_path, failure):
    adapter, provider = Adapter(PDF), Adapter(b'provider must stay unused')
    root = tmp_path/'raw'
    observed = []
    def unavailable(path):
        assert (root/body_key(PDF)).read_bytes() == PDF
        observed.append(path)
        raise failure
    with TemporaryDirectory(dir=tmp_path) as spool, inspection_reads(adapter, unavailable):
        result = fetch(adapter, spool, provider=provider)
        key, line = writer(root).write(result, family='documents')
    [capture] = line['captures']
    assert observed and all(not path.exists() for path in adapter.paths)
    assert adapter.calls == [URL] and provider.calls == []
    assert (root/body_key(PDF)).read_bytes() == PDF
    assert json.loads(gzip.decompress((root/key).read_bytes())) == line
    assert capture['sha256'] == hashlib.sha256(PDF).hexdigest() and capture['bytes'] == len(PDF)
    assert capture['complete'] is True and line['http_status'] == 200 and line['outcome'] == 'stored'
    assert (capture['sniffed_format'], capture['sniff_version'], capture['intact']) == (None,)*3
    assert capture['sniff_error'] == ('PdfToolError' if isinstance(failure, SniffResourceError) else 'SniffReadError')
    assert 'private path' not in json.dumps(line) and 'error_type' not in line
    assert result.final.body.sniffed_format is None


def test_html_is_inspected_after_storage_and_receipt_keeps_the_reading(tmp_path):
    data = b'<html><p>durable original</p></html>'
    adapter, root, observed = Adapter(data), tmp_path/'raw', []
    def after_storage(path):
        assert (root/body_key(data)).read_bytes() == data
        observed.append(path)
    with inspection_reads(adapter, after_storage):
        result = fetch(adapter, tmp_path/'spool')
        _, line = writer(root).write(result, family='documents')
    [capture] = line['captures']
    assert observed and capture['sniffed_format'] == 'html' and capture['sniff_version']
    assert capture['intact'] is None and result.final.body.sniffed_format is None


def test_body_store_failure_prevents_inspection_and_receipt(tmp_path):
    adapter, root = Adapter(b'<html>not stored</html>'), tmp_path/'raw'
    class Broken(LocalAdapter):
        def create(self, *args, **kwargs):
            raise OSError('store_failed')
    def unexpected(path):
        raise AssertionError('Inspection ran before successful storage')
    with inspection_reads(adapter, unexpected):
        result = fetch(adapter, tmp_path/'spool')
        with pytest.raises(OSError, match='store_failed'):
            writer(root, adapter=Broken(root)).write(result, family='documents')
    assert not list(root.rglob('*.jsonl.gz'))


def test_missing_capture_inspection_stays_on_the_existing_sniff_work_list(tmp_path):
    from congress_api.lake import readings
    from test_lake_readings import setup
    adapter, root = Adapter(PDF), tmp_path/'raw'
    def unavailable(path):
        assert (root/body_key(PDF)).is_file()
        raise SniffResourceError('PdfToolError')
    with TemporaryDirectory(dir=tmp_path) as spool, inspection_reads(adapter, unavailable):
        _, line = writer(root).write(fetch(adapter, spool), family='documents')
    fixture = tmp_path/'d2'; fixture.mkdir()
    args, digest = setup(fixture, body=PDF, copies=1, body_format=None)
    captures = pq.read_table(args['captures'])
    for name in ('sniffed_format', 'sniff_version'):
        captures = captures.append_column(name,
            pa.array([line['captures'][0][name]], type=pa.string()))
    pq.write_table(captures, args['captures'])
    args['local_root'] = root
    class UnavailableWorker:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, identity, payload):
            assert identity == digest.hex()
            assert Path(json.loads(payload)['path']).read_bytes() == PDF
            return dict(status='read_error', reason='SniffResourceError')
    result = readings.stage(**args, parser='sniff', work=fixture/'stage', worker_factory=UnavailableWorker)
    assert pq.read_metadata(result['work_list']).num_rows == 1
    assert pq.read_metadata(result['readings']).num_rows == 0
    assert result['pending_reads'] == 1 and result['unreadable_path'] is None


@pytest.mark.parametrize('budget', [100, 9])
def test_discovery_bound_drains_existing_queue_and_reports_real_resource_stop(tmp_path, budget):
    a, b, queued, cutoff, old, late = ['https://fixture.test/'+name for name in
                                     ('a', 'b', 'queued.pdf', 'cut', 'z', 'deferred.pdf')]
    rows = [dict(requested_url=a, attempts=0), dict(requested_url=queued, attempts=0),
            dict(requested_url=cutoff, attempts=1, last_outcome='size_limit'),
            dict(requested_url=old, attempts=1)]
    result, adapter, raw = run_fixture(tmp_path, rows, {
        a: (200, b'<html><a href="/b">b</a></html>', {}),
        b: (200, b'<html><a href="/a">cycle</a><a href="/deferred.pdf">later</a></html>', {}),
        queued: (200, b'%PDF-1.7\nqueued\n%%EOF', {}),
        cutoff: (200, b'%PDF-1.7\ncutoff\n%%EOF', {}),
        old: (200, b'old due evidence', {}),
    }, max_discovery_jobs=1, request_budget=budget, cutoff_urls=[cutoff])
    assert adapter.calls == ([a,b,queued,cutoff,old] if budget == 100 else [a,b,queued])
    assert late not in adapter.calls and adapter.calls.count(a) == 1
    assert result['discovery_jobs'] == 1 and not (tmp_path/'capture/plan-2').exists()
    assert result['stop_reason'] == ('queue_empty' if budget == 100 else 'request_budget')
    assert (raw/body_key(b'<html><a href="/a">cycle</a><a href="/deferred.pdf">later</a></html>')).is_file()
    [disposition] = result['cutoffs']
    assert disposition['disposition'] == ('attempted' if budget == 100 else 'deferred')
    if budget == 9:
        assert disposition['reason'] == 'request_budget'


@pytest.mark.parametrize('source', ['local', 'public'])
@pytest.mark.parametrize('flag', ['--url-normalized-sql', '--url-keys-sql', '--url-key-inputs'])
def test_authored_identity_flags_are_unknown_before_work_or_connection(tmp_path, capsys, source, flag):
    from congress_api.cli.capture_schedule import main
    selected = ['--release-root', str(release(tmp_path, []))] if source == 'local' else [
        '--pointer', 'https://public.fixture/current.json']
    work = tmp_path/'work'
    with pytest.raises(SystemExit) as error:
        main([*selected, flag, str(tmp_path/'authored'), '--engine-config',
            os.environ['DOCSPEC_JOB_CONFIG'], '--request-budget', '20',
            '--byte-budget', '1000', '--spool-budget', '1000', '--work', str(work)])
    assert error.value.code == 2 and 'unrecognized arguments' in capsys.readouterr().err
    assert not work.exists()



def test_unavailable_inspection_defers_expansion_and_preserves_receipt(tmp_path):
    from congress_api.retention.archive_members import ZipLimits
    adapter, root = Adapter(PDF), tmp_path/'raw'
    def unavailable(path):
        assert (root/body_key(PDF)).read_bytes()==PDF
        path.unlink()
        raise SniffReadError('source became unavailable')
    with TemporaryDirectory(dir=tmp_path) as spool, inspection_reads(adapter,unavailable):
        result=fetch(adapter,spool)
        key,line=writer(root,archive_limits=ZipLimits()).write(result,family='documents')
    [capture]=line['captures']
    assert (root/body_key(PDF)).read_bytes()==PDF
    assert json.loads(gzip.decompress((root/key).read_bytes()))==line
    assert capture['sniff_error']=='SniffReadError' and capture['expansion'] is None
    assert capture['complete'] is True and line['outcome']=='stored'
    assert capture['sniffed_format'] is None and capture['intact'] is None
