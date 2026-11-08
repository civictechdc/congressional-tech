# Congress Explorer 0.6.3 deployment

Congress Explorer 0.6.3 is published on PyPI, GitHub, the website and the hosted MCP service. The saved-PDF repair works through the deployed reader. The unfiltered ballot query still exceeds its ten-second deadline and remains open under `ct-m104`.

| Surface | Verified release |
| --- | --- |
| Package | `congress-mcp-v0.6.3`, source `75f2f7d42259f2fbfb796fdfd1293d139feb7047`; [publication workflow](https://github.com/civictechdc/congressional-tech/actions/runs/42473007248) passed |
| Website | Source `bf6455bf0be8489cb0f1192e0b36f5fcc37ec686`; [Pages run](https://github.com/civictechdc/congressional-tech/actions/runs/42473419368) passed; the served page links to all three 0.6.3 desktop/web downloads and the matching PyPI version |
| Hosted Worker | `1f976973-4cf0-4d7b-b467-d2a8098155c9` |
| Container image | `sha256:2d96dcf7aec3e6c1a3fd56cf069a169eefb9b52d281d702803dd7c50fcc73607`; both archive-specific replicas run application revision 5 |
| Archive | Unchanged: `5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1` |

The complete reader lane passed 217 tests with no skips. It reused three retained native fixtures. Fresh wheel installation and all three desktop launch configurations passed locally and in the Linux/macOS publication workflow. The actual container image has Explorer 0.6.3, pypdf 6.21.4, certifi 2026.10.23 and FastMCP 4.1.4.

The hosted official PDF for event 330080 returned its first window in 3.908 seconds; the committee PDF for event 100925 took 2.931 seconds. Both first and continued windows matched their retained originals, direct document reads agreed, and all four citations reopened with identical source, body, location and text digest. The Higgins witness occurrence and event 338785 caption citation also passed. These results complete `ct-4kuo`, `ct-irxg` and `ct-28tj` with their previously accepted scopes; caption publication is complete under `ct-9s7b`.

The first unfiltered ballot request failed at 10.114 seconds before any ballot-oracle query. Next and maximum-size pages were not attempted after that failure. Keyed Ackerman, an existing filtered cursor, changed-filter refusal and valid-empty results passed. The retained local speedup therefore does not establish usable unfiltered paging at the hosted quarter-vCPU limit.

The maintained smoke check first stopped at an HTTP 403 from its urllib readiness request. Using curl only for readiness let its unchanged assertions reach the legislative loop, where a query hit the deadline. Neither run passed. A separate control with two concurrent MCP sessions returned distinct parameterized SQL results successfully in 0.262 seconds. It establishes that transport control only.

The previous Worker `1d5dd704-046f-4704-b4be-3ab464637897` and image `sha256:556d1ff1dff5f272fe24ffd8bc4f5c2356c10986e241c2e904984b2df5591294` remain recorded with the same archive for rollback. Initial rollout traffic reached 0.6.2; final checks waited for both replicas at revision 5 and repeated 0.6.3 readiness responses.

Commands, package digests, test results, rollout metadata and exact hosted responses are retained in `.cache/archive-release/releases/congress-mcp-0.6.3-20261107/`. The combined hosted result is intentionally marked failed because its unfiltered ballot group failed; its six successful groups remain separately identified.

Separately merged producer dependency updates, four witness corrections and the House markup subject correction await their own scheduled-runtime or next-archive acceptance. This reader release did not rebuild or republish the archive.
