-- ct-kw85: the witness rows the place, seat, tier and decision steps read, once: eligible rows with a sitting
-- candidate (witness_member_candidates) or that may state a House seat (witness_member_facts.seat_cue), with their
-- own words. Its own step: witness_member_mentions reads it three times.
SELECT f.id AS witness_key,f.person,f.chamber,f.says_role,f.says_nominee,f.member_day_name_only,f.full_text,f.field_text,f.raw_text,
 f.seat_words,f.dates
FROM (SELECT DISTINCT witness_key FROM witness_member_candidates) c RIGHT JOIN witness_member_facts f ON f.id=c.witness_key
WHERE f.eligible AND (c.witness_key IS NOT NULL OR f.seat_cue)
