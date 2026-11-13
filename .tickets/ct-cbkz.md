---
id: ct-cbkz
status: open
deps: []
links: [ct-chc4, ct-m704, ct-f6hr]
created: 2026-11-12T15:38:26Z
type: task
priority: 2
assignee: mikewolfd
external-ref: ss-mkxe
tags: [congress_api, body_text, spicy-docs, html, xml, post-wave-6]
---
# Bump spicy-docs for XML/HTML markup normalization, re-read CPU markup cohorts, and compact superseded body_text rows

Deferred post-Wave-6 follow-up paired with spicy-stack ticket ss-mkxe (Owner decision A1 on 2026-11-12 body_text Parquet sample review). Keep the active pdf_text OCR run (PID 55948) 100% untouched: pdf_text and GPO <pre> html_text are verified clean. Once ss-mkxe lands in spicy-docs (fixing XML <metadata>/<dublinCore> leakage + inline XML tag line-breaking on <cosponsor>/<quote>/<term>/<external-xref>, and collapsing non-<pre> HTML/WARC template whitespace cliffs + separating adjacent inline <a>/<button> tokens like 'AboutChair'), vendor the updated spicy-docs wheel in Congressional Tech, bump the CPU-only markup reading versions (xml_text, html_text, warc — NOT pdf_text), run the fast CPU-only markup re-read (minutes, zero PDF OCR re-run), and compact superseded (parser, parser_version) rows out of body_text Parquet.

## Design

1. Vendor the post-ss-mkxe spicy-docs wheel and verify pdf_text version hash is unchanged while xml_text / html_text (and warc HTML text) reading versions advance cleanly.
2. Run CPU-only body_text re-derivation on the affected XML, non-<pre> HTML, and WARC cohorts (zero OCR / zero pdf_text re-read).
3. Compact superseded (parser, parser_version) rows in body_text (and readings where applicable) so FTS indexing (ct-m704) ingests only the single current normalized markup text per SHA-256 body.

## Acceptance Criteria

1. Vendored spicy-docs includes ss-mkxe; GPO <pre> HTML output and pdf_text reading version hash remain byte-identical (zero PDF OCR re-run).
2. CPU-only re-read completes across xml_text, html_text, and warc cohorts; sample Shas (bill XML ecec5e8dc421f8bd..., non-<pre> HTML ea2dedd3feb3dd99... and 0990bcfcbafa0dff...) show no Dublin Core header leakage, intact inline XML sentences, collapsed template blank-line cliffs, and separated adjacent inline link/button tokens.
3. Superseded (parser, parser_version) rows are compacted from body_text Parquet with row-count and uniqueness verification.


## Notes

**2026-11-13T17:46:16Z**

2026-11-13 reconciliation: retain this ticket's CPU markup-normalization scope with upstream ss-mkxe. New compatibility work (legacy HTML encodings, empty XML internal subsets and max_events) is tracked separately in ct-f6hr. The earlier statement that PDF text was clean was limited to that sample and is superseded by source-confirmed GPO loss: PR #151 fixed cleanup, and ct-kfsd owns its historical reread/publication. For this markup-only change, preserve PDF output relative to the chosen current baseline; do not restore an obsolete PDF pin. Before compaction, retain replayable prior readings/refusals and verify one current selection per body/parser. Verify current shared-reader implementation and qualification before duplicating it.
