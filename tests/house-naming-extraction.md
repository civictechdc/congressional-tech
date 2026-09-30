# Literal filename extraction

Decision: move the useful source-reading behavior of the native filename parser
into house-naming, separate from validation of names the package can render.
Hypothesis: source layouts, scoped token searches, date candidates and explicit
last-resort assumptions recover information that strict naming validation cannot,
without inventing extensions, dates, bill types, people or source identities.
Arms: retained drafts-final native outputs versus Engine.extract on the same
333,368 literal inputs. Keep Engine.parse behavior and records unchanged.
Cases: complete retained corpus, existing source examples, regression cases for
overlapping identifiers/dates/references, malformed inputs and user-requested
fallbacks. Reused corpus examples are development data, not unseen validation.
Held constant: native parser source, inventory, original guide text/code values,
existing rendering schemas. No network, PDF reads, external name dictionaries,
or inferred identities. Use the native parser as a comparator, not ground truth.
Decision rule: all original characters and extracted spans must round-trip;
every prior strict result must survive; all disagreements and skipped raw tokens
must remain inspectable. Retain ambiguity, invalid date slots and literal unknown
codes. Do not report fallback assumptions or complete byte retention as complete
semantic understanding. Input length is bounded; every retained corpus input
must be processed within that bound.

Observed extraction rules live in the package's existing catalog. The runtime
has no congress_api dependency. Global token searches must not reinterpret
structured IDs, dates or measure numbers. Generic numeric identifiers and assumed
names run only after recognized layouts and date/time recognition, with the
user's ZIP exclusion and hanging-pdf/tedtimony rules retained explicitly.

Follow-up before the named-date run: the omission audit found a written month/day/year
also emitting its year as a fallback numeric identifier. Reserve named date spans
before generic fallback, retain the original component fields, and check real
calendar validity without choosing missing years or centuries. Compare against
the same frozen native/strict baseline; retain extraction-verified as the prior run.
