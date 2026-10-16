"""Typed display facts never silently select conflicting source observations."""
import importlib.util
from pathlib import Path
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location('details', Path(__file__).resolve().parents[1] / 'apps/site/scripts/filename_details.py')
details = importlib.util.module_from_spec(spec)
spec.loader.exec_module(details)


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
