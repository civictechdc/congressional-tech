# Raw protection acceptance — November 6, 2026

`ct-1l1h` remains open. A read-only management request at **16:33:35 UTC** to Cloudflare account `174055408ff1560e60601c4d12c561c4`, bucket `congressional-tech-raw`, returned **HTTP 403**, `success: false`, error `10000`, `Authentication error`. This establishes an access gap; it establishes neither enabled nor missing locks. No infrastructure or raw objects changed.

The request used the existing local `CLOUDFLARE_KEY` as a bearer credential without logging its value. The first sandbox attempt failed DNS resolution; the network-enabled retry reached Cloudflare. The saved Wrangler login had expired at 16:26:41 UTC and its declared scopes omitted R2. The browser inventory reported that the Mac was locked and automatic unlock failed, so dashboard readback was unavailable. No credential refresh or new permission was requested.

The required management evidence is a successful [Get Bucket Lock Rules](https://developers.cloudflare.com/api/resources/r2/subresources/buckets/subresources/locks/methods/get/) response, or equivalent account-and-bucket dashboard readback, showing the complete active rule list. Require enabled `Indefinite` rules for `bodies/`, `receipts/` and `provenance/`. No replacement configuration was prepared: without the current list, missing rules and preservation of unrelated rules cannot be established.

## Retained B0 evidence

The November 5 [three-key reconciliation](../../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/capture-ops/b0-reconciliation.json) still has SHA-256 `816f743575f0846950b7d64d543c810ab75253498cf000ea39727c5be48c7095`, matching its retained custody record. All three saved live sizes and ETags match the original entries in the committed [B0 identity inventory](engine-first-20261027/b0/receipt-identities.json), differ from their verified scratch-cleaned entries, and match the retained report's local-original identities. These remain **November 5** live observations. No receipt was reopened, rescanned or downloaded in this check.

| Exact retained sample | Header-pattern matches | Path matches | Disposition |
| --- | ---: | ---: | --- |
| `receipts/congress/committees/2026-09-30/assemble-20260930.jsonl.gz` | 688 | 0 | Owner header disposition remains open. |
| `receipts/documents/2026-10-12/download-20261012T141417Z-fe374e92a5ee-000006.jsonl.gz` | 2,846 | 0 | Owner header disposition remains open. |
| `receipts/youtube/watch-pages/undated/assemble-20260930.jsonl.gz` | 0 | 8 | Preserve the November 2 and 4 historical-path exception. |

The header counts are scanner-pattern matches in the previously reconciled originals. They do not establish credential validity or current exposure. The path exception does not settle headers. Keep `cef-sqyq` closed for its tooling and [local qualification](engine-first-20261027/b0/README.md): 2,289 scratch receipts and 2,596,054 lines verified, with a clean final scratch scan. Its October 30 live-completion note does not override these exact counterexamples. Historical rewrites remain held.

## Reused writer qualification

Checked source revision: `742dbe70b42f0618e95816cd7cf0e6ba2f9939b0`. `retention/receipt_writer.py`, `retention/body_store.py`, `test_receipt_writer_contract.py` and `test_body_store_contract.py` are byte-identical to both retained qualification heads `5ab813f919484c5d994d52220d898b2f69ea1257` and `e8c9e0acc7cf75c8b1913adceecd8ec44bb107df`.

Reuse the [receipt lane's completed evidence](../../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/STATUS.md): frozen replay refuses unsafe paths before upload; safe retries retain their key and bytes; reused bodies carry qualified stored metadata; scratch cleanup precedes durable receipt upload. The retained focused checks qualify their recorded revisions and scopes. This documentation-only change ran no new Python suite or full lane and makes no new deployed-writer claim.

## Owner cutover handoff

1. Obtain and retain the complete management readback. Compare enabled indefinite rules for the three exact raw prefixes. Only then prepare any demonstrably missing owner-approved rule, preserving every unrelated rule and serializing the whole-list API update.
2. Reuse the switch plan's B1 qualification within its proven scope. The committed [B1 release](engine-first-20261027/b1/RELEASE.md) explicitly records local checks and no live probe. The previously reviewed evidence still lacks the live scratch result; obtain an existing owner result before deciding whether another probe is necessary. Never probe overwrite or deletion against raw.
3. Resolve the two header findings separately from historical paths before a missing receipt lock is applied. Follow the existing ordered prerequisites and provenance-exception review. The release owner controls every lock or raw-history change.
4. Retain post-change readback and repeat it after relevant infrastructure changes (the ticket's R2 check 4). Keep B9 weekly raw verification after locking. `ct-4jms` continues to own scheduled capture and the first merged writer's raw-preservation and receipt-body evidence.

Current responses and the bounded evidence check are retained under [the November 6 task evidence](../../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-1l1h/). No object listing, corpus replay, raw rewrite, lock update, publication, scheduler change or deployment ran.
