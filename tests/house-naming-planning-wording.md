# Planning wording and joined fiscal years

Decision: retain explicit budget views/estimates, authorization/oversight-plan
wording and visibly joined fiscal-year tokens that remain inside free text.

Hypothesis: the source already prints these distinctions; bounded literal rules
can expose them without replacing older readings, interpreting arbitrary topic
words, or resolving a committee identity. A lowercase-to-uppercase `FY` boundary
is visible in names such as `ViewsandEstimatesFY2020`. Lowercase `ify2020` is not
equivalent evidence.

Arms: accepted `meeting-results`, frozen historical native/strict `drafts-final`,
and the candidate catalog additions. This is a deliberate bundle of related
wording refinements; attribute gains to the bundle, not to a single component.

Cases: inventory all views/estimates and oversight-plan phrases, plus letter-joined
FY/year shapes, in the fixed 333,368-name corpus. Retain discovery outputs and
inspect actual source associations. Include separated and joined spelling,
leading fiscal years, trailing FY tokens, attached bill versions, notices,
amendment subjects, and explicit subsequent Congress wording. Negative controls
cover longer words, ambiguous letter runs, escaped URLs and witness identifiers.
Existing labels may coexist with longer phrases, but identical label spans must
not be duplicated. Source phrases do not prove a file's exclusive type or status.

Decision rule: accept only reviewed literal additions. Require exact field spans,
all previous complete outputs after removing additions, unchanged strict records,
typed-adapter parity, focused and regression tests, full omission audit and corpus
checks. Preserve failures and explain any revised boundary. Keep FY digits raw;
do not infer a century, event date, primary Congress or a committee identity.

Reuse existing harnesses; no downloads or new dependencies. Each full corpus run
is bounded to 30 minutes. This is reused development evidence, not an unseen
accuracy evaluation. Do not add generic activity-report recognition: the discovery
also found Suspicious Activity Reports and Short Activity Reporting, which are
unrelated topic phrases.
