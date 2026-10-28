SELECT m.component,min(CASE WHEN m.is_real_file THEN m.first_fetched END) AS first_fetched,
 CASE WHEN min(CASE WHEN m.is_real_file THEN m.first_fetched END) IS NULL THEN min(m.in_archive_since) END AS in_archive_since,
 array_sort(array_distinct(flatten(array_agg(a.document_kind)))) AS document_kind,
 array_sort(array_distinct(flatten(array_agg(a.document_family)))) AS document_family,
 array_sort(array_distinct(flatten(array_agg(a.committee_keys)))) AS committee_keys,
 array_sort(array_distinct(flatten(array_agg(a.chambers)))) AS chambers,
 array_sort(array_distinct(flatten(array_agg(a.meeting_keys)))) AS meeting_keys,
 array_sort(array_distinct(flatten(array_agg(a.measure_keys)))) AS measure_keys,
 array_sort(array_distinct(flatten(array_agg(a.bioguide_ids)))) AS bioguide_ids
FROM document_members m JOIN source_annotations a USING(source_id) GROUP BY m.component
