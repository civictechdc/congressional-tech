# Native browser contract fixtures

Expected results: both releases contain six visible documents, public-key and hearing navigation, review removal, saved-copy failure notices, versions, and source/recovery ranges. A missing detail file with a pointer change reloads the next release and preserves the public key. The next fixture changes only the first document's title to “Updated transportation agenda”.

These are native engine outputs from `model/fixtures/hand-release.json`, using engine revision `37ccde0`, with the converter at `993e5bcd`. The reader verifies every file's digest and the content-addressed release identity before serving it. Synthetic body hashes deliberately have no physical body objects; these fixtures cannot qualify a successful saved-copy canary or a live publication.

Current release: `bb67d15c1569d35230a781942d03dd89ef1c15420f0ac9e434056b19e4c71ca4`.
Next release: `8f11714a45da79ee1348aa3f41c5ded8166142dffaab54bf72d79dfc1761aa9c`.

Deploy and pull-request validation read these small committed native outputs without storage credentials. Regenerate through `viewer_publication.archive_release` with an explicitly pinned native runtime when the release schema changes; never rewrite manifests or fabricate Parquet bytes.
