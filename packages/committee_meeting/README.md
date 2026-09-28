# Committee Meeting data model

An executable, versioned metadata model for the Congressional Committee
Explorer. It covers meetings, committee terms, witness appearances, materials,
file formats, amendments, votes, provenance and coverage.

Start with the [model proposal](src/committee_meeting/MODEL.md), including its
relationship diagram, source mappings, identity rules, known gaps and adoption
sequence. The Python definitions live beside it in `src/committee_meeting/`.

The central distinctions are:

- A meeting can have several dated occurrences and convening committees.
- An appearance preserves its recorded name and affiliation without requiring
  a globally resolved person.
- A material can have several revisions and file formats, serve several
  meetings, or remain unlinked.
- A transcript can exist independently of a recording.
- Availability findings retain evidence, scope and dates; an inference does
  not imply captured text.
- Data issues make missing expectations, unperformed checks, conflicts, errors,
  stale inputs and correction history explicit. No open issues does not mean complete.

The [Congress API integration design](CONGRESS_API_INTEGRATION.md) describes
source-owned adapters, producing-code repairs and adoption. The
[execution receipt](INTEGRATION_EXECUTION.md) records implementation and checks.

Pydantic models validate individual records. `Catalog` additionally checks
references, identity uniqueness and relationship consistency. Generate JSON
Schema from those same definitions. Source adapters stay in their owner packages;
publication stays in the application. This package performs no network operations.

From the repository root, with Python 3.12+ and the package dependency installed:

```sh
PYTHONPATH=packages/committee_meeting/src .venv/bin/python -m unittest discover -s packages/committee_meeting/tests -v
PYTHONPATH=packages/committee_meeting/src .venv/bin/python -m committee_meeting.main > /tmp/committee-meeting.schema.json
PYTHONPATH=packages/committee_meeting/src .venv/bin/python packages/committee_meeting/examples/worked_catalog.py > /tmp/committee-meeting.example.json
```

The example is synthetic; tests also include a small retained House XML fixture.
This model supersedes the package's initial four-entity sketch. The
[original private design document](https://civictechdc.slack.com/docs/T02GC3VEL/F09N31638MQ)
remains a historical reference; its contents were not reviewed for this draft.
