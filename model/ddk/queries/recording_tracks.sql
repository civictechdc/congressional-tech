SELECT r.video_key,hex(t.body) AS body,t.suffix,t.format,t.language,t.production
FROM recordings r,UNNEST(r.tracks) AS tracks(t)
WHERE list_contains(r.event_ids,CAST(? AS BIGINT)) ORDER BY r.video_key,t.language,t.format LIMIT 100