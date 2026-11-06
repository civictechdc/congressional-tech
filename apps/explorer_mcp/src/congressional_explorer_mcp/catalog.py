"""Discovery directly from the selected, admitted DDK catalog and its files.

The producer owns definition checking. This reader checks delivery and its
checking decision; that decision does not establish data qualification.
"""
from hashlib import sha256
from pathlib import Path

from .models import ExplorerError, MAX_BYTES
from .release import encoded

ASSEMBLY = 'urn:ddk:catalog:assembly'
UPSTREAM = 'urn:congressional-tech:archive:upstream-relations'


def published_entities(catalog):
    """Read declared entity keys and direct document links without a qualification decision."""
    definitions = catalog['extensions'][ASSEMBLY]['datasetDefinitions']
    names = {item['alias']: definitions[item['alias']]['name'] for item in catalog['datasets']}
    relationships = catalog['relationships']
    address_paths = [[field['path'] for field in identity['fields']]
                     for identity in catalog['identities']
                     if names[identity['dataset']] == 'detail' and identity['kind'] == 'key']
    address_paths += [relation['target']['paths'] for relation in relationships
                      if names[relation['source']['dataset']] == 'detail'
                      and 'dataset' in relation['target']]
    keys = {}
    for identity in catalog['identities']:
        if identity['kind'] != 'key' or identity['scope'] != 'dataset_version':
            continue
        fields = [item['path'] for item in identity['fields']]
        if fields not in address_paths and all(len(path) == 1 and 'field' in path[0] for path in fields):
            keys[names[identity['dataset']]] = [path[0]['field'] for path in fields]
    links = {}
    for relation in relationships:
        source, target = relation['source'], relation['target']
        paths = source['paths']
        name = names.get(target.get('dataset'))
        if (names[source['dataset']] == 'list' and name in keys
                and len(paths) == 1 and len(paths[0]) == 2 and paths[0][1] == {'each': True}
                and target['paths'] == [[{'field': field}] for field in keys[name]]):
            links.setdefault(name, paths[0][0]['field'])
    return keys, links



class CatalogDiscovery:
    def __init__(self, selection):
        controls = selection['controls']
        self.catalog = controls['catalog.ddk']
        self.report = controls.get('catalog.report', {})
        if self.catalog.get('kind') != 'catalog' or self.catalog.get('specVersion') != '0.1':
            raise ExplorerError('Unsupported DDK catalog version')
        if self.catalog.get('audience') != 'public':
            raise ExplorerError('Archive discovery requires an admitted public catalog')
        if self.report.get('decision') != 'passed':
            raise ExplorerError('DDK catalog checking did not pass; incomplete or failed metadata cannot select a release')
        delivered = {item['name']: item for item in selection['manifest']['files']}
        companions = {item['path']: item for item in self.catalog['files']}
        if 'catalog.report.json' not in companions:
            raise ExplorerError('DDK catalog lacks its admitted checking report')
        for name, item in companions.items():
            if name not in delivered or item['sha256'] != delivered[name]['sha256']:
                raise ExplorerError(f'DDK companion differs from release delivery: {name}')
        assembly = self.catalog.get('extensions', {}).get(ASSEMBLY, {})
        if 'datasetDefinitions' not in assembly:
            raise ExplorerError('DDK catalog does not disclose effective field definitions')
        self.definitions = assembly['datasetDefinitions']
        self.datasets = {item['alias']: item for item in self.catalog['datasets']}
        self.names = {alias: self.definitions[alias]['name'] for alias in self.datasets}
        self.aliases = {name: alias for alias, name in self.names.items()}
        self.relationships = self.catalog['relationships']
        self.recipes = self.catalog['recipes']
        root_metadata = [item['extensions'] for item in assembly.get('projectExtensions', [])
                         if item['project'] == self.catalog['project'] and item['namespace'] == '']
        self.upstream = root_metadata[0].get(UPSTREAM, []) if root_metadata else []
        self.selection = selection
        self.companions = companions

    def entities(self, selection):
        return published_entities(self.catalog)

    def _available(self, value, aliases):
        missing = sorted({self.names[alias] for alias in aliases} - self.selection['tables'].keys())
        return dict(value, available=not missing, missing_tables=missing)

    def _relationship(self, value):
        return self._available(value, [item['dataset'] for item in (value['source'], value['target']) if 'dataset' in item])

    def _recipe(self, value, *, sql=False):
        result = self._available(value, value['inputs'].values())
        if sql:
            name = value['sql']
            expected = self.companions[name]
            retained = self.selection['files'][expected['sha256']]['path']
            with Path(retained).open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ExplorerError('Recipe SQL exceeds the response budget')
            if sha256(data).hexdigest() != expected['sha256']:
                raise ExplorerError('Retained recipe SQL differs from the admitted catalog')
            result.update(sql_path=name, sql=data.decode('utf-8'))
        return result

    @staticmethod
    def _select(values, selector):
        return next((item for item in values if item['id'] == selector), None)

    def dataset_info(self, reader, query):
        table, relationship, recipe = (query.get(key) for key in ('table', 'relationship', 'recipe'))
        if sum(value is not None for value in (table, relationship, recipe)) > 1:
            raise ExplorerError('Choose one table, relationship, or recipe selector')
        common = dict(release_id=reader.release_id, metadata_format='ddk.catalog/0.1',
                      catalog_id=self.catalog['id'], catalog_checking=self.report['decision'])
        if relationship is not None and self._select(self.relationships, relationship) is None:
            value = self._select(self.upstream, relationship)
            if value is not None:
                missing = sorted({join['table'] for join in value['joins']} - self.selection['tables'].keys())
                return dict(common, upstream=True, **value, missing_tables=missing)
        for selector, values, describe in ((relationship, self.relationships, self._relationship),
                                            (recipe, self.recipes, lambda value: self._recipe(value, sql=True))):
            if selector is not None:
                value = self._select(values, selector)
                if value is None:
                    raise ExplorerError(f'Unknown relationship or recipe {selector!r}; use get_dataset_info for published IDs')
                return dict(common, **describe(value))
        if table is not None:
            if table in self.selection['controls']:
                value = self.selection['controls'][table]
                if len(encoded(value)) > MAX_BYTES - 4096:
                    raise ExplorerError('Published control exceeds 128 KiB; use a table, relationship, or recipe selector')
                return value
            alias = self.aliases.get(table)
            if alias is None:
                reader.require(table)
                return dict(common, table=table, available=True, columns=reader.schemas[table])
            return dict(common, table=table, available=table in reader.schemas,
                columns=reader.schemas.get(table, {}), dataset=self.datasets[alias],
                definition=self.definitions[alias],
                identities=[item for item in self.catalog['identities'] if item['dataset'] == alias],
                versions=[item for item in self.catalog['versions'] if item['dataset'] == alias],
                coverage=[dict(file=item['name'], coverage=item.get('coverage', {}))
                          for item in self.selection['manifest']['files']
                          if item['name'].endswith('.parquet')
                          and (item.get('shard') or item['name'].removesuffix('.parquet')) == table],
                outgoing=[item['id'] for item in self.relationships if item['source'].get('dataset') == alias],
                incoming=[item['id'] for item in self.relationships if item['target'].get('dataset') == alias],
                recipes=[item['id'] for item in self.recipes if alias in item['inputs'].values()])
        tables = {name: dict(rows=sum(part['rows'] for part in parts), columns=list(reader.schemas[name]))
                  for name, parts in self.selection['tables'].items()}
        return dict(common, tables=tables, views=dict(documents='List and detail joined by release-local list_row'),
            entity_keys=reader.entity_keys, missing_entities=sorted(reader.entity_keys.keys() - tables.keys()),
            relationships=[self._relationship({key: item[key] for key in ('id', 'source', 'target')})
                           for item in self.relationships],
            recipes=[self._recipe({key: item[key] for key in ('id', 'title', 'inputs') if key in item})
                     for item in self.recipes],
            upstream_relations=self.upstream,
            coverage=[dict(file=item['name'], coverage=item.get('coverage', {}))
                      for item in self.selection['manifest']['files'] if item['name'].endswith('.parquet')],
            notes=['Missing tables are unavailable, not empty. Null fields retain the selected release values.',
                   'Catalog checking does not establish data qualification; identities and relationships are declarations.',
                   'Select a recipe to read its verified SQL companion, parameters and result grain.',
                   'Recipe parameters use the declared parameterOrder with positional SQL placeholders.',
                   'Witnesses are appearances; names do not establish identity or document ownership.'],
            limits=dict(page_rows=100, sql_rows=200, response_bytes=MAX_BYTES, duckdb_memory='512MB', spill='512MB'))
