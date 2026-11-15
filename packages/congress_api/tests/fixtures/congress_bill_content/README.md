# Congress.gov embedded bill fixture

`hr4307-enrolled.html.gz` is the retained original Congress.gov HTML for
H.R. 4307, 119th Congress. Its decoded SHA-256 is
`a6fb358f8a7c567829dafb5493ec352b88cd22a0ce835ec8bbf01237a9b47471`.
The original page contains a complete USLM bill inside
`xml#billTextUslm.generated-html-container`, alongside unrelated quick-search
member choices. The canonical URL is
`https://www.congress.gov/bill/119th-congress/house-bill/4307/text`.

`hr4307-enrolled.txt` is the retained paired XML output, SHA-256
`c513d914c7ebb4f95e17ed58eee29b2db04fca6ec2e42b8b4d38dcbe2508bfad`.
On 2026-11-15 the fix author directly read the entire embedded HTML bill and
new selected output, including the preface, four sections, nested clauses and
both signatures. That reading established the expected text before using
complete byte equality as the regression assertion. A smaller output alone
does not establish preservation. The letter-spaced session heading is source
typography and remains unchanged.

Source custody and actual prior output are retained under the main checkout's
`.cache/archive-release/ocr-recovery-20261113/repairs/corpus-assessment-20261113/triage-current-20261114/markup-exposed8-review-packets-20261115/`.
The original HTML packet is `a6fb358f8a7c`; the paired XML packet is
`60b48fe58f02`. Historical parser intermediaries are unavailable. New selected
fragment and output evidence belongs to `ct-g4yz-html-selection-20261115` beside
those packets. This fixture qualifies one body, not every Congress.gov page.
