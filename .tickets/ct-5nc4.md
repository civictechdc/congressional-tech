---
id: ct-5nc4
status: open
deps: []
links: []
created: 2026-11-11T01:05:10Z
type: bug
priority: 2
assignee: mikewolfd
---
# Hosted Explorer: first queries after a deploy exceed their deadline on a cold replica

After deploying release 77673bfb8fcf (version d1d22226, 2026-11-11 00:50Z), the smoke check failed twice in the first 10 minutes: get_member_ballots {'query': {'limit': 1}} 'Query exceeded its deadline; the query process was stopped' (00:59Z and 01:02Z), and once an httpx ReadError. A minute later the same call took 7.7 s and the full smoke passed (version 0.6.6, release 77673bfb8fcf; .cache/archive-release/hosted-explorer-20261111/smoke-77673bfb8fcf.json.txt). get_hearing_bundle also takes 8.2 s warm. So a client that arrives right after a deploy, or on a newly woken replica, gets errors on the largest tables (member_votes). Fix options: warm the replica before it reports ready (read member_votes once in start.sh or the readiness probe), or give the first read of a table a longer deadline. Measure the cold read time on the basic instance first.

