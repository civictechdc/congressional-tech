"""Verify ct-tcs4 refactoring: lazy guide loading, URL normalization, CLI error boundary, and appropriation stripping."""
import io
import json
import pytest

from house_naming.catalog import strip_appropriation_prefix, load_guide
from house_naming.cli import cli_error_boundary
from house_naming.errors import NamingError
from house_naming.extraction import validate_http_url, Extractor
from house_naming import Engine
import house_naming.naming as naming
import house_naming.bill_codes as bill_codes


def test_strip_appropriation_prefix():
    assert strip_appropriation_prefix('fy2020-agriculture') == 'agriculture'
    assert strip_appropriation_prefix('fy24-defense') == 'defense'
    assert strip_appropriation_prefix('financial-services') == 'financial-services'
    assert strip_appropriation_prefix('') == ''


def test_lazy_house_naming_and_bill_codes():
    # Test lazy Engine accessor
    eng = naming.get_engine()
    assert isinstance(eng, Engine)
    assert naming.HOUSE_NAMING is eng
    assert isinstance(naming.COLLECTION_CODES, tuple)
    assert 'crpt' in naming.COLLECTION_CODES
    assert isinstance(naming.APPROPRIATION_SUBJECTS, tuple)
    assert 'agriculture' in naming.APPROPRIATION_SUBJECTS

    # Test bill_codes lazy accessors
    assert isinstance(bill_codes.BILL_TYPES, dict)
    assert bill_codes.BILL_TYPES['hr'] == 'House Bill'
    assert isinstance(bill_codes.BILL_VERSIONS, dict)
    assert 'ih' in bill_codes.BILL_VERSIONS
    codes = bill_codes.BILL_CODES
    assert 'types' in codes and 'versions' in codes


def test_validate_http_url():
    # Valid URLs
    res = validate_http_url('https://docs.house.gov/bill.pdf')
    assert res.hostname == 'docs.house.gov'

    # Rejection of credentials
    with pytest.raises(NamingError) as exc:
        validate_http_url('https://user:pass@docs.house.gov/bill.pdf')
    assert exc.value.code == 'invalid-url'

    # Rejection of invalid port when restricted
    with pytest.raises(NamingError) as exc:
        validate_http_url(
            'https://docs.house.gov:8080/bill.pdf',
            allowed_ports={None, 80, 443},
            error_code='invalid-source-url',
            error_message='Disallowed port',
        )
    assert exc.value.code == 'invalid-source-url'

    # Rejection of spaces
    with pytest.raises(NamingError) as exc:
        validate_http_url('https://docs.house.gov/bill text.pdf')
    assert exc.value.code == 'invalid-url'


def test_cli_error_boundary(monkeypatch):
    stderr = io.StringIO()
    monkeypatch.setattr('sys.stderr', stderr)

    # Success returns 0
    assert cli_error_boundary(lambda: 0) == 0

    # BrokenPipeError returns 0
    def raise_broken_pipe():
        raise BrokenPipeError
    assert cli_error_boundary(raise_broken_pipe) == 0

    # NamingError with usage code returns 2
    def raise_usage_error():
        raise NamingError('usage', 'Bad argument')
    assert cli_error_boundary(raise_usage_error) == 2
    err = json.loads(stderr.getvalue())
    assert err['error']['code'] == 'usage'

    # NamingError with domain code returns 1
    stderr.truncate(0)
    stderr.seek(0)
    def raise_not_found():
        raise NamingError('not-found', 'Item not found')
    assert cli_error_boundary(raise_not_found) == 1
    err = json.loads(stderr.getvalue())
    assert err['error']['code'] == 'not-found'


def test_extractor_decomposed_stages():
    guide = load_guide()
    extractor = Extractor(guide)

    # Test stage 1 validation
    with pytest.raises(NamingError) as exc:
        extractor._validate_and_split_envelope('/absolute/path/file.pdf', None, None)
    assert exc.value.code == 'invalid-filename'

    # Test stage 1 successful envelope split
    start, stem_end, host, obs, readings, ignored = extractor._validate_and_split_envelope(
        'BILLS-112hr123ih.pdf?download=1', None, 'https://www.govinfo.gov/bills.pdf'
    )
    assert start == 0
    assert host == 'www.govinfo.gov'
    assert any(o['rule'] == 'query-shaped-suffix' for o in obs)
    assert any(o['rule'] == 'extension' for o in obs)
