"""Recorded link paths retain their hearing context without merging identities."""
import pytest

from congress_api.retention.document_index import DocumentSources, fill_document_kind
from congress_api.retention.catalog_staging import WorkingCatalog

HEARING = 'https://humanrightscommission.house.gov/events/hearings/armed-conflict-starvation-and-international-humanitarian-law'
ARTICLE = 'https://news.un.org/en/story/2021/09/1100782'
FILE = 'https://example.org/yemen.pdf'
RECEIPT = {'source_receipt_key': ['receipt.jsonl.gz'], 'source_receipt_line': ['4']}


@pytest.mark.parametrize('disk', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_publisher_reference_reaches_descendants_in_either_order(tmp_path, disk, reverse):
    state = WorkingCatalog(tmp_path / 'working.sqlite') if disk else None
    try:
        context = DocumentSources(working=state)
        links = [
            dict(url=ARTICLE, publisher_occurrences=[dict(site='humanrightscommission.house.gov',
                page=HEARING, date='2022-04-12', kind='hearing notice', name='Yemen', url=ARTICLE)]),
            dict(url=FILE, parent_url=ARTICLE, text='Yemen humanitarian event'),
            dict(url='https://example.org/attachment.pdf', parent_url=FILE, text='Attachment'),
        ]
        for link in reversed(links) if reverse else links:
            context.add_link(link, RECEIPT)
        for target in (FILE, 'https://example.org/attachment.pdf'):
            result = context.for_url(target)
            root = next(o for o in result['source_occurrences'] if o.get('source_original_page_url') == [HEARING])
            assert root['source_link_url'] == [ARTICLE]
            assert root['source_link_label'] == ['Yemen']
            assert root['source_page_date'] == ['2022-04-12']
            assert root['source_page_type'] == ['hearing notice']
            assert root['source_occurrence_scope'] == ['linked_ancestor']
            assert root['source_receipt_key'] == ['receipt.jsonl.gz']
            assert root['source_receipt_line'] == ['4']
        immediate = [o for o in context.for_url(FILE)['source_occurrences']
                     if o.get('source_original_page_url') == [ARTICLE]]
        assert len(immediate) == 1
        assert immediate[0]['source_link_url'] == [FILE]
        assert immediate[0]['source_link_label'] == ['Yemen humanitarian event']
    finally:
        if state:
            state.close()


def test_shared_pages_keep_hearings_paired_and_cycles_terminate():
    context = DocumentSources()
    for n in (1, 2):
        context.add_link(dict(url=ARTICLE, parent_url=f'https://committee.test/hearing/{n}',
            text=f'Reference {n}', native={'documentType': 'Witness Statement'},
            context={'eventId': n, 'title': f'Hearing {n}', 'chamber': 'House', 'congress': 119}))
    context.add_link(dict(url=FILE, parent_url=ARTICLE, text='Background file'))
    context.add_link(dict(url=ARTICLE, parent_url=FILE, text='Back to article'))
    result = context.for_url(FILE)
    roots = [o for o in result['source_occurrences'] if o.get('source_meeting_id')]
    assert {(tuple(o['source_meeting_id']), tuple(o['source_original_page_url']),
             tuple(o['source_link_label'])) for o in roots} == {
        (('1',), ('https://committee.test/hearing/1',), ('Reference 1',)),
        (('2',), ('https://committee.test/hearing/2',), ('Reference 2',)),
    }
    assert all(o['source_occurrence_scope'] == ['linked_ancestor'] for o in roots)
    assert 'source_document_type' not in result
    fill_document_kind(result)
    assert result['document_kind'] is None
    count = len(result['source_occurrences'])
    context.add_link(dict(url=FILE, parent_url=ARTICLE, text='Background file'))
    assert len(context.for_url(FILE)['source_occurrences']) == count
    assert not context.for_url('https://committee.test/unrelated.pdf')


def test_link_relationship_can_be_restored_before_new_parent_context():
    context = DocumentSources()
    context.restore_association(FILE, dict(source_occurrence_scope=['association'],
        source_association_basis=['linked_page'], source_associated_url=[ARTICLE]))
    context.add_link(dict(url=ARTICLE, parent_url=HEARING, text='Yemen'))
    assert context.for_url(FILE)['source_original_page_url'] == [HEARING]


def test_candidate_matches_do_not_establish_transitive_hearing_relationships():
    context = DocumentSources()
    context.add_link(dict(url=ARTICLE, parent_url=HEARING, text='Yemen'))
    context.add_transfer(ARTICLE, FILE, {'source_association_basis':['filename_match'],
                                       'source_associated_url':[ARTICLE]})
    context.add_link(dict(url='https://example.org/attachment.pdf',parent_url=FILE))
    assert HEARING not in context.for_url('https://example.org/attachment.pdf').get('source_original_page_url', [])
    # A later candidate match must not spread already inherited hearing facts.
    context.add_link(dict(url='https://example.org/known.pdf',parent_url=ARTICLE))
    context.add_transfer('https://example.org/known.pdf','https://example.org/candidate.pdf',
                        {'source_association_basis':['filename_match']})
    assert HEARING not in context.for_url('https://example.org/candidate.pdf').get('source_original_page_url', [])


def test_redirect_cycles_do_not_multiply_inherited_paths():
    context = DocumentSources()
    context.add_link(dict(url=ARTICLE,parent_url=HEARING,text='Yemen'))
    context.add_link(dict(url=FILE,parent_url=ARTICLE))
    aliases=[FILE,*[f'https://example.org/alias/{n}.pdf' for n in range(4)]]
    for source,target in zip(aliases,aliases[1:]+aliases[:1]):
        context.add_transfer(source,target,{'source_association_basis':['publisher_redirect'],
                                           'source_associated_url':[source]})
    for target in aliases:
        roots=[o for o in context.for_url(target)['source_occurrences']
               if o.get('source_original_page_url')==[HEARING]]
        assert len(roots)==1
        assert roots[0]['source_link_url']==[ARTICLE]


def test_sitewide_feed_does_not_connect_unrelated_hearings():
    context = DocumentSources()
    feed='https://docs.house.gov/BillsThisWeek-RSS.xml'
    context.add_link(dict(url=feed,parent_url=HEARING,text='RSS'))
    context.add_link(dict(url='https://committee.test/other-hearing',parent_url=feed))
    context.add_link(dict(url=FILE,parent_url='https://committee.test/other-hearing'))
    assert HEARING not in context.for_url(FILE).get('source_original_page_url', [])
    assert feed not in context.for_url(FILE).get('source_original_page_url', [])


def test_catalog_update_backfills_old_receipts_without_refetching_bodies(tmp_path, monkeypatch):
    import historical_raw_catalog as raw_catalog
    from historical_raw_archive import LegacyArchiveSeed as Archive
    from test_raw_catalog import initialize, table
    from test_raw_source_sync import response
    store = initialize(tmp_path)
    archive = Archive(store, 'lineage-backfill')
    receipt = response(ARTICLE, b'<html>retained</html>', 'text/html')
    receipt['source_context'] = {'observations': [dict(url=ARTICLE, publisher_occurrences=[
        dict(page=HEARING, date='2022-04-12', kind='hearing notice', name='Yemen', url=ARTICLE)])]}
    archive.record(receipt, outcome='saved', context=receipt['source_context'],
                   links=[dict(url=FILE, parent_url=ARTICLE, text='Event PDF')])
    archive.save()
    add_link = DocumentSources.add_link
    with monkeypatch.context() as old:
        old.setattr(raw_catalog, 'SOURCE_LINEAGE_VERSION', '0')
        old.setattr(DocumentSources, 'add_link', lambda self, link, receipt=None:
                    add_link(self, {k:v for k,v in link.items() if k != 'publisher_occurrences'}, receipt))
        raw_catalog.rebuild_catalog(store, archive.captures, workers=1)
    before_tables = [table(store, key) for key in (raw_catalog.FILENAMES, raw_catalog.DOCUMENTS)]
    before = before_tables[0].to_pylist()
    assert not any(HEARING in (o.get('source_original_page_url') or []) for r in before
                   for o in r.get('source_occurrences') or [])
    read, reads = store.read, []
    monkeypatch.setattr(store, 'read', lambda key: reads.append(key) or read(key))
    result = raw_catalog.rebuild_catalog(store, archive.captures, workers=1)
    assert not result.get('unchanged')
    assert result['receipt_records_replayed'] == 1
    assert result['sources_with_parent_after'] > result['sources_with_parent_before']
    from congress_api.retention.document_index import SOURCE_CONTEXT_FIELDS
    for old, key in zip(before_tables, (raw_catalog.FILENAMES, raw_catalog.DOCUMENTS)):
        new = table(store, key)
        protected = [f for f in old.column_names if f not in SOURCE_CONTEXT_FIELDS]
        assert old.select(protected).equals(new.select(protected))
        assert new.schema.metadata[b'source_lineage_version'] == b'1'
    after = table(store).to_pylist()
    child = next(r for r in after if r['source_url'] == FILE)
    assert HEARING in child['source_original_page_url']
    assert {r['source_id'] for r in before} == {r['source_id'] for r in after}
    assert {r['document_id'] for r in before} == {r['document_id'] for r in after}
    assert not any(key.startswith('bodies/') for key in reads)
    assert raw_catalog.rebuild_catalog(store, archive.captures, workers=1)['unchanged']


def test_later_download_batches_inherit_old_and_new_parent_evidence(tmp_path):
    from historical_raw_catalog import rebuild_catalog
    from historical_raw_archive import LegacyArchiveSeed as Archive
    from test_raw_catalog import initialize, table
    from test_raw_source_sync import response
    store = initialize(tmp_path)
    first = Archive(store, 'first-file')
    first.record(response(ARTICLE, b'<html>file link</html>', 'text/html'), outcome='saved',
                 links=[dict(url=FILE, parent_url=ARTICLE, text='Background file')])
    first.save()
    rebuild_catalog(store, workers=1)
    child_id = next(r['source_id'] for r in table(store).to_pylist() if r['source_url'] == FILE)
    second = Archive(store, 'later-parent')
    second.record(response(ARTICLE, b'<html>file link</html>', 'text/html'), outcome='saved', links=[],
        context={'observations': [dict(url=ARTICLE, publisher_occurrences=[
            dict(page=HEARING, name='Yemen', url=ARTICLE)])]})
    second.save()
    rebuild_catalog(store, workers=1)
    child = next(r for r in table(store).to_pylist() if r['source_id'] == child_id)
    assert HEARING in child['source_original_page_url']
    third = Archive(store, 'new-file')
    new_url = 'https://example.org/new-attachment.pdf'
    third.record(response(FILE, b'%PDF-new'), outcome='saved', links=[dict(url=new_url, parent_url=FILE)])
    third.save()
    rebuild_catalog(store, workers=1)
    descendant = next(r for r in table(store).to_pylist() if r['source_url'] == new_url)
    assert HEARING in descendant['source_original_page_url']
    assert any(o.get('source_occurrence_scope') == ['linked_ancestor']
               and o.get('source_original_page_url') == [HEARING] for o in descendant['source_occurrences'])


def test_missing_retained_receipt_cannot_mark_backfill_complete(tmp_path, monkeypatch):
    import historical_raw_catalog as raw_catalog
    from historical_raw_archive import LegacyArchiveSeed as Archive
    from test_raw_catalog import initialize
    from test_raw_source_sync import response
    store = initialize(tmp_path)
    archive = Archive(store, 'missing-receipt')
    archive.record(response(FILE, b'%PDF-saved'), outcome='saved', links=[])
    archive.save()
    with monkeypatch.context() as old:
        old.setattr(raw_catalog, 'SOURCE_LINEAGE_VERSION', '0')
        raw_catalog.rebuild_catalog(store, workers=1)
    selected = store.read('indexes/catalog.json')
    key = archive.captures['receipt_key'][0].as_py()
    del store.objects[key]
    with pytest.raises(ValueError, match='Missing capture receipt'):
        raw_catalog.rebuild_catalog(store, workers=1)
    assert store.read('indexes/catalog.json') == selected
