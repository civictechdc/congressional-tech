"""Comparison evidence must refuse changed behavior before reporting cost gains."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import compare_publication_costs as comparison


def test_runtime_receipt_records_absent_optional_packages(monkeypatch):
    import measure_publication_control as measurement

    def version(name):
        if name == 'optional':
            raise measurement.importlib.metadata.PackageNotFoundError(name)
        return '1.2.3'

    monkeypatch.setattr(measurement.importlib.metadata, 'version', version)
    assert measurement.installed_versions(['installed', 'optional']) == {
        'installed': '1.2.3', 'optional': None}


def write_json(path, value):
    path.write_text(json.dumps(value))


def descriptor(path, root, **extra):
    return dict(path=str(path.relative_to(root)), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **extra)


def publication(directory, *, compression='zstd'):
    root = directory / 'attempt/publication'
    root.mkdir(parents=True)
    ids = root / 'viewer/ids'
    ids.mkdir(parents=True)
    for prefix in range(256):
        (ids / f'{prefix:02x}.bin').write_bytes(b'')
    table = pa.table({'document_id': ['a', 'b', 'c'], 'reading': [None, 'value', 'other']})
    table = table.replace_schema_metadata({b'catalog_id': b'catalog'})
    pq.write_table(table, root / 'filenames.parquet', compression=compression)
    (root / 'groups.bin').write_bytes(b'group-positions')
    write_json(root / 'review-binding.json', {'rows': [{'document_id': 'a'}],
        'withdrawn': [{'document_id': 'b', 'reason': 'unbound'}]})
    files = {name: descriptor(root / filename, root, **extra) for name, filename, extra in (
        ('filenames', 'filenames.parquet', {'rows': 3}), ('groups', 'groups.bin', {}),
        ('review_binding', 'review-binding.json', {}))}
    manifest = {'version': 5, 'published_at': str(directory), 'ids': 'viewer/ids/',
        'compression_policy': {'codec': 'zstd', 'level': 9},
        'info': {'catalog_id': 'catalog', 'rows': 3, 'entries': 3}, 'source_manifest': {'catalog_id': 'catalog'}, 'files': files}
    write_json(root / 'manifest.json', manifest)
    value = {'version': 1, 'catalog_id': 'catalog', 'rows': 3, 'entries': 3,
             'groups': [], 'sources': [], 'recoveries': []}
    write_json(root / 'recovery-prepared.json', {'version': 1, 'inputs': {
        'version': 1, 'source_manifest': manifest['source_manifest'],
        'catalog': {name: manifest['info'][name] for name in ('catalog_id', 'rows', 'entries')},
        'files': {name: files[name] for name in ('filenames', 'groups')},
        'accepted_present': False, 'accepted_sha256': None}, 'value': value})
    recovery = comparison.encoded(value)
    sha = hashlib.sha256(recovery).hexdigest()
    (directory / 'published-recovery.json').write_bytes(recovery)
    write_json(directory / 'published-pointer.json', {'version': 1, 'catalog_id': 'catalog',
        'source_manifest': manifest['source_manifest'], 'recovery': {'bytes': len(recovery), 'sha256': sha,
            'path': f'releases/{sha[:32]}/{sha[32:]}/viewer-v2/recovery-status.json'}})
    return root


def update_file(root, name, path):
    manifest = json.loads((root / 'manifest.json').read_text())
    item = manifest['files'][name]
    manifest['files'][name] = descriptor(path, root, **{k: v for k, v in item.items()
        if k not in ('path', 'bytes', 'sha256')})
    write_json(root / 'manifest.json', manifest)
    recovery = json.loads((root / 'recovery-prepared.json').read_text())
    if name in recovery['inputs']['files']:
        recovery['inputs']['files'][name] = manifest['files'][name]
        write_json(root / 'recovery-prepared.json', recovery)


def test_exact_ordered_values_allow_encoding_difference_and_report_full_binding(tmp_path):
    publication(tmp_path / 'before', compression='NONE')
    publication(tmp_path / 'after')
    result = comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')
    assert len(result['files']) == 259
    parquet = next(item for item in result['files'] if item['file'] == 'filenames')
    assert not parquet['byte_identical']
    assert parquet['method'] == 'complete schema and ordered Arrow values'
    assert result['review_binding']['bound'] == 1 and result['review_binding']['withdrawn'] == 1
    assert result['review_binding']['withdrawn_reasons'] == {'unbound': 1}
    assert result['recovery_prepared']['exact_value_and_normalized_inputs'] is True


@pytest.mark.parametrize('change', ['version', 'ids', 'compression_policy', 'descriptor_path', 'descriptor_rows'])
def test_reader_visible_metadata_must_match_even_when_payload_values_match(tmp_path, change):
    publication(tmp_path / 'before')
    root = publication(tmp_path / 'after')
    manifest = json.loads((root / 'manifest.json').read_text())
    if change == 'ids':
        (root / 'viewer/ids').rename(root / 'viewer/other-ids')
        manifest['ids'] = 'viewer/other-ids/'
    elif change == 'descriptor_path':
        (root / 'filenames.parquet').rename(root / 'renamed.parquet')
        manifest['files']['filenames']['path'] = 'renamed.parquet'
    elif change == 'descriptor_rows':
        manifest['files']['filenames']['rows'] += 1
    elif change == 'version':
        manifest['version'] += 1
    else:
        manifest['compression_policy']['level'] = 3
    write_json(root / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='routing|descriptor'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')


@pytest.mark.parametrize('change', ['values', 'order', 'schema_metadata', 'review_binding'])
def test_matching_self_hashes_do_not_hide_changed_values_schema_or_binding(tmp_path, change):
    publication(tmp_path / 'before')
    root = publication(tmp_path / 'after')
    if change == 'review_binding':
        path = root / 'review-binding.json'
        binding = json.loads(path.read_text())
        binding['withdrawn'][0]['reason'] = 'different'
        write_json(path, binding)
        update_file(root, 'review_binding', path)
        expected = 'sidecar bytes'
    else:
        path = root / 'filenames.parquet'
        table = pq.read_table(path)
        if change == 'values':
            table = table.set_column(1, 'reading', pa.array([None, 'changed', 'other']))
        elif change == 'order':
            table = table.take(pa.array([2, 1, 0]))
        else:
            table = table.replace_schema_metadata({b'catalog_id': b'other'})
        pq.write_table(table, path)
        update_file(root, 'filenames', path)
        expected = 'values/schema'
    with pytest.raises(ValueError, match=expected):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')


@pytest.mark.parametrize('change', ['value', 'accepted_input', 'file_identity'])
def test_recovery_output_and_its_accepted_inputs_must_match(tmp_path, change):
    publication(tmp_path / 'before')
    root = publication(tmp_path / 'after')
    path = root / 'recovery-prepared.json'
    recovery = json.loads(path.read_text())
    if change == 'value':
        recovery['value']['groups'] = [1]
    elif change == 'accepted_input':
        recovery['inputs']['accepted_present'] = True
    else:
        recovery['inputs']['files']['filenames']['sha256'] = 'wrong'
    write_json(path, recovery)
    with pytest.raises(ValueError, match='Prepared recovery'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')


@pytest.mark.parametrize('kind', ['manifest', 'shard', 'recovery'])
def test_oversized_control_or_shard_is_rejected_before_its_read(tmp_path, monkeypatch, kind):
    root = publication(tmp_path / 'trial')
    path = root / {'manifest': 'manifest.json', 'shard': 'viewer/ids/00.bin',
                   'recovery': 'recovery-prepared.json'}[kind]
    with path.open('r+b') as stream:
        stream.truncate((4 if kind == 'manifest' else 32) * 1024**2 + 1)
    old_read, old_digest = Path.read_text, comparison.digest
    def guarded_read(self, *args, **kwargs):
        assert self != path, 'oversized file was opened before its size bound'
        return old_read(self, *args, **kwargs)
    def guarded_digest(selected):
        assert selected != path, 'oversized file was hashed before its size bound'
        return old_digest(selected)
    monkeypatch.setattr(Path, 'read_text', guarded_read)
    monkeypatch.setattr(comparison, 'digest', guarded_digest)
    with pytest.raises(ValueError, match='limit|bounds'):
        if kind == 'recovery':
            comparison.compare_outputs(tmp_path / 'trial', tmp_path / 'trial')
        else:
            comparison.outputs(tmp_path / 'trial')


STAGES = ('accepted_preparation', 'successful_publication', 'unchanged_poll',
          'explicit_resume_failure', 'explicit_resume')


def receipt(revision):
    return {'inputs': {'source_manifest_sha256': 'source', 'source_files': {'input': 'hash'},
        'python': '3.12', 'executable': '/same/python', 'maximum_source_bytes': 1024,
        'controlled_request_latency_ms': 1, 'measurement_sources': {'runner': 'same'},
        'command_process_model': 'cold', 'runtime': {'packages': {'pyarrow': '25', 'ijson': '3.6'}},
        'revision': revision, 'source_identity': {'implementation': revision}, 'prepared_recovery_supported': True},
        'outcomes': {'successful_publication': {'status': 'published'}, 'unchanged_poll': {'status': 'unchanged'},
            'explicit_resume': {'status': 'published'}, 'explicit_resume_failure': {'status': 'failed',
                'error_type': 'RuntimeError', 'error': 'Explicit bounded fixture probe failure'}},
        'sampling_errors': [], 'limits': {'scope': 'fixture'}, 'stages': [
            {'stage': name, 'status': 'failed' if name == 'explicit_resume_failure' else 'complete',
             'seconds': 1, 'sampled_process_tree_rss_peak_bytes': 1, 'scratch_bytes': 1,
             'counts': {'get_requests': 1}} for name in STAGES]}


def save_receipt(path, value):
    path.mkdir()
    write_json(path / 'costs.json', value)


@pytest.mark.parametrize('change', ['runtime', 'instrumentation', 'source_input', 'probe',
                                   'probe_type', 'missing_stage', 'duplicate_stage', 'sampling'])
def test_trial_mismatch_refuses_summary_before_payload_comparison(tmp_path, monkeypatch, change):
    before, after = receipt('before'), receipt('after')
    if change == 'runtime':
        after['inputs']['runtime']['packages']['ijson'] = 'changed'
    elif change == 'instrumentation':
        after['inputs']['measurement_sources']['runner'] = 'changed'
    elif change == 'source_input':
        after['inputs']['source_files']['input'] = 'changed'
    elif change == 'probe':
        after['outcomes']['explicit_resume_failure']['error'] = 'earlier journal failure'
    elif change == 'probe_type':
        after['outcomes']['explicit_resume_failure']['error_type'] = 'OSError'
    elif change == 'missing_stage':
        after['stages'].pop()
    elif change == 'duplicate_stage':
        after['stages'].append(deepcopy(after['stages'][0]))
    else:
        after['sampling_errors'].append('sampler failed')
    save_receipt(tmp_path / 'before', before)
    save_receipt(tmp_path / 'after', after)
    monkeypatch.setattr(comparison, 'compare_outputs', lambda *args, **kwargs: pytest.fail('read payloads after invalid trial'))
    with pytest.raises(ValueError):
        comparison.run([tmp_path / 'before'], [tmp_path / 'after'], tmp_path / 'summary.json')
    assert not (tmp_path / 'summary.json').exists()


def test_same_revision_with_changed_working_source_is_refused(tmp_path, monkeypatch):
    before, altered, after = receipt('before'), receipt('before'), receipt('after')
    altered['inputs']['source_identity']['implementation'] = 'dirty-edit'
    for name, value in [('b0', before), ('b1', altered), ('a0', after), ('a1', after)]:
        save_receipt(tmp_path / name, value)
    monkeypatch.setattr(comparison, 'compare_outputs', lambda *args, **kwargs: pytest.fail('read payloads after changed source'))
    with pytest.raises(ValueError, match='Working source identity'):
        comparison.run([tmp_path / 'b0', tmp_path / 'b1'], [tmp_path / 'a0', tmp_path / 'a1'], tmp_path / 'summary.json')


def test_combined_median_uses_each_trial_sum_and_memory_scratch_use_maxima(tmp_path, monkeypatch):
    paths = {'before': [], 'after': []}
    for arm in paths:
        for index, (prep, publish) in enumerate([(1, 10), (10, 1), (10, 10)]):
            value = receipt(arm)
            value['stages'][0].update(seconds=prep, counts={'get_requests': prep},
                sampled_process_tree_rss_peak_bytes=[1, 5, 3][index], scratch_bytes=[10, 5, 3][index])
            value['stages'][1].update(seconds=publish, counts={'get_requests': publish},
                sampled_process_tree_rss_peak_bytes=[2, 4, 6][index], scratch_bytes=[2, 4, 6][index])
            path = tmp_path / f'{arm}{index}'
            save_receipt(path, value); paths[arm].append(path)
    monkeypatch.setattr(comparison, 'compare_outputs', lambda *args, **kwargs: {'files': [], 'review_binding': {}})
    comparison.run(paths['before'], paths['after'], tmp_path / 'summary.json')
    result = json.loads((tmp_path / 'summary.json').read_text())
    arm = result['before']; combined = arm['complete_success_path']
    assert combined['seconds_median'] == 11  # Sum of the stage medians would incorrectly be 20.
    assert combined['seconds_range'] == [11, 20]
    assert combined['median_total_counts']['get_requests'] == 11
    assert combined['maximum_sampled_process_tree_rss_bytes'] == 6
    assert combined['maximum_stage_end_scratch_bytes'] == 10
    assert all(name in arm for name in STAGES)


def test_baseline_preparation_can_be_absent_only_with_explicit_capability(tmp_path):
    before = publication(tmp_path / 'before')
    publication(tmp_path / 'after')
    (before / 'recovery-prepared.json').unlink()
    with pytest.raises(ValueError, match='Prepared recovery evidence is missing'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')
    result = comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after', before_prepared_required=False)
    assert result['published_recovery']['byte_identical']
    assert result['recovery_prepared']['before'] is None
    assert result['recovery_prepared']['after_required'] is True
    assert result['recovery_prepared']['published_value_verified'] is True
    assert result['recovery_prepared']['exact_value_and_normalized_inputs'] is False


def test_absent_baseline_does_not_permit_missing_candidate_preparation(tmp_path):
    before = publication(tmp_path / 'before')
    after = publication(tmp_path / 'after')
    (before / 'recovery-prepared.json').unlink()
    (after / 'recovery-prepared.json').unlink()
    with pytest.raises(ValueError, match='Prepared recovery evidence is missing'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after', before_prepared_required=False)


@pytest.mark.parametrize('missing', ['published-pointer.json', 'published-recovery.json'])
def test_selected_control_captures_are_required_for_both_arms(tmp_path, missing):
    publication(tmp_path / 'before')
    publication(tmp_path / 'after')
    (tmp_path / 'before' / missing).unlink()
    with pytest.raises(ValueError, match='evidence is missing'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after', before_prepared_required=False)


@pytest.mark.parametrize('change', ['sha', 'bytes', 'body', 'catalog', 'source'])
def test_actual_selected_control_identity_must_match(tmp_path, change):
    publication(tmp_path / 'before')
    publication(tmp_path / 'after')
    path = tmp_path / 'after/published-pointer.json'
    pointer = json.loads(path.read_text())
    if change == 'sha':
        pointer['recovery']['sha256'] = 'a' * 64
    elif change == 'bytes':
        pointer['recovery']['bytes'] += 1
    elif change == 'body':
        (tmp_path / 'after/published-recovery.json').write_bytes(b'corruption')
    elif change == 'catalog':
        pointer['catalog_id'] = 'different'
    else:
        pointer['source_manifest']['catalog_id'] = 'different'
    write_json(path, pointer)
    with pytest.raises(ValueError, match='Published pointer|Published recovery'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')


def test_different_selected_recovery_cannot_pass_with_updated_self_hash(tmp_path):
    publication(tmp_path / 'before')
    publication(tmp_path / 'after')
    path = tmp_path / 'after/published-recovery.json'
    value = json.loads(path.read_text()); value['groups'] = [[0, [0]]]
    raw = comparison.encoded(value); path.write_bytes(raw)
    path = tmp_path / 'after/published-pointer.json'
    pointer = json.loads(path.read_text())
    pointer['recovery'].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    write_json(path, pointer)
    with pytest.raises(ValueError, match='Published recovery bytes changed'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')


@pytest.mark.parametrize('change', ['version', 'input_version', 'source', 'catalog', 'accepted_sha', 'missing_file', 'extra_file'])
def test_candidate_prepared_inputs_must_equal_manifest_and_accepted_source(tmp_path, change):
    before = publication(tmp_path / 'before')
    root = publication(tmp_path / 'after')
    (before / 'recovery-prepared.json').unlink()
    path = root / 'recovery-prepared.json'; value = json.loads(path.read_text())
    if change == 'version':
        value['version'] += 1
    elif change == 'input_version':
        value['inputs']['version'] += 1
    elif change == 'source':
        value['inputs']['source_manifest']['catalog_id'] = 'different'
    elif change == 'catalog':
        value['inputs']['catalog']['rows'] += 1
    elif change == 'accepted_sha':
        value['inputs']['accepted_sha256'] = 'a' * 64
    elif change == 'missing_file':
        del value['inputs']['files']['groups']
    else:
        value['inputs']['files']['extra'] = value['inputs']['files']['groups']
    write_json(path, value)
    with pytest.raises(ValueError, match='Prepared recovery inputs'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after', before_prepared_required=False)


@pytest.mark.parametrize('filename,limit', [('published-pointer.json', 4 * 1024**2),
                                           ('published-recovery.json', 32 * 1024**2)])
def test_captured_control_bound_is_checked_before_open(tmp_path, monkeypatch, filename, limit):
    publication(tmp_path / 'before')
    publication(tmp_path / 'after')
    path = tmp_path / 'after' / filename
    with path.open('r+b') as stream:
        stream.truncate(limit + 1)
    old_open = Path.open
    def guarded_open(self, *args, **kwargs):
        assert self != path, 'oversized captured control was opened before its bound'
        return old_open(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    with pytest.raises(ValueError, match='bounds'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')


@pytest.mark.parametrize('capability', [None, 'false', 0])
def test_missing_or_non_boolean_capability_is_not_optional_evidence(tmp_path, monkeypatch, capability):
    before, after = receipt('before'), receipt('after')
    after['inputs']['prepared_recovery_supported'] = capability
    save_receipt(tmp_path / 'before', before); save_receipt(tmp_path / 'after', after)
    monkeypatch.setattr(comparison, 'compare_outputs', lambda *args, **kwargs: pytest.fail('invalid capability accepted'))
    with pytest.raises(ValueError, match='explicit boolean'):
        comparison.run([tmp_path / 'before'], [tmp_path / 'after'], tmp_path / 'summary.json')


def test_runner_retains_exact_selected_bytes_and_refuses_invalid_capture(tmp_path):
    from types import SimpleNamespace
    import measure_publication_control as measurement
    raw = b'{ "version": 1, "preserved": true }'
    pointer = {'recovery': {'path': 'selected', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
    pointer_raw = json.dumps(pointer, indent=2).encode()
    objects = {'prefix/manifest.json': pointer_raw, 'prefix/selected': raw}
    measurement.save_published_controls(SimpleNamespace(objects=objects), SimpleNamespace(PREFIX='prefix/'), tmp_path)
    assert (tmp_path / 'published-pointer.json').read_bytes() == pointer_raw
    assert (tmp_path / 'published-recovery.json').read_bytes() == raw
    pointer['recovery']['sha256'] = 'a' * 64
    objects['prefix/manifest.json'] = comparison.encoded(pointer)
    with pytest.raises(ValueError, match='selected identity'):
        measurement.save_published_controls(SimpleNamespace(objects=objects), SimpleNamespace(PREFIX='prefix/'), tmp_path)


def test_runner_refuses_oversize_descriptor_before_recovery_lookup(tmp_path):
    from types import SimpleNamespace
    import measure_publication_control as measurement
    class Objects(dict):
        def __getitem__(self, name):
            assert name == 'prefix/manifest.json', 'oversized recovery descriptor caused a payload lookup'
            return super().__getitem__(name)
    objects = Objects({'prefix/manifest.json': comparison.encoded({'recovery': {
        'path': 'not-read', 'bytes': 32 * 1024**2 + 1, 'sha256': 'a' * 64}})})
    with pytest.raises(ValueError, match='evidence limit'):
        measurement.save_published_controls(SimpleNamespace(objects=objects), SimpleNamespace(PREFIX='prefix/'), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_prepared_accepted_mapping_requires_exact_raw_source_pin(tmp_path):
    roots = [publication(tmp_path / arm) for arm in ('before', 'after')]
    for root in roots:
        path = root / 'recovery-prepared.json'; value = json.loads(path.read_text())
        value['inputs'].update(accepted_present=True, accepted_sha256='a' * 64)
        write_json(path, value)
    with pytest.raises(ValueError, match='accepted source identity'):
        comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after')
    result = comparison.compare_outputs(tmp_path / 'before', tmp_path / 'after',
        accepted_identity={'present': True, 'sha256': 'a' * 64})
    assert result['recovery_prepared']['exact_value_and_normalized_inputs']


def test_run_passes_each_arm_capability_and_shared_accepted_pin(tmp_path, monkeypatch):
    before, after = receipt('before'), receipt('after')
    before['inputs']['prepared_recovery_supported'] = False
    for value in (before, after):
        value['inputs']['source_files']['viewer-publications/recoveries/accepted.json'] = {'bytes': 42, 'sha256': 'a' * 64}
    save_receipt(tmp_path / 'before', before); save_receipt(tmp_path / 'after', after)
    observed = []
    def compare(*args, **kwargs):
        observed.append(kwargs)
        return {'files': [], 'review_binding': {}}
    monkeypatch.setattr(comparison, 'compare_outputs', compare)
    comparison.run([tmp_path / 'before'], [tmp_path / 'after'], tmp_path / 'summary.json')
    assert observed == [{'before_prepared_required': False, 'after_prepared_required': True,
                         'accepted_identity': {'present': True, 'sha256': 'a' * 64}}]
    result = json.loads((tmp_path / 'summary.json').read_text())
    assert result['prepared_recovery_supported'] == {'before': False, 'after': True}


def test_candidate_cannot_waive_prepared_recovery_verification(tmp_path, monkeypatch):
    for arm in ('before', 'after'):
        value = receipt(arm)
        value['inputs']['prepared_recovery_supported'] = False
        save_receipt(tmp_path / arm, value)
    monkeypatch.setattr(comparison, 'compare_outputs',
        lambda *args, **kwargs: pytest.fail('Candidate waived prepared recovery verification'))
    with pytest.raises(ValueError, match='Candidate must support prepared recovery verification'):
        comparison.run([tmp_path / 'before'], [tmp_path / 'after'], tmp_path / 'summary.json')
    assert not (tmp_path / 'summary.json').exists()
