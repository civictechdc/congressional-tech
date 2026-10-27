"""S1 parser fixtures: expected evidence precedes the parser and model SQL."""

import json
from pathlib import Path

import pytest


CASES = json.loads((Path(__file__).parents[3] / 'model/fixtures/parser-cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_reading_preserves_unresolved_publisher_evidence(case):
    from congress_api.parsers.archive_readings import read_page

    actual = read_page(case['body'].encode(), case['parser'])
    assert actual['status'] == 'completed'
    for field, expected in case['expected'].items():
        if field == 'links':
            assert len(actual[field]) == len(expected)
            for value, wanted in zip(actual[field], expected, strict=True):
                assert {key: value[key] for key in wanted} == wanted
        else:
            assert actual[field] == expected
    assert read_page(case['body'].encode(), case['parser']) == actual
