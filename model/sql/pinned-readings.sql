-- links is the widest column and its only reader, link-inputs, selects its own rows.
-- The small pin table comes first because the engine builds the hash table on the left.
SELECT r.* EXCLUDE(links) FROM parser_versions v JOIN readings r ON r.parser=v.parser AND r.parser_version=v.version
