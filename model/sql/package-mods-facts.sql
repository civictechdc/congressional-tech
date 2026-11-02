-- What each package's own MODS states about its meetings (<eventId>, parsed into page_facts.named_meetings).
-- page_facts is already one pinned reading per body, so this aggregates the small MODS side only.
SELECT nullif(trim(r.package_id),'') AS package_id,
 array_sort(array_distinct(flatten(array_agg(p.named_meetings)))) AS named_meetings
FROM selected_appearance_records r
JOIN page_facts p ON p.body_sha=arrow_cast(decode(r.record_sha_hex,'hex'),'FixedSizeBinary(32)')
WHERE r.source='mods' AND r.status='completed' AND nullif(trim(r.package_id),'') IS NOT NULL
 AND p.status='completed' AND p.named_meetings IS NOT NULL
GROUP BY 1
