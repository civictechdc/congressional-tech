# S2 retained-body labels and edition-count handoff

The committed [sample](sample.json) contains **291 file contexts and 287 distinct retained bodies**: 244 decided labels and 47 explicit owner questions. It includes all 29 earlier human reviews, preserves their original decisions separately, and uses the 2026-10-25 rule labels only to select coverage. The historical captures input, selection job, selected output and seed files have SHA-256 pins. The native selection and statistics jobs are in [native-evidence.json](native-evidence.json).

Every body was fetched by a public, read-only raw GET, decoded and checked against its logical body digest before inspection. Independent reviewers verified all 574 stored/decoded hashes. Main-content extraction, visible text and publisher links support the labels. The sample has 88 real-document file contexts, 60 landing pages, 39 download wrappers, 38 soft errors, 16 listings, two challenges, one source record and 47 owner referrals. There are 45 real-document contexts with less than 2,048 visible UTF-8 bytes (580–1,929 bytes). A review correction classifies the retained USAID policy notice by its substantive main content rather than the absent fact sheet named in its request URL.

This is a coverage panel, not a probability sample or a measured population accuracy result. It includes archive members, short real pages, error/challenge/download/landing/listing pages, same-list and outside-list links, repeated listings and mirrored documents. The real repeated-listing example differs only in query-key case; a stronger different-directory case remains an owner question. Mirror examples have two or three addresses, not over 100. Publisher grouping examples record actual link assertions; their target bodies still need the model's real-file admission. No threshold or rendition group was widened.

The edition-count helper at `scripts/measure/edition_match_count.py` performs all joins, deduplication, grouping and export through the native engine. It counts distinct bodies outside the existing fingerprint-candidate set whose fingerprint equals an edition body in the same canonical rendition group. Missing relevant fingerprints remain unknown, and pending same-stem or publisher coverage prevents a decision-ready result. It joins groups and fingerprint values without expanding every candidate/reference pair.

The helper's synthetic fixture and five native tests establish behavior; **their counts are not the requested real measurement**. The real count is blocked on engine's E2 producer. The producer must supply a version-1 `canonical_model` descriptor with SQL/profile SHA-256 pins, exact source snapshots, coverage for `same_stem` and `publisher`, and four local Parquet files with SHA-256 pins:

| Relation | Fields |
| --- | --- |
| `rendition_members` | `group_kind`, `group_id`, `body_key` (or `body_sha`) before edition exclusion |
| `edition_bodies` | `body_key` (or `body_sha`) |
| `fingerprint_candidates` | `body_key` (or `body_sha`), including edition bodies |
| `fingerprints` | `body_key` (or `body_sha`), nullable `fingerprint` |

Body keys retain the logical `.gz` suffix (when canonical evidence exports 64-character `body_sha` values, `edition_match_count.py` projects the logical `bodies/sha256/<prefix>/<sha256>.gz` key inside the native engine before validation and joins); fingerprints are the agreed 64-character lowercase hexadecimal values. Missing or changed files, historical proxy descriptors and inconsistent fingerprints refuse qualification. Once the immutable canonical inputs exist, run:

```sh
.venv/bin/python -I scripts/measure/edition_match_count.py \
  --relations "$E2_RELATIONS" --engine-config "$DOCSPEC_JOB_CONFIG" \
  --work "$EVIDENCE/edition-count"
```

The fresh work directory receives `measurement.json`, native job/results and `matching-examples.parquet`. Exit zero means complete inputs and no unknown candidates; exit one preserves an incomplete result; exit two refuses invalid input. The owner's widening decision remains separate from this measurement. S2's model SQL, fixtures and raw-only reproduction check remain engine-owned.

## Full-corpus canonical E2 edition-match measurement

Running `scripts/measure/edition_match_count.py` against the canonical E2 model relations (`publish_v19/model/evidence/{rendition_members,edition_bodies,fingerprint_candidates,fingerprints}.parquet`, pinned to `captures` snapshot `4154903096594263476`, `readings` snapshot `1736963857314630684`, `filename_readings` snapshot `6787885063715806721`, `profile_sha256` `c403bc0d0d340f745dbb1d04e179cdd9ff18f4f95c5065befccd32663f2707b7`, and `source_sql_sha256` `94b033dfe1f0d8179e3a68e1edb27506ed5493e6d1b08aee3b7d2f043bc6b3c7`) produces [edition-match-count.json](edition-match-count.json):

| Metric | Count | Notes |
| --- | ---: | --- |
| `eligible_candidates` | **59** | Distinct rendition member bodies in edition-bearing groups outside `fingerprint_candidates` |
| `matching_candidates` | **0** | Candidate bodies whose fingerprint equals an edition body in the same canonical rendition group |
| `unknown_candidates` | **59** | Candidate bodies with `fingerprint IS NULL` or in groups with `missing_references > 0` |
| `known_nonmatching_candidates` | **0** | Candidate bodies where both candidate and all group edition references have non-null, non-matching fingerprints |
| `status` / `decision_ready` | `incomplete` / `false` | Preserved with exit code `1` because `unknown_candidates = 59` |

### Breakdown by rendition group kind (`same_stem` vs `publisher`)

Across the four canonical evidence relations (`rendition_members`: 634,853 rows; `edition_bodies`: 16,339 rows; `fingerprint_candidates`: 20,912 rows; `fingerprints`: 312,505 rows with 282,330 non-null fingerprints):

| Group kind | Total rows in `rendition_members` | Distinct groups | Edition-bearing groups (`reference_groups`) | Distinct edition bodies in groups | Eligible non-candidate bodies (`candidate_groups`) | Matching candidates | Unknown candidates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `same_stem` | 619,530 | 288,808 | 7,493 | 14,983 | **0** | **0** | **0** |
| `publisher` | 15,323 | 6,931 | 3,341 | 5,976 | **59** (in 34 groups) | **0** | **59** |
| **Combined (deduplicated by `body_key`)** | **634,853** | **295,739** | **10,834** | **15,799** | **59** | **0** | **59** |

- **`same_stem` yields 0 eligible candidates**: `fingerprint-candidates.sql` already includes every body in any `same_stem` group that has more than one distinct `body_sha` (4,573 multi-body `same_stem` members plus all 16,339 `edition_bodies` = 20,912 `fingerprint_candidates`). Consequently, `LEFT ANTI JOIN fingerprint_candidates` leaves **0** non-candidate bodies in `same_stem` groups.
- **`publisher` yields 59 eligible candidates across 34 groups**: All 59 eligible candidates are non-edition members of `publisher` rendition groups that contain at least one edition body (`edition_bodies`) and are not in a multi-body `same_stem` group.

### Concrete examples from the 34 `publisher` groups

1. **GovInfo `CHRG-*` hearing packages with `mods.xml` (`xml`) + `html` (`htm`) + `pdf` (`pdf`) renditions**:
   - `CHRG-117hhrg44535` (`group_id = 0a88baebedeb137f82ffcf66b1ef5aa9e10cb0c7ef7519c53087d3464b13c0fa`): candidate `xml` (`mods.xml`) body `5df30fc54a29eae79ef92c948e7770e7a35f7f59d11147964572efee08f72aee` (`fingerprint = 1fb38a400a9eb6626a5970bc058c4483bc29fc20660efde4e317a436e5db0c84`) paired with edition `html` body `f4bf881da89331022bc54df32ec0d3b3bdcd28a6c0f82e39a8e81ce8d5e0bb73` (`fingerprint = 7775f78541c3c979bcce165eb3673c2ec27829e682a45c36ef4be18dc792a6a3`, non-matching because MODS metadata XML does not equal full hearing transcript HTML) and edition `pdf` body `bd5f988bf7b8790497c10e7b8097bc7ac3d8380464de51a3aa02e69c5ba2a684` (`fingerprint IS NULL`).
   - `CHRG-109hhrg32242` (`group_id = 55bb33bf63390076ee0f9826a74099b8d483da786b9921081b76c8c3df925b86`): candidate `xml` (`mods.xml`) body `6de477eb6656ef996f1dc8c412c3c516c29dd76f32d0f25b7ad59063c7f44efa` (`fingerprint = 6df86bf808866c550a8832c2046461588940ec0d42823839b14fb1f8f010bc98`) paired with edition `html` body `3c9c874eb3717b9bcda2e8737846c6ef12aa7b7021be99c52b7ef7bbde3f45fe` (`fingerprint = 67c5522ce187d0df45a6ab3aa3f7c73d2b99289566e0bb05cb9e322a83de6664`) and edition `pdf` body `bc2c8a37ae0540328529e628e6426e95c26b9ef53c1bc488b43ef43b49fbcd81` (`fingerprint IS NULL`).
2. **House Floor XML + PDF bill/resolution pairs (`docs.house.gov/floor`)**:
   - `BILLS-112hr2560ih` (`group_id = a4300a70f62d68d9548ab37ec62f98f4a6ce28b8bc55ffbbbe249d44675021fd`): candidate `xml` body `0d9fd999da81128941312a67992f790c74c831741a19164a378f13a8b4926a53` (`fingerprint = 00f8341bf2e878046478598a6f82ef1d226e0c7cfcc01d4f6b29a6f924f8ca1a`) paired with edition `pdf` body `3b0e951fc2df27f2a0ab260aa860d950f5005e287be737a0b6011d862a51c3c5` (`fingerprint IS NULL`).
3. **Committee publisher pages with `pdf` + `zip`/`mp4`/`html` attachments**:
   - `transportation.house.gov` (`/calendar/eventsingle.aspx?EventID=398952`, `group_id = 398e3d90c3b6593fa919402e79dc3c3e7e9ff4e95f86c2eb88fd57d0c41e184c`): candidate `pdf` bodies (`1a6fa010...`, `2d06312b...`, `63e413e4...`, `b9516397...`) paired with an edition `zip` packet (`26bd1bf7...`), both having `fingerprint IS NULL`.
   - `agriculture.house.gov` (`/calendar/eventsingle.aspx?EventID=1736`, `group_id = 4b2520de7e3fc3c8c9ac43f1c73bc1bc6f0888faae87570079777b3983666742`): candidate `html` wrapper (`047a5b7a...`, `fingerprint = 57b98f79...`) paired with edition `pdf` (`4ea7fc03...`, `fingerprint IS NULL`).

### Source limits explaining `unknown_candidates = 59`

1. **Non-HTML/XML formats lack text fingerprints in `readings`**: The `readings` parser bundle computes `fingerprint` (normalized visible text SHA-256) only for `html` and `xml` readings (`page_facts`), not for `pdf`, `zip`, `mp4`, or `unknown` binary bodies:
   - Among the **15,799** distinct edition bodies appearing in rendition groups (`reference_groups`), **7,882** are `pdf` (0 with fingerprint), **7,876** are `html` (7,862 with fingerprint), **21** are `zip` (0 with fingerprint), **14** are `unknown` (1 with fingerprint), **5** are `xml` (5 with fingerprint), and **1** is `mp4` (0 with fingerprint).
   - Among the **59** eligible candidate bodies (`candidate_groups`), **42** are `pdf` (`0` with fingerprint), **14** are `xml` (`14` with fingerprint), and **3** are `html` (`3` with fingerprint).
2. **Every group containing the 17 fingerprinted candidates also contains a `pdf` edition reference**: For the 17 candidate bodies (`14 xml`, `3 html`) that do have a non-null fingerprint, all 17 belong to `publisher` groups that also include a `pdf` edition body whose `fingerprint IS NULL` (`missing_references > 0`). Even against the `html` edition bodies in those same groups (e.g., `CHRG-*` `mods.xml` vs hearing transcript `.htm`), **0 of 17** candidate fingerprints match the `html` edition fingerprint.

CODE review requested the bounded USAID label correction; it is fixed. ARCH review approved this handoff with no blocking findings. The corrected panel and count helper passed six focused checks; the combined ID/S2 group passed 38 with approved local snapshot `engine-656e7b5`. No real storage, credential or network write occurred.
