# Current rich reader fixture inputs

The nine small Arrow IPC schemas retain the exact native-inferred output types
from the full application JobSpec. `schemas.json` identifies the original job,
observation and each byte digest. That observation established schema inference
only; it did not admit sources or execute the model.

`packages/viewer_publication/tests/archive_entity_fixture.py` authors synthetic
current records with these physical types. It writes input tables before the
retained native job runs. The native job constructs every release file, runs the
current DDK-derived checks and supplies the actual candidate evidence. No old
release payload or manifest is copied or patched into this fixture.

The cases cover meeting materials, occurrence-level witnesses, historical
committee names, subcommittees, rosters, members, bill and nomination details,
caption tracks and document cross-filtering. They use current physical fields;
presentation labels and citations remain consumer behavior.
