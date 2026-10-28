SELECT r.* FROM pinned_readings r JOIN sniff_facts s ON r.body_sha=s.body_sha AND r.parser=s.format
WHERE r.parser IN ('html','xml','json')
