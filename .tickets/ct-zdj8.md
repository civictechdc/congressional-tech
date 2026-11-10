---
id: ct-zdj8
status: open
deps: []
links: []
created: 2026-11-10T19:45:31Z
type: task
priority: 2
assignee: mikewolfd
---
# New recordings cannot be traced to their page from the release's kept evidence

On candidate 77673bfb8fcf (2026-11-10), 83 of 118 new no-meeting YouTube recordings had no row in the kept evidence table publisher_links, though their pages were fetched that day and hold the links as ordinary anchors (youtube.com/watch, youtu.be) and embedded players; 35 others on similar pages do have rows. The gate reports these groups as 'source not traced', and attributing them took a read of raw page bodies (.cache/archive-release/release-20261110b/trace-recordings.json). Find why publisher_links omits these video links, and either keep the link that produced each recording in the evidence or give the gate the page for each new recording, so the group can carry an automatic cause on unattended nights.

