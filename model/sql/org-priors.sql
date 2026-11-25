-- Carry and emit 1-hop organization_redirects across releases (ct-6him).
-- Reads materialized org_priors_fresh plus current organizations and prior_organization_redirects.
-- Keeps every historical redirect pointing directly to the current live org_id in 1 hop.
WITH live_orgs AS (
 SELECT org_id FROM organizations
), restored_redirects AS (
 SELECT
  pr.old_org_id,
  pr.old_org_id AS org_id,
  cast('restored' AS VARCHAR) AS event,
  CASE
   WHEN pr.event='restored' THEN pr.release
   ELSE rm.release
  END AS release
 FROM live_orgs lo
 JOIN prior_organization_redirects pr ON pr.old_org_id=lo.org_id
 CROSS JOIN org_release_meta rm
), carried_non_live AS (
 SELECT pr.old_org_id,pr.org_id,pr.event,pr.release
 FROM live_orgs lo_self
 RIGHT ANTI JOIN prior_organization_redirects pr ON lo_self.org_id=pr.old_org_id
), carried_not_fresh AS (
 SELECT pr.old_org_id,pr.org_id,pr.event,pr.release
 FROM org_priors_fresh fg
 RIGHT ANTI JOIN carried_non_live pr ON fg.old_org_id=pr.old_org_id
), carried_redirects AS (
 SELECT
  pr.old_org_id,
  coalesce(f.org_id,lo_target.org_id) AS org_id,
  coalesce(f.event,pr.event) AS event,
  CASE
   WHEN f.old_org_id IS NOT NULL THEN rm.release
   ELSE pr.release
  END AS release
 FROM carried_not_fresh pr
 LEFT JOIN org_priors_fresh f ON f.old_org_id=pr.org_id
 LEFT JOIN live_orgs lo_target ON lo_target.org_id=pr.org_id
 CROSS JOIN org_release_meta rm
 WHERE coalesce(f.org_id,lo_target.org_id) IS NOT NULL
)
SELECT old_org_id,org_id,event,release FROM org_priors_fresh
UNION ALL
SELECT old_org_id,org_id,event,release FROM restored_redirects
UNION ALL
SELECT old_org_id,org_id,event,release FROM carried_redirects
