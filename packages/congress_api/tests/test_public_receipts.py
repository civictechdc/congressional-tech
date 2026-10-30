"""B0 prerequisite: running writers cannot add private metadata after cleanup."""
import gzip
import json
from pathlib import Path
import pytest


def test_new_receipt_header_allowlist_urls_and_paths_are_public():
    from congress_api.retention.receipt_privacy import public_receipt
    row = {'record': {'requested_url': 'https://api.congress.gov/v3/meeting?api_key=private&format=json%20xml',
                      'redirects': [{'url': 'https://example.gov/a?ToKeN=private&key=constant'}],
                      'headers': {'Content-Type': 'application/json', 'Set-Cookie': 'private',
                                  'Authorization': 'private', 'x-provider': 'private'},
                      'response_header_items': [{'name': 'ETag', 'value': 'public'},
                                                {'name': 'Cookie', 'value': 'private'}],
                      'body_path': '/private/tmp/local/file.json',
                      'content': {'body': None}},
           'captures': [{'pointer': ['content', 'body']}],
           'download_state': {'url': 'https://api.congress.gov/v3/meeting?api_key=private'}}
    clean = public_receipt(row)
    assert clean['record']['requested_url'] == 'https://api.congress.gov/v3/meeting?format=json%20xml'
    assert clean['record']['redirects'][0]['url'] == 'https://example.gov/a?key=constant'
    assert clean['record']['headers'] == {'Content-Type': 'application/json'}
    assert clean['record']['response_header_items'] == [{'name': 'ETag', 'value': 'public'}]
    assert clean['record']['body_path'] == 'file.json'
    assert clean['download_state']['url'] == 'https://api.congress.gov/v3/meeting'
    assert row['record']['body_path'].startswith('/private/')
    assert public_receipt(clean) == clean


def test_credential_registry_entries_remove_only_the_named_parameter():
    from congress_api.retention.receipt_privacy import credential_parameters, public_receipt
    for entry in credential_parameters():
        sample = entry['sample']
        assert public_receipt({'url': sample}) == {'url': entry['expected']}


def test_new_receipt_refuses_authority_credentials_and_pointer_path_keys():
    from congress_api.retention.receipt_privacy import public_receipt
    for row in [{'url': 'https://user:password@example.gov/a'},
                {'record': {'/tmp/a': None}, 'captures': [{'pointer': ['/tmp/a']}]}]:
        with pytest.raises(ValueError):
            public_receipt(row)
