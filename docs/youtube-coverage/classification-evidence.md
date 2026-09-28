# Meeting and committee classifications

The Explorer keeps original source values alongside the categories used for search. A category derived from a title retains the title as field evidence. Unknown means the retained evidence does not support a classification.

## Meeting type and access

Specific Congress.gov types take precedence. A generic `Meeting` remains Meeting unless the title explicitly names the proceeding, such as “Closed briefing” or “Business meeting.” A title about authorizing a future briefing does not make the current meeting a briefing. A business meeting followed by a briefing remains a business meeting.

The September 28, 2026 audit covered all 18,139 retained meetings from Congresses 112–119. Of 369 titles containing “briefing,” the rules classify 317 as briefings, retain 26 as business meetings and 25 as hearings, and keep one resolution authorizing a later proceeding as Meeting.

| Search type | Meetings |
| --- | ---: |
| Hearing | 13,891 |
| Markup | 1,849 |
| Business meeting | 1,050 |
| Meeting | 1,030 |
| Briefing | 317 |
| Field hearing | 2 |

Access uses explicit source phrases: Open, Closed, or Partly closed. It does not infer public access from the absence of “closed.” Topic phrases such as “Open Skies Treaty” and “Closed School Discharge” are not access declarations. A later closed session alone does not establish access to the main proceeding. Nonstandard phrases can still remain unknown.

| Access | Meetings |
| --- | ---: |
| Open | 269 |
| Closed | 673 |
| Partly closed | 21 |
| Unknown | 17,176 |

These counts describe the retained snapshot, not the complete upstream population. Regression cases live in `tests/test_explorer_meeting_classification.py`.

## Committee categories and hierarchy

The collector retains [Congress.gov’s Congress-scoped committee lists](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md), including exact `committeeTypeCode`, `parent`, name, system code, source URL, and retrieval time. The September 28 snapshot contains 2,044 committee terms across Congresses 112–119. Three additional terms occur only in meeting records, so the combined catalog has 2,047 terms. Those three retain unknown taxonomy.

The normalized categories are Standing, Select, Special, Joint, Subcommittee, Commission or Caucus, Task Force, Other, and Unknown. Original `committeeTypeCode` remains available as `source_committee_type` and in inline source evidence.

Committee level is separate from committee type. Explicit parent links take precedence over the documented system-code convention, including the few child committees whose codes end in `00`. A child's specific category, such as Task Force, remains its search category. A generic Subcommittee inherits its parent's category for filtering while retaining its original source category. Names alone do not establish taxonomy.

The weekly collector refreshes the latest two retained Congresses and missing historical Congresses. It saves metadata separately on `pipeline-data`; the offline exporter does no acquisition. An empty or failed refresh leaves the saved snapshot unchanged.
