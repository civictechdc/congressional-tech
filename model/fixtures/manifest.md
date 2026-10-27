# Congressional Document Archive: Acceptance Fixtures

**Note, 2026-10-26.** The acceptance sheet of [[IMPLEMENTATION-PLAN]] §5.3: each fixture is written with its expected outcome before any SQL. S1 rows come before track C, S2 rows beside it; S2's meeting, witness and spicy-regs rows wait for phase 2. E1 moves this table into the fixture directory as its manifest, and it is edited there from then on.

| Part | Fixture | Expected outcome |
|---|---|---|
| S1 | A PDF replaced while its XML stays, with historical pages linking both | Three documents: each PDF edition alone, and the XML alone |
| S1 | Two editions served at one address, and two mirrors that each pair one of them with the same XML | No document holds both editions |
| S1 | Re-packaged copies of each edition, each paired with one XML, never at a shared address | The known limit: such a copy can join the XML; the edition count measures how often |
| S1 | A ZIP repacked so `report.pdf` moves to another position, with mirrors pairing each edition with the same XML | One edition-ambiguous endpoint; the editions stay apart |
| S1 | Two archive members with one name and different bytes | An edition-ambiguous endpoint; neither member takes a rendition edge |
| S1 | A linked GovInfo ZIP holding one hearing's HTML and PDF with its METS (`dip.xml`), MODS and PREMIS manifests; a linked ZIP holding two different PDFs | The ZIP, HTML and PDF form one document and the manifests join none; no rendition edges |
| S1 | Several same-format files listed together; unrelated files on one page outside any list item | Each stays its own document; the unlisted files get no publisher group |
| S1 | One PDF body under two download names, listed with its XML | One document with both names and the XML; the group counts one PDF body |
| S1 | One page template under two hearings, where only hearing A's PDF and hearing B's XML were captured | No rendition edge between them |
| S1 | One page saved by a direct attempt and a provider retry with different page furniture; an archived page also imported as a rendered recovery | One document each: equal main-content fingerprints; the recovery attaches as labeled evidence |
| S1 | A page with relative links saved in two directories; a relative `<base href>`; a page whose relative links point at sibling archive members | Each copy's links resolve against its own address and base; member links target endpoints in the same container |
| S1 | A concatenated `href` whose two targets both exist | Two links, in `href` order, one target each |
| S1 | URLs written with raw spaces and with `%20` | One `url_key` |
| S1 | A placeholder page at thousands of addresses | Not a real file; it connects nothing, and its links are not resolved |
| S1 | A short real hearing page; a short soft-error page; a near-empty page; a "your download will begin" page | `document`; `error_response`; `error_response`; `wrapper`, with its file link queued |
| S1 | A broken PDF; a valid PDF with trailing bytes after its end marker; a new valid PDF; a PDF over the reader's limit with no end marker in its tail; an older gzip PDF that no check has reached | `damaged`; real; real, from the `intact` its capture recorded; `damaged` and reported; listed as `unchecked` until B13, and reported |
| S1 | An Office file; an End of Term `.warc.gz` or `.arc.gz` envelope stored beside its payload | One body, no members; `envelope`, and the payload's endpoint holds one real body |
| S1 | An older line with outcome `html` and a 2xx response; a site home page or "Under Maintenance" page served at a `.pdf` URL | A good fetch; not a real file (file-shaped), reported by error type |
| S1 | A feed page | `listing`, and no link context |
| S1 | A body whose parse crashes or hangs on every try | Retried once in the run, then an `unreadable` decision naming the producer; the work list empties, publish goes on, and a rebuild skips the same body |
| S1 | A response with no declared length read to a clean end; a body assembled from ranges of one entity; ranges whose entity changed in between | Complete; complete; not complete |
| S1 | A cut-off direct attempt and a complete provider retry in one fetch | The retry's body is real; the cut-off body is not |
| S1 | A recovered file that a real fetch also saved | A real body and link key; the recovery attaches as labeled evidence |
| S1 | Sniff bytes of `json` served under a misleading suffix and media type | `json` from bytes |
| S1 | Sniff bytes of `vtt` served under a misleading suffix and media type | `vtt` from bytes |
| S1 | Sniff bytes of `m3u8` served under a misleading suffix and media type | `m3u8` from bytes |
| S1 | Sniff bytes of `docx` served under a misleading suffix and media type | `docx` from bytes |
| S1 | Sniff bytes of `doc` served under a misleading suffix and media type | `doc` from bytes |
| S1 | Sniff bytes of `text` served under a misleading suffix and media type | `text` from bytes |
| S1 | Sniff bytes of `image` served under a misleading suffix and media type | `image` from bytes |
| S1 | Sniff bytes of `other` served under a misleading suffix and media type | `other` from bytes |
| S1 | Sniff bytes of `empty` served under a misleading suffix and media type | `empty` from bytes |
| S2 | One body under two filenames | Two source files in one document, which shows the saved file's name |
| S2 | Two editions served at one address | Two documents sharing a `version_keys` entry |
| S2 | A House witness list with two panels, a member witness and witness documents; one witness name at two meetings | Two panels; the member keeps the source's `bioguide_id`; each document carries its witness's `witness_key`; two keys for the name, not matched |
| S2 | A witness list naming one witness twice; a witness list naming none | One appearance, the first; one `appearance_records` row with no appearances |
| S2 | A witness list with two unnamed witnesses, one of them later named by the publisher | Two appearances, each keyed by `#` and its list position; the named one's key changes with its record version, the other's does not |
| S2 | A YouTube and a Senate recording, each with a caption track and the Senate one with its segment files | One `recordings` row each; the segments are not tracks |
| S2 | A bill with an amendment, and an amendment to that amendment | Both listed under the bill |
| S2 | A release with entity files | The manifest names `spicy-regs` and its generations as producer of `committees` through `nominations`, `archive` for the rest; `schema.json` matches every file's columns |
| S2 | One Congress.gov meeting record copied on 11 receipt lines, and a second version with a later `updateDate` | One `record_sha` per version; the later version is current |
| S2 | A Senate hearing page whose witness cards hold their testimony links | Appearances with the page as occasion; each testimony carries its witness's `witness_key` |
| S2 | A postponed meeting on a bill, recorded by House XML and Congress.gov | The House XML record is current; `status` postponed; the bill in `subject_keys` |
| S2 | A Senate hearing transcript whose MODS record lists witnesses and names no meeting | Appearances keyed by the package; the transcript's page lists them, and no document is credited to them |
| S2 | A Senate meeting whose Congress.gov record names a transcript jacket whose MODS record lists witnesses | The witnesses attach to the meeting, one `witness_key` each; the meeting's `transcripts` gives the transcript's list row |
| S2 | A joint (`NoChamber`) meeting's jacket held only as a `jhrg` package, and jacket 49104057 held as `CHRG-118shrg049104057` | Both resolve; the meeting's `chamber` is null |
| S2 | A Senate meeting video and a House YouTube video | `video_key`s `senate:{filename}` and `youtube:{id}` |
| S2 | A bill with one floor vote naming it and one named only in its actions; a nomination with a hearing, a cloture vote and a confirmation vote; one confirmed by voice vote | Two `floor_votes`, basis `vote_record` then `bill_action`; the nomination's two votes in order; the voice vote only in `latest_action_text` |
| S2 | An older recovery line with no category and no `recovery_evidence`, recovering a link a document was fetched from | Kind from its match basis; original link and import date from its fallbacks; one source file for its original link |
| S2 | A dead link pasted as `http://www.…/a.pdf/` for a document fetched from `https://…/a.pdf`; a published address that redirected to the saved file and later died | One lookup key finds each |
| S2 | A committee renamed on a boundary day; two subcommittees sharing a name | The half-open interval gives one name per day; `committee_keys` keep them apart |
| S2 | A bill named by a filename and by a meeting's related items | One `bill_id`; both find its title, sponsor and stage in the pinned `congress_bills` |
| S2 | A publish after spicy-regs moves a family's pointer | The new generation is pinned, recorded in `inputs/`, and changes the input identity |
| S2 | A kept release whose bills generation is four generations old | Spicy-regs' retention plan keeps it, citing the archive's pin list |
| S2 | A file named only by its download header; a URL with `?file=a.pdf&name=b.pdf` | The header's name (`filename*` first); `a.pdf` |
| S2 | An exact copy and a provider's saved-text copy at one URL | The exact copy is the saved file |
| S2 | A file whose kind only the publisher gives, by `doc_type`, and another by link text only | Each gets the publisher-kind registry's kind |
| S2 | A committee-removed document; one removed and later re-added | `removed_on` set; null |
| S2 | A meeting named only by a GovInfo MODS record; a meeting with no record | The package's source files carry the meeting; the meeting is listed by key with null details |
| S2 | A `Retry-After` beyond the family's recheck interval; a URL whose latest line has no time | `next_attempt_at` capped at the interval; due now |
| S2 | A relist whose first page is stored and a later page fails | The next run repeats the whole window |
| S2 | A queue link carrying a credential parameter | The queue row has it removed |
| S2 | A recovery at an edition-ambiguous link; a recovery import for a linked URL never fetched | A document of its own each; the URL enters the queue |
| S2 | A recovery-only link that later downloads | Its link URL key opens the document that now holds the download, where the recovery attaches |
| S2 | Two recoveries equal in kind, time and body; decisions that match one recovery row twice; a recovery whose decision rejects it | Both shown, in receipt order; one recovery, from the latest decision; no recovery |
| S2 | Two merged documents with different title overrides; two active merges on one document; a hide and its withdrawal | The latest override by `(decided_at, id)`; both merges applied; visible again |

## References

**[IMPLEMENTATION-PLAN]**
: *Congressional Document Archive: Implementation Plan.* Note, 2026-10-24. `docs/plans/simplification-plan-20261024.md`.
