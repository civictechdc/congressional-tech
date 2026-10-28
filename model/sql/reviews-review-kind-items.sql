WITH items AS (
 SELECT component,id,unnest(kind_values) AS raw_value FROM review_selected WHERE verdict='kind_override'
)
SELECT component,id,json_get_str(raw_value) AS kind FROM items
