SELECT c.*,b.format,b.intact,b.intact_basis,b.error_type FROM captures c
LEFT JOIN body_evidence b ON encode(c.sha256,'hex')=b.body_sha
