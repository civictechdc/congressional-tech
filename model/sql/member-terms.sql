-- Each Member's terms in office, parsed once from spicy-regs member terms. The members export lists them and
-- witness_members (ct-kw85) reads them to decide who held office on a hearing date.
SELECT bioguide_id,
 CASE lower(trim(term_type))
  WHEN 'rep' THEN 'house'
  WHEN 'sen' THEN 'senate'
  ELSE lower(nullif(trim(term_type),''))
 END AS chamber,
 nullif(trim(term_state),'') AS state,
 try_cast(term_district AS SMALLINT) AS district,
 nullif(trim(term_party),'') AS party,
 try_cast(term_start AS DATE) AS start_date,
 try_cast(term_end AS DATE) AS end_date
FROM spicy_member_terms WHERE bioguide_id IS NOT NULL
