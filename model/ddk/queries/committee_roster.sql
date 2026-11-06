SELECT r.congress,r.system_code,c.name AS committee,r.bioguide_id,m.name,r.title,r.rank,r.party
FROM rosters r LEFT JOIN committees c USING (system_code) LEFT JOIN members m USING (bioguide_id)
WHERE r.system_code=? AND r.congress=? ORDER BY r.rank,r.bioguide_id LIMIT 100