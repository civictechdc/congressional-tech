# Congress.gov detail reads

`meetings.parquet.congress_gov_detail_observation` tells a reader what the
selected release inputs establish about this event's Congress.gov detail reads.
It does not describe complete acquisition history.

| State | Meaning within those inputs |
| --- | --- |
| `successful` | At least one qualified detail read exists. |
| `failed` | A detail attempt failed, with no qualified success or uncertain detail response. |
| `listing_only_in_scope` | A qualified listing contains this meeting, with no detail attempt in scope. |
| `unknown` | Coverage or evidence cannot support a stronger statement. |

`successful_read` contains one successful observation's requested address,
retrieval time, receipt key, one-based receipt line, capture index, response body
digest and reader versions. All fields come from the same bound observation.
`latest_attempt` records the selected detail attempt's evidence, qualification
state, raw outcome and HTTP status. A later failed attempt does not erase an
earlier success. `listing` retains the listing evidence when available.

Each selection uses the latest dated observation and then receipt location to
break ties. An undated observation remains undated. `has_undated_attempt` warns
that the selected dated attempt cannot be called chronologically latest across
all observations. With no qualified evidence, the object states `unknown` and
its evidence objects are null.

The successful receipt must name an exact Congress.gov API detail route, return
to that same route, and bind a completed successful response to a selected
meeting record with the same Congress, chamber and event. A selected appearance
record with that body digest must also identify the same event. The qualified
appearance reader rejects listing responses, even single-item lists. Its exact
version is named in `model/sql/meeting-detail-evidence.sql`; its version includes
the shared staging code, which supplies no fallback event identifier. Other
reader versions remain unqualified until their behavior is checked. Empty or
omitted witnesses do not prevent a successful detail observation.

Listings require the corresponding successful listing route and same-body
meeting and detail-only reader evidence. Missing detail evidence alone never
proves a listing-only state. Legacy saved records without a bound fetch remain
unknown. A missing chamber remains unknown, including the current meeting
reader's treatment of `NoChamber`; the route does not fill that source fact.

`congress_gov_updated` remains Congress.gov's publisher update time.
`retrieved_at` is the archive receipt's retrieval time. The SpicyRegs attempt
journal's `recorded_at` is a third clock, supplied only by that journal. None
substitutes for another.

The `ct-r4rd` comparison should pin its actual
`committee_meetings_detail_reads.parquet` journal alongside its meeting inputs,
join on Congress, chamber and event, and retain journal generation, attempt ID,
outcome, `recorded_at`, field states and response witnesses. Compare the
observations each input supports; independent fetches need not have equal
timestamps or response digests. Reading this observation does not establish
field parity or authorize SpicyRegs retirement.
