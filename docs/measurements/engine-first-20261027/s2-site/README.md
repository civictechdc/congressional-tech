# S2 retained-body labels and edition-count handoff

The committed [sample](sample.json) contains **291 file contexts and 287 distinct retained bodies**: 244 decided labels and 47 explicit owner questions. It includes all 29 earlier human reviews, preserves their original decisions separately, and uses the 2026-10-25 rule labels only to select coverage. The historical captures input, selection job, selected output and seed files have SHA-256 pins. The native selection and statistics jobs are in [native-evidence.json](native-evidence.json).

Every body was fetched by a public, read-only raw GET, decoded and checked against its logical body digest before inspection. Independent reviewers verified all 574 stored/decoded hashes. Main-content extraction, visible text and publisher links support the labels. The sample has 88 real-document file contexts, 60 landing pages, 39 download wrappers, 38 soft errors, 16 listings, two challenges, one source record and 47 owner referrals. There are 45 real-document contexts with less than 2,048 visible UTF-8 bytes (580–1,929 bytes). A review correction classifies the retained USAID policy notice by its substantive main content rather than the absent fact sheet named in its request URL.

This is a coverage panel, not a probability sample or a measured population accuracy result. It includes archive members, short real pages, error/challenge/download/landing/listing pages, same-list and outside-list links, repeated listings and mirrored documents. The real repeated-listing example differs only in query-key case; a stronger different-directory case remains an owner question. Mirror examples have two or three addresses, not over 100. Publisher grouping examples record actual link assertions; their target bodies still need the model's real-file admission. No threshold or rendition group was widened.

The edition-count helper at `scripts/measure/edition_match_count.py` performs all joins, deduplication, grouping and export through the native engine. It counts distinct bodies outside the existing fingerprint-candidate set whose fingerprint equals an edition body in the same canonical rendition group. Missing relevant fingerprints remain unknown, and pending same-stem or publisher coverage prevents a decision-ready result. It joins groups and fingerprint values without expanding every candidate/reference pair.

The helper's synthetic fixture and five native tests establish behavior; **their counts are not the requested real measurement**. The real count is blocked on engine's E2 producer. The producer must supply a version-1 `canonical_model` descriptor with SQL/profile SHA-256 pins, exact source snapshots, coverage for `same_stem` and `publisher`, and four local Parquet files with SHA-256 pins:

| Relation | Fields |
| --- | --- |
| `rendition_members` | `group_kind`, `group_id`, `body_key` before edition exclusion |
| `edition_bodies` | `body_key` |
| `fingerprint_candidates` | `body_key`, including edition bodies |
| `fingerprints` | `body_key`, nullable `fingerprint` |

Body keys retain the logical `.gz` suffix; fingerprints are the agreed 64-character lowercase hexadecimal values. Missing or changed files, historical proxy descriptors and inconsistent fingerprints refuse qualification. Once the immutable canonical inputs exist, run:

```sh
.venv/bin/python -I scripts/measure/edition_match_count.py \
  --relations "$E2_RELATIONS" --engine-config "$DOCSPEC_JOB_CONFIG" \
  --work "$EVIDENCE/edition-count"
```

The fresh work directory receives `measurement.json`, native job/results and `matching-examples.parquet`. Exit zero means complete inputs and no unknown candidates; exit one preserves an incomplete result; exit two refuses invalid input. The owner's widening decision remains separate from this measurement. S2's model SQL, fixtures and raw-only reproduction check remain engine-owned.

CODE review requested the bounded USAID label correction; it is fixed. ARCH review approved this handoff with no blocking findings. The corrected panel and count helper passed six focused checks; the combined ID/S2 group passed 38 with approved local snapshot `engine-656e7b5`. No real storage, credential or network write occurred.
