# Retire the legacy HTTP fork after preserving XML recovery

Status: accepted, 2026-09-30; supersedes the earlier decision to keep both clients.

The original refactor characterized two behaviors: the production gateway with
pacing/retries and a bare-request legacy JSON/XML client. The owner subsequently
requested removal of unused code, conditional on preserving XML meeting recovery.

`congress-meetings` now retries detail requests as XML after HTTP 500 or JSON
decoding failure. Both formats use `http.get_with_retry` with five attempts.
`HttpRequestError` remains a `RuntimeError` and exposes the final status so callers
can decide recovery without parsing error text. Refusal, missing records, rate
limits and transport errors do not trigger XML recovery.

The byte-only `congress_source` parser and source models remain. Exact XML is
retained in `_source_xml`; unsuccessful interpretation keeps prior data and
pending source evidence. The unused `api.py` and `xml_to_dict.py` are removed.
Caption and transcription transports retain their characterized behavior.

See the [HTTP policy](../../packages/congress_api/README.md#http-policy),
`test_http_policy.py`, `test_congress_xml_recovery.py`, and
[removal audit](../legacy-congress-removal.md).
