from __future__ import annotations

from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from viewer_publication.archive_model import (
    APPEARANCE_RECORD_FIELDS,
    WITNESSES_SQL,
    _normalize_appearance_rows,
    appearance_records_have_rank_credentials,
    appearance_steps,
)


def test_witnesses_sql_and_appearance_fields_expose_rank_and_credentials(tmp_path: Path):
    struct_fields = APPEARANCE_RECORD_FIELDS["appearances"]["List"]["data_type"]["Struct"]
    field_names = {f["name"] for f in struct_fields}
    assert {"rank", "credentials"} <= field_names
    assert "r.rank," in WITNESSES_SQL
    assert "r.credentials," in WITNESSES_SQL

    normalized = _normalize_appearance_rows(
        [
            {
                "record_sha": "aa" * 32,
                "source": "mods",
                "package_id": "CHRG-118shrg1",
                "collection_state": "present",
                "appearances": [
                    {
                        "source_locator": "mods:witness[1]",
                        "name": "Michael E. Conley",
                        "rank": "Lt. Gen.",
                        "credentials": "USAF",
                        "position": "Commander",
                    }
                ],
            }
        ]
    )
    assert normalized[0]["appearances"][0]["rank"] == "Lt. Gen."
    assert normalized[0]["appearances"][0]["credentials"] == "USAF"

    # Legacy Parquet without rank/credentials in appearances struct degrades cleanly
    legacy_struct = pa.struct(
        [
            pa.field("source_locator", pa.string(), nullable=False),
            pa.field("name", pa.string(), nullable=True),
            pa.field("document_links", pa.list_(pa.string()), nullable=False),
        ]
    )
    legacy_path = tmp_path / "legacy_appearance_records.parquet"
    pq.write_table(
        pa.table(
            {
                "record_sha": pa.array([b"\x11" * 32], type=pa.binary(32)),
                "parser_version": ["v1"],
                "status": ["completed"],
                "error_type": pa.array([None], type=pa.string()),
                "source": ["mods"],
                "appearances": pa.array(
                    [[{"source_locator": "mods:witness[1]", "name": "Jane Doe", "document_links": []}]],
                    type=pa.list_(legacy_struct),
                ),
            }
        ),
        legacy_path,
    )
    assert appearance_records_have_rank_credentials(legacy_path) is False
    fallback_steps = appearance_steps(has_rank_credentials=False)
    for step_name in ("congress_gov_witness_items", "appearance_occurrences"):
        step = next(s for s in fallback_steps if s["name"] == step_name)
        assert "cast(NULL AS VARCHAR) AS rank" in step["sql"]
        assert "cast(NULL AS VARCHAR) AS credentials" in step["sql"]
    resolved_step = next(s for s in fallback_steps if s["name"] == "appearance_records_resolved")
    assert "w.rank," in resolved_step["sql"]
    assert "w.credentials," in resolved_step["sql"]
