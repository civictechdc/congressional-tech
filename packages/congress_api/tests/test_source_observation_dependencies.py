"""Receipt ownership includes unresolved event reads and accepted URL edges."""
from congress_api.retention.document_index import DocumentSources, context_values


def locator(name, line=1):
    return context_values(source_receipt_key=name, source_receipt_line=line)


def meeting(congress=119):
    return dict(eventId='7', chamber='House', congress=congress,
                title=f'Meeting {congress}', _url=f'https://example.gov/{congress}/meeting')


def test_unresolved_and_ambiguous_event_reads_keep_exact_receipt_ownership():
    observations = []
    context = DocumentSources(observe=observations.append)
    with context.observation(locator('page-receipt', 2)):
        assert context.event_context('7') == {}
    context.add_meeting(meeting(), locator('meeting-receipt', 3))
    with context.observation(locator('page-receipt', 2)):
        assert context.event_context('7')['source_meeting_title'] == {'Meeting 119'}
    context.add_meeting(meeting(118), locator('other-meeting', 4))
    with context.observation(locator('page-receipt', 2)):
        assert context.event_context('7') == {}
    reads = [item for item in observations if item['kind'] == 'event' and item['access'] == 'read']
    assert len(reads) == 3
    assert all(item['value'] == '7' and item['receipt_key'] == 'page-receipt'
               and item['receipt_line'] == 2 for item in reads)
    writes = [item for item in observations if item['kind'] == 'event' and item['access'] == 'write']
    assert {(item['receipt_key'], item['value']) for item in writes} == {
        ('meeting-receipt', '7'), ('other-meeting', '7')}
    assert 'source_receipt_key' not in context.meetings[('119', 'house', '7')]


def test_dependency_trace_preserves_interpretation_and_transfer_suppression():
    observed = []
    context, reference = DocumentSources(observe=observed.append), DocumentSources()
    for collector in (context, reference):
        collector.add_link(dict(url='https://example.gov/paper.pdf', parent_url='https://example.gov/page',
                                label='Publisher label'), locator('links', 9))
        collector.add_transfer('https://example.gov/feed-rss.xml', 'https://example.gov/other.pdf',
                               context_values(source_association_basis='linked_page'))
    assert context.for_url('https://example.gov/paper.pdf') == reference.for_url('https://example.gov/paper.pdf')
    writes = [item for item in observed if item['kind'] == 'url' and item['access'] == 'write']
    assert any(item['value'] == 'https://example.gov/paper.pdf' and item['receipt_key'] == 'links' for item in writes)
    assert not any(item['value'] == 'https://example.gov/feed-rss.xml' for item in observed)


def test_refresh_context_tracks_event_read_under_original_link_receipt():
    observations = []
    context = DocumentSources(observe=observations.append)
    context.add_url('https://example.gov/paper.pdf', {
        **locator('child', 6), **context_values(source_meeting_id='7', source_chamber='House',
                                              source_page_url='https://example.gov/actual-parent')})
    context.add_meeting(meeting(), locator('meeting', 3))
    context.refresh_meeting_context()
    assert any(item['kind'] == 'event' and item['access'] == 'read' and item['receipt_key'] == 'child'
               for item in observations)
    row = context.for_url('https://example.gov/paper.pdf')
    assert row['source_page_url'] == ['https://example.gov/actual-parent']
    assert row['source_receipt_key'] == ['child']
