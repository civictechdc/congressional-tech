-- Sitting Members of Congress acting officially are Member appearances, not witnesses (ct-kw85, owner decisions
-- 2026-11-10). A witness row is a Member appearance when it names a Member in office on the hearing date, as
-- match_basis records:
--  publisher_id  the publisher's Bioguide ID (house_xml) of a Member with a term covering the date;
--  name_state    family name and first name agree (witness_member_candidates) with a Member whose covering term's
--                state the row names, and the row names a chamber, a role, or only Congress and places;
--  name_chamber  ...whose covering term's chamber the row names ('U.S. Senator', 'Representative in Congress',
--                '(NM-01)', 'Rep.'), or Congress ('Member of Congress'), and no state;
--  name_role     ...the row opens a field with a congressional role or names a commission on which Members serve as
--                Members (the congressional_commissions registry), names no state, and the first name agrees in full;
--  seat          the row states a House seat (a state and district, a state at large, or a territory's Delegate or
--                Resident Commissioner) and a word of its name or first field is the family name of the Member
--                holding that seat on the date (witness_member_seats);
--  initial       the row states a congressional office and a state, and one side of the first name is a bare initial
--                ('C. Cox', 'JD Vance') of the only Member sitting in that chamber and state with that family name and
--                initial on the date (witness_member_decisions);
--  member_day    the row is a name alone at a hearing whose title says Member Day (not 'Former Members Day') and its
--                family and first name agree with exactly one Member sitting on the date;
--  group         another row of the same appearance (witness_precedence) matched.
-- A matched appearance one of whose rows says 'opening statement' by a Member the rosters seat on the hearing's
-- committee or its parent (witness_member_committees) is a committee member's own opening statement: outcome
-- 'statement', published as member_statement with the matched Member (owner decision 2026-11-10).
-- The row's own words keep it a witness when it says former or gives a closed span of years, names a state
-- legislature, a House or Senate officer or staffer, or 'Representative of' an organization. Several fitting Members
-- leave it 'ambiguous' unless an equal first name singles one out; the hearing's own nominee is 'nominee'. Either
-- keeps the whole appearance a witness, as do two different Members in one appearance. bioguide_id stays the
-- publisher's; the matched Member is published as matched_bioguide_id with match_basis. Nothing here feeds
-- witness_precedence, appearance_people or document matching, so no key or link moves.
WITH group_members AS (
 SELECT person,bioguide_id,bool_or(outcome='nominee') AS nominee FROM witness_member_decisions WHERE outcome IN ('member','nominee')
 GROUP BY person,bioguide_id
), groups AS (
 SELECT person,count(bioguide_id) AS members,min(bioguide_id) AS bioguide_id,bool_or(nominee) AS nominee
 FROM group_members GROUP BY person
), resolved AS (
 SELECT f.id AS witness_key,f.person,d.outcome AS own_outcome,d.basis AS own_basis,g.person AS group_person,g.members,g.nominee,g.bioguide_id
 FROM groups g RIGHT JOIN (witness_member_decisions d RIGHT JOIN (SELECT id,person FROM witness_member_facts WHERE side='witness') f
  ON d.witness_key=f.id) ON g.person=f.person
 WHERE d.witness_key IS NOT NULL OR g.person IS NOT NULL
), outcomes AS (
 SELECT witness_key,person,own_basis,bioguide_id,own_outcome,
  CASE WHEN group_person IS NULL THEN own_outcome
   WHEN nominee THEN CASE WHEN own_outcome='member' THEN 'nominee' ELSE own_outcome END
   WHEN members>1 THEN CASE WHEN own_outcome='member' THEN 'ambiguous' ELSE own_outcome END
   ELSE 'member' END AS outcome
 FROM resolved
)
SELECT o.witness_key,CASE WHEN o.outcome='member' AND c.person IS NOT NULL THEN 'statement' ELSE o.outcome END AS outcome,
 CASE WHEN o.outcome='member' THEN o.bioguide_id END AS matched_bioguide_id,
 CASE WHEN o.outcome='member' THEN CASE WHEN o.own_outcome='member' THEN o.own_basis ELSE 'group' END END AS match_basis
FROM witness_member_committees c RIGHT JOIN outcomes o ON c.person=o.person AND c.bioguide_id=o.bioguide_id
WHERE o.outcome IS NOT NULL
