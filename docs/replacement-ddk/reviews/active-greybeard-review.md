# Active independent greybeard and ETL review

## Native release request extraction — 2026-11-06

**Decision: keep this extraction. No blocking finding in the checked slice.** It gives the incumbent runner and a future native retained runner one maintained model graph. It does not establish the complete DDK replacement, managed recovery, or publication acceptance.

This checkpoint reviewed the actual uncommitted changes against baseline `a06eb64bf3caa4a44e12a89bdd08939323de3092` in:

- `packages/viewer_publication/src/viewer_publication/archive_format.py`
- `packages/viewer_publication/src/viewer_publication/archive_model.py`
- `packages/viewer_publication/tests/test_archive_native_request.py`

The reviewer inspected these files, their callers, relation-lifetime implementation and tests, and the retained JUnit records independently before reading any other reviewer conclusion. MCP and DDK consumer edits were still in progress and were excluded. No tests, native jobs, corpus reads, downloads, builds, or implementation edits were run by this reviewer.

### What the source establishes

- `archive_model.py:1042-1067` routes execution and planning through `_prepared_release`; the extraction introduces no second SQL graph. Its final dispatch at `archive_model.py:1361-1425` supplies the same application inputs, steps, exports and diagnostics to either finish function.
- `archive_format.py:237-336` constructs the native JobSpec with the existing core exports, auxiliary schemas, writer settings, queries and relation retirement. It copies the caller's step list before appending exports. `archive_model_lifetimes.py:63-69` constructs new step dictionaries instead of mutating the supplied ones.
- `archive_format.py:339-390` still owns incumbent execution, diagnostic enforcement, output-schema verification, control-file writes, content identity and manifest finalization. The extraction does not introduce a selection pointer, recovery database, payload copy, or additional native execution.
- The request tests compare the complete rendered graph with a retained pre-extraction inventory, preserve the exact native table pins, prohibit row reads and native submission during rendering, verify repeated rendering, and characterize the single submitted incumbent request. Invalid relation references, duplicate relations and invalid SQL refuse during rendering.

### Evidence and limits

Retained directory: `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/checks-native-request-01/`.

`junit.xml` preserves the first run: eight cases, five failures caused by an unsupported `capture_scope` keyword. Current source accepts that shared boundary argument, and `junit-02.xml` records eight cases with zero failures, errors or skips in 1.316 seconds: five request cases and three existing relation-lifetime cases. This is recorded focused-test evidence, not a reviewer rerun or a full-lane result. The captured engine stub deliberately stops after submission, so it proves request assembly rather than native execution, data correctness, finalization or recovery.

The change reduces the number of maintained graph assemblies to one. No speed or memory improvement was measured or claimed. Rendering does no data movement; it still reads SQL/schema definitions and computes relation dependencies. That is proportionate to request construction.

### Next boundary to check

The returned `(job, schema, diagnostics)` describes native computation. It does not include all release-finalization inputs. In particular, `capture_scope` is intentionally ignored by the JobSpec constructor, while the incumbent finalizer writes it at `archive_format.py:385`; the capture profile and origin also affect final release contents. A retained executor must bind those exact controls with its operation and use one maintained finalizer after restart. It must not reopen current registry definitions and silently finalize an old computation under new controls. This is an explicit next-slice requirement, not a reason to block the pure JobSpec extraction.

For subsequent checkpoints, review the new completed seam and changed dependencies only. Do not rerun unchanged corpus qualifications merely because this review resumes.

## MCP catalog consumer and authored declarations — 2026-11-06

**Decision: retain the direct standard-reader direction; complete the delivery fixes and qualify the successor before accepting this slice.** The completed consumer source uses the emitted DDK definitions, typed relationship paths and SQL companions directly. It does not reconstruct `schema.json` or reproduce DDK's generic relationship validation. Historical schema decoding remains isolated in `legacy_schema.py` and reads only the selected historical release.

Checked scope: `apps/explorer_mcp/src/congressional_explorer_mcp/{catalog,legacy_schema,reader,release}.py`, the corresponding server help and existing reader tests, the authored `model/ddk` definitions and recipe SQL, and the new test source. The optional publication-artifact hunk and shared successor qualification remain outside this checkpoint. The reviewer read no other review conclusions and ran no tests or native jobs.

### Findings raised during the checkpoint

1. **Upstream relationship selectors were lost.** The new consumer initially listed the upstream extension but searched only the standard relationship list when a caller selected `bill_actions`, despite existing server help and historical behavior supporting that selector. The author restored selected-extension lookup with release-local `missing_tables`. The reviewer verified the source correction at `catalog.py:113-117`. Executed regression evidence remains pending.
2. **Retired document addresses became entities.** Excluding only tables directly targeted by a `detail` relationship left `retired_links` in the new entity inventory. Existing reader tests explicitly exclude both live and retired document addresses. The author changed selection to compare typed declared key paths with document-address paths, preserving the behavior without table-name compatibility maps. The reviewer verified the correction at `catalog.py:49-71`. Executed regression evidence remains pending.
3. **Observed coverage disappeared from discovery.** The new response initially exposed definitions and catalog checking but omitted the selected manifest's observed coverage. The author restored exact per-file manifest coverage in the index and table responses, with standard version records kept separately. The reviewer verified the source correction at `catalog.py:135-155`. This reads metadata only and does not rescan rows. Executed regression evidence remains pending.
4. **Partial DDK controls can silently choose historical fallback.** `release.py` initially required report and lock only when `catalog.ddk.json` was present. A release with the old schema plus report/lock but no catalog therefore passed control admission and selected the historical decoder. The reviewer requested an all-or-none requirement for the three DDK controls; old releases with none retain historical readback. The author was notified. This finding concerns observable delivery shape, not generic catalog-schema validation.

### Ownership and evidence boundaries

- Exact companion hashes are compared with the selected release manifest, and selected recipe SQL is read from its admitted content-addressed object and checked against its companion digest (`catalog.py:32-38,81-93`). No current-workspace recipe lookup or body read is introduced.
- `parameterOrder` preserves positional SQL argument meaning independently of JSON property ordering. The authored two-argument `committee_roster` recipe declares `system_code` before `congress`, matching the actual SQL. Contextual relationships preserve explanatory joins separately from tables the recipe actually reads.
- The declaration tests compare 254 physical fields, 70 relationships and 16 recipe definitions/SQL digests against frozen incumbent metadata. The new real-DDK test is intended to retain the full archive's required unknown results as incomplete. These are inspected test intentions; no executed successor evidence was available at this checkpoint.
- The shared successor's project-extension location was changing during this review. Its inspected source places authored extensions in `extensions[urn:ddk:catalog:assembly].projectExtensions`, while the consumer initially expected a top-level upstream extension. Parent and author were asked to freeze one documented emitted shape before qualification, without adding a dual-shape fallback for an unreleased interface.
- Real publication must select the public disclosure path explicitly and bind upstream generations/paths from release evidence. The shared assembler defaults to a local audience; an authored upstream declaration alone does not replace the incumbent `_pin_upstream(entity_digests)` observation. This belongs to the forthcoming producer/publication seam, not a second consumer redaction or validation implementation.
- Publication still uses the incumbent schema owner and native finalization. Their retirement is not established by moving MCP discovery. The complete replacement and native lifecycle acceptance remain incomplete.

## Optional DDK artifact delivery — 2026-11-06

**Decision: keep the exact-byte delivery seam, with default adoption still disabled. Align the remaining publisher/browser path admission before wiring it into a publication.** This checkpoint inspects source only; the exact installed successor and real public positive fixture remain pending.

Checked the completed `_catalog_artifacts`, `_content_bytes` and optional `_execute(..., catalog_result=None)` changes in `archive_format.py`, the MCP partial-control repair and final project-extension lookup, and the genuine-DDK fixture source. No other reviewer conclusions were read. No tests, engine jobs or heavy work were run.

### Source findings and repairs

- **Public disclosure initially lacked an owning guard.** A passed local catalog could enter the archive manifest unchanged, although the shared assembler defaults to local audience and retains local source details. The reviewer raised this at the application publication boundary. The author added `result.catalog is not None` and `result.catalog['audience'] == 'public'` at `archive_format.py:212-213`. The reviewer verified that source correction. The helper keeps the shared owner's exact bytes and adds no second redactor or catalog-schema validator. The real local equality fixture now calls the actual assembler and asserts that public delivery refuses it; that test source is not an executed result.
- **Valid new artifact paths still fail existing downstream admission.** The incumbent publisher rejects every `/` in a release filename (`archive_publish.py:373-375`), so genuine recipe companions under `queries/<digest>.sql` cannot pass it. The browser reader's single-stem filename expression rejects the DDK control trio itself (`apps/site/src/components/explorer/reader/archive.ts:109`). MCP's inspected filename expression also omitted the supported `discovery.dcat.json` output produced by DDK `Assembly.output_documents`. Parent and author were notified. These are concrete compatibility refusals before activation, not evidence that the optional hook has already published anything.
- **Partial-control fallback is repaired in source.** `release.py:112-115` now requires all three DDK control files when any are declared. A historical release with none continues to use its historical schema; a broken DDK trio cannot silently select that decoder.
- **One successor extension shape is selected.** `CatalogDiscovery` now reads upstream declarations only from the matching root project's `extensions[urn:ddk:catalog:assembly].projectExtensions` entry. It does not accept both the abandoned top-level shape and the new shape. The exact installed successor still needs to execute this path.

### Preserved boundaries and limits

`_catalog_artifacts` snapshots the actual artifact mapping before native execution, requires a passed result and the complete trio, rejects absolute/traversing/noncanonical paths and non-byte values, and leaves the bytes unchanged. `_content_bytes` writes those bytes with the existing atomic writer and records SHA-256, MD5, size and the full relative name. The manifest includes those descriptors in its existing content identity. No new renderer, controller, selection pointer, journal, data-payload scan or model re-execution appears in this hunk.

The new fixture source uses the real DDK assembler/build path. Its passing scenario is a supported equality-only declaration; the full archive scenario explicitly expects an incomplete report and derives keys from its inspectable admitted catalog without selecting it. The fixture's authored upstream generation tests literal preservation, not live upstream availability. Existing release coverage comes from the selected manifest. These facts remain separate from native rule qualification and production acceptance.

The durable-finalization limitation is now explicit in the helper docstring: a native caller must retain the exact DDK bytes, origin, capture scope, content controls and entity generations together, then reuse them after restart. The optional argument does not implement that native request or automatically assemble a catalog. Bind these controls to the original retained operation before adopting this route; do not obtain a fresh catalog from current definitions after a completed computation or replay the model merely to attach metadata.

## Greenfield catalog consumer checkpoint — 2026-11-06

The user has since selected a coordinated greenfield migration. The historical
decoder and old-format admission described above have been removed. All new
readers require the public catalog, report and lock. The earlier review text is
retained as history, not a current compatibility requirement.

Independent source reviews closed the completed declaration/profile, consumer,
comparison, publication, pointer and retained-control changes. The final reader
review checked required-field presence, null and empty states, retired-address
history, recording associations, package context and companion delivery. No
further findings remained in that scope. Reviewers did not run the tests below.

Two findings materially changed the final source:

- Publication admission now requires an explicit model origin and refuses
  unsupported, malformed or display-only origins before uploading files.
- Transcript-source labels use an own-property check. Unknown values including
  `__proto__`, `constructor` and `toString` remain text; unit and render checks
  cover them.

The fixture HTTP server admits only exact manifest assets, including DDK SQL
and lineage companions, and checks resolved paths remain inside the release.
Current pointers require predecessor and conditional-write identity together;
unknown pointer shapes refuse while preserving the observed response bytes.
Retained controls preflight ancestor paths and conflicting bytes before writes.

Central execution evidence under
`<main checkout>/.cache/archive-release/ddk-replacement-20261106/` records:

- `checks-consumer-current-05`: 138 MCP passes and three replacement-native
  fixture skips; 41 browser unit/presentation passes; two final label passes;
  seven catalog/HTTP passes; five focused root cases; eight workflow definition
  cases; and a successful 30-page build. Peak MCP RSS was 0.707 GiB and final
  build RSS was 0.590 GiB.
- `checks-publication-catalog-04/retry-02.junit.xml`: 88 passes after the origin
  repair, preserving publication and gate refusal/recovery cases.
- `checks-comparison-catalog-04`: all 39 hand-worked comparison cases passed.
- `checks-pointer-current-01`: 61 initial passes and one fixture failure; the
  repaired native canary case passed in `retry-03.junit.xml` while retaining its
  missing-body refusal. The reviewer withdrew an initial mistaken fixture
  caveat after inspecting the actual helper and passing retry.

These results qualify the inspected consumer and delivery changes. They do not
establish a full root Python lane, replacement-native acceptance, managed
whole-job recovery, acquisition adoption, external publication or cutover. The
existing producer's schema owner and controller must retire atomically with the
parent-owned whole-job API. The optional catalog finalizer still accepts no
catalog on the incumbent path; it is not yet the mandatory producer boundary.

## Explicit model recovery requirements — 2026-11-06

Independent native-boundary review found no code blocker in removal of the
missing-`refresh_policy` fallback. The maintained campaign writer already emits
that field. Its authoring defaults remain separate from the model's required
serialized fields. The reviewer requested that distinction in documentation;
the recovery architecture and package README now state it explicitly.

`checks-recovery-policy-current-01/junit.xml` records six native passes, zero
failures or skips, in 68.991 seconds. The checks preserve explicit policy and
HTTP-history behavior, refuse null/invalid values, and require a native
missing-field failure without a final manifest. The watchdog recorded 0.496 GiB
peak RSS. This is one focused production-offline module, not a full lane or
replacement-native result. `source-delta.json` records the source-identity change
after the earlier whole-job preparation handoff.
