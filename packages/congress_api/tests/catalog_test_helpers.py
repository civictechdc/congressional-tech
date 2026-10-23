"""Resolve legacy test requests through the selected public catalog, when present."""
from pathlib import Path
from congress_api.retention.catalog_publication import MANIFEST_KEY,local_catalog_paths


def selected_path(path):
    if isinstance(path,(str,Path)):
        candidate=Path(path)
        if candidate.parent.name=='indexes' and candidate.name in ('document-filenames.parquet','documents.parquet'):
            root=candidate.parent.parent
            if (root / MANIFEST_KEY).is_file():
                return local_catalog_paths(root)[candidate.name=='documents.parquet']
    return path


def selected_table(store, *, documents=False):
    import pyarrow.parquet as pq
    from congress_api.retention.catalog_publication import read_catalog
    with read_catalog(store) as snapshot:
        return pq.read_table(snapshot.documents_path if documents else snapshot.filenames_path)


def table(store, key=None):
    """Read a parquet table from the store or public catalog snapshot."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.catalog_publication import read_catalog
    from historical_raw_catalog import FILENAMES, DOCUMENTS
    if key is None:
        key = FILENAMES
    if key in (FILENAMES, DOCUMENTS):
        with read_catalog(store) as snapshot:
            return pq.read_table(snapshot.filenames_path if key == FILENAMES else snapshot.documents_path)
    return pq.read_table(pa.BufferReader(store.read(key)))


def initialize(tmp_path):
    """Initialize test document-index files in tmp_path and return populated MemoryStore."""
    from congress_api.retention import document_index as index
    from historical_raw_catalog import FILENAMES, DOCUMENTS
    from testing_fakes import MemoryStore
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)
    index.write_filename_metadata(
        tmp_path,
        [
            dict(
                body_key=None,
                filename="Known statement.pdf",
                source_url="https://example.gov/Known%20statement.pdf",
            )
        ],
        workers=1,
    )
    store = MemoryStore()
    for key in (FILENAMES, DOCUMENTS):
        store.objects[key] = selected_path(tmp_path / key).read_bytes()
    return store


def source(name, body=None, **values):
    """Build a mock source record dictionary."""
    return {**dict(body_key=body, filename=name, source_url='https://example.gov/' + name,
                   media_type=['application/pdf'], http_status=['200'], capture_outcome=['saved']), **values}


def identity(row):
    """Resolve the source record identity string."""
    from congress_api.retention import document_index as index
    return index.source_identity(row)
