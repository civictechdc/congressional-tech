"""One DuckDB connection over selected Parquet files; no model reconstruction."""
import base64
from contextlib import closing
from hashlib import sha256
import json
from tempfile import TemporaryDirectory

import duckdb
from .models import (MAX_BYTES, ExplorerError, exact_scalar,
                     DocumentSearch, DocumentQuery, EntitySearch, EntityQuery, SqlQuery)
from .release import encoded, quote, literal
from .hearing_reader import HearingReader

# Published display columns that text search reads, wherever a table has them.
TEXT_FIELDS = ('name', 'title', 'short_title', 'public_law_number', 'description', 'organization', 'position', 'video_key',
               'source_description', 'committee_label', 'handle', 'note', 'action_text', 'question', 'member_name')

DOCUMENT_SUMMARY_COLUMNS = (
    'l.list_row,l.filename,l.title,l.congress,l.format,l.document_date,d.document_date_source,'
    'l.first_captured,l.date_kind,l.document_kind,l.saved_kind,l.hidden,'
    'hex(d.link_key) AS link_key,hex(d.saved_body) AS saved_body,d.saved_suffix'
)


def published_entities(schema):
    """Entity tables and their document links as the release's schema states them; the schema is the one identity owner.

    An entity table has a primary key that is a published identifier. A table keyed by a document's
    address (detail's identity, or what detail links to: links, retired_links) is read through
    get_document instead. A document link is the list.<column>[] relationship whose target fields
    are the entity's whole identity.
    """
    files = {item['name'].removesuffix('.parquet'): item for item in schema.get('files', [])}
    relationships = schema.get('relationships', []) if schema.get('relationships_version') == 1 else []
    addresses = [(files.get('detail', {}).get('identity') or {}).get('fields')]
    addresses += [r['target']['fields'] for r in relationships if r['source'].get('table') == 'detail' and 'table' in r['target']]
    keys = {}
    for name, item in files.items():
        identity = item.get('identity') or {}
        if identity.get('kind') == 'primary_key' and identity.get('scope') == 'published identifier' \
                and identity.get('fields') and identity['fields'] not in addresses:
            keys[name] = list(identity['fields'])
    links = {}
    for relation in relationships:
        source, target, fields = relation['source'], relation['target'], relation['source'].get('fields', [])
        if source.get('table') == 'list' and len(fields) == 1 and fields[0].endswith('[]') \
                and target.get('table') in keys and target.get('fields') == keys[target['table']]:
            links.setdefault(target['table'], fields[0].removesuffix('[]'))
    return keys, links


from .legislative_reader import LegislativeReader


class Reader(HearingReader, LegislativeReader):
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
            # Newer detail files repeat list's columns; older ones share only list_row.
            list_names = {row[0] for row in self.db.execute('DESCRIBE "list"').fetchall()}
            repeated = [row[0] for row in self.db.execute('DESCRIBE detail').fetchall() if row[0] in list_names]
            self.db.execute('CREATE VIEW documents AS SELECT l.*,d.* EXCLUDE(' + ','.join(map(quote, repeated)) + ') '
                            'FROM "list" l JOIN detail d USING(list_row)')
            allowed = [part['path'] for parts in selection['tables'].values() for part in parts]
            self.db.execute('SET allowed_paths=[' + ','.join(map(literal, allowed)) + ']')
            self.db.execute('SET enable_external_access=false')
            self.db.execute('SET lock_configuration=true')
            self.schemas = {table: {row[0]: row[1] for row in self.db.execute(f'DESCRIBE {quote(table)}').fetchall()}
                            for table in [*selection['tables'], 'documents']}
            self.document_summary = DOCUMENT_SUMMARY_COLUMNS + (
                ',d.document_date_status' if 'document_date_status' in self.schemas['detail'] else '')
            self.entity_keys, self.document_links = published_entities(selection['controls']['schema'])
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

    def search_text(self, value):
        from .models import TextSearch
        from .text_index import TextIndex
        return TextIndex(self.selection).search(TextSearch.model_validate(value))

    def resolve_index_citation(self, value):
        if not self.selection['manifest'].get('text_index'):
            return dict(state='unavailable',reason='This release has no retained full-text index')
        from .text_index import TextIndex
        return TextIndex(self.selection).resolve(value)

    def entity_summary_fields(self, table):
        # Scalar fields keep summaries useful for new tables and older schemas,
        # without decoding the nested lists that dominate large entity records.
        return [name for name, kind in self.schemas.get(table, {}).items()
                if '[]' not in kind and not kind.startswith(('STRUCT', 'MAP', 'BLOB'))]

    def overview(self, query):
        return dict(release_id=self.release_id, tables=sorted(self.selection['tables']),
            capabilities=['metadata_search', 'entity_lookup', 'document_metadata', 'verified_document_text',
                          'batch_documents', 'read_only_sql', 'published_relationships_and_recipes'],
            corpus_text_index=self.selection['manifest'].get('text_index') or 'unavailable in this release',
            discovery=dict(status='get_dataset_status()', table='get_dataset_info(table=...)',
                           relationship='get_dataset_info(relationship=...)', recipe='get_dataset_info(recipe=...)',
                           all='get_dataset_info()'),
            limits=dict(response_bytes=MAX_BYTES, batch_items=10),
            notes=['Availability and coverage describe the selected release; missing data is unavailable.',
                   'Document search reads metadata. Body text uses verified archived files.',
                   'Entity mode=summary omits nested fields; fields selects exact published columns.'])

    def dataset_status(self, query):
        groups = {}
        for item in self.selection['manifest']['files']:
            if item['name'].endswith('.parquet'):
                groups.setdefault(item.get('shard') or item['name'].removesuffix('.parquet'), []).append(item)
        collections = {}
        for table, files in groups.items():
            coverage = [item.get('coverage', {}) for item in files]
            def bound(key, aggregate):
                values = [value[key] for value in coverage if value.get(key) is not None]
                return aggregate(values) if values else None
            updates = [item.get('source_updated_at') or item.get('coverage', {}).get('source_updated_at') for item in files]
            updates = [value for value in updates if value is not None]
            collections[table] = dict(rows=sum(item['rows'] for item in files),
                source_updated_at=max(updates) if updates else None,
                source_update_status='published' if updates else 'unavailable in this release',
                source_update_basis=sorted({str(item.get('source_update_basis') or item.get('coverage', {}).get('source_update_basis'))
                    for item in files if item.get('source_update_basis') or item.get('coverage', {}).get('source_update_basis')}),
                observed_bounds=dict(date_start=bound('date_start', min), date_end=bound('date_end', max),
                                     congress_start=bound('congress_start', min), congress_end=bound('congress_end', max)),
                gaps=list(dict.fromkeys(gap for value in coverage for gap in value.get('gaps', []))))
        publication = self.selection.get('publication', {})
        published_at = publication.get('published_at') or self.selection['manifest'].get('published_at')
        return dict(release_id=self.release_id, published_at=published_at,
            publication_status='published' if published_at else 'publication date unavailable in this release',
            publication_basis=publication.get('basis'), collections=collections,
            text_index=self.selection['manifest'].get('text_index') or 'unavailable in this release',
            notes=['Source updates are publisher-supplied update dates, not archive captures or legislative activity dates.',
                   'Observed record dates and Congress bounds do not establish complete history.',
                   'Release publication time describes selection of the release, not when its sources changed.'])

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

        upstream = schema.get('upstream_relations')
        if relationship is not None and upstream and relationship not in {r['id'] for r in relationships}:
            value = next((value for value in upstream if value['id'] == relationship), None)
            if value is not None:
                # An upstream pin and a selected local table are separate availability facts.
                local = sorted({join['table'] for join in value['joins']} - self.selection['tables'].keys())
                return dict(release_id=self.release_id, upstream=True, **value, local_available=value['table'] in self.schemas, missing_tables=local)
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
            return dict(release_id=self.release_id, table=table, available=table in self.schemas, columns=self.schemas.get(table, {}),
                meanings=meaning.get('columns', []), purpose=meaning.get('purpose'), row_meaning=meaning.get('row_meaning'),
                identity=meaning.get('identity'), scope=meaning.get('gaps', []), notes=meaning.get('notes', {}),
                relationships_version=version,
                outgoing=[r['id'] for r in relationships if r['source'].get('table') == table],
                incoming=[r['id'] for r in relationships if r['target'].get('table') == table],
                recipes=[r['id'] for r in recipes if table in r['requires']],
                entity_response=dict(default_mode='detail', modes=['detail', 'summary'],
                    summary_fields=self.entity_summary_fields(table), fields=list(self.schemas.get(table, {})),
                    omitted_details='Use mode=detail, fields=[...], or query_sql to slice large nested lists.'))
        tables = {name: dict(rows=sum(p['rows'] for p in parts), columns=list(self.schemas[name]))
                  for name, parts in self.selection['tables'].items()}
        return dict(release_id=self.release_id, tables=tables,
            views=dict(documents='List and detail joined by release-local list_row'),
            entity_keys=self.entity_keys,
            entity_identity='published' if self.entity_keys else 'not published in this release',
            missing_entities=sorted(self.entity_keys.keys() - tables.keys()),
            relationships_version=version,
            relationship_metadata='published' if version == 1 else ('not published in this release' if version is None else 'unsupported version'),
            relationships=[relation_info({key: r[key] for key in ('id', 'source', 'target')}) for r in relationships],
            recipes=[recipe_info({key: r[key] for key in ('id', 'title', 'requires')}) for r in recipes],
            upstream_relations=upstream if upstream is not None else 'not published in this release',
            coverage=[dict(file=f['name'], coverage=f.get('coverage', {}))
                      for f in self.selection['manifest']['files'] if f['name'].endswith('.parquet')],
            notes=['Missing tables are unavailable, not empty. Null entity fields mean the release did not supply those values.',
                   'Witnesses are appearances; names do not establish identity or document ownership.',
                   'SQL preserves published types. BLOB values use DuckDB JSON escaping; hex(binary_column) gives portable identifiers.',
                   'References and cursors bind to this release. File URLs are returned for you to fetch and read.',
                   'Pass a relationship or recipe ID for join meaning or example SQL; examples are never run by discovery.',
                   'upstream_relations name SpicyRegs source tables. Only relations listed in local tables are readable; a generation pin alone is not local availability.'],
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

    def page(self, query, sql, args, *, order, expand=None):
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
        # Keep the lookahead limit beside ORDER BY so DuckDB can use Top N.
        # An outer relation limit after OFFSET leaves a full wide-row sort.
        selected = sql + f' ORDER BY {order} LIMIT ? OFFSET ?'
        # A caller may fetch full rows after selecting its ordered page keys.
        result = self.rows(expand(selected) if expand else selected,
                           [*args, query.limit+1, position], limit=query.limit)
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
        order = 'l.list_row'
        qualification = 'not applied to archive order'
        if query.sort != 'archive':
            order = f"l.document_date {'DESC' if query.sort == 'recent' else 'ASC'} NULLS LAST,l.list_row"
            if 'document_date_status' in self.schemas['detail']:
                allowed = ["d.document_date_status='accepted'"]
                if query.include_suspect:
                    allowed.append("d.document_date_status='suspect'")
                if query.include_undated:
                    allowed.append('l.document_date IS NULL')
                conditions.append('(' + ' OR '.join(allowed) + ')')
                qualification = 'published document_date_status; accepted dates by default'
            else:
                qualification = 'unavailable in this release; chronological order uses literal dates'
                if not query.include_undated:
                    conditions.append('l.document_date IS NOT NULL')
        result = self.document_rows(self.page(query,
            f'SELECT {self.document_summary} '
            'FROM "list" l JOIN detail d USING(list_row) WHERE ' + (' AND '.join(conditions) or 'true'), args, order=order))
        if query.sort != 'archive':
            result['date_qualification'] = qualification
        return result

    def _resolve_document(self, query):
        if query.release_id != self.release_id:
            raise ExplorerError('Document reference belongs to another release')
        match = self.db.execute('SELECT list_row FROM links WHERE link_key=unhex(?)', [query.link_key]).fetchall()
        redirected_from = None
        if not match and 'retired_links' in self.schemas:
            # Data model §8.2, Retired keys: a key this release no longer publishes redirects
            # to its successor or explains its removal; it never vanishes silently.
            versions = ("list_transform(address_versions,lambda v:lower(hex(v)))" if 'address_versions' in self.schemas['retired_links']
                        else 'NULL')
            retired = self.db.execute(f'SELECT hex(successor_key),last_release_id,last_filename,{versions} FROM retired_links '
                                      'WHERE link_key=unhex(?)', [query.link_key]).fetchall()
            if len(retired) == 1:
                successor, last_release, last_filename, others = retired[0]
                if successor is None:
                    listed = f'; other versions at the same address: {", ".join(others)}' if others else ''
                    raise ExplorerError(f'Document {query.link_key.lower()} is no longer in the archive; it was last published as '
                                        f'"{last_filename}" in release {last_release[:12]}{listed}')
                match = self.db.execute('SELECT list_row FROM links WHERE link_key=unhex(?)', [successor]).fetchall()
                redirected_from = query.link_key.lower()
        if len(match) != 1:
            raise ExplorerError('Document link is absent or ambiguous in this release')
        return match[0][0], redirected_from

    def indexed_caption_text(self,value):
        if not self.selection['manifest'].get('text_index'):return None
        from .hearing_models import TranscriptQuery
        from .text_index import TextIndex
        return TextIndex(self.selection).read_caption(value['source'],TranscriptQuery.model_validate(value['query']))

    def indexed_source_text(self,value):
        if not self.selection['manifest'].get('text_index'):return None
        from .text_index import TextIndex
        return TextIndex(self.selection).read_document(value['source'],DocumentQuery.model_validate(value['query']))

    def indexed_document_text(self,value):
        if not self.selection['manifest'].get('text_index'):return None
        from .text_index import TextIndex
        query=DocumentQuery.model_validate(value)
        return TextIndex(self.selection).read_document(self.document_body_target(query),query)

    def document_body_target(self, value):
        query = value if isinstance(value, DocumentQuery) else DocumentQuery.model_validate(value)
        position, redirected_from = self._resolve_document(query)
        row = self.rows(
            'SELECT list_row,filename,title,format,saved_kind,saved_media_type,saved_bytes,'
            'lower(hex(link_key)) AS link_key,lower(hex(saved_body)) AS saved_body,saved_suffix,witness_keys '
            'FROM documents WHERE list_row=?',
            [position],
            limit=1,
        )['rows'][0]
        body, suffix = row['saved_body'], row['saved_suffix']
        return dict(
            release_id=self.release_id,
            reference=dict(release_id=self.release_id, link_key=row['link_key']),
            redirected_from=redirected_from,
            list_row=row['list_row'],
            filename=row['filename'],
            title=row['title'],
            format=row['format'],
            saved_kind=row['saved_kind'],
            saved_media_type=row['saved_media_type'],
            saved_bytes=row['saved_bytes'],
            witness_keys=row['witness_keys'],
            saved_body=body.lower() if body else None,
            saved_suffix=suffix,
            saved_url=self.file_url(body, suffix),
            archive_origin=self.selection.get('archive_origin'),
        )

    def get_document(self, value):
        query = DocumentQuery.model_validate(value)
        if query.section == 'text':
            raise ExplorerError('Document body text is read by the MCP server outside the DuckDB query worker')
        position, redirected_from = self._resolve_document(query)
        if query.section == 'summary':
            if query.cursor:
                raise ExplorerError('Summary does not take a cursor')
            deferred = [name for name in ('page_metadata', 'selected_text') if name in self.schemas['documents']]
            exclude = f' EXCLUDE({",".join(deferred)})' if deferred else ''
            result = self.rows(f'SELECT *{exclude} REPLACE(hex(link_key) AS link_key,hex(saved_body) AS saved_body,'
                               'list_transform(alternates,lambda a:struct_pack(format:=a.format,body:=hex(a.body),suffix:=a.suffix,size:=a.size)) AS alternates),'
                               '(SELECT url FROM sources WHERE list_row=documents.list_row ORDER BY ordinal LIMIT 1) AS primary_source_url '
                               'FROM documents WHERE list_row=?', [position], limit=1)
            result.pop('columns'); result['release_id'] = self.release_id
            if redirected_from:
                result['redirected_from'] = redirected_from
            self.document_rows(result)
            row = result['rows'][0]
            row['sections'] = dict(
                sources='Published source URLs and context',
                recoveries='Recovered files and their relationship to this document',
                text='Verified archived document body text and snippet search',
            )
            if 'page_metadata' in deferred and row.get('main_content'):
                row['sections']['page_metadata'] = 'Paged publisher declarations with selection and source evidence'
            if (row.get('main_content') or {}).get('text_available'):
                row['sections']['selected_text'] = 'Publisher-marked text with selector, body digest and reading version'
            return result
        if query.section == 'page_metadata':
            if 'page_metadata' not in self.schemas['documents']:
                raise ExplorerError('Publisher page metadata is unavailable in this release')
            result = self.page(query, '''SELECT ordinal,item.* FROM (
                SELECT generate_subscripts(page_metadata,1) AS ordinal,unnest(page_metadata) AS item
                FROM documents WHERE list_row=?)''', [position], order='ordinal')
            source = self.rows('''SELECT lower(hex(link_key)) AS link_key,lower(hex(saved_body)) AS saved_body,
                saved_suffix,main_content.reader_version AS reader_version
                FROM documents WHERE list_row=?''', [position], limit=1)['rows'][0]
            source['saved_url'] = self.file_url(source['saved_body'], source.pop('saved_suffix'))
            result['source'] = source
        elif query.section == 'selected_text':
            result = self.selected_text(query, position)
        else:
            columns = '*' if query.section == 'sources' else '* REPLACE(hex(body) AS body)'
            result = self.page(query, f'SELECT {columns} FROM {query.section} WHERE list_row=?', [position], order='ordinal')
            if query.section == 'recoveries':
                for row in result['rows']:
                    row['saved_url'] = self.file_url(row['body'], row['suffix'])
        if redirected_from:
            result['redirected_from'] = redirected_from
        return result

    def selected_text(self, query, position):
        if 'selected_text' not in self.schemas['documents']:
            raise ExplorerError('Selected text is unavailable in this release. Use section=text for the saved body.')
        if query.cursor or query.page is not None or query.query is not None:
            raise ExplorerError('Selected text uses offset and max_chars')
        # At most six JSON bytes per character, with room for the citation.
        limit = min(query.max_chars, (MAX_BYTES - 8192) // 6)
        row = self.rows('''SELECT lower(hex(link_key)) AS link_key,lower(hex(saved_body)) AS saved_body,
            saved_suffix,main_content.selector AS selector,main_content.reader_version AS reader_version,
            main_content.text_sha256 AS text_sha256,length(selected_text) AS total_chars,
            substr(selected_text,?,?) AS text,witness_keys
            FROM documents WHERE list_row=?''', [query.offset + 1, limit, position], limit=1)['rows'][0]
        if row['text'] is None:
            raise ExplorerError('Selected text is unavailable for this document. Use section=text for the saved body.')
        next_offset = query.offset + len(row['text'])
        from .citations import text_citation
        citation=text_citation(dict(row,release_id=self.release_id),dict(kind='selected_text',offset=query.offset,length=len(row['text']),
            selector=row['selector'],selected_text_sha256=row['text_sha256']),row['text'])
        return dict(row, citation=citation, release_id=self.release_id, offset=query.offset,
                    next_offset=next_offset if next_offset < row['total_chars'] else None,
                    saved_url=self.file_url(row['saved_body'], row['saved_suffix']))

    def search_entities(self, value):
        query = EntitySearch.model_validate(value)
        key = self.entity_key(query.table)
        columns = self.schemas[query.table]
        conditions, args = [], []
        if query.text:
            fields = [name for name in TEXT_FIELDS if name in columns]
            conditions.append('(' + ' OR '.join(f'contains(lower(coalesce({quote(name)},\'\')),lower(?))' for name in fields) + ')' if fields else 'false')
            args += [query.text] * len(fields)
        scalars = ', '.join(k for k, t in columns.items() if '[]' not in t and not t.startswith(('STRUCT', 'MAP', 'BLOB')))
        for name, value in query.filters.items():
            if name not in columns:
                raise ExplorerError(f'Unknown filter field {name!r} on {query.table}; scalar filter fields are: {scalars}')
            if '[]' in columns[name] or columns[name].startswith(('STRUCT', 'MAP', 'BLOB')):
                raise ExplorerError(f'Use a scalar published filter; query_sql supports {name!r}; scalar filter fields are: {scalars}')
            query.filters[name] = value = exact_scalar(value, columns[name], f'{query.table}.{name}')
            conditions.append(f'{quote(name)}=?'); args.append(value)
        order = ','.join(map(quote, key))
        result = self.page(query, f'SELECT {self.entity_columns(query.table)} FROM {quote(query.table)} WHERE ' + (' AND '.join(conditions) or 'true'), args, order=order)
        return self.entity_rows(result, query.table, selected_fields=getattr(query, 'fields', None))

    def entity_key(self, table):
        """The table's published identity: absent tables are not published, never empty."""
        self.require(table)
        if table not in self.entity_keys:
            raise ExplorerError(f'Table {table!r} has no published identity in this release; use get_dataset_info or query_sql')
        return self.entity_keys[table]

    def entity_columns(self, table, fields=None):
        if table == 'recordings' and fields is None:
            return '* REPLACE(list_transform(tracks,lambda t:struct_pack(body:=hex(t.body),suffix:=t.suffix,format:=t.format,language:=t.language,production:=t.production)) AS tracks)'
        if fields is not None:
            return ','.join(
                'list_transform(tracks,lambda t:struct_pack(body:=hex(t.body),suffix:=t.suffix,format:=t.format,language:=t.language,production:=t.production)) AS tracks'
                if table == 'recordings' and name == 'tracks' else quote(name) for name in fields)
        return '*'

    def entity_rows(self, result, table=None, *, selected_fields=None):
        for row in result['rows']:
            if table == 'meetings' and selected_fields is None:
                row.setdefault('publisher_status', row.get('status'))
                row.setdefault('outcome', None)
                row['outcome_evidence_available'] = 'outcome' in self.schemas['meetings']
                if not row['outcome_evidence_available']:
                    row['outcome_reason'] = 'This release does not publish outcome evidence.'
            for track in row.get('tracks') or []:
                track['saved_url'] = self.file_url(track['body'], track['suffix'])
        return result

    def get_entity(self, value):
        query = EntityQuery.model_validate(value)
        self.require(query.table)
        fields = self.entity_keys.get(query.table, [])
        if len(fields) != 1:
            raise ExplorerError('Entity table has no single identifier; use search_entities or query_sql')
        key = fields[0]
        query.id = exact_scalar(query.id, self.schemas[query.table][key], f'{query.table}.{key}')
        stored = self.db.execute(f'SELECT {quote(key)} FROM {quote(query.table)} WHERE {quote(key)}=? LIMIT 1', [query.id]).fetchall()
        if not stored:
            raise ExplorerError('Entity is absent from this release')
        query.id = stored[0][0]
        if query.section == 'documents':
            if query.fields is not None or query.mode != 'detail':
                raise ExplorerError('Entity fields and mode apply to section=record; document pages use their own summary fields')
            field = self.document_links.get(query.table)
            if field:
                sql = f'list_contains(l.{field},?)'
            elif query.table == 'recordings':
                sql = 'EXISTS (SELECT 1 FROM recordings r,unnest(r.event_ids) e(event_id) WHERE r.video_key=? AND list_contains(l.meeting_keys,cast(e.event_id AS VARCHAR)))'
            else:
                raise ExplorerError('This entity has no published document relationship')
            return self.document_rows(self.page(query,
                f'SELECT {self.document_summary} '
                'FROM "list" l JOIN detail d USING(list_row) WHERE NOT coalesce(l.hidden,false) AND ' + sql,
                [str(query.id)], order='l.list_row'))
        if query.cursor:
            raise ExplorerError('Record does not take a cursor; query_sql can slice large nested fields')
        selected = query.fields
        if selected is not None:
            unknown = [name for name in selected if name not in self.schemas[query.table]]
            if unknown:
                raise ExplorerError(f'Unknown published field {unknown[0][:128]!r} on {query.table}; use get_dataset_info(table={query.table!r})')
        elif query.mode == 'summary':
            selected = self.entity_summary_fields(query.table)
        if selected is not None:
            selected = list(dict.fromkeys([key, *selected]))
        result = self.rows(f'SELECT {self.entity_columns(query.table, selected)} FROM {quote(query.table)} WHERE {quote(key)}=?', [query.id], limit=1)
        result.pop('columns'); result['release_id'] = self.release_id
        if selected is not None:
            result['omitted_fields'] = [name for name in self.schemas[query.table] if name not in selected]
            result['detail_access'] = 'Use mode=detail, fields=[...], or query_sql to slice large nested lists.'
        return self.entity_rows(result, query.table, selected_fields=query.fields)
