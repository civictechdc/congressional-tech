-- Published recovery rejections so Gate 2 proves corrected dead-link answers without a hand list (ct-faan)
-- and readers can see which wrong recovered copy was rejected for an address and when.
SELECT nullif(trim(original_url),'') AS original_url,
 CASE WHEN regexp_like(coalesce(body_sha256,''),'^[0-9a-fA-F]{64}$')
      THEN arrow_cast(decode(lower(body_sha256),'hex'),'FixedSizeBinary(32)') END AS rejected_body,
 nullif(trim(id),'') AS decision_id,
 arrow_cast(try_cast(decided_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS decided_at,
 nullif(trim(recovered_url),'') AS recovered_url,
 nullif(trim(identity_note),'') AS identity_note
FROM remaining_recovery_decisions
WHERE kind='rejected'
