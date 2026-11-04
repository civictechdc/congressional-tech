WITH remaining AS (
 SELECT r.* FROM recovery_decisions r WHERE NOT EXISTS (
 SELECT 1 FROM recovery_decisions s WHERE s.supersedes=r.id)
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY lower(body_sha256),original_url
 ORDER BY cast(decided_at AS TIMESTAMP WITH TIME ZONE) DESC,id DESC) AS selected FROM remaining
)
-- corpus_recovery.reconcile writes this note into immutable raw receipts; it only restates
-- evidence_sha256 and does not explain how the recovery relates to the original.
SELECT * EXCLUDE(identity_note),
 CASE WHEN identity_note='Reconciled from pinned accepted mappings '||evidence_sha256||'; receipt categories preserved'
 THEN NULL ELSE identity_note END AS identity_note
FROM ranked WHERE selected=1
