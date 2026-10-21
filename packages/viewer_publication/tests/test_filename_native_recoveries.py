"""Stable recovery links match the existing policy without unrelated row scans."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'apps/site/scripts'))
from viewer_publication.filename_recoveries import index_recoveries
from congress_api.retention.source_aliases import resolution_candidates

BODY = 'bodies/sha256/aa/' + 'a' * 64 + '.gz'
OTHER = 'bodies/sha256/bb/' + 'b' * 64 + '.gz'
URL = 'https://example.test/saved.pdf'


class Sources:
    def __init__(self, rows):
        self.rows, self.reads = rows, Counter()

    def urls(self):
        self.reads['enumerations'] += 1
        return sorted({r['source_url'] for r in self.rows if r.get('source_url')})

    def at_url(self, url):
        result = [r for r in self.rows if r.get('source_url') == url]
        self.reads['rows'] += len(result)
        return iter(result)

    def targeting(self, url):
        result = [r for r in self.rows if url in resolution_candidates(r)]
        self.reads['rows'] += len(result)
        return iter(result)


def records(*extra, unrelated=0):
    rows = [dict(source_url='../saved.pdf', source_resolved_url=[URL]),
            dict(source_url=URL, body_key=BODY, media_type=['application/pdf']), *extra]
    rows += [dict(source_url=f'https://other.test/{n}') for n in range(unrelated)]
    return [dict(row, source_id=f'source-{n}', document_id=f'document-{n}') for n, row in enumerate(rows)]


def info(rows, catalog='old'):
    return dict(catalog_id=catalog, rows=len(rows), entries=len({r['document_id'] for r in rows}))


def prepare(rows, accepted=(), **kwargs):
    from viewer_publication.filename_native_recoveries import index_selected_recoveries
    sources = Sources(rows)
    result = index_selected_recoveries(info(rows), {'selector_sha256': 'new'}, sources, accepted, **kwargs)
    return result, sources


def reference(tmp_path, rows, accepted):
    names = set().union(*(r.keys() for r in rows))
    table = pa.Table.from_pylist([{name: row.get(name) for name in names} for row in rows])
    pq.write_table(table, tmp_path / 'filenames.parquet')
    documents = list(dict.fromkeys(row['document_id'] for row in rows))
    (tmp_path / 'groups.bin').write_bytes(struct.pack('<' + 'I' * len(rows),
        *(documents.index(row['document_id']) for row in rows)))
    files = {name: dict(path=path, bytes=(tmp_path / path).stat().st_size,
                        sha256=hashlib.sha256((tmp_path / path).read_bytes()).hexdigest())
             for name, path in [('filenames', 'filenames.parquet'), ('groups', 'groups.bin')]}
    value = index_recoveries(tmp_path, dict(info=info(rows), files=files), accepted)
    value['sources'] = sorted([rows[pos]['source_id'], rows[pos]['document_id'], match]
                              for pos, match in value['sources'])
    value['groups'] = sorted([documents[pos], matches] for pos, matches in value['groups'])
    return value


@pytest.mark.parametrize('extra', [
    [],
    [dict(source_url='../saved.pdf', source_resolved_url=[None])],
    [dict(source_url=URL, body_key=OTHER)],
    [dict(source_url='../saved.pdf', body_key=OTHER)],
    [dict(source_url='mailto:' + URL)],
    [dict(source_url='../saved.pdf', source_resolved_url=['javascript:bad'])],
])
def test_stable_index_matches_existing_alias_policy(tmp_path, extra):
    rows = records(*extra)
    observed, _ = prepare(rows)
    expected = reference(tmp_path, rows, [])
    for field in ('recoveries', 'sources', 'groups'):
        assert observed[field] == expected[field]


def test_acceptance_and_correction_preserve_source_values_and_match_reference(tmp_path):
    rows = records(dict(source_url='https://example.test/original'))
    accepted = [dict(original_url='https://example.test/original', recovered_url=URL,
                     body_key=BODY, kind='pdf', recovery_status='recovered',
                     recovery_basis='official_document_identifier')]
    before = deepcopy(rows)
    observed, _ = prepare(rows, accepted)
    expected = reference(tmp_path, rows, accepted)
    for field in ('recoveries', 'sources', 'groups'):
        assert observed[field] == expected[field]
    assert rows == before


@pytest.mark.parametrize('unrelated', [10, 1000])
def test_fixed_change_reads_only_affected_urls_and_matches_clean_result(unrelated):
    before = records(unrelated=unrelated)
    old, _ = prepare(before)
    after = deepcopy(before)
    after[1]['body_key'] = OTHER
    changed = [before[1], after[1]]
    actual, source = prepare(after, previous=old, previous_identity=old['source_identity'],
                             changed_sources=iter(changed))
    clean, _ = prepare(after)
    assert actual == clean
    assert source.reads['enumerations'] == 0
    assert source.reads['rows'] <= 8
    assert actual['recoveries'][0]['body_key'] == OTHER


def test_mapping_only_change_and_no_change_need_no_global_source_walk():
    rows = records(unrelated=1000)
    old, _ = prepare(rows)
    same, source = prepare(rows, previous=old, previous_identity=old['source_identity'])
    assert same == old and not source.reads
    accepted = [dict(original_url='https://example.test/original', recovered_url=URL,
                     body_key=OTHER, kind='pdf', recovery_status='recovered',
                     recovery_basis='user_accepted_url_variant')]
    updated, source = prepare(rows, accepted, previous=old, previous_identity=old['source_identity'])
    clean, _ = prepare(rows, accepted)
    assert updated == clean
    assert source.reads['enumerations'] == 0 and source.reads['rows'] <= 8
    # A second possible retained body makes the automatic alias ambiguous.
    assert updated['recoveries'] == accepted


def test_removed_source_and_group_change_leave_no_stale_mapping():
    before = records()
    old, _ = prepare(before)
    after = [dict(before[0], document_id='new-group')]
    result, _ = prepare(after, previous=old, previous_identity=old['source_identity'],
                        changed_sources=[*before, *after])
    clean, _ = prepare(after)
    assert result == clean and result['sources'] == []


def test_previous_status_requires_its_exact_catalog_basis():
    rows = records()
    old, _ = prepare(rows)
    with pytest.raises(ValueError, match='basis'):
        prepare(rows, previous=old, previous_identity={'selector_sha256': 'wrong'})


def test_fixed_seed_sequence_equals_clean_policy_after_each_edit(tmp_path):
    import random
    rng = random.Random(716)
    current = records(*[dict(source_url=f'../alias-{i}', source_resolved_url=[URL]) for i in range(8)])
    status, _ = prepare(current)
    for step in range(30):
        old = deepcopy(current)
        position = rng.randrange(len(current))
        row = current[position]
        field = rng.choice(['body_key', 'source_resolved_url', 'document_id', 'http_status'])
        row[field] = rng.choice({
            'body_key': [None, BODY, OTHER],
            'source_resolved_url': [[URL], [None, URL], [], ['javascript:bad']],
            'document_id': ['shared-document', f'new-{position}'],
            'http_status': [None, ['200'], ['404']],
        }[field])
        status, source = prepare(current, previous=status, previous_identity=status['source_identity'],
                                 changed_sources=[old[position], current[position]])
        expected = reference(tmp_path, current, [])
        for key in ('recoveries', 'sources', 'groups'):
            assert status[key] == expected[key], (step, key)
        assert not source.reads['enumerations']


def test_output_budget_is_enforced_for_stable_metadata(monkeypatch):
    import viewer_publication.filename_native_recoveries as native
    monkeypatch.setattr(native, 'OUTPUT_BYTES', 100)
    with pytest.raises(ValueError, match='budget'):
        prepare(records())
