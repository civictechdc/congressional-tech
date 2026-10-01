"""Immutable, portable JSON/Parquet tables and self-contained local HTML."""

import base64
import html
from io import BytesIO
import json
from pathlib import Path

from .store import canonical, digest


def esc(value):
    return html.escape(str(value), quote=True)


def preview(store, page):
    if "image" not in page:
        return ""
    from PIL import Image
    with Image.open(BytesIO(store.read(page["image"]))) as image:
        image.thumbnail((520, 680))
        output = BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=72)
    url = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()
    rectangles = "".join(f'<rect x="{r["bbox"][0]}" y="{r["bbox"][1]}" width="{r["bbox"][2]-r["bbox"][0]}" height="{r["bbox"][3]-r["bbox"][1]}" />'
                         for r in page.get("layout", {}).get("regions", []))
    return f'<svg viewBox="0 0 1 1" preserveAspectRatio="none" style="aspect-ratio:{page["render_pixels"][0]}/{page["render_pixels"][1]}"><image href="{url}" width="1" height="1" preserveAspectRatio="none"/><g fill="none" stroke="#d54727" stroke-width=".002">{rectangles}</g></svg>'


def report(store, catalog, sha):
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Document catalog</title><style>body{font:16px system-ui;margin:2rem auto;max-width:1200px;padding:0 1rem;color:#172c34;background:#f7f5ee}h1{font-size:2rem}details{background:white;border:1px solid #ccd2cb;padding:1rem;margin:1rem 0}summary{cursor:pointer;overflow-wrap:anywhere}svg{width:100%;max-width:520px;background:white}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}article{display:grid;grid-template-columns:minmax(200px,1fr) 1fr;gap:1rem;border-top:1px solid #ddd;padding-top:1rem}input{font:inherit;padding:.6rem;width:90%}.tag{background:#e1e8e3;padding:.2rem .4rem}table{border-collapse:collapse}td,th{padding:.4rem;text-align:left;border-bottom:1px solid #ccc}@media(max-width:700px){article{grid-template-columns:1fr}}</style>',
        f'<h1>{esc(catalog["config"]["category"]["id"])} document catalog</h1>',
        '<p>Layout groups and semantic plans are candidates. Processing success and review judgments do not establish OCR or field accuracy. Red boxes show layout-model predictions. Prompt hits do not bound answers.</p>',
        f'<p>Catalog SHA-256: <code>{esc(sha)}</code></p><pre>{esc(json.dumps(catalog["summary"], indent=2))}</pre>',
        '<label>Filter documents <input id="query" placeholder="Filename, document ID or state"></label>',
        '<details><summary>Configuration, versions and scope</summary><pre>' + esc(json.dumps({"config": catalog["config"], "environment": catalog["environment"]}, indent=2)) + '</pre></details>',
        '<details><summary>Candidate groups and fixture choices</summary><pre>' + esc(json.dumps(catalog["groups"], indent=2)) + '</pre></details>']
    pages = {}
    plans = {p["document_id"]: p for p in catalog["plans"]}
    for page in catalog["pages"]:
        pages.setdefault(page["document_id"], []).append(page)
    for doc in catalog["documents"]:
        names = "; ".join(a["filename"] for a in doc["aliases"])
        parts.append(f'<details class="document" data-filter="{esc((names + " " + doc["document_id"] + " " + doc["status"]).lower())}"><summary>{esc(names)} — <span class="tag">{esc(doc["status"])}</span> — {doc["page_count"]} pages</summary>')
        parts.append('<pre>' + esc(json.dumps(doc, indent=2)) + '</pre>')
        if doc["document_id"] in plans:
            parts.append('<details><summary>Reviewable document and section plan</summary><pre>' + esc(json.dumps(plans[doc["document_id"]], indent=2)) + '</pre></details>')
        for page in pages.get(doc["document_id"], []):
            parts.append('<article><div>' + preview(store, page) + '</div><div>')
            parts.append(f'<h3>Page {page["page_number"]}</h3><p>{esc(", ".join(page["issues"]) or "No measured processing issues")}</p>')
            parts.append('<pre>' + esc(json.dumps({"text": page.get("text"), "anchors": page.get("anchors"), "transform": page.get("transform")}, indent=2)) + '</pre></div></article>')
        parts.append('</details>')
    parts.append('<details><summary>Unmatched and failed source entries</summary><pre>' + esc(json.dumps([e for e in catalog["source_entries"] if e["status"] != "ingested"], indent=2)) + '</pre></details>')
    parts.append('<details><summary>Review history</summary><pre>' + esc(json.dumps(catalog["reviews"], indent=2)) + '</pre></details>')
    parts.append('<script>document.getElementById("query").addEventListener("input",function(){const q=this.value.toLowerCase();document.querySelectorAll(".document").forEach(d=>{d.hidden=!d.dataset.filter.includes(q)})})</script></html>')
    return "".join(parts).encode()


def export_catalog(store, catalog, catalog_ref):
    import pyarrow as pa
    import pyarrow.parquet as pq
    relative = f"exports/{catalog['catalog_id']}"
    target = store.root / relative
    if target.exists():
        manifest = json.loads((target / "manifest.json").read_text())
        for ref in manifest["files"]:
            store.read(ref)
        return relative, store.put_json(manifest)
    target.mkdir(parents=True)
    sections = [{"document_id": plan["document_id"], "plan_context_sha256": plan["context_sha256"],
                 "provenance_kind": plan["provenance"]["kind"], **section} for plan in catalog["plans"] for section in plan["sections"]]
    tables = {name: catalog[name] for name in ["source_entries", "documents", "pages", "groups", "section_groups", "plans", "profile_candidates", "fixtures", "reviews", "review_targets"]}
    tables["sections"] = sections
    (target / "catalog.json").write_bytes(canonical(catalog))
    (target / "report.html").write_bytes(report(store, catalog, catalog_ref["sha256"]))
    for name, rows in tables.items():
        (target / f"{name}.json").write_bytes(canonical(rows))
        # Stable scalar columns support SQL filtering; lossless record_json
        # preserves category-specific/nested shapes without schema invention.
        ids = ["source_entry_id", "document_id", "page_id", "group_id", "section_id", "fixture_id", "profile_candidate_id", "status", "format", "page_number", "source_sha256", "context_sha256"]
        columns = {key: [row.get(key) for row in rows] for key in ids if any(key in row for row in rows)}
        columns["record_json"] = [canonical(row).decode() for row in rows]
        arrays = {key: pa.array(values, type=pa.int64() if key == "page_number" else pa.string()) for key, values in columns.items()}
        pq.write_table(pa.table(arrays), target / f"{name}.parquet", compression="zstd")
    files = [{"path": str(path.relative_to(store.root)), "sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
             for path in sorted(target.iterdir()) if path.is_file()]
    manifest = {"version": 1, "catalog_sha256": catalog_ref["sha256"], "files": files}
    (target / "manifest.json").write_bytes(canonical(manifest))
    return relative, store.put_json(manifest)
