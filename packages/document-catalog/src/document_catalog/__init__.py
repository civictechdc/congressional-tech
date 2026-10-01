"""Build local document catalogs from retained bytes.

Input: files or a JSON manifest and a versioned category configuration.
Processing: exact-byte identity, PDF capture, local OCR/layout observations,
candidate layout grouping, immutable evidence and layered section judgments.
Output: JSON/Parquet catalogs, plans, representative fixtures and local HTML.
Checking: ``document-catalog validate`` checks integrity and completeness, not
OCR, semantic, template or extracted-field accuracy. No field extraction runs.
"""

__version__ = "0.1.0"
