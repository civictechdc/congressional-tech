# Preserve the characterized HTTP fork

Status: accepted, 2026-09-30.

Production `meetings.get` delegates to `http.get_with_retry` with five attempts.
Legacy `api.request_source` performs a single bare request and supports XML
fallback. They are different behaviors; the wrapper is not a second production
HTTP implementation.

Keep the fork while isolating optional TinyDB exploration. The package README
owns the HTTP policy matrix; `test_http_policy.py` fixes the observed retry,
timeout, parameter, error and fallback behavior. A later change to the legacy
client needs its own behavior decision. No HTTP protocol, container, or package
split is needed for this refactor.
