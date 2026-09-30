# Numeric subjects and explicit parts in loose report filenames

Decision: expose the numeric subject slot in HRPT/SRPT names without assuming it
is an official report number, a bill number or an embedded Congress. Extract
explicit Part/p markers separately and protect those assigned slots from generic
date and Bioguide scans.

Discovery: 213 HRPT/SRPT basenames, including 70 numeric-looking subjects.
Retained meeting JSON covers 68 of those 70; original House XML covers 60.
Sixteen retained PDFs were inspected by native extraction on their first two
pages. Numeric subjects refer variously to measures, reports and local numbers.
HRPT-114-114-2Part1.pdf has an actual PDF heading Report 114-12, Part 1; do not
repair its printed 114-2. HRPT-119-4550.pdf contains Report 119-233 accompanying
H.R. 4550. HRPT-117-1.pdf prints a report-number placeholder. Basenames such as
HRPT-118-1.pdf recur across unrelated meeting documents.

Hypothesis: one context-bound numeric-subject rule plus reuse of the existing
part readers adds useful source fields while leaving identities unresolved.
A full numeric subject may contain separated or joined numeric components;
do not split joined digits or label a component as a Congress. Only an explicit
trailing Part/p-number may follow it. Apply the rule inside report-file payloads,
reserve its fields before generic searches, and avoid duplicating part readings.
The containing payload, strict records and all prior literal output must remain.

Controls include report/measure/local-ID source examples, literal Part suffixes,
calendar-plausible numbers and p111111 (which must not become a Bioguide ID),
leading zeros, nonnumeric subjects, unrelated families and ordinary date names.
The numbered source sample must not gain publication_number, measure_number,
citation_number or a second Congress from these fields alone.

Compare all 333,368 names against damaged-transport and the frozen native/strict
baseline. Retain the existing single strict-correction expectation. Require all
prior complete outputs after removing reviewed additions to remain exact; any
unexpected reclassification must fail review. Run focused/full tests, typed
adapter equivalence, corpus checks, native omission audit, catalog checks and
source-hash checks. Retain failed trials. No fetching or new dependencies; each
full run is bounded to 30 minutes. This is reused development evidence, not an
unseen semantic accuracy estimate.
