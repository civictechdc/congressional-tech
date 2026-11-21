# Run 44737429192

Candidate `caf35cec7d01d2ee9bf0dd37e4369823a966a22a8830ef7f164b2d82ee816277` replaced the generic match for meeting 116718 with publisher-listed
video `youtube:Fyr9cXKd6NU`. The admitted October 31 Congress.gov JSON lists the event and video URL.
The new November 20 committee HTML embeds the same video and links to the House calendar
entry for 116718. Both decompressed bodies match the SHA-256 on the first line of their
respective raw receipts. [Receipt keys and hashes](nightly-replay.json)

| File | Failed candidate SHA-256 | Available release SHA-256 |
| --- | --- | --- |
| `recordings.parquet` | `9e5204fe8f38d11b868cc43b89b5c07bff773b4c2ee42235f32a1656d7449887` | `9e5204fe8f38d11b868cc43b89b5c07bff773b4c2ee42235f32a1656d7449887` |
| `recording_matches.parquet` | `0a7989e8b49fe6bd2f13eb3eb404562e861fd7aa63d99da906a370f46b66645e` | `0a7989e8b49fe6bd2f13eb3eb404562e861fd7aa63d99da906a370f46b66645e` |
| `meetings.parquet` | `592c9465f9b31b7ff9bda61522b79d61f30a2da94ac52ef733c4a1627e9d0956` | `b79188e659ecf13df00a618a0934ad7f86d0c3cf3bde1f03cc9d68bf519d4ebb` |
| `detail.parquet` | `fbc6dc517e208371f8c70f15d1d7ba1b0b257ed895ddb792b4ca89cb9355a60c` | `7a8d60d882ca4a74ddc31648c3373fcac66d89ca3b7ac2f25152e76af4e7147a` |

The recording tables match byte for byte. The meeting and detail tables differ. The replay
used the failed run's gate report, manifest, admitted receipts, and a receipt-derived video
link export. The base release's pinned calendar supplied the meeting identity fields, which
the failed comparison reports unchanged. The independent replacement check used raw bytes.

The gate explained 46 groups using equal fixture definitions and the available
`0e7084cde775` meeting and detail tables for the model-side replacement and column checks.
This is a partial historical replay. The original failed meeting and detail tables were unavailable.

All 673 unlinked keys traced to 653 new receipts.
The busiest receipt accounted for 4 keys. All 55
added linked keys had their event corroborated. [Replay script](replay.py)
