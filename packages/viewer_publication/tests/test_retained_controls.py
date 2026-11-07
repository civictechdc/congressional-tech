"""Control delivery retries preserve custody and refuse changed inputs before writes."""
import pytest

from viewer_publication.archive_format import _retain_controls


def custody(path):
    value = path.stat()
    return value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def test_same_control_finalization_preserves_bytes_and_custody(tmp_path):
    controls = {'catalog.ddk.json': b'{"kind":"catalog"}\n', 'manifest.json': b'{"release_id":"fixture"}\n'}
    _retain_controls(tmp_path, controls)
    original = {name: custody(tmp_path/name) for name in controls}
    _retain_controls(tmp_path, controls)
    assert {name: custody(tmp_path/name) for name in controls} == original
    assert {name: (tmp_path/name).read_bytes() for name in controls} == controls


def test_changed_control_refuses_before_any_new_control_or_manifest_write(tmp_path):
    original = {'catalog.ddk.json': b'original schema', 'manifest.json': b'original manifest'}
    _retain_controls(tmp_path, original)
    before = {name: custody(tmp_path/name) for name in original}
    changed = {'new_control.json': b'new', 'catalog.ddk.json': b'changed schema', 'manifest.json': b'changed manifest'}
    with pytest.raises(ValueError, match='Retained release control differs'):
        _retain_controls(tmp_path, changed)
    assert not (tmp_path/'new_control.json').exists()
    assert {name: custody(tmp_path/name) for name in original} == before
    assert {name: (tmp_path/name).read_bytes() for name in original} == original


def test_partial_identical_controls_can_complete_without_replacing_existing_files(tmp_path):
    (tmp_path/'catalog.ddk.json').write_bytes(b'held schema')
    held = custody(tmp_path/'catalog.ddk.json')
    query = 'queries/' + 'a' * 64 + '.sql'
    controls = {'catalog.ddk.json': b'held schema', query: b'SELECT 1', 'manifest.json': b'completed manifest'}
    _retain_controls(tmp_path, controls)
    assert custody(tmp_path/'catalog.ddk.json') == held
    assert (tmp_path/query).read_bytes() == b'SELECT 1'
    assert (tmp_path/'manifest.json').read_bytes() == b'completed manifest'


def test_retained_control_refuses_symlink_parent(tmp_path):
    outside = tmp_path/'outside'
    outside.mkdir()
    output = tmp_path/'release'
    output.mkdir()
    (output/'queries').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='Unsafe retained release control path'):
        _retain_controls(output, {'queries/' + 'a' * 64 + '.sql': b'SELECT 1'})
    assert not list(outside.iterdir())


@pytest.mark.parametrize('existing_parent', [False, True])
def test_file_parent_conflict_refuses_before_any_new_control_is_written(tmp_path, existing_parent):
    query = 'queries/' + 'a' * 64 + '.sql'
    controls = {'new_control.json': b'new', query: b'SELECT 1', 'manifest.json': b'new manifest'}
    if existing_parent:
        (tmp_path/'queries').write_bytes(b'retained original')
        before = custody(tmp_path/'queries')
    else:
        # Both names are individually safe, but cannot be files together.
        controls['queries'] = b'conflicting flat control'
    with pytest.raises(ValueError, match='parent is not a directory'):
        _retain_controls(tmp_path, controls)
    assert not (tmp_path/'new_control.json').exists()
    assert not (tmp_path/'manifest.json').exists()
    if existing_parent:
        assert custody(tmp_path/'queries') == before
        assert (tmp_path/'queries').read_bytes() == b'retained original'
    else:
        assert not list(tmp_path.iterdir())


def test_invalid_control_bytes_refuse_before_any_file_is_written(tmp_path):
    with pytest.raises(ValueError, match='content must be bytes'):
        _retain_controls(tmp_path, {'new_control.json': b'new', 'bad.json': 'not encoded'})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('alias', ['parent', 'symlink'])
def test_controls_cannot_enter_native_storage_through_a_path_alias(tmp_path, alias):
    from viewer_publication.archive_format import _controls_directory

    native = tmp_path/'native'
    native.mkdir()
    if alias == 'symlink':
        (tmp_path/'alias').symlink_to(native, target_is_directory=True)
        controls = tmp_path/'alias/controls'
    else:
        (tmp_path/'other').mkdir()
        controls = tmp_path/'other/../native/controls'
    with pytest.raises(ValueError, match='symlink|separate'):
        _controls_directory(controls, (native,))
    assert not list(native.iterdir())


@pytest.mark.parametrize('native_status', ['pending', 'unknown', 'failed'])
def test_successful_observation_of_unfinished_work_never_calls_accept(tmp_path, native_status):
    from hashlib import sha256
    import json
    from types import SimpleNamespace
    from viewer_publication.archive_format import execute_native_release, NativeReleaseNotReady
    from viewer_publication.archive_catalog import capture_definitions

    request = dict(action='prepare', dataset='archive', operation='one')
    project = capture_definitions(tmp_path/'definitions')
    path = tmp_path/'release-request.json'
    raw = json.dumps(dict(native=request, workspace=str(tmp_path/'native'), project=str(project),
                          native_rules=dict(path=str(tmp_path/'native-rules.json'),sha256='a'*64),
                          controls_dir=str(tmp_path/'controls'))).encode()
    path.write_bytes(raw)
    response = dict(status='succeeded', result=dict(status=native_status),
                    evidence={'path': 'original-retained-observation'})
    calls = []
    def observe(workspace, value, *, snapshot_source=None):
        assert snapshot_source is None
        calls.append((workspace, value))
        return response
    with pytest.raises(NativeReleaseNotReady) as failure:
        execute_native_release(dict(path=str(path), sha256=sha256(raw).hexdigest()),
                               adapter=SimpleNamespace(managed_job=observe))
    assert failure.value.response is response
    assert calls == [(str(tmp_path/'native'), request)]
    assert not (tmp_path/'controls').exists()
