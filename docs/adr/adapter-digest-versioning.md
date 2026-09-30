# Preserve layered adapter identity

Status: accepted, 2026-09-30.

The application persists IDs. `congress_api` supplies source observation digests
and semantic keys; exact-file reuse and transcript byte hashes have different
roles. A single universal digest would break existing identities.

Keep the current encoding and key rules. An incompatible change requires an
explicit migration and version decision even while the package is at 0.x.
Preserve the prior registry, use aliases only for unambiguous identities, and
compare IDs as well as fields. Additive metadata does not justify replacing
existing domain IDs. The [compatibility policy](../congress-api-contracts.md#adapter-identity-policy)
owns the exact rules and verification gates; no second implementation is added.
