SELECT b.bill_id,v.vote_id,v.basis,v.chamber,v.date,v.question,v.result,v.yea,v.nay
FROM bills b,UNNEST(b.floor_votes) AS votes(v)
WHERE b.bill_id=? ORDER BY v.date,v.vote_id LIMIT 100