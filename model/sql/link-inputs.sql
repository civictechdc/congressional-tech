WITH expanded AS (
 SELECT c.page_body,c.context_url,c.member_path,c.first_good_at,c.last_good_at,p.base_href,
 unnest(p.links) AS link,unnest(range(0,cast(array_length(p.links) AS BIGINT))) AS link_index
 FROM page_contexts c JOIN page_facts p ON c.page_body=encode(p.body_sha,'hex')
)
SELECT page_body,context_url,member_path,first_good_at,last_good_at,base_href,link_index,
 link['href'] AS href,link['text'] AS text,link['tag'] AS tag,link['basis'] AS basis,
 link['group_path'] AS group_path,link['doc_type'] AS doc_type,link['add_date'] AS add_date,
 link['publish_date'] AS publish_date,link['remove_date'] AS remove_date FROM expanded WHERE link['href'] IS NOT NULL
