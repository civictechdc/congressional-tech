# Congressional Document Archive: Acceptance Fixtures

**Note, 2026-10-26.** The acceptance sheet of [[IMPLEMENTATION-PLAN]] §5.3: each fixture is written with its expected outcome before any SQL, and edited here. S1 rows come before track C, S2 rows beside it; *Phase* says which phase's release must pass the row.

| Part | Phase | Fixture | Expected outcome |
|---|---|---|---|
| D1 | 1 | A list-valued House record contains `kind = vote` with domain outcomes `unknown`, `agreed`, `rejected`, `tied`, `other`, alongside a referenced acquisition sibling; a vote inherits a 404 failure or a 200 body | The vote domain field never supplies acquisition outcome: retain line acquisition facts or existing missing-outcome derivation. Four public rows preserve ordinals, sibling facts and the exact 34-column schema; unknown acquisition outcomes on the line or non-vote items still refuse, and ordinary record behavior stays unchanged. |
| D1 | 1 | Reduced external/provider-responses assembly line489 has two `captured_original_page` items and one `original_body_unresolved`, each with a nested fetch receipt; wrong-family, daily-name, unknown-vocabulary and unknown-receipt controls | Only the registry's named domain values are excluded. Nested receipt status, time and completeness survive; each item keeps its row. Other unrecognized outcomes, including unlisted Vote values, refuse. Known acquisition values retain priority, and registry bytes bind the mapping identity. Source and public schemas remain24 and34 columns. |
| D1 | 1 | The old-index comparison has 2,048 matching captures with distinct 8 KiB context URLs, 64-row Parquet row groups and a 192 MiB native memory budget | The comparison completes with every occurrence matched, no changed or unmatched rows, and all evidence exports intact. Consumed tables are released before later joins; summary counts retain the complete input populations. |
| D1 | 1 | The full old-index comparison has2,048 and8,192 long-context captures, one removable secondary file, one contradictory retained file, a restored HTTP status, a restored list item and an unexplained new row under the same192MiB budget | Both scales preserve exact duplicate counts, NULL matching, all old-only original fields and owner_gate. Native signed grouping spills; old-only/new-only/matched rows require no full wide hash build. String sort inputs use plain Utf8. |
| F5 | 1 | A superseded CT module is referenced only by a test and a measurement script; another is imported by a kept runtime module and workflow | Only the runtime module and workflow count as production callers. Removed-subject tests remain in the deletion inventory. All 18 strip groups belong to CT; docspec-rs has no actionable files. |
| S1 | 1 | A PDF replaced while its XML stays, with historical pages linking both | Three documents: each PDF edition alone, and the XML alone |
| S1 | 1 | Two editions served at one address, and two mirrors that each pair one of them with the same XML | No document holds both editions |
| S1 | 1 | Re-packaged copies of each edition, each paired with one XML, never at a shared address | The known limit: such a copy can join the XML; the edition count measures how often |
| S1 | 1 | A ZIP repacked so `report.pdf` moves to another position, with mirrors pairing each edition with the same XML | One edition-ambiguous endpoint; the editions stay apart |
| S1 | 1 | Two archive members with one name and different bytes | An edition-ambiguous endpoint; neither member takes a rendition edge |
| S1 | 1 | A linked GovInfo ZIP holding one hearing's HTML and PDF with its METS (`dip.xml`), MODS and PREMIS manifests; a linked ZIP holding two different PDFs | The ZIP, HTML and PDF form one document and the manifests join none; no rendition edges |
| S1 | 1 | Several same-format files listed together; unrelated files on one page outside any list item | Each stays its own document; the unlisted files get no publisher group |
| S1 | 1 | One source file at several archive-member paths and directories | One source identity, every address retained; same-stem memberships consider every directory |
| S1 | 1 | One PDF body under two download names, listed with its XML | One document with both names and the XML; the group counts one PDF body |
| S1 | 1 | One page template under two hearings, where only hearing A's PDF and hearing B's XML were captured | No rendition edge between them |
| S1 | 1 | One page saved by a direct attempt and a provider retry with different page furniture; an archived page also imported as a rendered recovery | One document each: equal main-content fingerprints; the recovery attaches as labeled evidence |
| S1 | 1 | A page with relative links saved in two directories; a relative `<base href>`; a page whose relative links point at sibling archive members | Each copy's links resolve against its own address and base; member links target endpoints in the same container |
| S1 | 1 | A concatenated `href` whose two targets both exist | Two links, in `href` order, one target each |
| S1 | 1 | URLs written with raw spaces and with `%20` | One `url_key` |
| S1 | 1 | A placeholder page at thousands of addresses | Not a real file; it connects nothing, and its links are not resolved |
| S1 | 1 | A short real hearing page; a short soft-error page; a near-empty page; a "your download will begin" page | `document`; `error_response`; `error_response`; `wrapper`, with its file link queued |
| S1 | 1 | A broken PDF; a valid PDF with trailing bytes after its end marker; a new valid PDF; a PDF over the reader's limit with no end marker in its tail; an older gzip PDF that no check has reached | `damaged`; real; real, from the `intact` its capture recorded; `damaged` and reported; listed as `unchecked` until B13, and reported |
| S1 | 1 | An Office file; an End of Term `.warc.gz` or `.arc.gz` envelope stored beside its payload | One body, no members; `envelope`, and the payload's endpoint holds one real body |
| S1 | 1 | An older line with outcome `html` and a 2xx response; a site home page or "Under Maintenance" page served at a `.pdf` URL | A good fetch; not a real file (file-shaped), reported by error type |
| S1 | 1 | A feed page | `listing`, and no link context |
| S1 | 1 | A body whose parse crashes or hangs on every try | Retried once in the run, then an `unreadable` decision naming the producer; the work list empties, publish goes on, and a rebuild skips the same body |
| S1 | 1 | A response with no declared length read to a clean end; a body assembled from ranges of one entity; ranges whose entity changed in between | Complete; complete; not complete |
| S1 | 1 | A cut-off direct attempt and a complete provider retry in one fetch | The retry's body is real; the cut-off body is not |
| S1 | 1 | A recovered file that a real fetch also saved | A real body and link key; the recovery attaches as labeled evidence |
| S1 | 1 | Sniff bytes of `json` served under a misleading suffix and media type | `json` from bytes |
| S1 | 1 | Sniff bytes of `vtt` served under a misleading suffix and media type | `vtt` from bytes |
| S1 | 1 | Sniff bytes of `m3u8` served under a misleading suffix and media type | `m3u8` from bytes |
| S1 | 1 | Sniff bytes of `docx` served under a misleading suffix and media type | `docx` from bytes |
| S1 | 1 | Sniff bytes of `doc` served under a misleading suffix and media type | `doc` from bytes |
| S1 | 1 | Sniff bytes of `text` served under a misleading suffix and media type | `text` from bytes |
| S1 | 1 | Sniff bytes of `image` served under a misleading suffix and media type | `image` from bytes |
| S1 | 1 | Sniff bytes of `other` served under a misleading suffix and media type | `other` from bytes |
| S1 | 1 | Sniff bytes of `empty` served under a misleading suffix and media type | `empty` from bytes |
| S2 | 1 | One body under two filenames | Two source files in one document, which shows the saved file's name |
| S2 | 1 | Two editions served at one address | Two documents sharing a `version_keys` entry |
| S2 | 2 | A House witness list with two panels, a member witness and witness documents; one witness name at two meetings | Two panels; the member keeps the source's `bioguide_id`; each document carries its witness's `witness_key`; two keys for the name, not matched |
| S2 | 2 | A witness list naming one witness twice; a witness list naming none | One appearance, the first; one `appearance_records` row with no appearances |
| S2 | 2 | A witness list with two unnamed witnesses, one of them later named by the publisher | Two appearances, each keyed by `#` and its list position; the named one's key changes with its record version, the other's does not |
| S2 | 2 | A YouTube and a Senate recording, each with a caption track and the Senate one with its segment files | One `recordings` row each; the segments are not tracks |
| S2 | 2 | A bill with an amendment, and an amendment to that amendment | Both listed under the bill |
| S2 | 2 | A release with entity files | The manifest names `spicy-regs` and its generations as producer of `committees` through `nominations`, `archive` for the rest; `schema.json` matches every file's columns |
| S2 | 2 | One Congress.gov meeting record copied on 11 receipt lines, and a second version with a later `updateDate` | One `record_sha` per version; the later version is current |
| S2 | 2 | A Senate hearing page whose witness cards hold their testimony links | Appearances with the page as occasion; each testimony carries its witness's `witness_key` |
| S2 | 2 | A postponed meeting on a bill, recorded by House XML and Congress.gov | The House XML record is current; `status` postponed; the bill in `subject_keys` |
| S2 | 2 | A Senate hearing transcript whose MODS record lists witnesses and names no meeting | Appearances keyed by the package; the transcript's page lists them, and no document is credited to them |
| S2 | 2 | A Senate meeting whose Congress.gov record names a transcript jacket whose MODS record lists witnesses | The witnesses attach to the meeting, one `witness_key` each; the meeting's `transcripts` gives the transcript's list row |
| S2 | 2 | A joint (`NoChamber`) meeting's jacket held only as a `jhrg` package, and jacket 49104057 held as `CHRG-118shrg049104057` | Both resolve; the meeting's `chamber` is null |
| S2 | 2 | A Senate meeting video and a House YouTube video | `video_key`s `senate:{filename}` and `youtube:{id}` |
| S2 | 2 | A bill with one floor vote naming it and one named only in its actions; a nomination with a hearing, a cloture vote and a confirmation vote; one confirmed by voice vote | Two `floor_votes`, basis `vote_record` then `bill_action`; the nomination's two votes in order; the voice vote only in `latest_action_text` |
| S2 | 1 | An older recovery line with no category and no `recovery_evidence`, recovering a link a document was fetched from | Kind from its match basis; original link and import date from its fallbacks; one source file for its original link |
| S2 | 1 | A v5 seed recovery whose input carries no import record | `recoveries.imported_at` is null and displays as unknown; the raw rebuild fills the actual import date |
| S2 | 1 | A dead link pasted as `http://www.…/a.pdf/` for a document fetched from `https://…/a.pdf`; a published address that redirected to the saved file and later died | One lookup key finds each |
| S2 | 2 | A committee renamed on a boundary day; two subcommittees sharing a name | The half-open interval gives one name per day; `committee_keys` keep them apart |
| S2 | 2 | A bill named by a filename and by a meeting's related items | One `bill_id`; both find its title, sponsor and stage in the pinned `congress_bills` |
| S2 | 2 | A publish after spicy-regs moves a family's pointer | The new generation is pinned, recorded in `inputs/`, and changes the input identity |
| S2 | 2 | A kept release whose bills generation is four generations old | Spicy-regs' retention plan keeps it, citing the archive's pin list |
| S2 | 1 | A file named only by its download header; a URL with `?file=a.pdf&name=b.pdf` | The header's name (`filename*` first); `a.pdf` |
| S2 | 1 | An exact copy and a provider's saved-text copy at one URL | The exact copy is the saved file |
| S2 | 1 | A file whose kind only the publisher gives, by `doc_type`, and another by link text only | Each gets the publisher-kind registry's kind |
| S2 | 1 | A committee-removed document; one removed and later re-added | `removed_on` set; null |
| S2 | 1 | A meeting named only by a GovInfo MODS record; a meeting with no record | The package's source files carry the meeting; the meeting is listed by key with null details |
| S2 | 1 | A `Retry-After` beyond the family's recheck interval; a URL whose latest line has no time | `next_attempt_at` capped at the interval; due now |
| S2 | 2 | A relist whose first page is stored and a later page fails | The next run repeats the whole window |
| S2 | 1 | A queue link carrying a credential parameter | The queue row has it removed |
| S2 | 1 | A recovery at an edition-ambiguous link; a recovery import for a linked URL never fetched | A document of its own each; the URL enters the queue |
| S2 | 1 | A recovery-only link that later downloads | Its link URL key opens the document that now holds the download, where the recovery attaches |
| S2 | 1 | Two recoveries equal in kind, time and body; decisions that match one recovery row twice; a recovery whose decision rejects it | Both shown, in receipt order; one recovery, from the latest decision; no recovery |
| S2 | 1 | Two merged documents with different title overrides; two active merges on one document; a hide and its withdrawal | The latest override by `(decided_at, id)`; both merges applied; visible again |

## E4 comparison

The authored cases and outcomes are in [`e4-parity.json`](e4-parity.json); the
versioned input example is [`e4-parity-inputs.example.json`](e4-parity-inputs.example.json).

| Step | Phase | Case | Expected outcome |
|---|---|---|---|
| E4 | 1 | A split/merge shares source evidence; unchanged editions share an address | Every evidence-backed document pair remains; exact unchanged memberships do not cross-join |
| E4 | 1 | Each known cause and an unrelated title or review-note change | Only the cause's fields/direction are explained; every other difference remains listed |
| E4 | 1 | A rejected XML placeholder also satisfies the soft-error predicate | Both explanations remain, with each count deduplicated by difference ID |
| E4 | 1 | Equal ID inputs with a wrong declared ID; changed inputs with valid IDs | Invalid IDs refuse qualification; valid input changes have their own count/examples |
| E4 | 1 | Classified differences, one fact held only by derived tables | All uncovered rows remain; unclassified and derived-only cases prevent qualification |
| E4 | 1 | Converted shared HTML, multiple formats, source contexts and dates | Only demonstrated converter gaps; fixture success never qualifies the model |
| E4 | 1 | An unrelated visible filename regression in a converted candidate | Unexplained differences remain; conversion gaps cannot excuse it |

Unordered SQL row numbering is not a physical Parquet row-position guarantee.
The comparator uses the producer's explicitly ordered relation and verifies its
public output bytes and row values instead.

D2 exact listing size cases: a capture lacking stored size and MD5 takes both pins only from its exact listed key and completes the actual conditional GET; its original capture remains unchanged. Missing listed size or ETag and an unrecorded alternate suffix refuse before any GET. Existing capture/listing size and MD5 conflict cases continue to refuse. These expectations cover both selected inventories and direct listing work lists in `test_readings_listed_etag.py`.

## References

**[IMPLEMENTATION-PLAN]**
: *Congressional Document Archive: Implementation Plan.* Note, 2026-10-24. `docs/plans/simplification-plan-20261024.md`.
