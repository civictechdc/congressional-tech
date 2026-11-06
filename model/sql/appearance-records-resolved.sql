WITH ranked_context_observations AS (
 SELECT *,
  row_number() OVER(
   PARTITION BY occasion,source,context_key,coalesce(package_id,'')
   ORDER BY (effective_state IN ('present','empty')) DESC,(effective_state='absent') ASC,updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,(effective_state='present') DESC,record_sha_hex ASC
  ) AS ctx_rn
 FROM appearance_observations WHERE observation_eligible
), current_context_observations AS (
 SELECT *
 FROM ranked_context_observations
 WHERE ctx_rn=1
), superseded_source_bodies AS (
 SELECT DISTINCT old.occasion,old.source,old.record_sha_hex
 FROM ranked_context_observations old
 JOIN current_context_observations cur
  ON old.occasion=cur.occasion AND old.source=cur.source AND old.context_key=cur.context_key
  AND coalesce(old.package_id,'')=coalesce(cur.package_id,'')
 WHERE old.ctx_rn>1 AND old.record_sha_hex<>cur.record_sha_hex
), ranked_source_observations AS (
 SELECT c.*,
  -- One current body per print: several prints that stand for one meeting each keep their witnesses.
  row_number() OVER(
   PARTITION BY c.occasion,c.source,coalesce(c.package_id,'')
   ORDER BY (c.effective_state IN ('present','empty')) DESC,(c.effective_state='absent') ASC,(sb.record_sha_hex IS NOT NULL) ASC,c.updated DESC NULLS LAST,c.retrieved_at DESC NULLS LAST,(c.effective_state='present') DESC,c.record_sha_hex ASC,c.context_key ASC
  ) AS obs_rn
 FROM current_context_observations c
 LEFT JOIN superseded_source_bodies sb
  ON c.occasion=sb.occasion AND c.source=sb.source AND c.record_sha_hex=sb.record_sha_hex
), current_source_observations AS (
 SELECT *
 FROM ranked_source_observations
 WHERE obs_rn=1
), ranked_sources AS (
 -- One window over the occasion, as before: the lowest code is 2*priority for a present top source and
 -- 2*priority-1 when a top-priority body states none or failed. Joins or repeated references to these
 -- rows, which carry their appearance lists, made the engine sort them again.
 SELECT *,first_value(CASE WHEN effective_state='present' THEN 2*priority ELSE 2*priority-1 END) OVER(
  PARTITION BY occasion ORDER BY CASE WHEN effective_state='present' THEN 2*priority ELSE 2*priority-1 END ASC) AS top_code
 FROM current_source_observations
 WHERE effective_state IN ('present','empty','unresolved')
), selected_observations AS (
 -- When the top-ranked source lists witnesses, every source's current body publishes and precedence is
 -- per person, not per source (red-f2): a lower row is superseded only by the same person from a
 -- higher-ranked body. A top source that states none or failed still blocks lower fallback (ct-30fp).
 SELECT * FROM ranked_sources
 WHERE effective_state='present' AND (top_code%2=0 OR 2*priority-1=top_code)
), unnested_occurrences AS (
 SELECT
  s.record_sha_hex,
  s.source,
  s.occasion,
  s.context_key,
  s.event_id,
  s.package_id,
  s.page_url,
  s.resolved_base,
  s.priority,
  unnest(r.appearances) AS a,
  unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM selected_observations s
 -- (record_sha_hex,source) is the selected records' key: one pinned version per body and parser.
 JOIN selected_appearance_records r ON r.record_sha_hex=s.record_sha_hex AND r.source=s.source
 WHERE r.appearances IS NOT NULL AND coalesce(array_length(r.appearances),0)>0
), extracted_occurrences AS (
 SELECT
  record_sha_hex,
  source,
  occasion,
  context_key,
  event_id,
  package_id,
  page_url,
  resolved_base,
  priority,
  ordinal,
  coalesce(nullif(trim(a['source_locator']),''),source||':witness['||cast(ordinal+1 AS VARCHAR)||']') AS source_locator,
  nullif(trim(a['name_key']),'') AS name_key,
  nullif(trim(a['name']),'') AS name,
  nullif(trim(a['honorific']),'') AS honorific,
  nullif(trim(a['given']),'') AS given,
  nullif(trim(a['middle']),'') AS middle,
  nullif(trim(a['family']),'') AS family,
  nullif(trim(a['suffix']),'') AS suffix,
  nullif(trim(a['position']),'') AS position,
  nullif(trim(a['organization']),'') AS organization,
  nullif(trim(a['on_behalf_of']),'') AS on_behalf_of,
  nullif(trim(a['location']),'') AS location,
  nullif(trim(a['panel']),'') AS panel,
  cast(a['panel_order'] AS SMALLINT) AS panel_order,
  cast(a['display_order'] AS SMALLINT) AS display_order,
  nullif(trim(a['witness_type']),'') AS witness_type,
  a['testified'] AS testified,
  nullif(trim(a['bioguide_id']),'') AS bioguide_id,
  a['document_links'] AS document_links
 FROM unnested_occurrences
), with_witness_key AS (
 SELECT
  substr(encode(sha256(json_array('witness-occurrence-v2',occasion,source,record_sha_hex,source_locator,context_key)),'hex'),1,16) AS witness_key,
  *
 FROM extracted_occurrences
), raw_link_rows AS (
 SELECT
  witness_key,
  resolved_base,
  unnest(document_links) AS raw_link,
  unnest(range(0,cast(array_length(document_links) AS BIGINT))) AS link_idx
 FROM with_witness_key
 WHERE document_links IS NOT NULL AND coalesce(array_length(document_links),0)>0
), resolved_link_rows AS (
 SELECT
  witness_key,
  link_idx,
  CASE
   WHEN resolved_base IS NOT NULL THEN url_resolve(trim(raw_link),resolved_base)
   WHEN regexp_like(trim(raw_link),'(?i)^https?://') THEN trim(raw_link)
  END AS resolved_url
 FROM raw_link_rows
 WHERE raw_link IS NOT NULL AND trim(raw_link)<>''
), aggregated_links AS (
 SELECT
  witness_key,
  array_agg(resolved_url ORDER BY link_idx) AS document_urls
 FROM resolved_link_rows
 WHERE resolved_url IS NOT NULL AND regexp_like(resolved_url,'(?i)^https?://')
 GROUP BY witness_key
)
SELECT
 w.witness_key,
 w.occasion,
 w.source,
 arrow_cast(decode(w.record_sha_hex,'hex'),'FixedSizeBinary(32)') AS record_sha,
 w.record_sha_hex,
 w.source_locator,
 w.context_key,
 w.event_id,
 w.package_id,
 w.page_url,
 w.name_key,
 w.name,
 w.honorific,
 w.given,
 w.middle,
 w.family,
 w.suffix,
 w.position,
 w.organization,
 w.on_behalf_of,
 w.location,
 w.panel,
 w.panel_order,
 w.display_order,
 w.witness_type,
 w.testified,
 w.bioguide_id,
 coalesce(al.document_urls,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS document_urls,
 w.ordinal
FROM with_witness_key w
LEFT JOIN aggregated_links al ON w.witness_key=al.witness_key
