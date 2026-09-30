# Retire unused Congress exploration tools

Status: accepted, 2026-09-30; supersedes the earlier decision to retain aliases.

The owner requested removal of unused, superseded code after an intent audit,
then explicitly required implementing both remaining acquisition capabilities
before removal. `congress-meetings` now recovers HTTP 500/invalid-JSON detail
responses through XML; `congress-committees` retains full detail/history records.
Both preserve source evidence and prior successful snapshots on failure.

Remove `congress-fetch`, `congress-analyze`, their TinyDB implementations, old
module aliases, one-off converter and legacy HTTP/XML wrappers. Do not create a
separate legacy package. Production retention and source models remain. The
independent YouTube collectors still use TinyDB; their code, dependencies,
workflow commands and caches remain in place.

The [intent audit](../legacy-congress-removal.md) records the original purposes,
callers, replacements, removed interfaces and verification. This is an explicit
owner-approved compatibility break for the unused exploration commands/imports.
