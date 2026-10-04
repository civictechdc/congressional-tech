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
