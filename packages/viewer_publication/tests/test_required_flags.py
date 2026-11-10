"""Six published boolean flags stay `required` in their Parquet footers (ct-8m0e).

Each is spelled `<expression> IS TRUE` in the last projection of a retained model step: `hidden` (step
`normalized`, archive_model.py), `is_real_file` (record-roles.sql) and `filename_date_eligible`
(source-annotations-filename.sql). `coalesce(<expression>, false)` holds the same values, and an engine
that types a column from the statement as written marks both required. An engine that types it from the
optimized plan reads coalesce as `x IS NOT NULL AND x`, never null but typed nullable, and the column turns
optional; `x IS NOT DISTINCT FROM true` is typed nullable either way.

So on the engine pinned on 2026-11-10 (b0342a7) this test passes for coalesce and for IS TRUE alike and
fails for `IS NOT DISTINCT FROM true`. Its job is to fail when an engine that types from the optimized plan
is pinned while one of the three is spelled another way: on that line a fixture model job flipped all six
(measured 2026-11-10 by one job file run on both binaries; ticket ct-8m0e names the evidence).

IS TRUE suits these three and not saved-name-conflicts.sql because nothing later in their own statements
reads them. The planner types IS TRUE nullable while the plan declares it not null, and refuses any
aggregate whose input holds such a column. GROUP BY, DISTINCT and UNION all plan as one, and so does a
later statement that reads the flag through a step that is not materialized (a view is planned inside
its reader). A retained step hands its readers the declared type, so use IS TRUE only for a flag in the
last projection of a materialized step, and `IS NOT DISTINCT FROM true` for one read again before that.
"""
import os

import pyarrow.parquet as pq

from docspec_client.client import NativeDatasets
from test_phase2_model_entities import _stage_raw_fixture

FLAGS = [
    ('release/list.parquet', 'hidden'),
    ('release/detail.parquet', 'hidden'),
    ('model/evidence/document_rows.parquet', 'hidden'),
    ('model/evidence/record_roles.parquet', 'is_real_file'),
    ('model/evidence/capture_sources.parquet', 'is_real_file'),
    ('model/evidence/source_filename_readings.parquet', 'filename_date_eligible'),
]


def _repetition(path, column):
    """A top-level column's repetition in the Parquet schema itself, not in the embedded Arrow schema."""
    schema = pq.ParquetFile(path).schema
    node = next(schema.column(i) for i in range(len(schema.names)) if schema.column(i).path == column)
    return 'required' if node.max_definition_level == 0 else 'optional'


def test_six_published_flags_are_required_in_their_footers(tmp_path):
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    staged = _stage_raw_fixture(tmp_path, engine, [dict(url='https://fixture.test/report.pdf', format='pdf',
        compress=False, data=b'%PDF-1.7\nfixture retained bytes\n%%EOF\n')])
    build_release(captures=staged['captures'], readings=staged['readings'],
        filename_readings=staged['filename_readings'],
        parser_versions={p: staged['parser_versions'][p] for p in ['sniff', 'html', 'xml', 'json']},
        catalog_version=staged['catalog_version'], engine=engine, output=tmp_path / 'release',
        scratch=tmp_path / 'model')
    # The reader tells the two apart: a document's title may be absent.
    assert _repetition(tmp_path / 'release/list.parquet', 'title') == 'optional'
    assert pq.ParquetFile(tmp_path / 'release/list.parquet').metadata.num_rows == 1
    assert {f'{path}:{column}': _repetition(tmp_path / path, column) for path, column in FLAGS} == {
        f'{path}:{column}': 'required' for path, column in FLAGS}
