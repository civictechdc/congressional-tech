WITH expanded AS (
 SELECT c.page_body,c.context_url,c.member_path,c.first_good_at,c.last_good_at,r.base_href,
 unnest(r.links) AS link,unnest(range(0,cast(array_length(r.links) AS BIGINT))) AS link_index
 FROM page_contexts c JOIN (
   SELECT r.* FROM readings r JOIN parser_versions v ON r.parser=v.parser AND r.parser_version=v.version
   WHERE r.parser IN ('html','xml','json') AND r.links IS NOT NULL
 ) r ON c.page_body=encode(r.body_sha,'hex')
)
SELECT page_body,context_url,member_path,first_good_at,last_good_at,base_href,link_index,
 link['href'] AS href,link['text'] AS text,link['tag'] AS tag,link['basis'] AS basis,
 link['group_path'] AS group_path,link['doc_type'] AS doc_type,link['add_date'] AS add_date,
 link['publish_date'] AS publish_date,link['remove_date'] AS remove_date FROM expanded WHERE link['href'] IS NOT NULL
