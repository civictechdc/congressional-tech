"""Gate 3 (ct-tk10): one fixture runs raw receipt lines through captures, readings, filenames
and the model to release files, and checks each record against the contract, not the code.

Lines are trimmed real lines; each keeps its source key and line number (fixtures file and
fb408404_receipt_lines.jsonl). Bodies the mirror does not hold are synthetic, and each
substitution is listed in SUBSTITUTIONS. archive_publish_job.execute runs this file through
scripts/dev.py before any runtime or SDK is built.

Cannot see: envelope shapes not in this fixture (there is no fixed count, ct-d0o0); scale and
memory (ct-r8jd); value distributions on real data (gates 1 and 4 run on the real candidate).
Measured: about 12 s for the four builds (one base, three mutants) on darwin-arm64.
"""
import gzip
from hashlib import md5, sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from capture_qualification_helpers import write_qualified_bytes
from docspec_client.client import NativeDatasets

HERE = Path(__file__).parent
LINES = [json.loads(text) for text in (HERE / 'fixtures/e2e_receipt_lines.jsonl').read_text().splitlines()]
FB = {json.loads(text)['key']: json.loads(text) for text in
      (HERE.parents[1] / 'congress_api/tests/fixtures/fb408404_receipt_lines.jsonl').read_text().splitlines()}
ZIP_KEY, EMPTY_KEY = LINES[0]['key'], LINES[1]['key']
HTTP_202 = 'receipts/external/provider-responses/2026-10-11/download-20261011T134611Z-e84fedd3f9c2-000012.jsonl.gz'
NO_ADDRESS = 'receipts/external/wayback/2026-09-29/assemble-20260930.jsonl.gz'
ZIP_URL = 'https://www.govinfo.gov/content/pkg/CHRG-118shrg62354.zip'
MEMBERS = {  # real member names from the ZIP line; synthetic bytes
    'CHRG-118shrg62354/dip.xml': b'<?xml version="1.0"?><mets xmlns="http://www.loc.gov/METS/" OBJID="CHRG-118shrg62354"/>\n',
    'CHRG-118shrg62354/html/CHRG-118shrg62354.htm': b'<html><head><title>Hearing CHRG-118shrg62354</title></head><body><pre>'
        + b'Hearing before the Committee. ' * 80 + b'</pre></body></html>',
}
PAGE = b'<html><head><title>FDA User Fee Agreements</title></head><body><p>' + b'Hearing page. ' * 60 + b'</p></body></html>'
SUBSTITUTIONS = [
    'ZIP line: content.sha256, range_transfer sha256/size/bytes, archive_members[0,1] content.sha256, declared_bytes,'
    ' compressed_bytes, and captures[0..2] sha256/body_key/bytes/stored_sha256/stored_bytes take the synthetic ZIP'
    ' and member values (the real ZIP is 978 MB and not in the mirror).',
    'Empty-2xx line: the page body 6f3be45c... becomes PAGE; the empty prior-attempt body e3b0c442... is exact.',
    'HTTP 202 and no-address lines: each body the mirror lacks (8984f2bd..., 7653f19f..., ae138caf...) becomes a'
    ' synthetic HTML body of its own digest, everywhere the line names it; statuses, URLs and envelopes are unchanged.',
]
ABSENT = {  # real digest -> synthetic stand-in, for bodies the local mirror does not hold
    '8984f2bd879c5aff7f47f3383ecff3c74ce9425f403ccca6724927ecb42e004e': b'<html><body>Please wait while we verify your browser.</body></html>',
    '7653f19fd819b75101a3dbe1a1bc3893f38a8a26ba65160df3ecb3acce1de83c': b'<html><head><title>A Dire Shortage</title></head><body>' + b'HELP hearing. ' * 50 + b'</body></html>',
    'ae138caf8767f7be2fe6f47f1663b0e2e28d903264707aa9b6f73bb7b223902c': b'<html><body>Too many requests</body></html>',
}


def replace_body(value, real, facts):
    """Point every mention of a real digest at a synthetic body, with its sizes."""
    if isinstance(value, dict):
        if value.get('sha256') == real:
            for name in ('bytes', 'stored_sha256', 'stored_bytes'):
                if name in value:
                    value[name] = facts[name]
        return {k: replace_body(v, real, facts) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_body(v, real, facts) for v in value]
    if isinstance(value, str) and real in value:
        return value.replace(real, facts['sha256'])
    return value


def digest(data):
    return sha256(data).hexdigest()


def store(raw, data):
    key = f'bodies/sha256/{digest(data)[:2]}/{digest(data)}.gz'
    stored = gzip.compress(data, mtime=0)
    (raw / key).parent.mkdir(parents=True, exist_ok=True)
    (raw / key).write_bytes(stored)
    return dict(sha256=digest(data), body_key=key, bytes=len(data), stored_sha256=digest(stored), stored_bytes=len(stored))


def substitute(capture, facts):
    capture.update({k: facts[k] for k in ('sha256', 'body_key', 'bytes', 'stored_sha256', 'stored_bytes') if k in capture or k == 'sha256'})


def raw_mirror(root):
    raw = root / 'raw'
    zipped = BytesIO()
    with ZipFile(zipped, 'w') as archive:
        for name, data in MEMBERS.items():
            archive.writestr(name, data, compress_type=ZIP_DEFLATED)
    zip_bytes = zipped.getvalue()
    zip_facts = store(raw, zip_bytes)
    member_facts = [store(raw, data) for data in MEMBERS.values()]
    rows = {}
    zip_row = json.loads(json.dumps(LINES[0]['row']))
    record = zip_row['record']
    record['content']['sha256'] = zip_facts['sha256']
    record['range_transfer'].update(sha256=zip_facts['sha256'], size=len(zip_bytes), bytes=len(zip_bytes))
    with ZipFile(BytesIO(zip_bytes)) as archive:
        infos = {info.filename: info for info in archive.infolist()}
    for member, facts in zip(record['archive_members'], member_facts):
        info = infos[member['original_name']]
        member['content']['sha256'] = facts['sha256']
        member.update(declared_bytes=info.file_size, compressed_bytes=info.compress_size,
                      parent_archive_body_key=zip_facts['body_key'])
    for capture, facts in zip(zip_row['captures'], [zip_facts, *member_facts]):
        substitute(capture, facts)
    rows[ZIP_KEY] = zip_row
    page_row = json.loads(json.dumps(LINES[1]['row']))
    page = store(raw, PAGE)
    store(raw, b'')
    page_row['record']['content']['sha256'] = page['sha256']
    for capture in page_row['captures']:
        if capture['sha256'] != digest(b''):
            substitute(capture, page)
    rows[EMPTY_KEY] = page_row
    for key in (HTTP_202, NO_ADDRESS):
        row = FB[key]['row']
        for real, data in ABSENT.items():
            row = replace_body(row, real, store(raw, data))
        rows[key] = row
    receipts = []
    for key, row in rows.items():
        data = gzip.compress((json.dumps(row, separators=(',', ':')) + '\n').encode(), mtime=0)
        receipts.append((key, write_qualified_bytes(raw / key, data)))
    return raw, receipts, dict(zip=zip_facts, members=member_facts, page=page)


def build(root, spec, *, captures=None, model_root=None, label='release'):
    from viewer_publication.archive_model import ROOT, build_release
    if captures is not None:  # a mutated capture mapping: re-derive what the producers stage from it
        from archive_job_fixture import derive_model_spec
        work = root / (label + '-derived')
        work.mkdir()
        spec = derive_model_spec(work, raw=root / 'raw', captures=captures, entities=True)
    from archive_job_fixture import spicy_input
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        # Entities on, so all six admission suites run (entity_profile_completeness included);
        # entity files need stated spicy-regs generations (925036be).
        build_release(spicy_regs=spicy_input(),captures=spec['captures']['path'], readings=spec['readings']['path'],
            filename_readings=spec['filename_readings']['path'], parser_versions=spec['parser_versions'],
            meeting_records=spec['meeting_records']['path'], appearance_records=spec['appearance_records']['path'],
            catalog_version=spec['catalog_version'], engine=engine, output=root / label,
            scratch=root / (label + '-model'), root=model_root or ROOT, include_entities=True)
    return root / label


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    from archive_job_fixture import rebuild_model_spec
    root = tmp_path_factory.mktemp('e2e')
    raw, receipts, facts = raw_mirror(root)
    spec = rebuild_model_spec(root, raw=raw, receipts=receipts, entities=True)
    return root, spec, facts, build(root, spec)


def rows(release, name):
    return pq.read_table(release / f'{name}.parquet').to_pylist()


def violations(release, spec, facts):
    """Each contract clause below names its source; an empty list means the release meets it."""
    found = []
    listed = rows(release, 'list')
    links = {r['link_key']: r['list_row'] for r in rows(release, 'links')}
    sources = rows(release, 'sources')
    state = {r['requested_url']: r for r in rows(release, 'url_state')}
    key = lambda facts_: bytes.fromhex(facts_['sha256'])[:8]
    html_member = facts['members'][1]
    # ZIP (data model §7.3 "ZIPs are capture transport"; §8.2 body keys: a ZIP resolves to its first document).
    if links.get(key(facts['zip'])) is None or links[key(facts['zip'])] != links.get(key(html_member)):
        found.append('zip body key does not resolve to its member document')
    # The METS manifest (dip.xml) is a member the ZIP lists, but "its METS, MODS and PREMIS
    # manifests join none" (data model §7.4, owner decision 2026-11-01): never a document.
    if key(facts['members'][0]) in links or any(s['member_path'] == 'CHRG-118shrg62354/dip.xml' for s in sources):
        found.append('the METS manifest is a listed document')
    if key(html_member) not in links:
        found.append('zip member is not a listed document')
    else:
        row = links[key(html_member)]
        member_sources = [s for s in sources if s['list_row'] == row]
        if not any(s['url'] == ZIP_URL and s['member_path'] == 'CHRG-118shrg62354/html/CHRG-118shrg62354.htm' for s in member_sources):
            found.append('zip member source lacks the ZIP URL and its member path')
    if any(s['url'] == ZIP_URL and s['member_path'] is None for s in sources):
        found.append('the ZIP itself is listed as a document')
    # HTTP 202 (ct-c6b0, 3bf52b65): failed, never a document; url_state records the 202 failure.
    challenge = ABSENT['8984f2bd879c5aff7f47f3383ecff3c74ce9425f403ccca6724927ecb42e004e']
    if bytes.fromhex(digest(challenge))[:8] in links:
        found.append('HTTP 202 body is a listed document')
    reliefweb = state.get('https://reliefweb.int/report/el-salvador/battered-climate-shocks-and-bruised-economic-crisis-millions-more-central-america')
    if not reliefweb or reliefweb['last_outcome'] != 'failed' or reliefweb['last_status'] != 202:
        found.append('url_state does not record the HTTP 202 as failed')
    # Empty 2xx (§7.3 real_files: bytes > 0): never a document.
    if bytes.fromhex(digest(b''))[:8] in links:
        found.append('empty body is a listed document')
    # NULL URL (§8.1 sources.url non-null; ct-n2cy): no NULL address; the no-address capture stays NULL in captures.
    if any(s['url'] is None for s in sources):
        found.append('a sources row has a NULL url')
    return found


def test_raw_lines_reach_release_files_as_the_contract_states(built):
    root, spec, facts, release = built
    assert violations(release, spec, facts) == []
    captures = pq.read_table(spec['captures']['path']).to_pylist()
    wayback = [c for c in captures if c['receipt_key'] == NO_ADDRESS]
    assert [c['url'] for c in wayback] == [None, None]  # the raw line has no record address
    assert {c['outcome'] for c in captures if c['receipt_key'] == HTTP_202} == {'failed'}
    reports = {q['name']: q['data'] for q in json.loads((root / 'release-model/result.json').read_text())['queries']}
    suites = ['invariants', 'model_invariants', 'url_state_invariants', 'profile_completeness',
              'entity_profile_completeness', 'relationship_invariants']
    for suite in suites:
        assert suite in reports and not any(reports[suite][0].values()), suite


def mutate_captures(root, spec, name, change):
    table = pq.read_table(spec['captures']['path'])
    rows_ = [change(dict(r)) for r in table.to_pylist()]
    path = root / f'{name}-captures.parquet'
    pq.write_table(pa.Table.from_pylist(rows_, schema=table.schema), path)
    return path


def test_mutant_http_202_treated_as_stored_is_caught(built):
    root, spec, facts, _ = built
    stored = lambda r: dict(r, outcome='stored', fetch_outcome='stored') if r['receipt_key'] == HTTP_202 else r
    # Cluster e1's model invariant refuses a good fetch that is not a document at build time,
    # before any release file exists; that is where this mutant is caught now.
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build(root, spec, captures=mutate_captures(root, spec, 'm202', stored), label='m202')
    assert not (root / 'm202/manifest.json').exists()
    reports = {q['name']: q['data'] for q in json.loads((root / 'm202-model/result.json').read_text())['queries']}
    assert reports['model_invariants'][0]['non_document_good_fetches'] > 0


def test_mutant_members_not_real_is_caught(built):
    """bc0a146c class: archive members stop being real files."""
    root, spec, facts, _ = built
    failed = lambda r: dict(r, outcome='failed') if r['member_path'] is not None else r
    release = build(root, spec, captures=mutate_captures(root, spec, 'mzip', failed), label='mzip')
    assert 'zip member is not a listed document' in violations(release, spec, facts)


def test_mutant_null_address_published_refuses_before_manifest(built):
    """068f2a40 class: a NULL capture address reaches sources; gate 4 refuses at write."""
    from viewer_publication.archive_model_profile import ROOT, _definition_hashes
    root, spec, facts, _ = built
    broken = root / 'broken-root'
    for relative in _definition_hashes(ROOT):
        target = broken / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    sql = broken / 'model/sql/document-addresses.sql'
    assert ' AND c.context_url IS NOT NULL' in sql.read_text()
    sql.write_text(sql.read_text().replace(' AND c.context_url IS NOT NULL', ''))
    no_context = lambda r: dict(r, context_url=None) if r['receipt_key'] == NO_ADDRESS else r
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build(root, spec, captures=mutate_captures(root, spec, 'mnull', no_context), model_root=broken, label='mnull')
    assert not (root / 'mnull/manifest.json').exists()
    reports = {q['name']: q['data'] for q in json.loads((root / 'mnull-model/result.json').read_text())['queries']}
    assert reports['relationship_invariants'][0]['null_sources_url'] > 0
