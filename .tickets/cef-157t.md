---
id: cef-157t
status: closed
deps: []
links: []
created: 2026-10-28T07:34:27Z
type: task
priority: 2
assignee: mikewolfd
---
# Retain reader fixture generation when the F0 converter is deleted

The hand-authored release builder currently lives in archive_release.py, so surviving reader/gate/metadata tests import the migration converter. Move the one fixture builder into a dedicated fixture module, retain the converter delegate until the switch, and verify the existing native release outcomes without changing format or SQL behavior.


## Notes

**2026-10-28T08:06:37Z**

Binding 7a0c83c0 moves the single builder unchanged into archive_fixture.py; migration delegate remains until switch. Native fixture, reader, gate and metadata consumers pass within the 109-check focused group (36.30s/71cc6eb). CODE review c87f8643..d768355e APPROVE/no findings. archive_release wc-l 183 to127, new fixture63. No legacy source removed at switch.
