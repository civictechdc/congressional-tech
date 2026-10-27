# Recorded line-count corrections

These measured values correct mistaken line counts in earlier commit bodies; history is preserved. Behavioral test results are unchanged.

| Commit | File under congress_api | Before | After |
|---|---|---:|---:|
| `1aaffe75` | `retention/r2.py` | 581 | 579 |
| `1aaffe75` | `retention/body_store.py` | 201 | 251 |
| `1aaffe75` | `retention/body_keys.py` | 73 | 78 |
| `1aaffe75` | `retention/pipeline_raw.py` | 242 | 244 |
| `e1dfc758` | `retention/body_store.py` | 251 | 264 |
| `e1dfc758` | `retention/r2.py` | 579 | 580 |
| `e1dfc758` | `retention/pipeline_raw.py` | 244 | 245 |
| `7c5dc9f5` | `cli/raw_verify.py` | 81 | 81 |
| `7c5dc9f5` | `cli/raw_repair.py` | 57 | 59 |

`42eb6537` also contains the parent-authored `BodyStore.reference` implementation because two shared-index commits overlapped. Its contracts are `816afbbb`, and its accepted store/reference run passed 46 tests. Later commits use explicit-path `git commit --only`. No commit was rewritten.
