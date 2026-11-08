# Congress Explorer 0.6.4 deployment

Congress Explorer 0.6.4 is published on PyPI, GitHub, the website and both hosted replicas. The first unfiltered ballot request now completes within the existing ten-second deadline. The archive remains `5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1`.

| Hosted request | Elapsed time | Result |
| --- | ---: | --- |
| First unfiltered page | 7.115 seconds | Matched retained rows |
| Next page | 7.961 seconds | Matched retained rows |
| Maximum page, 100 rows | 6.894 seconds | All rows matched |

The first ballot request preceded every overview or live oracle query. Both older cursors resumed correctly; the keyed query, changed-filter refusal and valid-empty result also passed. Version 0.6.3 had timed out on its first unfiltered request at 10.114 seconds. These observations cover early pages under the unchanged quarter-vCPU, 1 GiB and ten-second limits. They do not establish deep-offset performance or latency under sustained concurrent load.

The final reader lane passed **221 tests with no skips**, including retained native fixtures and pinned Poppler checks. Fresh wheel installation and all three desktop launch configurations passed. The [publication workflow](https://github.com/civictechdc/congressional-tech/actions/runs/42476844188) passed Linux/macOS installation, PyPI publication and fresh package checks. The [Pages run](https://github.com/civictechdc/congressional-tech/actions/runs/42477367271) passed, and the served setup page links to all three 0.6.4 downloads and the matching PyPI version.

The source tag `congress-mcp-v0.6.4` names `f2dd37fc3e712321e495971752f4200668fb91e3`; the reader subtree is `c44899fdcc49390b3aab173405fda6a209c8a41d`. Worker `5a6a2351-c4c8-4d3b-8714-a34fff894ebc` runs image `sha256:5cd350a5d0f487ef2727e00c70ec73cfe07c6bf804deca6c4f095c6befdf1b6e`. Both archive-specific replicas run application revision 6. An isolated check of the actual image confirmed version 0.6.4 and exact repaired reader bytes. The previous 0.6.3 Worker and image remain recorded for rollback.

The maintained hosted smoke also passed, including two concurrent clients and all 18 tools invoked. Its ballot request took 7.092 seconds. Read-only SQL, document citations, the hearing dossier and transcript checks passed. The generic event probe selected no retained cue, and corpus text search correctly remained unavailable, so its `research_qualified` flag remains false. The prior exact caption acceptance carries forward. Only the readiness transport used curl; the maintained assertions were unchanged.

Evidence is under `.cache/archive-release/releases/congress-mcp-0.6.4-20261108/`. The ballot result SHA-256 is `bf9e3a2d1cadfb8dc7b91e0cc1313b16dd41a9d525bd14a4a0138fbc9e74c398`; the maintained smoke result is `498964bcf1971d8524d33e1a6035d2696ef95c5aeeaac25e32b58257800257bc`. The release branch was merged and pruned; the immutable tag is retained. `ct-m104` remains open for the separate `ct-gi01` preservation and `ct-082q` source/publication obligations. This reader release did not rebuild or republish the archive.
