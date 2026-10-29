"""Offline operation counts through maintained GPO paths, baseline vs candidate."""
import builtins
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

source, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
workspace = Path(__file__).resolve().parents[3]
for package in ('congress_api', 'congress_shared', 'committee_meeting', 'docspec_client'):
    sys.path.insert(0, str(source / 'packages' / package / 'src'))
sys.path.insert(0, str(workspace / 'packages/congress_api/tests'))
import pytest
import requests
from congress_api.transport import zip_member, http
from congress_api.retention import gpo as evidence
from test_zip_member_transport import RangeSession, URL, MEMBER
from test_gpo_io_efficiency import collector_fixture, track_evidence_writes, VERSION_B

result = {'source': str(source), 'head': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(), 'files': {}, 'zip': []}
for relative in ('acquisition/gpo.py', 'transport/zip_member.py'):
    path = source / 'packages/congress_api/src/congress_api' / relative
    result['files'][relative] = {'loaded_path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
for case in ('success', 'oversized', 'interrupted', 'wrong-range', 'changed-etag'):
    copies, delivered = [], []
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(http, 'pace_request', lambda *args, **kwargs: None)
        def freeze(value=b'', *args, **kwargs):
            if isinstance(value, bytearray):
                copies.append(len(value))
            return builtins.bytes(value, *args, **kwargs)
        monkeypatch.setattr(zip_member, 'bytes', freeze, raising=False)
        def mutate(response, call, body):
            if case == 'oversized':
                body = b'x' * 100000
            if case == 'wrong-range':
                response.headers['Content-Range'] = 'bytes 0-0/2'
            if case == 'changed-etag' and call > 1:
                response.headers['ETag'] = '\"changed\"'
            if case == 'interrupted':
                def chunks(chunk_size):
                    yield body[:8192]
                    yield body[8192:16384]
                    raise requests.exceptions.ChunkedEncodingError('interrupted fixture stream')
                response.iter_content = chunks
            delivered.append(body)
            return body
        session = RangeSession(mutate=mutate)
        record = {'case': case}
        try:
            member = zip_member.read_zip_member(session, URL, MEMBER)
            record.update(accepted=True, member_sha256=hashlib.sha256(member.data).hexdigest(), response_bytes=sum(r['bytes'] for r in member.source['requests']))
        except zip_member.ZipMemberReadError as error:
            record.update(accepted=False, error=str(error), rejected_bytes=len(error.data), rejected_sha256=hashlib.sha256(error.data).hexdigest(), source=error.source)
        record.update(copy_calls=len(copies), copy_bytes=sum(copies), copy_sizes=copies, requests=len(session.calls), streams_closed=all(r.raw.closed for r in session.responses))
        result['zip'].append(record)
with pytest.MonkeyPatch.context() as monkeypatch:
    fixture = Path(tempfile.mkdtemp(prefix='acquisition-', dir=output.parent))
    state, csv, retained, run = collector_fixture(fixture, monkeypatch)
    run()
    state['listing'] = []
    writes = track_evidence_writes(monkeypatch, retained)
    before = retained.read_bytes()
    run()
    result['settled'] = {'write_calls': len(writes), 'written_bytes': sum(writes), 'byte_identical': before == retained.read_bytes()}
    writes.clear()
    old_row = evidence.read_csv(csv)
    state.update(listing=[{'packageId': 'CHRG-110shrg41912', 'lastModified': VERSION_B}], mods=b'<mods>')
    try:
        run()
        code = 0
    except SystemExit as error:
        code = error.code
    result['new_failure'] = {'exit': code, 'write_calls': len(writes), 'written_bytes': sum(writes), 'rejected_body_retained': evidence.body_bytes(evidence.read(retained)['CHRG-110shrg41912']['failed_mods']) == b'<mods>', 'prior_csv_preserved': old_row == evidence.read_csv(csv), 'pending': json.loads(Path(str(retained) + '.pending.json').read_text())}
output.write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({'output': str(output), 'settled': result['settled'], 'new_failure': result['new_failure'], 'zip': [{k:r[k] for k in ('case','copy_calls','copy_bytes','requests','streams_closed')} for r in result['zip']]}, indent=2))
