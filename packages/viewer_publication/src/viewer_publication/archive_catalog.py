"""Archive native invariants from the admitted standard catalog.

DDK owns declaration admission. This module retains only application SQL rules;
the native job evaluates them over its exact completed exports.
Exact native schema and field-ID qualification belongs to the shared runtime.
"""
from collections.abc import Mapping
from pathlib import Path

ASSEMBLY = 'urn:ddk:catalog:assembly'
PRODUCTION = 'archive-model'
CHECK_GENERATOR = {'id': 'urn:congressional-tech:archive:native-publication-checks', 'version': '1.0.0'}


def _local_catalog(result):
    """Use the complete private view from the same public or local assembly."""
    catalog = result.local_catalog
    if (result.local_report.get('decision') != 'passed' or catalog is None
            or catalog.get('audience') != 'local'):
        raise ValueError('Archive native checks require admitted local DDK declarations')
    return catalog


def native_catalog_mapping(result, job, *, private_outputs):
    """Name every native member's place in the public dataset catalog.

    Original source views and private materializations remain in the complete
    native candidate. This catalog describes public release datasets only; an
    explicit disposition preserves that distinction in its retained evidence.
    DDK verifies receipt membership and acceptance when assembling the catalog.
    """
    catalog = _local_catalog(result)
    definitions = catalog['extensions'][ASSEMBLY]['datasetDefinitions']
    by_file = {}
    for alias, table in definitions.items():
        name = table['physicalName']
        if name in by_file:
            raise ValueError('Archive output has multiple dataset declarations: ' + name)
        by_file[name] = alias
    private = set(private_outputs)
    names = [item['name'] for item in job['outputs']]
    if len(set(names)) != len(names) or private - set(names):
        raise ValueError('Private output scope differs from the native job')
    public = set(names) - private
    if not public or public - by_file.keys():
        raise ValueError('Every public native output needs one admitted dataset declaration')
    return dict(production=PRODUCTION, inputs={},
                outputs={name: by_file[name] for name in names if name in public},
                out_of_catalog=dict(
                    inputs=[dict(name=item['name'], reason='Source view retained in the complete native candidate; outside the public release dataset catalog.')
                            for item in job['inputs']],
                    outputs=[dict(name=name, reason='Private model materialization retained in the complete native candidate; not a public release asset.')
                             for name in names if name in private]))


def publication_checks(result, auxiliary, published):
    """Return native reports and their authored field/key coverage together.

    Required flags and scalar keys come directly from admitted ODCS properties
    and DDK identities. Application relationships retain their native SQL owner.
    Bindings identify coverage, not passed assertions. Shared qualification must
    bind the complete writer, original report SQL, accepted counter and a supported
    generator interpretation. These counts do not establish complete candidate
    membership, nested schema parity, external existence or source-value truth.
    """
    catalog = _local_catalog(result)
    definitions = catalog['extensions'][ASSEMBLY]['datasetDefinitions']
    return _publication_checks(definitions, catalog['identities'], auxiliary, published)


def _publication_checks(definitions, declared_identities, auxiliary, published):
    """One SQL generator for admission and captured-definition verification."""
    from viewer_publication.archive_format import CORE_RELATIONS

    published = set(published)
    tables = [(alias, definitions[alias]) for alias in sorted(definitions)]
    undeclared = published - {table['physicalName'] for table in definitions.values()}
    if undeclared:
        raise ValueError('Archive outputs lack admitted dataset definitions: ' + ', '.join(sorted(undeclared)))
    identities = {}
    for item in declared_identities:
        if item['kind'] == 'key':
            identities.setdefault(item['dataset'], []).append(item)
    bindings = []

    def bind(alias, table, paths, facet, column):
        bindings.append(dict(dataset=alias, facet=facet, paths=tuple(tuple(path) for path in paths),
            output=table['physicalName'], report='relationship_invariants', column=column))

    def exported(table):
        return 'outputs."' + table['physicalName'].replace('"', '""') + '"'

    checks = ['''(SELECT count(*) FROM details d WHERE d.link_key IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM links l WHERE l.link_key=d.link_key)) AS missing_primary_link''']
    for alias, table in tables:
        if table['name'] != 'detail' or table['physicalName'] not in published:
            continue
        checks.append(f'''(SELECT count(*) FROM (SELECT link_key FROM {exported(table)} WHERE link_key IS NOT NULL
        GROUP BY link_key HAVING count(*)>1)) AS duplicate_document_key''')
        if any(len(key['fields']) == 1 and tuple(key['fields'][0]['path']) == ({'field': 'link_key'},)
               and not key['fields'][0].get('virtual') for key in identities.get(alias, [])):
            bind(alias, table, [[{'field': 'link_key'}]], 'key_unique', 'duplicate_document_key')
    for alias, table in tables:
        name = table['name']
        if table['physicalName'] not in published:
            continue
        relation = CORE_RELATIONS.get(name) or (f'{name}_export' if name in auxiliary else None)
        required = [field['name'] for field in table['properties'] if field.get('required') is True]
        if relation is None:
            if required and table['physicalName'] in published:
                raise ValueError(f'Declared non-null column has no export relation: {name}.{required[0]}')
            continue
        for column in required:
            quoted = '"' + column.replace('"', '""') + '"'
            counter = f'null_{name}_{column}'
            checks.append(f'(SELECT count(*) FROM {exported(table)} WHERE {quoted} IS NULL) AS {counter}')
            bind(alias, table, [[{'field': column}]], 'required', counter)
            if (name in CORE_RELATIONS or name == 'url_state') and any(
                    len(key['fields']) == 1 and tuple(key['fields'][0]['path']) == ({'field': column},)
                    and not key['fields'][0].get('virtual') for key in identities.get(alias, [])):
                bind(alias, table, [[{'field': column}]], 'key_not_null', counter)
    for alias, table in tables:
        name = table['name']
        if table['physicalName'] not in published or name not in auxiliary or name == 'url_state':
            continue  # url_state has its own native uniqueness diagnostic.
        keys = identities.get(alias, [])
        if len(keys) != 1 or any(field.get('virtual') or len(field['path']) != 1
                                or 'field' not in field['path'][0] for field in keys[0]['fields']):
            raise ValueError(f'Archive export requires a declared physical scalar key: {name}')
        types = {field['name']: field['logicalType'] for field in table['properties']}
        if any(types[field['path'][0]['field']] in {'object', 'array'} for field in keys[0]['fields']):
            raise ValueError(f'Archive export requires a declared physical scalar key: {name}')
        columns = ['"' + field['path'][0]['field'].replace('"', '""') + '"' for field in keys[0]['fields']]
        fields = ','.join(columns)
        nulls = ' OR '.join(column + ' IS NULL' for column in columns)
        counter = f'invalid_{name}_key'
        checks.append(f'(SELECT count(*) FROM (SELECT {fields} FROM {exported(table)} GROUP BY {fields} HAVING count(*)>1 OR {nulls})) AS {counter}')
        paths = tuple(tuple(field['path']) for field in keys[0]['fields'])
        bind(alias, table, paths, 'key_unique', counter)
        properties = {field['name']: field for field in table['properties']}
        if all(properties[path[0]['field']].get('required') is True for path in paths):
            bind(alias, table, paths, 'key_not_null', counter)
    if 'meetings' in auxiliary:
        checks.append('''(SELECT count(*) FROM (SELECT unnest(meeting_keys) AS key FROM ordered) refs
            WHERE key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM meetings_export m WHERE m.event_id=try_cast(refs.key AS BIGINT))) AS missing_document_meeting''')
        checks.append('''(SELECT count(*) FROM (SELECT unnest(transcripts) AS item FROM meetings_export) refs
            WHERE item['list_row'] IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ordered o WHERE o.list_row=refs.item['list_row'])) AS missing_transcript_document''')
    if 'retired_links' in auxiliary:
        # Data model §8.2, Retired keys: a ledger key is never also published, and
        # every redirect lands on a published key.
        checks.append('''(SELECT count(*) FROM retired_links_export r
            WHERE EXISTS (SELECT 1 FROM links l WHERE l.link_key=r.link_key)) AS retired_key_still_published''')
        checks.append('''(SELECT count(*) FROM retired_links_export r WHERE r.successor_key IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM links l WHERE l.link_key=r.successor_key)) AS missing_retired_successor''')
    if 'witnesses' in auxiliary:
        checks.append('''(SELECT count(*) FROM (SELECT unnest(witness_keys) AS key FROM ordered) refs
            WHERE key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM witnesses_export w WHERE w.witness_key=refs.key)) AS missing_document_witness''')
    if 'witnesses' in auxiliary and 'witness_key_map' in auxiliary:
        # An earlier key is never also published, every key it resolves to is, and the status says which
        # columns are set (ct-kb4w). One pass over each export: every key a map row names, published
        # exactly when it is not the row's old key.
        checks.append('''(SELECT count(*) FROM (SELECT m.old_key,unnest(array_concat(make_array(m.old_key),
                CASE WHEN m.witness_key IS NULL THEN m.candidate_keys ELSE array_append(m.candidate_keys,m.witness_key) END)) AS key
            FROM witness_key_map_export m) refs LEFT JOIN witnesses_export w ON w.witness_key=refs.key
            WHERE (refs.key=refs.old_key)=(w.witness_key IS NOT NULL)) AS misplaced_witness_key_map_key''')
        checks.append('''(SELECT count(*) FROM witness_key_map_export
            WHERE (status='unambiguous') <> (witness_key IS NOT NULL) OR (status='unresolved') <> (basis IS NULL)
            OR (status='ambiguous') <> (coalesce(cardinality(candidate_keys),0)>1)
            OR status NOT IN ('unambiguous','ambiguous','unresolved')) AS inconsistent_witness_key_map''')
    reports = [dict(name='relationship_invariants', sql='SELECT ' + ',\n'.join(checks))]
    return reports, bindings


def _verified_native_rule_records(context, original_job):
    """Bind counters to complete exports and their actual writer projection."""
    from viewer_publication.archive_format import CORE_RELATIONS, release_output_sql

    if context.production.get('alias') != PRODUCTION:
        raise ValueError('Archive native rules require the archive-model production')

    def named(items):
        result = {item['name']: item for item in items}
        if len(result) != len(items):
            raise ValueError('Native rule coverage requires unique original member names')
        return result

    outputs = named(original_job['outputs'])
    queries = named(original_job['queries'])
    auxiliary = set()
    for output, alias in context.outputs.items():
        table = context.datasets[alias]
        if output not in outputs or table['physicalName'] != output:
            raise ValueError('Native output differs from its authored dataset')
        if table['name'] not in CORE_RELATIONS:
            auxiliary.add(table['name'])
    reports, bindings = _publication_checks(context.datasets, context.identities, auxiliary, context.outputs)
    for report in reports:
        if queries.get(report['name']) != report:
            raise ValueError('Native report differs from the authored field/key checks')
    # These supported native export settings select/reorder fields and encode
    # every row. New filtering or expression settings need a qualified profile.
    settings_fields = {'profile', 'row_group_rows', 'order_by', 'columns',
                       'dictionary_columns', 'delta_columns', 'key_column', 'created_by', 'footer_limit'}
    for output in {binding['output'] for binding in bindings}:
        table = context.datasets[context.outputs[output]]
        writer = outputs[output]
        if writer.get('sql') != release_output_sql(table['name']):
            raise ValueError('Native output SQL differs from its complete declared writer')
        settings = writer['settings']
        if (not isinstance(settings, Mapping) or set(settings) != settings_fields
                or settings['profile'] not in {'whole', 'ranged', 'lookup'}):
            raise ValueError('Native rule coverage does not support these writer settings')
        columns = settings['columns']
        if (not isinstance(columns, (tuple, list)) or any(not isinstance(column, str) for column in columns)
                or (columns and (len(columns) != len(set(columns))
                    or set(columns) != {field['name'] for field in table['properties']}))):
            raise ValueError('Native writer projection differs from authored fields')
    return bindings


class ArchiveNativeRuleProfileV1:
    """Explicit application interpretation of captured SQL and writer coverage."""

    identity = CHECK_GENERATOR
    source = Path(__file__).resolve()

    def bindings(self, context, original_job):
        from ddk.catalog_native_rules import NativeRuleBinding

        return [NativeRuleBinding(**record) for record in _verified_native_rule_records(context, original_job)]
