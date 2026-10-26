# The lead editor's grade of the docs at 40ee51b2

This is the opinion of the editor who wrote most of these documents, so it is anchored. Validate it or disagree with it, with evidence.

**Grade: about 87/100.**

| Area | Score | Reason given |
|---|---|---|
| Raw-data safety | 9.5 | Create-only writes, 412 means unchanged with no download, bucket lock, pointer-safe receipt cleanup with a backup copy first, full re-hash before the first raw check |
| Grounded in data | 9.5 | Nearly every rule cites a measured number; principle 9 says rules follow the data |
| Internal consistency | 9 | No contradictions found on one full read; the reference checker reports 193 references, 0 problems |
| Executable plan | 8.5 | Clear dependency order and decision gates, but the two biggest platform bets (Basin/Iceberg under maintenance, M1; DataFusion wide joins in 16 GB, M2) are still open |
| Simplicity | 7 | See below |
| Readability and concision | 7 | See below |

## What holds it back

1. **The grouping model is the hard part.** The edition rules (`ambiguous_bodies`, `edition_bodies`, fingerprint candidates) and the two rendition kinds (publisher group, same directory and stem) in DM §7.5 are correct but intricate. They have only been checked against hand-written fixtures; they meet real data only at D2 and E4.
2. **Ceremony.** The plan's process rules (P §3: a ticket before the first commit, `wc -l` in every PR, epic rules) cut against a "minimum ceremony" doctrine for a solo greenfield project. *Correction after checking:* the owner asked for readable W3C style, so the specs' framing (conformance, BCP 14, Status sections) stays; the point applies only to boilerplate that does not help a reader.
3. **Density.** Many sentences carry three or four clauses plus numbers, e.g. the queue rule (DM §7.7) and the fetching paragraph (A §7.1). DM alone is about 9,900 words; the four documents are about 27,800.
4. **Nits.** A §6's diagram says `captures` is "one row per body a receipt line references", leaving out the bodiless-line rows A §8.2 and DM §6.1 define. P §1 says the old capture schema "carries `stored_sha256`", while DM drops `stored_sha256`; correct for the old path, confusing to a reader.

## What would raise it

1. Run S1's fixtures as an executable model now, and also on a small slice of real data, not only on hand-written cases.
2. Cut boilerplate and process rules that do not help a reader, then one more concision pass on DM §7.
3. Run M1 and M2; their outcomes may reshape the lake, so re-grade after them.

## Already checked

Invariant 2's "no body ETag contains `-`" holds for older bodies as far as measured: 24 older bodies in four size bands up to more than 100 MB have plain MD5 ETags, and today's `R2Store.put_file` uses one `put_object`. Raise it again only with new evidence.
