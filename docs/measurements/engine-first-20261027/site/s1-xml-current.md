# Current XML leaf qualification

The twelve retained House XML entities pass the current byte sniffer and XML
reader at site source `519ee332`. Each auxiliary cache file was opened once,
read within the maintained 64 MiB bound, decoded when its held bytes had gzip
magic, and checked against the qualified entity SHA-256 before parsing. One
cache file was gzip; eleven held decoded XML. These are auxiliary cache facts,
not claims about the canonical raw object's physical encoding.

All twelve sniffs completed as XML with `intact=null` (XML has no PDF integrity
verdict); all XML readings completed without error. The observed roots match
the historical evidence: eleven `floorschedule`, one `committee-meeting`.
The measured leaf loop took 0.0233 seconds. It made twelve body opens and no
network requests. No grouping or data join ran in Python.

Private evidence is in `codex-site/run4/s1-current-xml-oneread/`: selectors are
from `codex-raw/run2/e4-gap-locators/xml-selectors.parquet`; `readings.jsonl`
retains each source pointer, exact entity digest, current versions and parser
result. `qualification.json` checks the saved records. The first post-read
assertion expected the wrong status/integrity vocabulary; the clarification
checks the maintained values without reopening any body.

This qualifies the current leaves, not the canonical D1/D2 receipt path or
model classification. Raw's normalized original-receipt packet is still needed
for that path. Valid GovInfo ZIP and End of Term envelope semantic coverage
remain unqualified in the known local inventory. No new detector or rule was
added.
