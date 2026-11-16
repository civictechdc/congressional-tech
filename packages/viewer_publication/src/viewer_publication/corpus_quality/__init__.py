"""DRY Corpus Quality & Dataset Validation Suite for congressional-tech releases."""
from __future__ import annotations

import importlib
from typing import Any

from .core import (
    DEFAULT_STOPWORDS,
    CorpusDocRow,
    HeaderFooterWindows,
    QualityFinding,
    Severity,
    extract_header_footer_windows,
    extract_url_host,
    iter_corpus_rows,
    iter_word_ngrams,
    load_corpus_rows,
    resolve_docmeta_paths,
    structural_shingles,
    tokenize_words,
    unwrap_archive_url,
    url_path_template,
)

__all__ = [
    "DEFAULT_STOPWORDS",
    "CorpusDocRow",
    "HeaderFooterWindows",
    "QualityFinding",
    "Severity",
    "extract_header_footer_windows",
    "extract_url_host",
    "iter_corpus_rows",
    "iter_word_ngrams",
    "load_corpus_rows",
    "resolve_docmeta_paths",
    "structural_shingles",
    "tokenize_words",
    "unwrap_archive_url",
    "url_path_template",
    # Lazy submodule exports so sibling modules load cleanly without import cycles
    "provenance_validator",
    "tfidf_drift",
    "tail_clusters",
    "stratified_sampler",
]

_LAZY_SUBMODULES = frozenset(
    {
        "provenance_validator",
        "tfidf_drift",
        "tail_clusters",
        "stratified_sampler",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_SUBMODULES:
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
