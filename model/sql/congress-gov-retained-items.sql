-- Retained Congress.gov items (ct-960v): when a newer Congress.gov read omits a document reference,
-- document URL, bill, or nomination an earlier Congress.gov read of the same meeting listed, retain it
-- marked no_longer_listed with last_listed_on, unlisted_since, and unlisted_by_record_sha.
WITH cg_current AS (
 SELECT event_id,record_sha_hex,updated,retrieved_at,
  subject_keys,subjects_state,document_urls,document_references,document_urls_state
 FROM meeting_records_current
 WHERE source='congress_gov'
), cur_doc_urls_raw AS (
 SELECT event_id,unnest(document_urls) AS url FROM cg_current WHERE coalesce(array_length(document_urls),0)>0
 UNION ALL
 SELECT event_id,r['url'] AS url FROM (
  SELECT event_id,unnest(document_references) AS r FROM cg_current WHERE coalesce(array_length(document_references),0)>0
 )
), cur_doc_urls AS (
 SELECT DISTINCT event_id,trim(url) AS url_key
 FROM cur_doc_urls_raw
 WHERE url IS NOT NULL AND trim(url)<>''
), cur_dref_unnested AS (
 SELECT event_id,unnest(document_references) AS r,
  unnest(range(0,cast(array_length(document_references) AS BIGINT))) AS idx
 FROM cg_current WHERE coalesce(array_length(document_references),0)>0
), cur_dref_rows AS (
 SELECT event_id,0 AS grp,0 AS last_rn,idx,
  named_struct(
   'collection',r['collection'],
   'ordinal',r['ordinal'],
   'url',r['url'],
   'role',r['role'],
   'format',r['format'],
   'description',r['description'],
   'name',r['name'],
   'listing_status','listed',
   'last_listed_on',cast(NULL AS DATE),
   'unlisted_since',cast(NULL AS DATE),
   'unlisted_by_record_sha',cast(NULL AS VARCHAR)
  ) AS item
 FROM cur_dref_unnested
), hist_dref_unnested AS (
 SELECT event_id,hist_rn,obs_date,
  unnest(document_references) AS r,
  unnest(range(0,cast(array_length(document_references) AS BIGINT))) AS idx
 FROM congress_gov_meeting_history
 WHERE hist_rn>1 AND coalesce(array_length(document_references),0)>0
), hist_dref_keyed AS (
 SELECT event_id,hist_rn,obs_date,idx,r,trim(r['url']) AS url_key
 FROM hist_dref_unnested
 WHERE r['url'] IS NOT NULL AND trim(r['url'])<>''
), hist_dref_candidates AS (
 SELECT h.event_id,h.hist_rn,h.obs_date,h.idx,h.r,h.url_key
 FROM cur_doc_urls cu
 RIGHT ANTI JOIN (
  hist_dref_keyed h
  JOIN cg_current c ON c.event_id=h.event_id AND c.document_urls_state IN ('present','empty','absent')
 ) ON cu.event_id=h.event_id AND cu.url_key=h.url_key
), hist_dref_picked AS (
 SELECT *,
  row_number() OVER(PARTITION BY event_id,url_key ORDER BY hist_rn ASC,idx ASC) AS pick_rn
 FROM hist_dref_candidates
), hist_dref_unlisted AS (
 SELECT p.event_id,p.url_key,max(u.hist_rn) AS unlisted_rn
 FROM (SELECT event_id,url_key,hist_rn FROM hist_dref_picked WHERE pick_rn=1) p
 JOIN congress_gov_meeting_history u ON u.event_id=p.event_id AND u.hist_rn<p.hist_rn AND u.document_urls_state IN ('present','empty','absent')
 GROUP BY p.event_id,p.url_key
), retained_dref_rows AS (
 SELECT p.event_id,1 AS grp,cast(p.hist_rn AS BIGINT) AS last_rn,p.idx,
  named_struct(
   'collection',p.r['collection'],
   'ordinal',p.r['ordinal'],
   'url',p.r['url'],
   'role',p.r['role'],
   'format',p.r['format'],
   'description',p.r['description'],
   'name',p.r['name'],
   'listing_status','no_longer_listed',
   'last_listed_on',p.obs_date,
   'unlisted_since',uh.first_obs_date,
   'unlisted_by_record_sha',uh.record_sha_hex
  ) AS item
 FROM hist_dref_picked p
 JOIN hist_dref_unlisted un ON un.event_id=p.event_id AND un.url_key=p.url_key
 JOIN congress_gov_meeting_history uh ON uh.event_id=p.event_id AND uh.hist_rn=un.unlisted_rn
 WHERE p.pick_rn=1
), all_dref_rows AS (
 SELECT * FROM cur_dref_rows
 UNION ALL
 SELECT * FROM retained_dref_rows
), drefs_agg AS (
 SELECT event_id,array_agg(item ORDER BY grp ASC,last_rn ASC,idx ASC) AS document_references
 FROM all_dref_rows
 GROUP BY event_id
), hist_doc_urls_unnested AS (
 SELECT event_id,unnest(document_urls) AS url FROM congress_gov_meeting_history
 WHERE hist_rn>1 AND coalesce(array_length(document_urls),0)>0
), hist_doc_urls_keyed AS (
 SELECT DISTINCT event_id,trim(url) AS url
 FROM hist_doc_urls_unnested
 WHERE url IS NOT NULL AND trim(url)<>''
), retained_doc_url_rows AS (
 SELECT DISTINCT h.event_id,h.url
 FROM cur_doc_urls cu
 RIGHT ANTI JOIN (
  hist_doc_urls_keyed h
  JOIN cg_current c ON c.event_id=h.event_id AND c.document_urls_state IN ('present','empty','absent')
 ) ON cu.event_id=h.event_id AND cu.url_key=h.url
), retained_doc_urls_agg AS (
 SELECT event_id,array_agg(url ORDER BY url ASC) AS retained_document_urls
 FROM retained_doc_url_rows
 GROUP BY event_id
), cur_subjects_unnested AS (
 SELECT event_id,unnest(subject_keys) AS sk FROM cg_current WHERE coalesce(array_length(subject_keys),0)>0
), cur_subjects AS (
 SELECT DISTINCT event_id,lower(trim(sk)) AS subject_key
 FROM cur_subjects_unnested
 WHERE sk IS NOT NULL AND trim(sk)<>''
), hist_subjects_unnested AS (
 SELECT event_id,hist_rn,obs_date,unnest(subject_keys) AS sk
 FROM congress_gov_meeting_history
 WHERE hist_rn>1 AND coalesce(array_length(subject_keys),0)>0
), hist_subjects_keyed AS (
 SELECT event_id,hist_rn,obs_date,lower(trim(sk)) AS subject_key
 FROM hist_subjects_unnested
 WHERE sk IS NOT NULL AND trim(sk)<>''
), hist_subject_candidates AS (
 SELECT h.event_id,h.hist_rn,h.obs_date,h.subject_key
 FROM cur_subjects cs
 RIGHT ANTI JOIN (
  hist_subjects_keyed h
  JOIN cg_current c ON c.event_id=h.event_id AND c.subjects_state IN ('present','empty','absent')
 ) ON cs.event_id=h.event_id AND cs.subject_key=h.subject_key
), hist_subject_picked AS (
 SELECT *,
  row_number() OVER(PARTITION BY event_id,subject_key ORDER BY hist_rn ASC) AS pick_rn
 FROM hist_subject_candidates
), hist_subject_unlisted AS (
 SELECT p.event_id,p.subject_key,max(u.hist_rn) AS unlisted_rn
 FROM (SELECT event_id,subject_key,hist_rn FROM hist_subject_picked WHERE pick_rn=1) p
 JOIN congress_gov_meeting_history u ON u.event_id=p.event_id AND u.hist_rn<p.hist_rn AND u.subjects_state IN ('present','empty','absent')
 GROUP BY p.event_id,p.subject_key
), retained_subject_structs AS (
 SELECT p.event_id,p.subject_key,
  named_struct(
   'subject_key',p.subject_key,
   'last_listed_on',p.obs_date,
   'unlisted_since',uh.first_obs_date,
   'unlisted_by_record_sha',uh.record_sha_hex
  ) AS item
 FROM hist_subject_picked p
 JOIN hist_subject_unlisted un ON un.event_id=p.event_id AND un.subject_key=p.subject_key
 JOIN congress_gov_meeting_history uh ON uh.event_id=p.event_id AND uh.hist_rn=un.unlisted_rn
 WHERE p.pick_rn=1
), retained_subjects_agg AS (
 SELECT event_id,
  array_agg(subject_key ORDER BY subject_key ASC) AS retained_subject_keys,
  array_agg(item ORDER BY subject_key ASC) AS unlisted_subjects
 FROM retained_subject_structs
 GROUP BY event_id
)
SELECT c.event_id,
 coalesce(
  dr.document_references,
  CASE WHEN c.document_references IS NOT NULL THEN array_slice(make_array(named_struct(
   'collection',cast(NULL AS VARCHAR),'ordinal',cast(NULL AS INT),'url',cast(NULL AS VARCHAR),
   'role',cast(NULL AS VARCHAR),'format',cast(NULL AS VARCHAR),'description',cast(NULL AS VARCHAR),
   'name',cast(NULL AS VARCHAR),'listing_status',cast(NULL AS VARCHAR),
   'last_listed_on',cast(NULL AS DATE),'unlisted_since',cast(NULL AS DATE),
   'unlisted_by_record_sha',cast(NULL AS VARCHAR))),1,0)
  END
 ) AS document_references,
 coalesce(du.retained_document_urls,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS retained_document_urls,
 coalesce(sb.retained_subject_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS retained_subject_keys,
 coalesce(sb.unlisted_subjects,array_slice(make_array(named_struct(
  'subject_key',cast(NULL AS VARCHAR),'last_listed_on',cast(NULL AS DATE),
  'unlisted_since',cast(NULL AS DATE),'unlisted_by_record_sha',cast(NULL AS VARCHAR))),1,0)) AS unlisted_subjects
FROM cg_current c
LEFT JOIN drefs_agg dr ON dr.event_id=c.event_id
LEFT JOIN retained_doc_urls_agg du ON du.event_id=c.event_id
LEFT JOIN retained_subjects_agg sb ON sb.event_id=c.event_id
