---
id: cef-96wc
status: closed
deps: []
links: [ct-klyz, ct-4jms, ct-5kto, ct-77zb, cef-jh7i, ct-t906]
created: 2026-10-28T05:00:43Z
type: task
priority: 1
assignee: mikewolfd
---
# Prepare the engine-first cut-over checklist

Record ordered owner cut-over gates, exact plan commands, rollback and deletion preparation without disabling live capture or deleting imported code.


## Notes

**2026-10-30T14:32:32Z**

Synced with master epic ct-77zb: remaining operational cut-over tasks are tracked in ct-klyz (B14 live run & remove weekly meeting job), ct-4jms (capture-archive.yml live run against url_state.parquet), ct-z5cc (Cloudflare origin rules via Wrangler/Terraform), and ct-5kto (F5 18-group legacy code deletion).

**2026-10-30T17:46:00Z**

Closed: all linked engine-first cut-over checklist items (ct-klyz in c5297fa7, ct-4jms in 602556b4, ct-z5cc in e67d9a77, cef-jh7i in f619d529, ct-t906 in b752bc9a, and ct-5kto F5 18-group deletions in 703a5920..32a1a3c6) are completed and verified on main.
