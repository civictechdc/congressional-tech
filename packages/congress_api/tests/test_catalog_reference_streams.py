"""The existing pair-reference rules also validate changed bounded chunk streams."""
import pyarrow as pa
import pytest

from congress_api.retention.catalog_validation import CatalogReferenceCheck


SCHEMA = pa.schema([('source_id', pa.string()), ('document_id', pa.string())],
                   metadata={b'catalog_id': b'candidate'})


def rows(*pairs):
    return pa.Table.from_pylist([dict(source_id=source, document_id=document)
                                for source, document in pairs], schema=SCHEMA)


def test_complete_group_checks_references_across_multiple_chunks():
    with CatalogReferenceCheck(SCHEMA, SCHEMA) as check:
        check.add_sources(rows(('a', 'doc')))
        check.add_sources(rows(('b', 'doc')))
        check.add_documents(rows(('b', 'doc')))
        assert check.finish() == dict(source_rows=2, document_rows=1)


@pytest.mark.parametrize('source_chunks,documents', [
    ([rows(('a', 'doc')), rows(('a', 'doc'))], rows(('a', 'doc'))),
    ([rows(('a', 'missing'))], rows(('a', 'doc'))),
    ([rows(('a', 'doc'))], rows(('missing', 'doc'))),
    ([rows(('a', 'doc'))], rows(('a', 'doc'), ('a', 'doc'))),
    ([rows((None, 'doc'))], rows(('a', 'doc'))),
])
def test_streamed_reference_errors_preserve_existing_refusal(source_chunks, documents):
    with pytest.raises(ValueError, match='Document/source index references do not match'):
        with CatalogReferenceCheck(SCHEMA, SCHEMA) as check:
            for table in source_chunks:
                check.add_sources(table)
            check.add_documents(documents)
            check.finish()


def test_streamed_schema_identity_error_preserves_existing_refusal():
    with pytest.raises(ValueError, match='Document/source catalog_id values do not match'):
        CatalogReferenceCheck(SCHEMA, SCHEMA.with_metadata({b'catalog_id': b'other'}))


def test_failed_or_finished_check_cannot_accept_more_input():
    with CatalogReferenceCheck(SCHEMA, SCHEMA) as check:
        check.add_sources(rows(('a', 'doc')))
        with pytest.raises(ValueError, match='references do not match'):
            check.add_sources(rows(('a', 'doc')))
        with pytest.raises(ValueError):
            check.finish()
    with CatalogReferenceCheck(SCHEMA, SCHEMA) as check:
        check.add_sources(rows(('a', 'doc')))
        check.add_documents(rows(('a', 'doc')))
        check.finish()
        with pytest.raises(ValueError):
            check.add_sources(rows(('b', 'doc')))
    with pytest.raises(ValueError, match='cannot be reopened'):
        with check:
            pass
