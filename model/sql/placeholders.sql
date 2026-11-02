-- DM 7.3. All capture modes contribute literal context addresses.
-- Over 100 distinct addresses needs over 100 rows, so only those bodies pay for distinct strings.
WITH candidate_placeholder_shas AS (
 SELECT sha256 FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING count(*)>100
)
SELECT c.sha256
FROM captures c JOIN candidate_placeholder_shas s ON c.sha256=s.sha256
GROUP BY c.sha256
HAVING count(DISTINCT c.context_url) > 100
