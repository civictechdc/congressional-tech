SELECT n.nomination_id,v.vote_id,v.date,v.question,v.result,v.yea,v.nay
FROM nominations n,UNNEST(n.floor_votes) AS votes(v)
WHERE n.nomination_id=? ORDER BY v.date,v.vote_id LIMIT 100