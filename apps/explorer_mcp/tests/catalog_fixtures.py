"""Real public declaration artifacts for bounded reader fixtures, without native qualification."""
import json
from pathlib import Path
import shutil
import subprocess


def assemble_catalog_fixture(repository, root, *, change_project=None, change_definitions=None):
    source = root / 'definitions'
    shutil.copytree(repository / 'model/ddk', source)
    project = json.loads((source / 'project.ddk.json').read_text())
    contract = json.loads((source / 'archive.odcs.json').read_text())
    product = json.loads((source / 'archive.odps.json').read_text())
    # A declared future table exercises reader extensibility without changing MCP code.
    contract['schema'].append(dict(id='future_data', name='future_data', physicalName='future_data.parquet',
        logicalType='object', businessName='Future reader example (fixture)', dataGranularityDescription='One future fixture row',
        description='Synthetic reader example for testing future fields and exact decimals; not observed congressional data.',
        properties=[dict(name='future_field', logicalType='string', physicalType='string', required=True, description='Synthetic example text for reader extensibility.'),
                    dict(name='amount', logicalType='number', physicalType='decimal128(38,18)', required=True, description='Synthetic exact decimal used to check numeric precision.')]))
    project['artifacts']['future-data'] = dict(kind='dataset', path='archive.odcs.json', object='future_data',
        catalogId='urn:congressional-tech:archive:dataset:future-data', role='application')
    product['outputPorts'].append(dict(name='future-data', contractId=contract['id'], version=contract['version']))
    owner = next(alias for alias, row in project['artifacts'].items() if row['kind'] == 'product')
    project['catalog']['ports'].append(dict(product=owner, direction='output', port='future-data', version=contract['version'], dataset='future-data'))
    if change_project is not None:
        change_project(project)
    if change_definitions is not None:
        change_definitions(project, contract, product)
    (source/'project.ddk.json').write_text(json.dumps(project))
    (source/'archive.odcs.json').write_text(json.dumps(contract))
    (source/'archive.odps.json').write_text(json.dumps(product))

    def paths(value, prefix=()):
        yield list(prefix)
        for field in value.get('properties', []):
            path = (*prefix, {'field': field['name']})
            yield from paths(field, path)
        if 'items' in value:
            path = (*prefix, {'each': True})
            yield from paths(value['items'], path)

    datasets = {alias: row for alias, row in project['artifacts'].items() if row['kind'] == 'dataset'}
    identifiers = {project['id'], project['catalog']['id'], contract['id'], product['id']}
    identifiers.update(row['catalogId'] for row in datasets.values())
    for row in project['catalog']['relationships']:
        identifiers.add(row['id'])
        if 'external' in row['target']:
            identifiers.add(row['target']['external'])
        if 'rule' in row:
            identifiers.add(row['rule']['id'])
    identifiers.update(row['id'] for row in project['catalog']['recipes'])
    identifiers.add('urn:congressional-tech:archive:relationship-profile')
    definitions = {row['name']: row for row in contract['schema']}
    policy = dict(identifiers=sorted(identifiers),
        aliases=sorted(set(project['artifacts']) | {row['object'] for row in datasets.values()}),
        descriptions=True, recipes=[row['id'] for row in project['catalog']['recipes']],
        definitionFields={row['catalogId']: list(paths(definitions[row['object']])) for row in datasets.values()},
        projectExtensions=[dict(project=dict(id=project['id'], version=project['version']),
                                extensions=list(project['extensions']))])
    policy_path = source / 'public.json'
    policy_path.write_text(json.dumps(policy))
    output = root / 'artifacts'
    script = '''from ddk.catalog import assemble_catalog
from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1
from viewer_publication.archive_format import _retain_controls, _catalog_artifacts
from pathlib import Path
import json,sys
result=assemble_catalog(sys.argv[1],disclosure_policy=sys.argv[2],
    relationship_profile=ArchiveRelationshipProfileV1(),permitted_roots=[sys.argv[3],sys.argv[4]])
assert result.report["decision"] == "passed",result.report
assert not result.catalog["versions"] and not result.catalog["checks"]
output=Path(sys.argv[5]);output.mkdir()
_retain_controls(output,_catalog_artifacts(result))
'''
    result = subprocess.run([str(repository / '.venv/bin/python'), '-c', script,
        str(source/'project.ddk.json'), str(policy_path), str(repository), str(root), str(output)],
        cwd=repository, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return output
