SELECT component,id,'invalid_review_value' AS error FROM review_selected
WHERE (verdict='hide' AND hide_value IS NULL)
 OR (verdict='title_override' AND (value_text IS NULL OR value_text=''))
 OR (verdict='kind_override' AND coalesce(array_length(kind_values),0)=0)
UNION SELECT component,id,'invalid_review_value' FROM review_kind_items WHERE kind IS NULL OR kind=''
