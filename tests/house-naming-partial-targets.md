# Visible targets in incomplete legislative filenames

Decision: reuse the existing whole-slot `substitute-target` rule when a `BILLS`
payload has no recognized inner layout. Do not invent a new truncation grammar
or repair damaged source text.

Hypothesis: the two retained House XML basenames beginning with the written-out
substitute phrase can expose their amendment marker, target marker and visible
target text without changing any previous output. A missing version or extension
must not hide those literal fields or acquire a fabricated value.

Arms: frozen native/strict results in `drafts-final`, accepted extraction in
`category-wording-final`, and this reuse of the existing target rule. Use the
same 333,368-name inventory. It is reused development evidence, not an unseen
accuracy test.

Cases: all four unresolved legislative payloads reviewed against retained source
XML/receipts in `remaining-structured-raw-xml.json` and
`remaining-structured-origins.json`; constructed complete, incomplete, whitespace
and repeated-extension variants; unrelated free filenames, malformed target
boundaries, and complete sponsor/amendment layouts. The partial `B0005` tail must
remain literal text, not a recovered sponsor ID. The damaged `xmlhttps:` name
must remain damaged. Source metadata absent from the basename stays absent.

Intervention: after all normal legislative payload priorities fail, remove only
the optional leading hyphen separating Congress from that payload for matching
and apply the existing full-slot target rule with the original source offset.
Keep the enclosing payload, strict results, diagnostics and residual target text.
Do not run unrestricted subject searches or treat the partial match as a full
legislative payload layout.

Gate: all focused and existing tests pass; full native/strict/adapter comparison,
omission audit and corpus mechanical checks pass; every previously returned
result is exact after removing only reviewed new `substitute-target` observations.
Manually review every changed name and field. Expect only the two reviewed
basenames in this corpus to change. Keep all four incomplete payloads on the
review list. Preserve failed trials. The existing 30-minute run bound applies.

Out of scope: changing opaque-identifier interpretation, changing review counts
to hide unresolved cases, repairing URLs, or using XML metadata as filename text.
