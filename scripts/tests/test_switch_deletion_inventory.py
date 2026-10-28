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


def test_strip_scope_has_only_the_eighteen_congressional_tech_groups(inventory):
    groups=inventory.seeds()
    assert len(groups)==18
    assert {g['binding_row'] for g in groups}==set(range(1,19))
    assert all(g['repo']=='ct' for g in groups)


def test_current_native_cli_adapter_is_not_a_deletion_candidate(inventory):
    for group in inventory.seeds():
        assert not any(fnmatch.fnmatch('src/cli_args.rs',p) for p in group['patterns'])


@pytest.mark.parametrize('path,role',[
    ('packages/example/tests/test_old.py','test'),
    ('tests/fixtures/old.py','fixture'),
    ('model/fixtures/old.json','fixture'),
    ('scripts/measure/old.py','measurement'),
    ('scripts/measure/tests/test_old.py','test'),
    ('docs/old.md','documentation'),
    ('.github/workflows/capture.yml','production'),
    ('packages/congress_api/src/congress_api/lake/daily.py','production'),
])
def test_test_fixture_and_measurement_references_are_not_production_users(inventory,path,role):
    assert inventory.consumer_role(path)==role


def test_inventory_separates_production_users_from_removed_subject_tests(inventory,tmp_path):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    sources={
        'docs/plans/bindings-20261025.md':'# Binding\n',
        inventory.RET+'catalog_rows.py':'def obsolete(): pass\n',
        inventory.RET+'catalog_updates.py':'def obsolete(): pass\n',
        'packages/congress_api/tests/test_old.py':
            'from congress_api.retention import catalog_rows\ncatalog_rows.obsolete()\n',
        'scripts/measure/old.py':
            'from congress_api.retention import catalog_rows\ncatalog_rows.obsolete()\n',
        inventory.CA+'lake/daily.py':
            'from congress_api.retention import catalog_updates\ncatalog_updates.obsolete()\n',
        '.github/workflows/kept.yml':'run: python -m congress_api.retention.catalog_updates\n',
    }
    for path,source in sources.items():
        target=tmp_path/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(source)
    subprocess.run(['git','-C',str(tmp_path),'add','.'],check=True)
    tree=subprocess.check_output(['git','-C',str(tmp_path),'write-tree']).decode().strip()
    result=inventory.build(tmp_path,None,tree,None)
    assert len(result['groups'])==18
    assert all(row['repo']=='ct' for row in result['files'].values())
    old=result['files']['ct:'+inventory.RET+'catalog_rows.py']
    assert old['production_callers']==[]
    assert {c['consumer_role'] for c in old['static_callers']}=={'test','measurement'}
    live=result['files']['ct:'+inventory.RET+'catalog_updates.py']
    assert {c['path'] for c in live['production_callers']}=={
        inventory.CA+'lake/daily.py','.github/workflows/kept.yml'}
    graph=result['production_import_graph']
    assert inventory.CA+'lake/daily.py' in graph
    assert 'packages/congress_api/tests/test_old.py' not in graph
    assert 'scripts/measure/old.py' not in graph
    assert 'ct:packages/congress_api/tests/test_old.py' in result['files']


def test_shared_client_fallback_has_exact_path_and_preserved_public_api(inventory):
    group=next(g for g in inventory.seeds() if g['binding_row']==10)
    path='packages/docspec_client/src/docspec_client/transport.py'
    assert {'_blake3_rotr32','_blake3_g','_blake3_round','_blake3_compress',
            '_blake3_chunk_output','blake3_hex'}.issubset(group['partial'][path])
    specs=group['partial']['packages/docspec_client/src/docspec_client/specs.py']
    assert 'producer_input_entry' not in specs
    assert 'build_export_spec' not in specs and 'parse_export_pin' not in specs
    assert 'apps/site/scripts/measure-archive.mjs' in inventory.SPEED_KEEP
    assert 'scripts/measure/benchmark_viewer_browser.mjs' not in inventory.SPEED_KEEP
    measurements=next(g for g in inventory.seeds() if g['binding_row']==15)
    for path in ('scripts/measure/benchmark_viewer_browser.mjs',
                 'scripts/measure/tests/test_viewer_benchmark.py'):
        assert path in measurements['patterns']


def test_current_publisher_custody_helpers_survive_the_switch(inventory):
    assert 'packages/congress_shared/src/congress_shared/custody.py' in inventory.HARD_KEEP
    assert 'packages/congress_api/src/congress_api/retention/derived_files.py' in inventory.HARD_KEEP
    publication=next(g for g in inventory.seeds() if g['binding_row']==6)
    client='packages/viewer_publication/src/viewer_publication/client.py'
    assert 'require_publication_client' not in publication['partial'][client]


def test_first_flip_pointer_writer_and_receipt_dependencies_survive(inventory):
    assert set(inventory.PUBLICATION_CLIENT_KEEP)=={
        'require_publication_client','publish_manifest_pointer','VerifiedTransfer'}
    assert set(inventory.PUBLICATION_CLIENT_KEEP_IMPORTS)=={'dataclasses.dataclass','hashlib'}
    publication=next(g for g in inventory.seeds() if g['binding_row']==6)
    partial=publication['partial']['packages/viewer_publication/src/viewer_publication/client.py']
    assert not set(partial)&set(inventory.PUBLICATION_CLIENT_KEEP)
