"""Temporary disk grouping agrees with the reference and isolates changed groups."""
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import document_index as index
from congress_api.retention.catalog_staging import WorkingCatalog, DiskRows


def source(name, url, body=None):
    return dict(body_key=body, filename=name, source_url=url,
                media_type=['application/pdf'], http_status=['200'], capture_outcome=['saved'])


def semantic(table):
    return sorted(table.to_pylist(), key=lambda row: row['source_id'])


def test_disk_rows_replays_mutations_and_map_requires_explicit_save(tmp_path):
    state = WorkingCatalog(tmp_path / 'working.sqlite')
    try:
        rows = DiskRows(state.connection)
        rows.append({'filename':'a.pdf'})
        for row in rows:
            row['source_url'] = 'https://example.gov/a.pdf'
        assert list(rows) == [{'filename':'a.pdf','source_url':'https://example.gov/a.pdf'}]
        mapping = state.mapping('facts')
        mapping['url'] = {'words':['literal']}
        row = mapping['url']
        row['words'].append('new')
        assert mapping['url'] == {'words':['literal']}
        mapping['url'] = row
        assert mapping['url']['words'] == ['literal','new']
    finally:
        state.close()


def test_transitive_merge_split_and_unchanged_groups_equal_clean_replay(tmp_path):
    rows = [source('a.pdf','https://example.gov/a.pdf','body-A'),
            source('b.pdf','https://example.gov/b.pdf','body-B'),
            source('c.pdf','https://example.gov/c.pdf','body-C')]
    schema = pa.schema([*index.SOURCE_SCHEMA,('capture_outcome',index.STRINGS)])
    path = tmp_path / 'document-filenames.parquet'
    index.write_document_indexes(path, rows, schema)
    previous = pq.ParquetFile(path)
    previous_documents = path.with_name('documents.parquet').read_bytes()
    # Same endpoint has a new body: connects A and B transitively, C is intact.
    added = source('a.pdf','https://example.gov/a.pdf','body-B')
    merged = tmp_path / 'merged'; merged.mkdir()
    result = index.write_document_indexes(merged / path.name, [*rows,added], schema,
        previous=previous,previous_documents=previous_documents)
    assert result['reused_document_groups'] == 1
    assert result['recomputed_document_groups'] == 1
    clean = tmp_path / 'clean';clean.mkdir()
    index.write_document_indexes(clean / path.name,[*rows,added],schema)
    for name in (path.name,'documents.parquet'):
        assert semantic(pq.read_table(merged / name)) == semantic(pq.read_table(clean / name))
    # Removing the bridge splits the component and recomputes both sides.
    split = tmp_path / 'split';split.mkdir()
    result = index.write_document_indexes(split / path.name,rows,schema,
        previous=pq.ParquetFile(merged / path.name),previous_documents=(merged / 'documents.parquet').read_bytes())
    assert result['reused_document_groups'] == 1
    assert result['recomputed_document_groups'] == 2
    for name in (path.name,'documents.parquet'):
        assert semantic(pq.read_table(split / name)) == semantic(pq.read_table(tmp_path / name))


def test_grouping_matches_reference_for_download_variants_and_failed_shared_body(tmp_path):
    rows = [source('a.pdf','https://example.gov/a.pdf','body-A'),
            source('a.pdf?download=1','https://example.gov/a.pdf?download=1','body-A'),
            source('else.pdf','https://else.gov/else.pdf','body-A'),
            {**source('error.pdf','https://error.gov/error.pdf','body-A'), 'http_status':['404']}]
    schema = pa.schema([*index.SOURCE_SCHEMA,('capture_outcome',index.STRINGS)])
    expected_rows,_,expected_documents,_ = index.prepare_document_indexes([dict(row) for row in rows],schema)
    path = tmp_path / 'document-filenames.parquet'
    index.write_document_indexes(path, iter(rows), schema)
    actual_sources = pq.read_table(path)
    assert semantic(actual_sources) == semantic(pa.Table.from_pylist(expected_rows,schema=actual_sources.schema))
    # Arrow null-fills fields absent from raw dictionaries.
    actual = pq.read_table(path.with_name('documents.parquet'))
    expected = pa.Table.from_pylist(expected_documents,schema=actual.schema)
    assert semantic(actual) == semantic(expected)


def test_distinct_publication_code_is_preserved(tmp_path):
    schema = pa.schema([*index.SOURCE_SCHEMA,('publication_code_code',index.STRINGS),('publication_type',index.STRINGS)])
    path = tmp_path / 'document-filenames.parquet'
    index.write_document_indexes(path,[{**source('a.pdf','https://example.gov/a.pdf'),
        'publication_code_code':['literal'],'publication_type':['normalized']}],schema)
    for file in (path,path.with_name('documents.parquet')):
        row, = pq.read_table(file).to_pylist()
        assert row['publication_code_code'] == ['literal']


def test_policy_change_invalidates_group_reuse(tmp_path,monkeypatch):
    schema = index.SOURCE_SCHEMA
    path = tmp_path / 'document-filenames.parquet'
    row = {**source('a.pdf','https://example.gov/a.pdf'), 'source_document_type':['Witness Statement']}
    schema = schema.append(pa.field('source_document_type',index.STRINGS))
    index.write_document_indexes(path,[row],schema)
    previous = pq.ParquetFile(path)
    documents = path.with_name('documents.parquet').read_bytes()
    original = index.fill_document_kind
    def changed(row):
        original(row)
        row['document_kind'] = ['changed-policy']
    monkeypatch.setattr(index,'fill_document_kind',changed)
    result = index.write_document_indexes(path,[row],schema,previous=previous,previous_documents=documents)
    assert result['reused_document_groups'] == 0
    assert pq.read_table(path.with_name('documents.parquet')).to_pylist()[0]['document_kind'] == ['changed-policy']


def test_recovery_coalesces_duplicate_source_observations(tmp_path):
    from congress_api.retention.document_recovery import recover_sources
    state = WorkingCatalog(tmp_path / 'working.sqlite')
    try:
        first = {**source('a.pdf','https://example.gov/a.pdf'), 'source_document_type':['Report']}
        second = {**first, 'source_document_type':['Witness Statement']}
        captures = pa.table({'body_key':pa.array([],type=pa.string())})
        expected = recover_sources([first,second],captures,read_receipt=lambda key: None)
        # No eligible recovery inputs must still preserve duplicate source facts.
        actual = list(recover_sources([first,second],captures,read_receipt=lambda key: None,working=state))
        assert actual[0]['source_document_type'] == ['Report','Witness Statement']
        assert {value for row in expected for value in row['source_document_type']} == set(actual[0]['source_document_type'])
    finally:
        state.close()


def test_filename_refresh_rejects_publication_after_input_snapshot(tmp_path,monkeypatch):
    import pytest
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog,publish_catalog,local_catalog_paths
    (tmp_path / 'indexes').mkdir()
    old = source('old.pdf','https://example.gov/old.pdf')
    new = source('new.pdf','https://example.gov/new.pdf')
    index.write_filename_metadata(tmp_path,[old],workers=1)
    store = LocalStore(tmp_path)
    before = read_catalog(store)
    competing = tmp_path / 'competing';competing.mkdir()
    index.write_document_indexes(competing / 'document-filenames.parquet',[old,new],index.SOURCE_SCHEMA)
    original = index.write_filename_metadata
    published = False
    def write(*args, **kwargs):
        nonlocal published
        # The refresh has selected its input by this entry point. Publish
        # before the wrapper would capture a second selector version.
        if not published:
            published = True
            publish_catalog(store,competing / 'document-filenames.parquet',competing / 'documents.parquet',previous=before)
        return original(*args, **kwargs)
    monkeypatch.setattr(index,'write_filename_metadata',write)
    with pytest.raises(RuntimeError,match='Concurrent catalog update'):
        index.refresh_filename_metadata(tmp_path,workers=1)
    assert {row['filename'] for row in pq.read_table(local_catalog_paths(tmp_path)[0]).to_pylist()} == {'old.pdf','new.pdf'}


def test_normalized_occurrences_match_resident_transfer_and_first_locator(tmp_path):
    state = WorkingCatalog(tmp_path / 'working.sqlite')
    try:
        resident,disk = index.DocumentSources(),index.DocumentSources(working=state)
        original = 'https://example.gov/original.pdf'
        final = 'https://example.gov/final.pdf'
        later = 'https://example.gov/later.pdf'
        for context in (resident,disk):
            for number in range(30):
                values = index.context_values(source_page_url=f'https://example.gov/page/{number}',
                    source_document_label=f'Literal {number}',source_receipt_key='receipts/first.jsonl.gz',
                    source_receipt_line=number+1)
                context.add_url(original,values)
                context.add_url(original,{**values,'source_receipt_key':{'receipts/duplicate.jsonl.gz'}})
            context.add_transfer(original,final,index.context_values(source_association_basis='publisher_redirect',
                source_associated_url=original,source_receipt_key='receipts/edge.jsonl.gz'))
            context.add_transfer(final,later,index.context_values(source_association_basis='retained_html_link',
                source_associated_url=final))
            context.add_url(original,index.context_values(source_page_url='https://example.gov/new-parent',
                source_document_type='Witness Statement',source_document_type_basis='publisher',
                source_receipt_key='receipts/later.jsonl.gz'))
        for url in (original,final,later):
            assert disk.for_url(url) == resident.for_url(url)
        assert all(occurrence['source_receipt_key'] == ['receipts/first.jsonl.gz']
                   for occurrence in disk.for_url(final)['source_occurrences']
                   if occurrence.get('source_document_label'))
    finally:
        state.close()


def test_occurrence_insert_and_read_serialization_grows_linearly(tmp_path,monkeypatch):
    from congress_api.retention import catalog_staging
    dumps,loads = catalog_staging.pickle.dumps,catalog_staging.pickle.loads
    encoded,decoded = [],[]
    def encode(value,*args,**kwargs):
        payload = dumps(value,*args,**kwargs)
        encoded.append(len(payload))
        return payload
    def decode(payload,*args,**kwargs):
        decoded.append(len(payload))
        return loads(payload,*args,**kwargs)
    monkeypatch.setattr(catalog_staging.pickle,'dumps',encode)
    monkeypatch.setattr(catalog_staging.pickle,'loads',decode)
    costs = []
    for count in (100,200):
        state = WorkingCatalog(tmp_path / f'working-{count}.sqlite')
        try:
            encoded.clear();decoded.clear()
            context = index.DocumentSources(working=state)
            url = 'https://example.gov/shared.pdf'
            for number in range(count):
                context.add_url(url,index.context_values(source_page_url=f'https://example.gov/page/{number}',
                    source_document_label=f'Literal {number}',source_receipt_key='receipts/first.jsonl.gz'))
            context.add_transfer(url,'https://example.gov/final.pdf',index.context_values(
                source_association_basis='publisher_redirect',source_associated_url=url))
            assert len(context.for_url(url)['source_occurrences']) == count
            costs.append((sum(encoded),sum(decoded),max(encoded)))
        finally:
            state.close()
    # Doubling observations doubles single-observation writes/reads. A complete
    # per-URL map per insertion or lookup grows approximately fourfold.
    assert costs[1][0] < costs[0][0]*2.2
    assert costs[1][1] < costs[0][1]*2.2
    assert max(cost[2] for cost in costs) < 1024


def test_normalized_recovery_references_preserve_order_and_scale(tmp_path,monkeypatch):
    from congress_api.retention import catalog_staging
    dumps,loads = catalog_staging.pickle.dumps,catalog_staging.pickle.loads
    encoded,decoded = [],[]
    def encode(value,*args,**kwargs):
        payload = dumps(value,*args,**kwargs);encoded.append(len(payload));return payload
    def decode(payload,*args,**kwargs):
        decoded.append(len(payload));return loads(payload,*args,**kwargs)
    monkeypatch.setattr(catalog_staging.pickle,'dumps',encode)
    monkeypatch.setattr(catalog_staging.pickle,'loads',decode)
    costs=[]
    for count in (100,200):
        state = WorkingCatalog(tmp_path / f'references-{count}.sqlite')
        try:
            encoded.clear();decoded.clear()
            references = state.recovery_references()
            for number in range(count):
                references.append({'receipt_key':'z-first.gz','receipt_line':2 if number%2 else 1,
                    'pointer_json':f'["capture-{number}"]','context_url':'https://example.gov/a.pdf'})
            references.append({'receipt_key':'a-second.gz','receipt_line':1,'pointer_json':'[]'})
            assert list(references.receipts()) == ['a-second.gz','z-first.gz']
            assert list(references.lines('z-first.gz')) == [(1,count//2),(2,count//2)]
            first = list(references.captures('z-first.gz',1))
            assert [row['pointer_json'] for row in first] == [f'["capture-{number}"]' for number in range(0,count,2)]
            first[0]['pointer_json'] = 'mutated detached value'
            assert next(references.captures('z-first.gz',1))['pointer_json'] == '["capture-0"]'
            costs.append((sum(encoded),sum(decoded),max(encoded)))
        finally:
            state.close()
    assert costs[1][0] < costs[0][0]*2.2
    assert costs[1][1] < costs[0][1]*2.2
    assert max(cost[2] for cost in costs) < 1024


def test_disk_recovery_matches_resident_and_missing_line_errors(tmp_path):
    import gzip,json,pytest
    from congress_api.retention.document_recovery import recover_sources
    url='https://example.gov/a.pdf'
    first={'receipt_key':'z-first.gz','receipt_line':2,'pointer_json':'[]','context_url':url,'body_key':'body-A','family':'documents'}
    second={**first,'receipt_key':'a-second.gz','receipt_line':1,'body_key':'body-B'}
    captures=pa.Table.from_pylist([first,second])
    payloads={'z-first.gz':gzip.compress(('{}\n'+json.dumps({'record':{'url':url,'http_status':200,'content_type':'application/pdf'}})+'\n').encode()),
              'a-second.gz':gzip.compress((json.dumps({'record':{'url':url,'http_status':200,'content_type':'application/pdf'}})+'\n').encode())}
    original={**source('a.pdf',url),'source_document_label':['Literal publisher label']}
    expected=recover_sources([original],captures,read_receipt=payloads.get)
    state=WorkingCatalog(tmp_path / 'recovery-equivalent.sqlite')
    try:
        actual=list(recover_sources([original],captures,read_receipt=payloads.get,working=state))
        assert actual == expected
    finally:
        state.close()
    for missing in ('receipt','line'):
        bad=dict(payloads)
        if missing=='receipt':
            bad.pop('z-first.gz')
        else:
            bad['z-first.gz']=gzip.compress(b'{}\n')
        for disk in (False,True):
            state=WorkingCatalog(tmp_path / f'error-{missing}-{disk}.sqlite') if disk else None
            try:
                with pytest.raises(ValueError,match='Missing capture receipt' if missing=='receipt' else 'Capture index references missing receipt lines'):
                    recover_sources([original],captures,read_receipt=bad.get,working=state)
            finally:
                if state is not None:
                    state.close()


def test_raw_releases_context_before_recovery_and_consumed_output_before_parse(tmp_path,monkeypatch):
    from congress_api.retention import raw_catalog
    from congress_api.retention.raw_archive import Archive
    from test_raw_catalog import initialize
    store=initialize(tmp_path)
    Archive(store,'lifecycle').save()
    recover=raw_catalog.recover_sources
    extract=index.extract
    state=None
    checks=[]
    def tables():
        return {row[0] for row in state.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def recovery(*args,**kwargs):
        nonlocal state
        state=kwargs['working']
        assert not tables() & {'occurrences','occurrence_urls','extra_filters','transfers','meetings','events'}
        assert 'sources' in tables()
        checks.append('context released')
        return recover(*args,**kwargs)
    def parse(key):
        assert not tables() & {'recovery_rows','recovery_result'}
        assert 'filename_rows' in tables()
        checks.append('recovery output released')
        return extract(key)
    monkeypatch.setattr(raw_catalog,'recover_sources',recovery)
    monkeypatch.setattr(index,'parser_fingerprint',lambda:'fresh-lifecycle-test')
    monkeypatch.setattr(index,'extract',parse)
    raw_catalog.rebuild_catalog(store,workers=1)
    assert checks == ['context released','recovery output released']


def test_recovery_sorts_receipts_before_inheriting_failed_probe_facts(tmp_path):
    """A body inherits observations from lexically earlier receipts, as before staging."""
    import copy,gzip,json
    from congress_api.retention.document_recovery import recover_sources
    url='https://example.gov/a.xml'
    base=dict(receipt_line=1,pointer_json='[]',context_url=url,family=None,source_file='ordinary.jsonl')
    captures=pa.Table.from_pylist([
        {**base,'receipt_key':'z-body.gz','body_key':'body-A'},
        {**base,'receipt_key':'a-facts.gz','body_key':None},
        {**base,'receipt_key':'a-facts.gz','receipt_line':2,'body_key':None,
         'source_file':'x/pdf_xml_probe/attempts.jsonl'}])
    def payload(records):
        return gzip.compress(('\n'.join(json.dumps({'record':r}) for r in records)+'\n').encode())
    receipts={'z-body.gz':payload([{'url':url,'http_status':200,'content_type':'application/xml'}]),
              'a-facts.gz':payload([{'url':url,'http_status':404,'usable':False},
                  {'xml_url':url,'pdf_url':'https://example.gov/a.pdf','status':'missing','arm':'extension replacement'}])}
    original=dict(body_key=None,filename='a.xml',source_url=url)
    results=[]
    for disk in (False,True):
        state=WorkingCatalog(tmp_path / 'receipt-order.sqlite') if disk else None
        try:
            rows=list(recover_sources([copy.deepcopy(original)],captures,read_receipt=receipts.get,working=state))
            row,=rows
            assert row['http_status'] == ['200','404']
            assert row['source_probe_status'] == ['missing']
            assert row['source_receipt_key'] == ['a-facts.gz','z-body.gz']
            assert row['response_usable'] == ['false']
            results.append(rows)
        finally:
            if state:state.close()
    assert results[0] == results[1]


def test_native_cached_xml_evidence_follows_alias_across_4096_rows(tmp_path,monkeypatch):
    from congress_api.retention.document_evidence import evidence_fingerprint
    fields=dict(body_format=['xml'],content_document_kind=['witness-list'],
                source_record_type=['witness-list'],source_record_identifier=['123'],
                source_record_document_url=['https://example.gov/witness.pdf'])
    typed=source('WList.xml','https://example.gov/WList.xml','shared-xml')
    anonymous=source('anonymous','https://example.gov/copy','shared-xml')
    previous=pa.Table.from_pylist([{**typed,**fields}]).replace_schema_metadata(
        {'body_evidence_fingerprint':evidence_fingerprint()})
    monkeypatch.setattr(index,'extract',lambda key: {'document_kind':['witness-list']} if key[0]=='WList.xml' else {})
    rows=[typed,*[source(f'filler-{n}.pdf',f'https://example.gov/filler-{n}.pdf') for n in range(4095)],anonymous]
    result=index.write_filename_metadata(tmp_path,rows,workers=1,previous=previous,
        read_body=lambda key: (_ for _ in ()).throw(AssertionError('metadata-only reads body')))
    sources=pq.read_table(result['output']).to_pylist()
    actual=next(row for row in sources if row['filename']=='WList.xml')
    for field,values in fields.items():
        assert actual[field] == values
    documents=pq.read_table(result['documents_output']).to_pylist()
    document=next(row for row in documents if row['body_key']=='shared-xml')
    for field,values in fields.items():
        assert document[field] == values


def test_typed_xml_cache_requires_original_qualifying_alias():
    from congress_api.retention.document_evidence import enrich_sources
    row={**source('WList.xml','https://example.gov/WList.xml','shared-xml'),'document_kind':['witness-list']}
    cached={('xml','shared-xml'):{'body_format':['xml'],'source_record_type':['witness-list']}}
    enrich_sources([row],read_body=lambda key: None,extract=lambda key: {},cached=cached)
    assert row.get('body_format') is None
    assert row.get('source_record_type') is None


def test_document_output_order_uses_scalar_index_for_large_payloads(tmp_path):
    rows=[{**source(name,f'https://example.gov/{number}.pdf'),
           'source_document_label':[f'{number}:'+'literal publisher evidence '*4096]}
          for number,name in enumerate(['Z.pdf','a.pdf','A.pdf','ß.pdf','ss.pdf','İ.pdf']*4)]
    schema=pa.schema([*index.SOURCE_SCHEMA,('capture_outcome',index.STRINGS),('source_document_label',index.STRINGS)])
    state=WorkingCatalog(tmp_path / 'ordered.sqlite')
    try:
        path=tmp_path / 'document-filenames.parquet'
        index.write_document_indexes(path,rows,schema,working=state)
        plan=[row[3] for row in state.connection.execute(
            'EXPLAIN QUERY PLAN SELECT value FROM output_documents ORDER BY sort_name,id')]
        assert not any('TEMP B-TREE' in detail for detail in plan)
        assert any('USING INDEX output_document_order' in detail for detail in plan)
        documents=pq.read_table(path.with_name('documents.parquet')).to_pylist()
        assert documents == sorted(documents,key=lambda row:((row['filename'] or '').casefold(),row['document_id']))
        assert sorted(label for row in documents for label in row['source_document_label']) == sorted(row['source_document_label'][0] for row in rows)
    finally:
        state.close()
