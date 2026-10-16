"""Qualified native filenames keep their kinds and evidence in both tables."""
import pyarrow.parquet as pq
import pytest

from catalog_test_helpers import selected_path
from congress_api.retention import document_index as index


@pytest.mark.parametrize('name,url,kind,family', [
    ('PLAW-115publ401.pdf', 'https://www.congress.gov/115/plaws/publ401/PLAW-115publ401.pdf', 'public-law', 'legislation'),
    ('h2978fs_rh_xml.pdf', 'https://docs.house.gov/billsthisweek/20260518/h2978fs_rh_xml.pdf', 'legislative-text', 'legislation'),
    ('103-3.pdf', 'https://financialservices.house.gov/uploadedfiles/103-3.pdf', 'published-hearing', 'published-hearing'),
])
def test_native_kind_survives_paired_catalog_write(tmp_path, name, url, kind, family):
    (tmp_path / 'indexes').mkdir()
    index.write_filename_metadata(tmp_path, [dict(filename=name, source_url=url, body_key=None)], workers=1)
    for filename in ('document-filenames.parquet', 'documents.parquet'):
        row, = pq.read_table(selected_path(tmp_path / 'indexes' / filename)).to_pylist()
        assert row['document_kind'] == [kind]
        assert row['document_kind_source'] == ['filename']
        assert row['document_family'] == [family]
        if name == '103-3.pdf':
            assert not row.get('congress')
