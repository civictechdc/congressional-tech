# Historical committee rosters (113–118): source and owner

Decided for ct-8cno on 2026-11-08 and handed to spicy-stack ss-ehci. Evidence and manifest:
`.cache/archive-release/investigations/rosters-113-118-20261108/` in the main checkout. The ss-ehci
plan and reader patch are in `data/ss-ehci-cdir-plan.md` and `data/ss-ehci-cdir-reader.patch`.

## Source

The GovInfo Congressional Directory (collection CDIR) has one package per Congress: 113 is
CDIR-2014-02-18, 114 is 2016-02-12, 115 is 2018-07-27 and 2018-10-01, 116 is 2020-07-22, 117 is
2022-10-26 and 118 is 2024-04-25. Each package prints House, Senate and joint committee and
subcommittee lists. The package MODS states the Congress and each member's bioguide ID.

Wayback copies of the chamber files the roster builder reads today cannot fill the gap. House
`MemberData.xml` captures start in June 2015, so the 113th is missing. Senate
`cvc_member_data.xml` states no Congress and lists no subcommittees.

Limits:

- Each Congress is one dated snapshot, so changes during the Congress are invisible.
- Rank is the printed order within the majority or minority column.
- The ranking member is usually inferred as the first minority entry.
- Ex officio members appear only where printed.
- Some printed lists are stale. The 117th Senate Appropriations list still names Tom Udall.

## Owner

SpicyRegs owns the work. It already supports CDIR, owns `committee_assignments`, owns the
committee name history used to map printed names to `system_code`, and holds the raw store. This
repository adds no CDIR reader.

`model/sql/entity-rosters.sql` already keeps each source Congress and deduplicates on
`(congress, system_code, bioguide_id)`. Once ss-ehci publishes the history generation,
congressional-tech has these steps: pin it, run the key checks and
`scripts/measure/roster_history_raw_check.py`, describe the per-Congress source and limits in
the schema docs, publish, and query the installed `committee_roster` recipe for 116, 117 and 118.

## Prototype validation

`roster_history_raw_check.py` compares each committee's members in both directions against a
second publisher's record. Results on the prototype parse:

| Congress | Independent record | Committees | Seat agreement | Chairs |
|---|---|---|---|---|
| 117 House | Clerk MemberData.xml (2022-11-01) | 127 | 0.993 | 123/123 |
| 117 Senate | cvc_member_data.xml (2022-09-20) | 18 | 0.985 | 18/18 |
| 113 both | congress-legislators `committee-membership-current.yaml` (2014-02-13) | 205 | 0.964 | 200/203 |

As a planted test, the House Agriculture chair was swapped with the ranking member and one
subcommittee seat was removed. The check flagged both.
