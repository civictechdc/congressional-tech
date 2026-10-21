"""Typed display facts never silently select conflicting source observations."""
from datetime import datetime, timezone
import viewer_publication.filename_details as details


def test_typed_facts_preserve_unknown_and_conflicting_states():
    assert details.typed_value('http_status', ['200']) == 200
    assert details.typed_value('http_status', ['0200']) is None
    assert details.typed_value('http_status', ['200','404']) is None
    assert details.typed_value('response_usable', ['false']) is False
    assert details.typed_value('response_body_complete', ['true','false']) is None
    assert details.typed_value('response_usable', None) is None
    assert details.typed_value('response_usable', []) is None
    assert details.typed_value('state_checked_at', ['2026-10-14T09:00:00-04:00']) == datetime(2026,10,14,13,tzinfo=timezone.utc)
    assert details.typed_value('state_checked_at', ['2026-10-14T09:00:00']) is None
