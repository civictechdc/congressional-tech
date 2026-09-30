# Remarks wording: results

Accepted run: `.cache/filename-engine-comparison-20260929/remarks-wording/`.
Previous accepted extractor: `calendar-wording/`.

**102 filenames gain 115 fields:** 102 literal remarks labels and 13 qualifier
words in 12 filenames. All 333,368 strict results remain unchanged. The full
field review finds no removed fields or changed existing metadata, and all
2,570,514 observed spans match the original source text.

The source inventory contained 85 Opening Remarks, three Oral Remarks, one
Written Remarks, one Prepared Remarks and 12 bare Remarks filenames. Each now
has exactly one remarks label. Closing Remarks is covered by a constructed
test, not an observed corpus example. The parser does not assign official House
vocabulary meanings, document contents or speaker identities from these labels.

| Example | Added fields |
| --- | --- |
| `AMD CEO Lisa Su Senate Commerce Committee Prepared Remarks May 2025.pdf` | `Prepared Remarks`; existing month/year precision survives. |
| `9.12 Opening Remarks Final Final.pdf` | `Opening Remarks`, both literal `Final` words. |
| `Chairman Manchin Final remarks.pdf` | `remarks`, preceding `Final`. |
| `Sfraga.Testimony.Remarks.pdf` | `Remarks`; existing `Testimony` remains a separate label. |
| `061620_-chairman-kennedy-opening-remarks&download=1` | `opening-remarks`; date and query fields stay separate. |

Qualifiers after a remarks label must form a terminal group, using existing
date/identifier-aware checks. Qualifiers directly before the label remain
eligible. This keeps Public inside the topic in constructed
`Prepared Remarks Public Health Hearing`, while `Final Remarks Public Health
Hearing` retains only Final as a qualifier. The first focused run missed same-
group terminal qualifiers; its two failures remain in the cache, and the
corrected grouping passes both remarks and existing biography/questionnaire tests.

**1,884 tests pass**, including 32 new cases. Generated JSON, ECMAScript and
whitespace checks pass. The native comparator, previous guide rules, strict
schemas and vocabulary meanings remain unchanged. The full omission audit has
no unexplained omissions. Source hashes match the comparison snapshot.

A separate diagnostic inventory ranks repeated words in descriptive and
fallback fields across all 333,368 inputs. It retains 14,973 phrases occurring
in at least three names; 45,764 inputs contain such uncovered words of any
frequency. These counts do not mean those filenames are wholly unparsed:
literal titles, names and broad descriptions intentionally remain source text.

The ranking exposed an amendment-number gap worth testing next. Of 313
candidate filenames, 48 have attached `1v1`-style identifiers and 156 have a
hanging `pdf` after a number. The other 109 candidates overlap dates or opaque
IDs and must remain protected. Raw source rows and both parser outputs are
retained in `amendment-number-wording-discovery.json`.

Changes remain local and uncommitted. This is verified development-corpus
improvement, not complete semantic coverage. Application consumers are unchanged.
