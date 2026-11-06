"""Congress research over the current archive release model."""
__version__ = '0.6.2'

# Shared by shipped launch checks and transport tests. Adding a public tool must
# update the same declared surface that installed and hosted checks verify.
TOOL_NAMES = frozenset({
    'get_overview', 'get_dataset_status', 'get_dataset_info', 'search_documents',
    'get_document', 'get_documents', 'search_entities', 'get_entity', 'query_sql',
    'get_bill_actions', 'get_roll_calls', 'get_member_ballots', 'get_activity', 'run_research_query',
    'get_transcript', 'get_hearing_bundle', 'resolve_citation',
})
