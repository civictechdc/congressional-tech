-- What each package's own MODS states: the meetings it names (<eventId>, parsed into
-- page_facts.named_meetings), the days it was held (<heldDate>) and its published title.
-- page_facts is already one pinned reading per body, so this aggregates the small MODS side only.
SELECT nullif(trim(r.package_id),'') AS package_id,
 array_sort(array_distinct(flatten(array_agg(coalesce(p.named_meetings,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')))))) AS named_meetings,
 array_sort(array_distinct(flatten(array_agg(coalesce(r.held_dates,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')))))) AS held_dates,
 max(r.title) AS title
FROM selected_appearance_records r
LEFT JOIN page_facts p ON p.body_sha=arrow_cast(decode(r.record_sha_hex,'hex'),'FixedSizeBinary(32)') AND p.status='completed'
WHERE r.source='mods' AND r.status='completed' AND nullif(trim(r.package_id),'') IS NOT NULL
GROUP BY 1
