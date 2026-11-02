-- links is the widest column and its only reader, link-inputs, selects its own rows.
-- selected_readings is the one readings selection: pins plus registry-covered older rows.
SELECT r.* EXCLUDE(links) FROM selected_readings r
