import importlib.util
import json
from pathlib import Path

import pytest


PATH = Path(__file__).parents[1] / 'prepare_ecoi_notice_candidate.py'
SPEC = importlib.util.spec_from_file_location('prepare_ecoi_notice_candidate', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CATALOG = 'https://www.ecoi.net/en/document/2074278.html'
TARGET = 'https://www.usaid.gov/sites/default/files/documents/fact-sheet.pdf'
CANDIDATE = 'https://www.ecoi.net/en/file/local/2074278/fact-sheet.pdf'


def page():
    return (f'<meta name="dc.identifier" content="2074278">'
            f'<meta name="dc.source" content="{TARGET}">'
            '<meta name="dc.title" content="Ukraine - Complex Emergency Fact Sheet #16, Fiscal Year (FY) 2022  ">'
            '<meta name="dc.date" content="2022-05-20">'
            f'<a href="{TARGET}">Original link</a>'
            '<a href="/en/file/local/2074278/fact-sheet.pdf">PDF</a>').encode()


def extract(raw, **changes):
    return MODULE.extract_record(raw, **dict(catalog_url=CATALOG, target_url=TARGET,
                                             candidate_url=CANDIDATE, **changes))


def test_real_catalog_fields_bind_both_urls_without_inventing_an_identifier(tmp_path):
    catalog = tmp_path / 'catalog.html'
    catalog.write_bytes(page())
    result = MODULE.prepare(catalog, catalog_url=CATALOG, target_url=TARGET,
                            candidate_url=CANDIDATE, reviewed_by='fixture reviewer',
                            reviewed_at='2026-11-06T17:00:00Z', output=tmp_path / 'review')
    facts = result['extracted_facts']
    assert facts['target']['url'] == TARGET
    assert facts['candidate']['url'] == CANDIDATE
    assert facts['target']['identifiers'] == facts['candidate']['identifiers']
    assert facts['target']['identifiers']['document'] == '2074278'
    assert result['acceptance_status'] == 'review_required'
    assert result['import_status'] == 'not_performed'
    assert 'receipt' not in result['identity_sources']['candidate']
    saved = json.loads((tmp_path / 'review/identity-metadata.json').read_text())
    assert saved['raw_source']['path'] == str(catalog)
    assert 'not issued by USAID' in saved['authority']


@pytest.mark.parametrize('wrong', [
    lambda raw: raw.replace(b'content="2074278"', b'content="2074279"'),
    lambda raw: raw.replace(TARGET.encode(), TARGET.replace('/documents/', '/2022-12/').encode()),
    lambda raw: raw.replace(b'<a href="/en/file/local/2074278/fact-sheet.pdf">PDF</a>', b''),
    lambda raw: raw.replace(b'2022-05-20', b'2022-05'),
    lambda raw: raw + b'<meta name="dc.identifier" content="2074278">',
    lambda raw: b' ' * (1024 * 1024 + 1),
])
def test_wrong_source_or_unavailable_evidence_refuses(wrong):
    with pytest.raises(ValueError):
        extract(wrong(page()))


def test_refuses_candidate_from_another_catalog_record():
    with pytest.raises(ValueError, match='outside this catalog'):
        MODULE.extract_record(page(), catalog_url=CATALOG, target_url=TARGET,
                              candidate_url=CANDIDATE.replace('/2074278/', '/2074279/'))
