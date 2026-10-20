"""Catalog continuation identities preserve sorting without resident key lists."""
from hashlib import sha256
from contextlib import closing

import pytest

from congress_api.retention.catalog_inputs import CatalogKeys
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.immutable_metadata import encoded


@pytest.mark.parametrize('values', [[], ['z', 'a', 'z'], ['é', '🌶', 'a"b', '\n', '\x00']])
def test_streaming_identity_matches_existing_canonical_list(tmp_path, values):
    with closing(WorkingCatalog(tmp_path / 'work.sqlite')) as work:
        keys = CatalogKeys(work, 'keys', iter(values), 'Keys')
        expected = sorted(set(values))
        assert list(keys) == list(keys) == expected
        assert keys.identity() == dict(count=len(expected), sha256=sha256(encoded(expected)).hexdigest())
        assert len(keys) == len(expected)
        assert all(value in keys for value in expected)


@pytest.mark.parametrize('values,message', [(['a', 'a'], 'must not repeat'), (['a', None], 'nonempty'), ([''], 'nonempty')])
def test_invalid_or_repeated_removals_refuse(tmp_path, values, message):
    with closing(WorkingCatalog(tmp_path / 'work.sqlite')) as work:
        with pytest.raises(ValueError, match=message):
            CatalogKeys(work, 'keys', iter(values), 'Deletions', reject_duplicates=True)
