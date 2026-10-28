"""F5 preparation preserves source scopes, tracked sources and shared boundaries."""
import fnmatch
import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def inventory():
    path=Path(__file__).resolve().parents[2]/'scripts/measure/cxb_switch_deletions.py'
    spec=importlib.util.spec_from_file_location('switch_inventory_under_test',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_function_local_import_does_not_rebind_later_global_calls(inventory):
    source=b'''from package.covers import cover
def fingerprint():
    from package import cover
    return cover()
def later():
    return cover()
def shadow(cover):
    return cover()
'''
    calls={row['scope']:row['target'] for row in inventory.py_index('example.py',source)['calls']}
    assert calls['fingerprint']=='package.cover'
    assert calls['later']=='package.covers.cover'
    assert calls['shadow'].startswith('<unresolved-local>.')


def test_class_import_is_visible_in_class_body_but_not_method_globals(inventory):
    source=b'''from package.covers import cover
class Wrapper:
    from alternate import cover
    value=cover()
    def method(self):
        return cover()
'''
    calls={row['scope']:row['target'] for row in inventory.py_index('example.py',source)['calls']}
    assert calls['Wrapper']=='alternate.cover'
    assert calls['Wrapper.method']=='package.covers.cover'


def test_nested_definitions_are_qualified_and_unknown_calls_stay_unknown(inventory):
    source=b'''def caller(argument):
    def nested():
        return 1
    nested()
    argument()
    len([])
    unknown.run()
'''
    calls={row['name']:row for row in inventory.py_index('example.py',source)['calls']}
    assert calls['nested']['target']=='example.caller.nested'
    assert calls['nested']['resolution']=='lexical_definition_reference'
    assert calls['argument']['resolution']=='unresolved_local_call_syntax'
    assert calls['len']['resolution']=='unresolved_name_call_syntax'
    assert calls['unknown.run']['resolution']=='unresolved_attribute_call_syntax'


def test_tracked_target_source_is_read_and_build_target_is_excluded(inventory,tmp_path):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    source='src/engine/history/target/tests.rs'
    build='target/debug/generated.rs'
    for path in (source,build):
        file=tmp_path/path;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text('fn fixture() {}\n')
    subprocess.run(['git','-C',str(tmp_path),'add','.'],check=True)
    tree=subprocess.check_output(['git','-C',str(tmp_path),'write-tree']).decode().strip()
    _,entries,bodies=inventory.snapshot(tmp_path,tree)
    assert source in entries and bodies[source]==b'fn fixture() {}\n'
    assert build not in entries
    assert not inventory.safe('packages/source-fetch/target/debug/generated.rs')
    assert not inventory.safe('../outside.py')


def test_engine_lifecycle_integration_tests_are_in_the_deferred_group(inventory):
    group=next(g for g in inventory.seeds() if g['binding_row']==19)
    for path in ('tests/backfill.rs','tests/continuous_backfill.rs',
                 'tests/availability_retirement.rs','tests/restore.rs','tests/succession.rs'):
        assert any(fnmatch.fnmatch(path,p) for p in group['patterns']),path
    assert not any(fnmatch.fnmatch('tests/sql_jobs.rs',p) for p in group['patterns'])


def test_current_native_cli_adapter_is_not_a_deletion_candidate(inventory):
    group=next(g for g in inventory.seeds() if g['binding_row']==19)
    assert not any(fnmatch.fnmatch('src/cli_args.rs',p) for p in group['patterns'])


def test_shared_client_fallback_has_exact_path_and_preserved_public_api(inventory):
    group=next(g for g in inventory.seeds() if g['binding_row']==10)
    path='packages/docspec_client/src/docspec_client/transport.py'
    assert {'_blake3_rotr32','_blake3_g','_blake3_round','_blake3_compress',
            '_blake3_chunk_output','blake3_hex'}.issubset(group['partial'][path])
    specs=group['partial']['packages/docspec_client/src/docspec_client/specs.py']
    assert 'producer_input_entry' not in specs
    assert 'build_export_spec' not in specs and 'parse_export_pin' not in specs
    assert 'scripts/measure/tests/test_viewer_benchmark.py' in inventory.SPEED_KEEP


def test_current_publisher_custody_helpers_survive_the_switch(inventory):
    assert 'packages/congress_shared/src/congress_shared/custody.py' in inventory.HARD_KEEP
    assert 'packages/congress_api/src/congress_api/retention/derived_files.py' in inventory.HARD_KEEP
    publication=next(g for g in inventory.seeds() if g['binding_row']==6)
    client='packages/viewer_publication/src/viewer_publication/client.py'
    assert 'require_publication_client' not in publication['partial'][client]
