"""One DuckDB connection over selected Parquet files; no model reconstruction."""
import base64
from contextlib import closing
from hashlib import sha256
import json
from tempfile import TemporaryDirectory

import duckdb
from .models import (MAX_BYTES, ENTITY_KEYS, DOCUMENT_LINKS, ExplorerError, exact_scalar,
                     DocumentSearch, DocumentQuery, EntitySearch, EntityQuery, SqlQuery)
from .release import encoded, quote, literal


class Reader:
    def __init__(self, selection, *, scratch=None):
        self.selection = selection
        self.release_id = selection['release_id']
        self.scratch = TemporaryDirectory(prefix='congress-mcp-query-') if scratch is None else None
        self.db = duckdb.connect(config=dict(threads=2, memory_limit='512MB',
            temp_directory=scratch or self.scratch.name, max_temp_directory_size='512MB',
            autoinstall_known_extensions=False, autoload_known_extensions=False,
            allow_persistent_secrets=False, enable_external_file_cache=False))
        try:
            for table, parts in selection['tables'].items():
                queries = []
                for part in parts:
                    extra = f",file_row_number+{part['offset']} AS list_row" if table in ('list', 'detail') else ''
                    queries.append(f'SELECT * EXCLUDE(file_row_number){extra} FROM read_parquet('
                                   f"{literal(part['path'])},file_row_number=true)")
                self.db.execute(f'CREATE VIEW {quote(table)} AS ' + ' UNION ALL '.join(queries))
            self.db.execute('CREATE VIEW documents AS SELECT l.*,d.* EXCLUDE(list_row) '
                            'FROM "list" l JOIN detail d USING(list_row)')
            allowed = [part['path'] for parts in selection['tables'].values() for part in parts]
            self.db.execute('SET allowed_paths=[' + ','.join(map(literal, allowed)) + ']')
            self.db.execute('SET enable_external_access=false')
            self.db.execute('SET lock_configuration=true')
            self.schemas = {table: {row[0]: row[1] for row in self.db.execute(f'DESCRIBE {quote(table)}').fetchall()}
                            for table in [*selection['tables'], 'documents']}
        except BaseException:
            self.close()
            raise

    def close(self):
        self.db.close()
        if self.scratch:
            self.scratch.cleanup()

    def require(self, table):
        if table not in self.schemas:
            raise ExplorerError(f'Table {table!r} is not published in this release; use get_dataset_info')

    def dataset_info(self, query):
        table, relationship, recipe = (query.get(key) for key in ('table', 'relationship', 'recipe'))
        if sum(value is not None for value in (table, relationship, recipe)) > 1:
            raise ExplorerError('Choose one table, relationship, or recipe selector')
        schema = self.selection['controls']['schema']
        declared = {item['name'].removesuffix('.parquet'): item for item in schema['files']}
        version = schema.get('relationships_version')
        relationships = schema.get('relationships', []) if version == 1 else []
        recipes = schema.get('recipes', []) if version == 1 else []

        def availability(value, required):
            missing = sorted(set(required) - self.selection['tables'].keys())
            return dict(value, available=not missing, missing_tables=missing)

        def relation_info(value):
            return availability(value, [endpoint['table'] for endpoint in (value['source'], value['target']) if 'table' in endpoint])

        def recipe_info(value):
            return availability(value, value['requires'])

        for selector, values, describe in ((relationship, relationships, relation_info), (recipe, recipes, recipe_info)):
            if selector is not None:
                if version != 1:
                    message = 'no published relationship metadata' if version is None else f'unsupported relationship metadata version {version}'
                    raise ExplorerError(f'This release has {message}; inspect its tables and raw schema')
                value = next((value for value in values if value['id'] == selector), None)
                if value is None:
                    raise ExplorerError(f'Unknown relationship or recipe {selector!r}; use get_dataset_info for published IDs')
                return dict(release_id=self.release_id, relationships_version=version, **describe(value))
        if table is not None:
            if table in self.selection['controls']:
                result = self.selection['controls'][table]
                if len(encoded(result)) > MAX_BYTES - 4096:
                    raise ExplorerError('Published control exceeds 128 KiB; use a table, relationship, or recipe selector')
                return result
            if table not in declared:
                self.require(table)
            meaning = declared.get(table, {})
            return dict(table=table, available=table in self.schemas, columns=self.schemas.get(table, {}),
                meanings=meaning.get('columns', []), purpose=meaning.get('purpose'), row_meaning=meaning.get('row_meaning'),
                identity=meaning.get('identity'), scope=meaning.get('gaps', []), notes=meaning.get('notes', {}),
                relationships_version=version,
                outgoing=[r['id'] for r in relationships if r['source'].get('table') == table],
                incoming=[r['id'] for r in relationships if r['target'].get('table') == table],
                recipes=[r['id'] for r in recipes if table in r['requires']])
        tables = {name: dict(rows=sum(p['rows'] for p in parts), columns=list(self.schemas[name]))
                  for name, parts in self.selection['tables'].items()}
        return dict(release_id=self.release_id, tables=tables,
            views=dict(documents='List and detail joined by release-local list_row'),
            missing_entities=sorted((set(ENTITY_KEYS) | {'rosters'}) - tables.keys()),
            relationships_version=version,
            relationship_metadata='published' if version == 1 else ('not published in this release' if version is None else 'unsupported version'),
            relationships=[relation_info({key: r[key] for key in ('id', 'source', 'target')}) for r in relationships],
            recipes=[recipe_info({key: r[key] for key in ('id', 'title', 'requires')}) for r in recipes],
            coverage=[dict(file=f['name'], coverage=f.get('coverage', {}))
                      for f in self.selection['manifest']['files'] if f['name'].endswith('.parquet')],
            notes=['Missing tables are unavailable, not empty. Null entity fields mean the release did not supply those values.',
                   'Witnesses are appearances; names do not establish identity or document ownership.',
                   'SQL preserves published types. BLOB values use DuckDB JSON escaping; hex(binary_column) gives portable identifiers.',
                   'References and cursors bind to this release. File URLs are returned for you to fetch and read.',
                   'Pass a relationship or recipe ID for join meaning or example SQL; examples are never run by discovery.'],
            limits=dict(page_rows=100, sql_rows=200, response_bytes=MAX_BYTES, duckdb_memory='512MB', spill='512MB'))

    def rows(self, sql, args=(), *, limit=100):
        """Serialize and byte-bound each row in DuckDB before Python decoding."""
        relation = self.db.sql(sql, params=list(args)).limit(limit + 1)
        if len(relation.columns) > 128:
            raise ExplorerError('Select at most 128 columns')
        if len(set(relation.columns)) != len(relation.columns):
            raise ExplorerError('Give duplicate result columns distinct aliases')
        columns = [dict(name=name, type=str(kind)) for name, kind in zip(relation.columns, relation.types)]
        fields = ','.join(f'{quote(name)} := {quote(name)}' for name in relation.columns)
        payload = relation.project(f'to_json(struct_pack({fields})) AS payload')
        cursor = payload.project(f'CASE WHEN octet_length(encode(payload)) <= {MAX_BYTES} THEN payload END AS payload')
        result, used, more = [], len(encoded(columns)) + 4096, False
        with closing(cursor.iter_rows(batch_size=1)) as iterator:
            for row in iterator:
                if len(result) == limit:
                    more = True
                    break
                if row[0] is None:
                    raise ExplorerError('Result row exceeds 128 KiB; select fewer fields or slice nested lists')
                value = json.loads(row[0], parse_float=str, parse_constant=str)
                size = len(encoded(value)) + 1
                if used + size > MAX_BYTES:
                    if not result:
                        raise ExplorerError('Result row exceeds the response budget')
                    more = True
                    break
                result.append(value); used += size
        return dict(rows=result, has_more=more, columns=columns)

    def query_sql(self, query):
        query = SqlQuery.model_validate(query)
        statements = self.db.extract_statements(query.sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ExplorerError('Use one read-only SELECT, including WITH or FROM-first SQL')
        result = self.rows(query.sql, query.parameters, limit=query.limit)
        result.update(release_id=self.release_id, truncated=result['has_more'])
        return result

    def page(self, query, sql, args, *, order):
        binding = sha256(encoded([self.release_id, query.model_dump(exclude={'cursor'})])).hexdigest()
        position = 0
        if query.cursor:
            try:
                saved = json.loads(base64.urlsafe_b64decode(query.cursor))
                if saved['binding'] != binding or type(saved['position']) is not int or saved['position'] < 0:
                    raise ValueError()
                position = saved['position']
            except (ValueError, KeyError, TypeError) as error:
                raise ExplorerError('Cursor belongs to another release or query') from error
        result = self.rows(sql + f' ORDER BY {order} OFFSET ?', [*args, position], limit=query.limit)
        result.pop('columns')
        if result['has_more']:
            result['next_cursor'] = base64.urlsafe_b64encode(encoded(dict(binding=binding, position=position+len(result['rows'])))).decode()
        result['release_id'] = self.release_id
        return result

    def file_url(self, body, suffix):
        base = self.selection.get('archive_origin')
        if not body or base is None:
            return None
        if len(body) != 64 or any(c not in '0123456789abcdef' for c in body.lower()) or suffix not in ('', '.pdf', '.gz'):
            raise ExplorerError('Invalid published body location')
        return f"{base.rstrip('/')}/bodies/sha256/{body[:2].lower()}/{body.lower()}{suffix}"

    def document_rows(self, result):
        for row in result['rows']:
            row['reference'] = dict(release_id=self.release_id, link_key=row.pop('link_key').lower())
            body, suffix = row.pop('saved_body'), row.pop('saved_suffix')
            row['saved_url'] = self.file_url(body, suffix)
            for alternate in row.get('alternates') or []:
                alternate['saved_url'] = self.file_url(alternate['body'], alternate['suffix'])
        return result

    def search_documents(self, value):
        query = DocumentSearch.model_validate(value)
        conditions, args = ([] if query.include_hidden else ['NOT coalesce(l.hidden,false)']), []
        if query.text:
            conditions.append("contains(lower(coalesce(l.filename,'')||' '||coalesce(l.title,'')),lower(?))")
            args.append(query.text)
        for column in ('congress', 'format'):
            if (value := getattr(query, column)) is not None:
                conditions.append(f'l.{column}=?'); args.append(value)
        for parameter, column in [('document_kind', 'document_kind'), ('committee_key', 'committee_keys'),
            ('meeting_key', 'meeting_keys'), ('measure_key', 'measure_keys'), ('witness_key', 'witness_keys'), ('bioguide_id', 'bioguide_ids')]:
            if (value := getattr(query, parameter)) is not None:
                conditions.append(f'list_contains(l.{column},?)'); args.append(value)
        return self.document_rows(self.page(query,
            'SELECT l.list_row,l.filename,l.title,l.congress,l.format,l.document_date,l.document_kind,l.saved_kind,'
            'hex(d.link_key) AS link_key,hex(d.saved_body) AS saved_body,d.saved_suffix '
            'FROM "list" l JOIN detail d USING(list_row) WHERE ' + (' AND '.join(conditions) or 'true'), args, order='l.list_row'))

    def get_document(self, value):
        query = DocumentQuery.model_validate(value)
        if query.release_id != self.release_id:
            raise ExplorerError('Document reference belongs to another release')
        match = self.db.execute('SELECT list_row FROM links WHERE link_key=unhex(?)', [query.link_key]).fetchall()
        if len(match) != 1:
            raise ExplorerError('Document link is absent or ambiguous in this release')
        position = match[0][0]
        if query.section == 'summary':
            if query.cursor:
                raise ExplorerError('Summary does not take a cursor')
            result = self.rows('SELECT * REPLACE(hex(link_key) AS link_key,hex(saved_body) AS saved_body,'
                               'list_transform(alternates,lambda a:struct_pack(format:=a.format,body:=hex(a.body),suffix:=a.suffix,size:=a.size)) AS alternates) '
                               'FROM documents WHERE list_row=?', [position], limit=1)
            result.pop('columns'); result['release_id'] = self.release_id
            self.document_rows(result)
            row = result['rows'][0]
            row['sections'] = dict(sources='Published source URLs and context', recoveries='Recovered files and their relationship to this document')
            return result
        columns = '*' if query.section == 'sources' else '* REPLACE(hex(body) AS body)'
        result = self.page(query, f'SELECT {columns} FROM {query.section} WHERE list_row=?', [position], order='ordinal')
        if query.section == 'recoveries':
            for row in result['rows']:
                row['saved_url'] = self.file_url(row['body'], row['suffix'])
        return result

    def search_entities(self, value):
        query = EntitySearch.model_validate(value)
        if query.table not in ENTITY_KEYS and query.table != 'rosters':
            raise ExplorerError('Choose a phase 2 entity table; get_dataset_info lists availability')
        self.require(query.table)
        columns = self.schemas[query.table]
        conditions, args = [], []
        if query.text:
            fields = [name for name in ('name', 'title', 'description', 'organization', 'position', 'video_key') if name in columns]
            conditions.append('(' + ' OR '.join(f'contains(lower(coalesce({quote(name)},\'\')),lower(?))' for name in fields) + ')' if fields else 'false')
            args += [query.text] * len(fields)
        for name, value in query.filters.items():
            if name not in columns or '[]' in columns[name] or columns[name].startswith(('STRUCT', 'MAP')):
                raise ExplorerError(f'Use a scalar published filter; query_sql supports nested {name!r}')
            query.filters[name] = value = exact_scalar(value, columns[name], f'{query.table}.{name}')
            conditions.append(f'{quote(name)}=?'); args.append(value)
        order = quote(ENTITY_KEYS[query.table]) if query.table in ENTITY_KEYS else 'congress,system_code,bioguide_id,rank'
        result = self.page(query, f'SELECT {self.entity_columns(query.table)} FROM {quote(query.table)} WHERE ' + (' AND '.join(conditions) or 'true'), args, order=order)
        return self.entity_rows(result)

    def entity_columns(self, table):
        if table == 'recordings':
            return '* REPLACE(list_transform(tracks,lambda t:struct_pack(body:=hex(t.body),suffix:=t.suffix,format:=t.format,language:=t.language,production:=t.production)) AS tracks)'
        return '*'

    def entity_rows(self, result):
        for row in result['rows']:
            for track in row.get('tracks') or []:
                track['saved_url'] = self.file_url(track['body'], track['suffix'])
        return result

    def get_entity(self, value):
        query = EntityQuery.model_validate(value)
        if query.table not in ENTITY_KEYS:
            raise ExplorerError('Entity table has no single identifier; use search_entities or query_sql')
        self.require(query.table)
        key = ENTITY_KEYS[query.table]
        query.id = exact_scalar(query.id, self.schemas[query.table][key], f'{query.table}.{key}')
        stored = self.db.execute(f'SELECT {quote(key)} FROM {quote(query.table)} WHERE {quote(key)}=? LIMIT 1', [query.id]).fetchall()
        if not stored:
            raise ExplorerError('Entity is absent from this release')
        query.id = stored[0][0]
        if query.section == 'documents':
            field = DOCUMENT_LINKS.get(query.table)
            if field:
                sql = f'list_contains(l.{field},?)'
            elif query.table == 'recordings':
                sql = 'EXISTS (SELECT 1 FROM recordings r,unnest(r.event_ids) e(event_id) WHERE r.video_key=? AND list_contains(l.meeting_keys,cast(e.event_id AS VARCHAR)))'
            else:
                raise ExplorerError('This entity has no published document relationship')
            return self.document_rows(self.page(query, 'SELECT l.list_row,l.filename,l.title,l.format,l.hidden,'
                'hex(d.link_key) AS link_key,hex(d.saved_body) AS saved_body,d.saved_suffix '
                'FROM "list" l JOIN detail d USING(list_row) WHERE NOT coalesce(l.hidden,false) AND ' + sql,
                [str(query.id)], order='l.list_row'))
        if query.cursor:
            raise ExplorerError('Record does not take a cursor; query_sql can slice large nested fields')
        result = self.rows(f'SELECT {self.entity_columns(query.table)} FROM {quote(query.table)} WHERE {quote(key)}=?', [query.id], limit=1)
        result.pop('columns'); result['release_id'] = self.release_id
        return self.entity_rows(result)
