"""Normal MCP client checks shared by installed, desktop and hosted releases."""
from hashlib import sha256
import time

from . import TOOL_NAMES, __version__
from .citations import TEXT_READER_VERSION


async def check_client(client, release_id=None, *, plan=None, require_research=False):
    """Check available research paths; retain explicit gaps on older fixtures.

    A release qualification can supply event_id, document_reference and search_text
    from its retained evidence, and require actual text/citation round trips.
    """
    plan = plan or {}
    tools = await client.list_tools()
    assert {tool.name for tool in tools} == TOOL_NAMES
    assert all(tool.annotations.read_only_hint for tool in tools)
    assert client.server_info is not None and client.server_info.version == __version__
    checks, timings, called = [], {}, set()

    async def call(name, arguments=None, label=None):
        started = time.monotonic()
        result = (await client.call_tool(name, arguments or {})).data
        called.add(name)
        timings[label or name] = round(time.monotonic() - started, 3)
        if isinstance(result, dict) and result.get('release_id') is not None and release_id is not None:
            assert result['release_id'] == release_id, (name, result['release_id'], release_id)
        return result

    def record(name, state='passed', **details):
        checks.append(dict(operation=name, state=state, **details))

    async def sql(text, parameters=None):
        return (await call('query_sql', {'query': dict(sql=text, parameters=parameters or [], limit=5)}, text))['rows']

    async def round_trip(citation, label):
        result = await call('resolve_citation', {'citation': citation}, label)
        assert result['state'] == 'resolved', result
        assert sha256(result['text'].encode()).hexdigest() == citation['text_sha256']
        record(label, location=citation['location'])

    info = await call('get_dataset_info')
    release_id = release_id or info['release_id']
    assert info['release_id'] == release_id
    overview = await call('get_overview')
    status = await call('get_dataset_status')
    assert overview['release_id'] == status['release_id'] == release_id
    tables = info['tables']
    record('discovery', tables=len(tables), publication_status=status['publication_status'])
    found = await call('search_documents', {'query': {'limit': 1}})
    assert found['rows'], 'A release must include a visible document'
    reference = found['rows'][0]['reference']
    document = await call('get_document', {'query': reference})
    assert document['rows'][0]['filename'] == found['rows'][0]['filename']
    batch = await call('get_documents', {'query': {'items': [reference, dict(reference, release_id='0' * 64)]}})
    assert batch['items'][0]['result'] == document and batch['items'][1]['status'] == 'error'
    recent = await call('search_documents', {'query': {'sort': 'recent', 'limit': 5}}, 'accepted-document-dates')
    assert 'date_qualification' in recent
    assert all(row.get('document_date_status') != 'suspect' for row in recent['rows'])
    record('documents-and-batch', sample_rows=len(document['rows']), date_qualification=recent['date_qualification'])

    single_keys = [(name, keys[0]) for name, keys in info['entity_keys'].items() if name in tables and len(keys) == 1]
    if single_keys:
        table, key = next((value for value in single_keys if value[0] == 'bills'), single_keys[0])
        schema = await call('get_dataset_info', {'table': table}, 'focused-schema')
        entities = await call('search_entities', {'query': {'table': table, 'limit': 1}})
        assert entities['rows']
        identity = entities['rows'][0][key]
        entity = await call('get_entity', {'query': {'table': table, 'id': identity}})
        compact = await call('get_entity', {'query': {'table': table, 'id': identity, 'fields': [key]}}, 'compact-entity')
        assert compact['rows'] == [{key: identity}]
        assert entity['rows'][0][key] == identity and schema['available']
        record('entity-and-compact-fields', table=table, identity=identity)
    else:
        assert (await call('get_dataset_info', {'table': 'list'}, 'focused-schema'))['available']
        record('entity-and-compact-fields', 'unavailable', reason='Selected release lacks published entity identity metadata')

    for tool, table_name in [('get_bill_actions', 'bill_actions'), ('get_roll_calls', 'roll_call_votes'), ('get_member_ballots', 'member_votes')]:
        result = await call(tool, {'query': {'limit': 1}})
        assert result['coverage']['status'] == ('available' if table_name in tables else 'unavailable')
        if require_research:
            assert result['rows'], f'{tool} has no retained detail row to qualify'
        record(tool, 'passed' if table_name in tables else 'unavailable', rows=len(result['rows']), coverage=result['coverage'])
    activity = await call('get_activity', {'query': {'since': plan.get('since', '2026-01-01'), 'until': plan.get('until', '2027-01-01'), 'limit': 2}})
    if require_research:
        assert activity['rows'], 'The probe plan must select a retained activity interval'
    record('activity', 'unavailable' if activity['coverage']['status'] == 'unavailable' else 'passed', rows=len(activity['rows']), coverage=activity['coverage'])
    # Older fixtures do not declare the new recipes; retain that boundary.
    try:
        named = await call('run_research_query', {'query': {'name': 'recent_bills', 'limit': 1}})
        if require_research:
            assert named['rows'], 'No retained recent bill was read'
        record('named-query', 'unavailable' if named['coverage']['status'] == 'unavailable' else 'passed', rows=len(named['rows']))
    except Exception as error:
        if 'does not publish the named research recipe' not in str(error):
            raise
        called.add('run_research_query')
        record('named-query', 'unavailable', reason='Selected release lacks named research recipes')

    cue_read = False
    if 'meetings' in tables:
        event = plan.get('event_id')
        if event is None:
            rows = await sql('SELECT event_id FROM meetings ORDER BY CASE WHEN event_id=338785 THEN 0 ELSE 1 END,event_id LIMIT 1')
            event = rows[0]['event_id'] if rows else None
        if event is not None:
            inventory = await call('get_transcript', {'event_id': event, 'limit': 10})
            bundle = await call('get_hearing_bundle', {'event_id': event, 'limit': 1})
            assert bundle['sections']['meeting']['rows'][0]['event_id'] == int(event)
            record('hearing-dossier-and-inventory', event_id=event, sources=len(inventory['rows']))
            captions = [row for row in inventory['rows'] if row['kind'] == 'captions' and row.get('saved_url')]
            if captions:
                cues = await call('get_transcript', {**captions[0]['reference'], 'limit': 1}, 'caption-cue-read')
                if cues['rows']:
                    await round_trip(cues['rows'][0]['citation'], 'caption-citation-round-trip')
                    cue_read = True
                else:
                    record('caption-cue-read', 'unavailable', state_detail=cues['state'], missing_resources=cues.get('missing_resources'))
    if not cue_read:
        record('caption-cue-round-trip', 'unavailable', reason='No readable retained cue selected; use an evidence-backed event_id plan')

    body_read = False
    body_reference = plan.get('document_reference')
    if body_reference:
        text = await call('get_document', {'query': {**body_reference, 'section': 'text', 'page': 1, 'max_chars': 500}}, 'document-page-read')
        if text.get('citation'):
            await round_trip(text['citation'], 'document-citation-round-trip')
            body_read = True
    if not body_read:
        record('document-page-round-trip', 'unavailable', reason='Supply a retained readable document_reference in the probe plan')

    search_read = False
    if 'search_text' in TOOL_NAMES:
        try:
            search = await call('search_text', {'query': {'text': plan.get('search_text', 'Congress'), 'limit': 1}})
            if search.get('rows'):
                await round_trip(search['rows'][0]['citation'], 'search-citation-round-trip')
                search_read = True
            record('body-search', 'passed' if search_read else 'unavailable', coverage=search.get('coverage'), rows=len(search.get('rows', [])))
        except Exception as error:
            if 'Corpus text index is unavailable in this release; metadata search and get_document remain available' not in str(error):
                raise
            called.add('search_text')
            record('body-search', 'unavailable', reason='Corpus text index is unavailable in this release')
    if 'resolve_citation' not in called:
        # Exercise a release-bound refusal without fetching unavailable originals.
        result = await call('resolve_citation', {'citation': dict(version=1, source=dict(reference, release_id='0' * 64),
            saved_body='0' * 64, reader_version=TEXT_READER_VERSION, location=dict(kind='body_text', page=1, offset=0, length=1), text_sha256='0' * 64)})
        assert result['state'] in ('unavailable', 'different_source')
        record('stale-citation-refusal')
    for query, expected in [({'sql': 'SELECT FROM'}, 'Parser Error'),
        ({'sql': 'SELECT imaginary_column FROM documents'}, 'imaginary_column'),
        ({'sql': 'SELECT ? AS n'}, 'parameters: 1'),
        ({'sql': 'DROP VIEW documents'}, 'read-only SELECT')]:
        result = await client.call_tool('query_sql', {'query': query}, raise_on_error=False)
        assert result.is_error and expected in result.content[0].text
    assert await sql('SELECT ? AS n', [7]) == [{'n': 7}]
    record('sql-diagnostics-and-read-only')
    if require_research:
        assert cue_read and body_read and search_read and single_keys, 'Research qualification requires entity, caption, document and search citation round trips'
        assert called == TOOL_NAMES, f'Tools without a successful normal call: {sorted(TOOL_NAMES-called)}'
        assert all(item['state'] != 'unavailable' for item in checks if item['operation'] in
                   {'get_bill_actions', 'get_roll_calls', 'get_member_ballots', 'activity', 'named-query'})
    return dict(status='ok', version=__version__, release_id=release_id, tools=sorted(TOOL_NAMES),
        tables=len(tables), sample_rows=len(document['rows']), checks=checks, seconds=timings,
        tool_coverage=dict(called=sorted(called), unavailable=sorted(TOOL_NAMES-called)),
        research_qualified=cue_read and body_read and search_read)
