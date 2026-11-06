"""Archive native invariants from the admitted standard catalog.

DDK owns declaration admission. This module retains only application SQL rules;
the native job evaluates them over its existing materialized output relations.
Exact native schema and field-ID qualification belongs to the shared runtime.
"""

ASSEMBLY = 'urn:ddk:catalog:assembly'


def dataset_definitions(result):
    """Use DDK's admitted effective objects without rebuilding a release schema."""
    if (result.report.get('decision') != 'passed' or result.catalog is None
            or result.catalog.get('audience') != 'local'):
        raise ValueError('Archive native checks require admitted local DDK declarations')
    return result.catalog['extensions'][ASSEMBLY]['datasetDefinitions']


def publication_checks(result, auxiliary, published):
    """Count required columns, entity keys and domain references before selection.

    Required flags and scalar keys come directly from admitted ODCS properties
    and DDK identities. Application relationships retain their native SQL owner.
    These counts do not establish complete candidate membership, nested schema
    parity, external existence or the truth of in-domain source values.
    """
    from viewer_publication.archive_format import CORE_RELATIONS

    definitions = dataset_definitions(result)
    published = set(published)
    undeclared = published - {table['physicalName'] for table in definitions.values()}
    if undeclared:
        raise ValueError('Archive outputs lack admitted dataset definitions: ' + ', '.join(sorted(undeclared)))
    identities = {}
    for item in result.catalog['identities']:
        if item['kind'] == 'key':
            identities.setdefault(item['dataset'], []).append(item)
    checks = ['''(SELECT count(*) FROM details d WHERE d.link_key IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM links l WHERE l.link_key=d.link_key)) AS missing_primary_link''',
        '''(SELECT count(*) FROM (SELECT link_key FROM details WHERE link_key IS NOT NULL
        GROUP BY link_key HAVING count(*)>1)) AS duplicate_document_key''']
    for alias, table in definitions.items():
        name = table['name']
        relation = CORE_RELATIONS.get(name) or (f'{name}_export' if name in auxiliary else None)
        required = [field['name'] for field in table['properties'] if field.get('required') is True]
        if relation is None:
            if required and table['physicalName'] in published:
                raise ValueError(f'Declared non-null column has no export relation: {name}.{required[0]}')
            continue
        for column in required:
            quoted = '"' + column.replace('"', '""') + '"'
            checks.append(f'(SELECT count(*) FROM {relation} WHERE {quoted} IS NULL) AS null_{name}_{column}')
    for alias, table in definitions.items():
        name = table['name']
        if name not in auxiliary or name == 'url_state':
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
        checks.append(f'(SELECT count(*) FROM (SELECT {fields} FROM {name}_export GROUP BY {fields} HAVING count(*)>1 OR {nulls})) AS invalid_{name}_key')
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
    return [dict(name='relationship_invariants', sql='SELECT ' + ',\n'.join(checks))] if checks else []
