-- Only the keys, retained so role joins never rebuild the eligibility join in their hash tables.
SELECT receipt_key,receipt_line,capture_index FROM good_fetches
