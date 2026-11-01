# Explorer to native comparison, 2026-11-01

Frozen-input numbers. They may move: v21 captures disagree with current captures in at least 12,873 rows, and the archive-member eligibility rule (`ct-qg8e`) is undecided. The ledger is in `explorer-native-comparison-20261101.json`.

## Inputs

- Old release `56c87f8a7e29314d9e1477c0` from pipeline-data.
- Documents, meetings and witnesses from live release `448651e7`, each checked against its manifest sha256.
- The five new tables and the resolved meetings, built by `scripts/measure/explorer_tables_frozen.py` from v21 frozen inputs.
- `video_records` and `committee_records`, produced locally from public bodies.

This is not a full model run. It does not prove byte identity of other files, the real `detail` size, the release ID or full-job memory.

## Commands

```
python scripts/measure/explorer_tables_frozen.py --spec SPEC --release V21 --lake LAKE --decisions DECISIONS --output TABLES --runtime RUNTIME
python scripts/measure/explorer_native_comparison.py --old OLD --release V21 --overlay TABLES --data apps/committee_youtube/data --lake LAKE --decisions DECISIONS --output RESULT.json --release-id ID --commit SHA
```

Both run through the guard. The builder took 1.5 s and 873 MB RSS at a 1 GiB pool. The comparison took 2.3 s and 749 MB.

## Results

| Family | Old rows | Matched | Old only |
|---|---|---|---|
| Meetings | 18,453 | 18,141 | 312 other-source meetings |
| Document files | 335,973 | 325,590 | 10,383 pending print links |
| House documents | 18,126 | 17,993 | 133 |
| Senate documents | 14,606 | 11,172 | 3,434 pending page links |
| Amendments | 19,985 | 19,984 | 1, where the CSV text is double-encoded and the native value is correct |
| Curated decisions | 7,200 | 7,200 | 0 |
| Recording pairs | 16,313 | 8,100 | 8,213 pending matcher |
| Completeness | 17,606 | 17,606 | 0 |
| Videos | 67,351 | 67,351 | 0; 22 new from the later snapshot |
| Channels | 119 | 119 | 0 |

`old_state_only` covers rows with no native source yet, and it is a label rather than a plan: 6,369 `meeting_witnesses` rows and 586 `house_witnesses_found` rows need an owner.

All 264,732 old issue rows, in 35 title and status classes, have a disposition. They stay by old-release reference.

Value checks found 0 mismatches: 200 curated verdicts, 200 meeting dates, 200 video titles and 119 channel IDs.

## Open findings

- **45 meetings conflict on recordings.** The old completeness file says `recording=yes`, while coverage says `confirmed_absent` from a curated negative verdict. The old matcher lets strong evidence beat a negative verdict, and the native matcher arrives in R2.
- **Pending recording pairs exceed the plan.** 8,213 pairs are pending, against 6,108 expected. The reason code is assigned without checking each pair.

## Depends on `list_row` or document grouping

Rerun these after a rebuild: meeting transcripts, documents coverage, recording pairs and document-file accounting.

## What this cannot see

The ledger proves completeness, not that each reason is right. Natural keys can hide a wrong value, and name normalization can merge two different people.
