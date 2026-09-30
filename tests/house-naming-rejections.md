# House naming rejection inventory — 2026-09-29

This inventories the pre-implementation rejections. The
[implementation results](house-naming-implementation.md) record which groups
are now accepted and the remaining limits.

**Most rejections are not case differences.** Case-only changes explain 46,688
of the 175,442 rejected PDF/XML filenames (26.61%). Of those, 41,788 need only
`Wstate` changed to `WState`. Separator and numeric-padding probes found another
217 candidate matches; 128,537 PDF/XML names still have no matching convention
under these probes.

This follows the [full parser comparison](filename-engine-comparison-results.md)
and uses its recovered population, not a proven restoration of the deleted
`output/` snapshot. No production parser changed and no documents were fetched.

## Every rejection is accounted for

The retained primary run rejected 268,187 distinct names. The new inventory's
filename set equals that entire rejection set, with no duplicates or omissions.

| Group | Count |
| --- | ---: |
| PDF/XML: `Wstate` → `WState` alone | 41,788 |
| PDF/XML: extension case alone, such as `.PDF` → `.pdf` | 238 |
| PDF/XML: other or combined case differences | 4,662 |
| PDF/XML: separator changes, sometimes also case | 201 |
| PDF/XML: numeric padding, sometimes also separators/case | 16 |
| PDF/XML: no supported shape found by these probes | 128,537 |
| Other recognized document extensions, principally HTML | 35,053 |
| Extensionless URL basenames/routes | 57,664 |
| Other extensions | 28 |
| **Total** | **268,187** |

The first six rows total 175,442 rejected PDF/XML names. Including other
recognized document extensions gives 210,495 rejected document filenames.
The House package deliberately supports only `.pdf` and `.xml`; other extensions
were inventoried separately, not renamed to make them pass.

## Case and formatting examples

| Original | Validated diagnostic rendering | Explanation |
| --- | --- | --- |
| `HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf` | `HHRG-113-AG00-WState-ColbyJ-20130314.pdf` | Marker case only |
| `BILLS-112-HR3116-C001063-Amdt-1DD.PDF` | `BILLS-112-HR3116-C001063-Amdt-1DD.pdf` | Extension case only |
| `BILLS-112-hr3116-S000030-Amdt-1WW.pdf` | `BILLS-112-HR3116-S000030-Amdt-1WW.pdf` | Measure-type case only |
| `BILLS-113-HR2879ih.pdf` | `BILLS-113hr2879ih.pdf` | Extra separator and case |
| `BILLS-115HR0625ih.pdf` | `BILLS-115hr625ih.pdf` | Padded numeric measure number and case |

Every candidate was rendered and re-parsed through `house-naming` itself.
The probes preserve free-text field values, field order, and original names;
they do not fill missing metadata, rewrite dates, or delete arbitrary suffixes.

The 217 formatting candidates are **not automatically safe corrections**:

- Twenty-four inputs have multiple diagnostic interpretations. For example,
  changing separators in `BILLS-115-HR146-B001250-Amdt-_1.pdf` can produce either
  a floor-amendment or committee-amendment convention. Both candidates remain
  in the inventory rather than selecting one.
- Nineteen filenames contain underscore placeholders before `PIH`. Treating
  those underscores as separators permits a preintroduced-bill record, but
  removes the explicit placeholder from the rendered spelling.
- For 133 appropriations-amendment filenames, fixing a separator yields the
  broad `appropriation-described` kind. The amendment identifier remains inside
  its description rather than becoming structured amendment metadata.

Case tolerance therefore offers a well-isolated coverage improvement. Broader
formatting tolerance needs explicit handling of these semantic distinctions.

## The remaining 128,537 PDF/XML names

These groups are mutually exclusive observations based on the existing
extractor's fields and rules. They describe the shapes not matched by the
bounded probes, not a claim that every possible alternative repair was tried.

| Observed group | Count | What differs |
| --- | ---: | --- |
| Date-first committee documents | 41,164 | Date precedes SD, QFR, MbrRoster, CPg, or TOC; these layouts are absent from the package |
| GPO hearing package filenames | 34,714 | CHRG publication identifiers have no filename convention in the package |
| Free-form names and other publishers | 22,322 | Titles, personal names, UUIDs, hashes, and other non-House-template basenames |
| Other legislative filename variants | 15,416 | Missing measure type/number, titles and descriptors, additional suffixes, committee print references, and other local formats |
| Committee vote documents | 8,503 | The common CRPT vote layout omits the literal HMTG segment required by the package; some vote identifiers also differ |
| Committee transcript filenames | 2,912 | HHRG/HMKP/HMTG transcript layouts have no corresponding filename convention |
| Witness documents under HMTG or HMKP | 2,912 | Witness conventions are hard-coded to HHRG |
| Other committee/report/print variants | 594 | Remaining report parts, print layouts, witness lists, missing identifiers, and other forms |
| **Total** | **128,537** | |

Representative raw names and the specific missing support:

- `HHRG-112-HM00-20110310-SD001.pdf`: date-first supporting document. This is
  one of 38,174 date-first SD filenames within the first group.
- `HHRG-114-FA00-20160211-QFR001.pdf`: date-first QFR document. There are 1,424
  date-first QFR names across committee meeting families.
- `CHRG-106hhrg53880.pdf`: published GPO hearing. Neither casing nor separator
  changes supply a missing CHRG convention.
- `CRPT-113-AP00-Vote001-20130521.pdf`: the current template expects
  `CRPT-{congress}-HMTG-{committeeCode}-Vote{voteId}-{voteDate}`. Supplying that
  absent token would exceed a formatting change.
- `HMTG-113-AP06-Wstate-BrewerB-20130424.pdf`: fixing `Wstate` still fails because
  the package's witness-statement template requires HHRG. Changing the collection
  would change source metadata; support should retain the original collection.
- `BILLS-113pih-BACPACAct.pdf`: the preintroduced template requires a measure
  type before PIH, but the filename does not supply it.
- `BILLS-113-3389-A000055-Amdt-001b.pdf`: the subject is numeric without a printed
  measure type. There are 4,786 numeric-subject amendment names in the residual
  group; the diagnostic did not invent `HR` or another type.
- `BILLS-113-HR4660ih(asfiled).pdf`: extra descriptive suffix.
- `BILLS-115hr1892eas2.pdf`: version occurrence after the stage.
- `BILLS-115HR__-RCP115-77.pdf`: unnumbered measure and committee-print reference.
- `HHRG-115-IF02-MState--20170131.pdf`: missing member identifier, which the
  package requires.

## Method and verification

The audit used the same frozen primary outputs and checked current package
hashes against that run before and after processing. It derived diagnostic
matchers from the package's own templates and field schemas, then tried, in
order: case; case plus separators; those plus integer padding; and relaxed
date/integer lexical shapes followed by the package's validation.

Separators were bounded to hyphens, underscores, and whitespace at template
boundaries. Free-text captures were retained. The last diagnostic found no
additional validated candidates or schema/calendar failure cases in this
population. That does not establish that the source documents or all residual
filenames are valid.

All rejections completed in 16.44 seconds. Constructed controls verified that
invalid calendar dates, absent conventions, and a changed collection prefix do
not count as successful repairs; additional controls checked padded numbers and
retention of competing interpretations. Human review covered the remaining
PDF/XML shape groups and representative native candidate outputs, not document
contents or every individual filename.

Reproduce from the repository root, using a new output directory:

```sh
.venv/bin/python tests/inventory_house_naming_rejections.py \
  --run .cache/filename-engine-comparison-20260929/run \
  --output .cache/filename-engine-comparison-20260929/rejections-rerun
```

## Inventory files

Files are under `.cache/filename-engine-comparison-20260929/rejections/`:

| Artifact | Contents |
| --- | --- |
| `rejections.parquet` | Every rejected name, original issue, suffix class, category, observed shape, extractor fields, candidate names/kinds, ambiguity and validation codes |
| `shapes.parquet` | All 234 groups with counts and raw examples |
| `shape-inventory.md` | Readable table of all 234 groups |
| `candidates.jsonl.gz` | Per-name probe attempts, full candidate records, exact text edits, and validation failures |
| `summary.json` | Counts, hashes, timing and completion |
| `analysis.json` | Case-only breakdown and the eight residual groups |
| `controls.json` | Seven additional constructed-control results |
| `summarize.py` | Reproducible summary grouping and completeness assertions |

These are local cache artifacts. Original filenames, primary parser outputs,
and production behavior remain unchanged.
