"""Read genuine DDK artifacts; the small equality fixture is not archive qualification."""
import json
import shutil
import subprocess

import pytest

from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.catalog import published_entities, UPSTREAM
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import prepare
from conftest import REPO, manifest


@pytest.fixture(scope='module')
def catalog_release(phase2, tmp_path_factory):
    root = tmp_path_factory.mktemp('ddk-consumer')
    source = root / 'project'
    source.mkdir()
    # This independent two-table scenario exercises supported equality semantics.
    # Its passed DDK report does not stand in for the 70-relationship archive.
    contract = json.loads((REPO / 'model/ddk/archive.odcs.json').read_text())
    contract['id'] = 'urn:test:mcp:contract'
    contract['schema'] = [item for item in contract['schema'] if item['name'] in ('bills', 'members')]
    (source / 'contract.odcs.json').write_text(json.dumps(contract))
    product = dict(apiVersion='v1.1.0', kind='DataProduct', id='urn:test:mcp:product', version='1.0.0',
                   name='Two-table MCP delivery fixture', status='active',
                   outputPorts=[dict(name=name, contractId=contract['id'], version='1.0.0') for name in ('bills', 'members')])
    (source / 'product.odps.json').write_text(json.dumps(product))
    sql = ('SELECT b.bill_id,m.name FROM bills b JOIN members m ON b.sponsor_bioguide_id=m.bioguide_id '
           'WHERE b.bill_id=?')
    (source / 'bill-sponsor.sql').write_text(sql)
    relation = dict(id='urn:test:mcp:relationship:bill_sponsor',
                    source=dict(dataset='bills', paths=[[dict(field='sponsor_bioguide_id')]]),
                    target=dict(dataset='members', paths=[[dict(field='bioguide_id')]]),
                    match='equal', cardinality='many_to_one', scope='same_release',
                    resolution='unresolved_allowed', meaning='Declared sponsor reference in this fixture.', nulls='skip')
    project = dict(specVersion='0.1', kind='project', id='urn:test:mcp:project', version='1.0.0',
        requiredChecks=['core.documents', 'core.references', 'core.graph', 'core.calls', 'core.datasets',
                        'core.policies', 'catalog.relationships'],
        artifacts={name: dict(kind='dataset', path='contract.odcs.json', object=name,
                             catalogId='urn:test:mcp:dataset:' + name) for name in ('bills', 'members')},
        catalog=dict(id='urn:test:mcp:catalog',
            ports=[dict(product='product', direction='output', port=name, version='1.0.0', dataset=name)
                   for name in ('bills', 'members')],
            identities=[dict(dataset=name, kind='key', scope='dataset_version', meaning='Declared fixture identifier.',
                             fields=[dict(path=[dict(field=field)], virtual=False, physicalType='string')])
                        for name, field in (('bills', 'bill_id'), ('members', 'bioguide_id'))],
            relationships=[relation],
            recipes=[dict(id='urn:test:mcp:recipe:bill_sponsor', title='Fixture sponsor', notes=['Equality-only delivery test.'],
                          contextualRelationships=[], parameterOrder=['bill_id'], sql='bill-sponsor.sql', dialect='duckdb',
                          inputs=dict(bills='bills', members='members'), relationships=[relation['id']],
                          parameters=dict(type='object', properties=dict(bill_id=dict(type='string', examples=['119-hr-1'])),
                                          required=['bill_id'], additionalProperties=False),
                          resultGrain='One bill sponsor')]))
    project['artifacts']['product'] = dict(kind='product', path='product.odps.json')
    project['extensions'] = {UPSTREAM: [dict(id='bill_actions', family='bill-family', table='bill_actions',
        key_columns=['bill_id'], joins=[dict(table='bills', field='bill_id')], row_meaning='One recorded bill action',
        limits='External history.', available=True, generation='f' * 64,
        path='generations/bill-family/' + 'f' * 64 + '/bill_actions.parquet')]}
    (source / 'project.ddk.json').write_text(json.dumps(project))
    def paths(value, prefix=()):
        for field in value.get('properties', []):
            path = (*prefix, {'field': field['name']})
            yield list(path)
            yield from paths(field, path)
        if 'items' in value:
            path = (*prefix, {'each': True})
            yield list(path)
            yield from paths(value['items'], path)
    policy = dict(identifiers=[project['id'], project['catalog']['id'], contract['id'], product['id'],
                              relation['id'], 'urn:test:mcp:recipe:bill_sponsor',
                              'urn:test:mcp:dataset:bills', 'urn:test:mcp:dataset:members'],
                  aliases=['bills', 'members', 'product'], descriptions=True,
                  recipes=['urn:test:mcp:recipe:bill_sponsor'],
                  definitionFields={'urn:test:mcp:dataset:' + item['name']: list(paths(item))
                                    for item in contract['schema']},
                  projectExtensions=[dict(project=dict(id=project['id'], version=project['version']), extensions=[UPSTREAM])])
    (source / 'public.json').write_text(json.dumps(policy))
    output = root / 'catalog'
    script = '''from ddk.catalog import assemble_catalog
from viewer_publication.archive_format import _catalog_artifacts, _retain_controls
from pathlib import Path
import json,sys
result=assemble_catalog(sys.argv[1],exports=['catalog.dcat'])
if result.report["decision"] != "passed":
    print(json.dumps(result.report)); sys.exit(1)
try:
    _catalog_artifacts(result)
except ValueError as error:
    assert "public DDK catalog" in str(error)
else:
    raise AssertionError("Local catalog cannot enter public archive delivery")
local=Path(sys.argv[2]).parent/'local-catalog'; local.mkdir()
_retain_controls(local,result.artifacts)
public=assemble_catalog(sys.argv[1],disclosure_policy=sys.argv[3],exports=['catalog.dcat'])
assert public.report["decision"] == "passed", public.report
assert public.catalog["audience"] == "public"
output=Path(sys.argv[2]); output.mkdir()
_retain_controls(output,_catalog_artifacts(public))
'''
    result = subprocess.run([str(REPO / '.venv/bin/python'), '-c', script,
                             str(source / 'project.ddk.json'), str(output), str(source / 'public.json')], cwd=REPO,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    release = root / 'release'
    shutil.copytree(phase2.parent, release, ignore=shutil.ignore_patterns(
        'catalog.*.json', 'discovery.dcat.json', 'queries', 'lineage', 'manifest.json'))
    (release / 'schema.json').unlink(missing_ok=True)
    shutil.copytree(output, release, dirs_exist_ok=True)
    return manifest(release)


def test_standard_catalog_is_the_discovery_and_recipe_owner(catalog_release, tmp_path):
    reader = Reader(prepare(tmp_path, catalog_release))
    try:
        info = reader.dataset_info({})
        assert info['metadata_format'] == 'ddk.catalog/0.1'
        assert info['catalog_checking'] == 'passed' and 'qualification' not in info
        assert info['coverage']
        assert any(item['name'] == 'discovery.dcat.json' for item in reader.selection['manifest']['files'])
        assert info['entity_keys'] == {'bills': ['bill_id'], 'members': ['bioguide_id']}
        table = reader.dataset_info({'table': 'bills'})
        assert table['definition']['name'] == 'bills'
        assert table['coverage'][0]['file'] == 'bills.parquet'
        assert any(item['name'] == 'floor_votes' and item['logicalType'] == 'array'
                   for item in table['definition']['properties'])
        relation = reader.dataset_info({'relationship': 'urn:test:mcp:relationship:bill_sponsor'})
        assert relation['target'] == {'dataset': 'members', 'paths': [[{'field': 'bioguide_id'}]]}
        recipe = reader.dataset_info({'recipe': 'urn:test:mcp:recipe:bill_sponsor'})
        assert recipe['available'] and recipe['inputs'] == {'bills': 'bills', 'members': 'members'}
        assert recipe['parameterOrder'] == ['bill_id']
        upstream = reader.dataset_info({'relationship': 'bill_actions'})
        assert upstream['upstream'] and upstream['missing_tables'] == []
        assert upstream['generation'] == 'f' * 64
        assert reader.query_sql({'sql': recipe['sql'], 'parameters': ['119-hr-1']})['rows'] == [
            {'bill_id': '119-hr-1', 'name': 'Sam Example'}]
        assert reader.dataset_info({'table': 'catalog.ddk'})['kind'] == 'catalog'
    finally:
        reader.close()


def test_actual_archive_keys_keep_document_addresses_separate_while_qualification_is_incomplete(tmp_path):
    inspection = tmp_path / 'archive-inspection.json'
    script = ('from ddk.catalog import assemble_catalog; from pathlib import Path; import json,sys; '
              'r=assemble_catalog(sys.argv[1]); '
              'Path(sys.argv[2]).write_text(json.dumps({"catalog":r.catalog,"report":r.report}))')
    result = subprocess.run([str(REPO / '.venv/bin/python'), '-c', script,
                             str(REPO / 'model/ddk/project.ddk.json'), str(inspection)], cwd=REPO,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    admitted = json.loads(inspection.read_text())
    assert admitted['report']['decision'] == 'incomplete'
    assert admitted['catalog'] is not None
    keys, links = published_entities(admitted['catalog'])
    baseline = json.loads((REPO / 'model/registries/release-schema.json').read_text())
    expected = {item['name'].removesuffix('.parquet'): item['identity']['fields'] for item in baseline['files']
                if item['identity']['scope'] == 'published identifier'
                and item['name'] not in ('links.parquet', 'retired_links.parquet')}
    assert keys == expected
    assert links['witnesses'] == 'witness_keys'
    assert 'links' not in keys and 'retired_links' not in keys


def test_catalog_recipe_missing_delivery_is_unavailable_not_empty(catalog_release, tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(catalog_release.parent, root)
    (root / 'members.parquet').unlink()
    reader = Reader(prepare(tmp_path / 'selected', manifest(root)))
    try:
        recipe = reader.dataset_info({'recipe': 'urn:test:mcp:recipe:bill_sponsor'})
        assert recipe['available'] is False and recipe['missing_tables'] == ['members']
        assert reader.dataset_info({'table': 'members'})['available'] is False
    finally:
        reader.close()


@pytest.mark.parametrize('fault', ['incomplete', 'missing_report', 'missing_catalog', 'missing_lock', 'wrong_sql', 'local', 'definitions'])
def test_catalog_refuses_unadmitted_or_changed_delivery(catalog_release, tmp_path, fault):
    root = tmp_path / 'release'
    shutil.copytree(catalog_release.parent, root)
    if fault == 'incomplete':
        path = root / 'catalog.report.json'
        value = json.loads(path.read_text())
        value['decision'] = 'incomplete'
        path.write_text(json.dumps(value))
    elif fault == 'missing_report':
        (root / 'catalog.report.json').unlink()
    elif fault == 'missing_catalog':
        (root / 'catalog.ddk.json').unlink()
    elif fault == 'missing_lock':
        (root / 'catalog.lock.json').unlink()
    elif fault == 'local':
        shutil.copytree(catalog_release.parent.parent/'local-catalog', root, dirs_exist_ok=True)
    elif fault == 'definitions':
        path = root / 'catalog.ddk.json'
        value = json.loads(path.read_text())
        del value['extensions']['urn:ddk:catalog:assembly']['datasetDefinitions']
        path.write_text(json.dumps(value))
    else:
        path = next((root / 'queries').glob('*.sql'))
        path.write_text('SELECT 1 AS wrong_recipe')
    with pytest.raises(ExplorerError, match='checking|required|differs|public catalog|field definitions'):
        prepare(tmp_path / 'selected', manifest(root))


def test_unknown_standard_catalog_version_refuses(catalog_release, tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(catalog_release.parent, root)
    path = root / 'catalog.ddk.json'
    value = json.loads(path.read_text())
    value['specVersion'] = 'future'
    path.write_text(json.dumps(value))
    with pytest.raises(ExplorerError, match='Unsupported DDK catalog version'):
        prepare(tmp_path / 'selected', manifest(root))
