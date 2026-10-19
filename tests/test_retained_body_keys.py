"""The shared key rule preserves each evidence consumer's refusal behavior."""
import gzip
from hashlib import sha256

import pytest

from congress_api.retention.body_keys import body_key_digest
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.document_index import validated_body_readings
from filename_aliases import valid_body


def reading(key):
    return dict(body_key=key, parser_fingerprint='1' * 64, status='completed',
                error_type=None, body_format=['pdf'])


@pytest.mark.parametrize('key', [None, '', False, 0, [], {}, 'other',
    'bodies/sha256/bb/' + 'a' * 64 + '.gz',
    'bodies/sha256/aa/' + 'a' * 63 + '.gz',
    'bodies/sha256/aa/' + 'A' * 64 + '.gz',
    'bodies/sha256/aa/' + 'a' * 64 + '.gz\n',
    '../bodies/sha256/aa/' + 'a' * 64 + '.gz'])
def test_invalid_and_missing_keys_keep_existing_abstention_and_reading_errors(tmp_path, key):
    assert body_key_digest(key) is None
    assert valid_body(key) is False
    def unexpected_read(_key):
        pytest.fail('Invalid keys must not read retained bytes')
    assert read_retained_body(tmp_path, key, read_compressed=unexpected_read) is None
    message = 'distinct qualified' if isinstance(key, str) else 'identity and parser fingerprint strings'
    with pytest.raises(ValueError, match=message):
        validated_body_readings([reading(key)])


@pytest.mark.parametrize('key', [1, True, ['not a key'], {'not': 'a key'}, b'not a key'])
def test_nonempty_wrong_types_keep_regex_errors_and_explicit_pdf_refusal(tmp_path, key):
    for parse in (body_key_digest, valid_body, lambda value: read_retained_body(tmp_path, value)):
        with pytest.raises(TypeError):
            parse(key)
    with pytest.raises(ValueError, match='identity and parser fingerprint strings'):
        validated_body_readings([reading(key)])


def test_valid_digest_is_shared_without_changing_body_bytes_or_completed_reading(tmp_path):
    data = 'Exact source bytes: José 🏛️\n'.encode()
    digest = sha256(data).hexdigest()
    key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    assert body_key_digest(key) == digest
    assert valid_body(key) is True
    original = reading(key)
    assert validated_body_readings([original]) == {key: original}
    payload = gzip.compress(data)
    assert read_retained_body(tmp_path, key, read_compressed=lambda requested: payload if requested == key else None) == data
    with pytest.raises(ValueError, match='Retained body digest mismatch'):
        read_retained_body(tmp_path, key, read_compressed=lambda _: gzip.compress(data + b'changed'))
