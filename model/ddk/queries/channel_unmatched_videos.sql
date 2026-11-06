SELECT v.video_key,v.title,v.published_at FROM videos v
WHERE v.handle=? AND NOT EXISTS (SELECT 1 FROM recording_matches m WHERE m.video_key=v.video_key)
ORDER BY v.published_at DESC NULLS LAST LIMIT 100