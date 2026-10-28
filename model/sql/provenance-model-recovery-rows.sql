-- Unknown kinds remain visible to the fatal diagnostic instead of disappearing.
SELECT * FROM recovery_candidates WHERE kind IS DISTINCT FROM 'rejected'
