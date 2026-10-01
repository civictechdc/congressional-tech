"""The corpus-facing API must preserve the shared engine's source evidence."""
import gzip
import json

import pytest

from house_naming import filenames
from house_naming.filename_corpus import build_corpus
from house_naming.naming import HOUSE_NAMING


@pytest.mark.parametrize('name', [
    'HR111111.pdf', 'H.R. 12345.pdf', 'Exhibit 12345.pdf', 'x-SD111111.pdf',
    'HHRG-112-ED-WState-IveyB-20110231.pdf',
    'BILLS-119hr2147483648ih.pdf', 'BILLS-119hr1rhuc.pdf',
    'BILLS-119HR2RepClyburnSomeTitleih.pdf',
    'Burman Statement - Attachment 3-27-19 SENR Cmte WP Subcmte Hrg.pdf',
])
def test_adapter_preserves_every_field_and_diagnostic(name):
    context = {'119': ('Clyburn',)}
    actual = filenames.parse_filename(name, member_surnames=context).model_dump(mode='json')
    expected = HOUSE_NAMING.extract(name, member_surnames=context)
    for key, target in [('input', 'filename'), ('stem_end', 'stem_end'),
                        ('observations', 'matches'), ('pieces', 'pieces'),
                        ('suppressed', 'suppressed'), ('issues', 'issues'),
                        ('rejected_candidates', 'rejected_candidates'), ('metadata', 'metadata')]:
        assert actual[target] == expected[key]


def test_adapter_calls_public_engine_once_and_preserves_context(monkeypatch):
    original = HOUSE_NAMING.extract
    calls = []
    def capture(name, **kwargs):
        calls.append((name, kwargs))
        return original(name, **kwargs)
    monkeypatch.setattr(HOUSE_NAMING, 'extract', capture)
    context = {'119': ('Clyburn',)}
    name = 'BILLS-119HR2RepClyburnSomeTitleih.pdf'
    parsed = filenames.parse_filename(name, member_surnames=context)
    assert calls == [(name, {'member_surnames': context})]
    assert any(f.name == 'member_surname_token' and f.raw == 'Clyburn' for m in parsed.matches for f in m.fields)
    assert not hasattr(filenames, 'RULES') and not hasattr(filenames, 'UNMATCHED_RULES')


def test_corpus_uses_engine_observations_and_retains_invalid_candidates(tmp_path):
    names = ['HR111111.pdf', 'H.R. 12345.pdf', 'AName-20261340.pdf']
    result = build_corpus(names, tmp_path)
    assert result['literal_filenames'] == 3
    assert result['structural_collisions'] == 0
    rows = list(map(json.loads, gzip.open(tmp_path / 'review.jsonl.gz', 'rt')))
    row = next(r for r in rows if r['filename'] == 'HR111111.pdf')
    assert any(f['name'] == 'measure_number' and f['raw'] == '111111' for m in row['matches'] for f in m['fields'])
    assert not any(f['name'] in {'date_token', 'short_date_token'} for m in row['matches'] for f in m['fields'])
    assert any(s['rule'] == 'short-date-compact' for s in row['suppressed'])


def test_registry_and_vocabulary_have_one_owner():
    assert filenames.registry() == [dict(r, flags=['IGNORECASE', 'ASCII']) for r in HOUSE_NAMING.extraction_rules()]
    copied = HOUSE_NAMING.extraction_rules()
    copied[0]['pattern'] = 'changed locally'
    assert copied != HOUSE_NAMING.extraction_rules()
    from house_naming.bill_codes import BILL_VERSIONS
    assert BILL_VERSIONS["rhuc"] == "Returned to House by Unanimous Consent"
    field = next(f for m in filenames.parse_filename('BILLS-119hr1rhuc.pdf').matches for f in m.fields
                 if f.name == 'version_token')
    assert field.code == 'rhuc'
    assert field.label == 'Returned to House by Unanimous Consent'
    assert field.vocabulary_url == 'https://www.govinfo.gov/help/bills'


@pytest.mark.parametrize('name,label', [
    ('Opening Statement.pdf', 'Opening Statement'),
    ('responses-to-questions-for-the-record', 'responses-to-questions-for-the-record'),
])
def test_complete_known_label_is_not_split_into_a_subject(name, label):
    matches = filenames.parse_filename(name).matches
    assert [m.rule for m in matches if m.scope == 'stem'] == ['label-only']
    assert any(f.name == 'label' and f.raw == label for m in matches for f in m.fields)
    assert not any(f.name == 'subject_token' for m in matches for f in m.fields)


def test_specific_malformed_sponsor_layout_retains_reference_without_duplicate_layout():
    parsed = filenames.parse_filename('BILLS-116-HR2474-KOOO395-Amdt-17.pdf')
    assert [m.rule for m in parsed.matches if m.scope == 'legislative-payload'] == ['unverified-sponsor-amendment']
    fields = [f for m in parsed.matches for f in m.fields]
    assert any(f.name == 'sponsor_identifier_token' and f.raw == 'KOOO395' for f in fields)
    assert any(f.name == 'measure_number' and f.raw == '2474' for f in fields)
    assert not any(f.name == 'bioguide_token' and f.raw == 'KOOO395' for f in fields)
