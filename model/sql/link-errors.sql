-- Any invalid repaired part invalidates that entire literal in its own page context.
SELECT DISTINCT page_body,context_url,member_path,base_href,href,target_error AS error
FROM link_targets WHERE target_error IS NOT NULL
