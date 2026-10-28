WITH records AS (SELECT unnest(recoveries) AS r FROM accepted_input), flat AS (
 SELECT r['body_key'] AS body_key,r['kind'] AS format,r['original_url'] AS original_url,
 r['recovered_url'] AS recovered_url,r['recovery_basis'] AS recovery_basis,r['recovery_status'] AS recovery_status FROM records
)
SELECT f.*,k.kind,
 encode(sha256(json_array(f.body_key,f.original_url,f.recovered_url,f.recovery_basis,f.recovery_status)),'hex') AS recovery_key,
 array_element(regexp_match(f.body_key,'([a-f0-9]{64})'),1) AS body_hex
FROM flat f LEFT JOIN recovery_kinds k ON f.recovery_basis=k.category OR f.recovery_basis=k.match_basis
