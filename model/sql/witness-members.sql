-- Sitting Members of Congress acting officially are Member appearances, not witnesses (ct-kw85, owner decisions
-- 2026-11-10). A witness row is a Member appearance when it names a Member in office on the hearing date, as
-- match_basis records:
--  publisher_id  the publisher's Bioguide ID (house_xml) of a Member with a term covering the date;
--  name_state    family name and first name agree (witness_member_candidates) with a Member whose covering term's
--                state the row names, and the row names a chamber, a role, or only Congress and places;
--  name_chamber  ...whose covering term's chamber the row names ('U.S. Senator', 'Representative in Congress',
--                '(NM-01)', 'Rep.'), or Congress ('Member of Congress'), and no state;
--  name_role     ...the row opens a field with a congressional role, names no state, and the first name agrees in full;
--  group         another row of the same appearance (witness_precedence) matched.
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
 SELECT f.id AS witness_key,d.outcome AS own_outcome,d.basis AS own_basis,g.person AS group_person,g.members,g.nominee,g.bioguide_id
 FROM groups g RIGHT JOIN (witness_member_decisions d RIGHT JOIN (SELECT id,person FROM witness_member_facts WHERE side='witness') f
  ON d.witness_key=f.id) ON g.person=f.person
 WHERE d.witness_key IS NOT NULL OR g.person IS NOT NULL
), outcomes AS (
 SELECT witness_key,own_basis,bioguide_id,own_outcome,
  CASE WHEN group_person IS NULL THEN own_outcome
   WHEN nominee THEN CASE WHEN own_outcome='member' THEN 'nominee' ELSE own_outcome END
   WHEN members>1 THEN CASE WHEN own_outcome='member' THEN 'ambiguous' ELSE own_outcome END
   ELSE 'member' END AS outcome
 FROM resolved
)
SELECT witness_key,outcome,
 CASE WHEN outcome='member' THEN bioguide_id END AS matched_bioguide_id,
 CASE WHEN outcome='member' THEN CASE WHEN own_outcome='member' THEN own_basis ELSE 'group' END END AS match_basis
FROM outcomes WHERE outcome IS NOT NULL
