"""Qualified PDF text supplies the existing Tier-1 cover-kind policy.

This input changes kind/family only under body-cover-kinds.sql's existing scope.
It does not rename publisher files or infer document associations.
"""
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

from congress_api.retention.provenance import json_input, run_job
from viewer_publication.archive_format import _settings
from viewer_publication.body_text_slices import slice_pages

ROOT = Path(__file__).parents[4]
FIELDS = ("body_sha256", "parser_version", "text_sha256", "source_review_sha256", "cover_document_kind")


def model_input(value, scratch):
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    if value is None:
        source = json_input(scratch, "pdf_cover_evidence_input", [], **{name: "Utf8" for name in FIELDS})
    else:
        path = Path(value["path"])
        rows = pq.read_table(path, columns=list(FIELDS)).to_pylist()
        allowed = {row["id"].removeprefix("cover:")
                   for row in json.loads((ROOT/"model/registries/page-signals.json").read_text())
                   if row["kind"] == "cover_kind"}
        seen = set()
        for row in rows:
            body = row["body_sha256"]
            if body in seen:
                raise ValueError("PDF cover evidence repeats a body")
            seen.add(body)
            if any(not isinstance(row[name], str) or not re.fullmatch("[0-9a-f]{64}", row[name])
                   for name in FIELDS[:-1]):
                raise ValueError("PDF cover evidence requires exact reading/text/review identities")
            if row["cover_document_kind"] not in allowed:
                raise ValueError("PDF cover evidence must name a supported kind")
        source = dict(name="pdf_cover_evidence_input", kind="parquet", path=str(path))
    step = dict(name="pdf_cover_signals", sql="""SELECT
        arrow_cast(decode(body_sha256,'hex'),'FixedSizeBinary(32)') AS body_sha,
        'completed' AS status, false AS error_response, cover_document_kind
        FROM pdf_cover_evidence_input""", materialize=True)
    return source, step


def classify_selected_covers(records, *, engine, work, source_review_sha256, root=ROOT):
    """Classify a bounded set of already-selected text rows with maintained SQL.

    The caller supplies selected body/parser/version/text identities and their
    retained source review. No new extraction or LLM classification occurs.
    """
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    rows = []
    from hashlib import sha256
    for row in records:
        if row["parser"] != "pdf_text":
            raise ValueError("PDF cover input requires selected PDF text")
        if sha256(row["text"].encode()).digest() != row["text_sha256"]:
            raise ValueError("PDF cover input text digest mismatch")
        text_head = slice_pages(row["text"], row["page_offsets"], max_pages=1)[:2048]
        rows.append(dict(body_sha256=row["body_sha"].hex(), parser_version=row["parser_version"],
                         text_sha256=row["text_sha256"].hex(), source_review_sha256=source_review_sha256,
                         text_head=text_head, text_bytes=len(text_head.encode())))
    inputs = [json_input(work, "pdf_heads", rows, body_sha256="Utf8", parser_version="Utf8",
                         text_sha256="Utf8", source_review_sha256="Utf8", text_head="Utf8", text_bytes="Int64")]
    rules = json.loads((Path(root)/"model/registries/page-signals.json").read_text())
    inputs.append(json_input(work, "page_signals", rules,
                             id="Utf8", kind="Utf8", pattern="Utf8", number="Int64"))
    output = work / "pdf-cover-evidence.parquet"
    steps = [dict(name="page_facts", sql="""SELECT decode(body_sha256,'hex') AS body_sha,
        'completed' AS status, cast(NULL AS VARCHAR) AS xml_root, cast(NULL AS VARCHAR) AS title,
        cast(NULL AS VARCHAR) AS heading, text_head,text_bytes,
        cast(0 AS BIGINT) AS link_count,cast(0 AS BIGINT) AS link_text_bytes FROM pdf_heads"""),
        dict(name="cover_signals", sql=(Path(root)/"model/sql/body-signals.sql").read_text(), materialize=True)]
    result = run_job(work/"job", engine, inputs=inputs, steps=steps,
        outputs=[dict(name=output.name, path=str(output),
                      sql="""SELECT h.body_sha256,h.parser_version,h.text_sha256,h.source_review_sha256,
                        s.cover_document_kind FROM pdf_heads h JOIN cover_signals s
                        ON decode(h.body_sha256,'hex')=s.body_sha
                        WHERE s.status='completed' AND NOT s.error_response AND s.cover_document_kind IS NOT NULL""",
                      settings=_settings("whole", ["body_sha256"]))],
        queries=[dict(name="coverage", sql="""SELECT count(*) AS inspected,
          count(cover_document_kind) AS classified FROM cover_signals""")])
    return output, result
