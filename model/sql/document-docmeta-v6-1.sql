-- Join materialized docmeta_v6_1 records onto the release's details keys.
-- Small docmeta_v6_1_unified table stays on the inner join's build side.
SELECT
    d.list_row,
    u.link_key,
    u.doc_key,
    u.saved_body,
    coalesce(u.package_id, d.package_id) AS package_id,
    u.disposition,
    u.sub_disposition,
    u.v6_route,
    u.docmeta_source,
    u.resolution_state,
    u.is_alias,
    u.canonical_link_key,
    u.canonical_doc_key,
    u.canonical_partition_bucket,
    u.canonical_v6_route,
    u.filename,
    u.effective_format,
    u.primary_kind,
    u.status,
    u.congress,
    u.chamber,
    u.committees,
    u.docmeta_json,
    u.strict_v4_valid
FROM docmeta_v6_1_unified u
JOIN (SELECT list_row, doc_key, link_key, saved_body, package_id FROM details) d
  ON u.link_key = d.link_key AND u.doc_key = d.doc_key
ORDER BY d.list_row
