---
id: cef-157t
status: in_progress
deps: []
links: []
created: 2026-10-28T07:34:27Z
type: task
priority: 2
assignee: mikewolfd
---
# Retain reader fixture generation when the F0 converter is deleted

The hand-authored release builder currently lives in archive_release.py, so surviving reader/gate/metadata tests import the migration converter. Move the one fixture builder into a dedicated fixture module, retain the converter delegate until the switch, and verify the existing native release outcomes without changing format or SQL behavior.

