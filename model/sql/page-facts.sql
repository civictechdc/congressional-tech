SELECT r.* EXCLUDE(links) FROM sniff_facts s JOIN pinned_readings r ON r.body_sha=s.body_sha AND r.parser=s.format
WHERE r.parser IN ('html','xml','json')
