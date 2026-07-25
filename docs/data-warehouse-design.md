# Data Warehouse: review and proposed direction

**Status:** Draft / to be continued. Nothing here is decided.
**Last updated:** 2026-07-25
**Concerns:** `packages/committee_meeting`, branch `78-implement-library-for-data-warehouse`, issue #78 (closed)

This captures a review of the stalled data-warehouse work and a proposed
architecture for serving it. It is a starting point for whoever picks this up
— not a finished plan.

---

## 1. Where things stand

`packages/committee_meeting` on `main` is a **README describing a platform, with
no implementation behind it** — the only source file is a `print("Hello from
committee-meeting!")` stub. Its README documents an ER diagram
(Committee → CommitteeMeeting → Recording → Transcript) that nothing implements.

The implementation *does* exist, stranded on branch
**`78-implement-library-for-data-warehouse`**: 8 commits by Evan Tung,
2025-12-18 → 2026-02-08. Issue #78 was closed, but the branch was never merged
and is now well behind `main`.

That branch adds SQLModel table classes for all four entities, Alembic
migrations, a `connection.py`, and a clean `__all__` export surface.

---

## 2. Review of branch 78

The instinct is right — a shared schema layer so `congress_api`, `youtube_api`,
and future transcript tooling stop each inventing their own TinyDB blobs. The
craft is decent: docstrings throughout, `StrEnum` for closed vocabularies,
`TYPE_CHECKING` guards against circular imports, migrations from day one.

The problems are real, and worth fixing before any merge:

### 2.1 It does not run

`Recording.meeting` declares `back_populates="recordings"`, but the attribute on
`CommitteeMeeting` is `recording` (singular). The commit "make relationship
between committee meeting and recording 1:1" renamed one side and missed the
other, so SQLAlchemy raises at mapper configuration — **importing the package
fails.** The code was never executed.

### 2.2 The 1:1 is not enforced anywhere

Typing the attribute `Optional["Recording"]` does not make the relationship
scalar; SQLAlchemy infers a collection from the FK direction unless
`sa_relationship_kwargs={"uselist": False}` is passed. There is also no unique
constraint on `recording.meeting_id`. The intent exists only in the type hint.

### 2.3 The schema cannot reproduce the product we already ship

The live YouTube coverage dashboard slices by **congress number**, **chamber**,
and **party control**, and maps committees to **YouTube channel handles**
(`youtube-accounts.csv`). The schema has **no `congress` field** and **no
channel/handle** — the README's `recording_channels` was dropped in translation.
As modeled, the warehouse cannot answer the question the org already answers
every week.

### 2.4 It is a schema, not a warehouse

No `fetched_at`, `source_system`, or `updated_at`. A warehouse's job is "what did
we know, from where, and when." Related: `Committee` is modeled as immutable, but
committee names and rosters change between congresses — a slowly-changing
dimension in a static table's clothes.

### 2.5 Naive datetimes

Hearings are Eastern; YouTube upload timestamps are UTC. Storing both as naive
`datetime` guarantees a silent mix-up later.

### 2.6 Fragile default DB path

`_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / ...` resolves
outside the package and depends on install layout — the same class of bug that
broke the YouTube tooling's `globals.py`. Works editable, breaks installed.

### 2.7 No tests

One in-memory SQLite round-trip test (create tables, insert
committee → meeting → recording → transcript, read it back) would have caught
2.1 and 2.2 immediately. For a schema library, that test *is* the smoke test.

### 2.8 The meta-lesson

The failure is sequencing, not skill. The most abstract layer was built first,
in isolation, with **no consumer to falsify it**, and the issue was closed before
anything imported it. Architecture that is not under load is just opinion. That
is why it sat broken for five months and nobody noticed.

---

## 3. Proposed direction: Parquet + DuckDB-WASM

Rather than operate a database, **publish columnar files and query them directly
from the browser.**

```
ingest (Python, in CI) → DuckDB → *.parquet (partitioned, published with the site)
                                      ↓
browser: DuckDB-WASM → SQL over HTTP range requests → no backend at all
```

### Why it fits this project

- **Removes the operational floor.** No Postgres, no API layer, no connection
  pooling, no migrations (regenerate from source rather than migrate), and no
  "who operates the database" question — which a volunteer org answers badly.
  The five-month stall is the argument.
- **Verified viable on current hosting.** GitHub Pages returns
  `accept-ranges: bytes` (checked 2026-07-25), so DuckDB-WASM can read byte
  ranges out of a large Parquet file instead of downloading all of it.
- **Org precedent.** `spicy-regs` already publishes Parquet and uses DuckDB —
  same idiom, shared tooling and skills.
- **One artifact, many consumers.** The dashboard, a researcher's notebook
  (`pd.read_parquet(url)`), and any future tool read the *same* files.

### The honest caveat: not for today's dashboard

The current coverage report is ~24 KB / 337 rows. DuckDB-WASM is several MB of
engine — shipping it to query kilobytes is strictly worse than the CSV parse the
dashboard already does.

It becomes correct when the **raw grain** is exposed (30k+ videos, every meeting,
every transcript, sliced by congress) and people can ask their own questions.

**So: two tiers.**

| Tier | Artifact | Used by |
|---|---|---|
| Pre-aggregated | small JSON/CSV (a few KB) | default dashboard view — instant, no engine |
| Raw grain | partitioned Parquet | "Explore" view that **lazy-loads** DuckDB-WASM on demand |

### Implementation notes

- **Partition Hive-style** — `congress=118/chamber=house/*.parquet` — so DuckDB
  skips whole files before reading a byte.
- **Keep transcript text out of the main tables.** Store a URL/pointer; full text
  is what explodes Parquet size. Separate, partitioned, fetched on demand.
- **Self-host the WASM** rather than loading from a CDN — one less external
  dependency to rot.
- **Schema discipline still applies.** Parquet replaces the *serving* layer, not
  the *modeling* layer. Grain, stable keys, `congress`, `channel`, and
  `fetched_at` provenance are all still required. Columnar files don't excuse a
  bad model; they make a good one free to serve.

### What this means for branch 78

It doesn't make that work obsolete — it makes the **heavy half** obsolete. Keep
the entity design and the thinking about relationships; drop SQLModel, Alembic,
and connection handling; emit Parquet from the ingest instead.

---

## 4. Open questions

- Do we want SQL-in-the-browser exploration at all, or is a fixed dashboard
  enough? (This decides whether DuckDB-WASM is justified.)
- Where do Parquet files live — committed to the repo, attached to a release, or
  written to the Pages artifact at build time? (Committing generated data has
  bitten this repo before.)
- Is `committee_meeting` the right package name? It contains Committee,
  Recording, and Transcript too — named after one of its four entities.
- Do we reconcile with `spicy-regs`' conventions (partitioning, naming, data
  dictionary) so the two datasets feel like one family?
- Who owns this? The branch stalled once already for lack of an owner.

---

## 5. Suggested next step: one thin vertical slice

Do **not** rebuild all four tables first. Prove the pattern end to end on data we
already have:

1. A CI step that writes the YouTube data at **raw grain** (one row per video,
   with `congress`, `chamber`, `committee`, `handle`, `has_event_id`,
   `fetched_at`) to partitioned Parquet.
2. An **"Explore"** island on the site that lazy-loads DuckDB-WASM and runs one
   real SQL query against those files.
3. If that feels good, meetings and transcripts follow the same mold — each
   landing **together with a real writer and a real reader**, never alone.

The rule that would have saved branch 78: **a schema lands with a caller, or it
doesn't land.**
