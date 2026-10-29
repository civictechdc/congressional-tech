SELECT c.* EXCLUDE(intact),b.format,b.intact,b.intact_basis,b.error_type FROM body_evidence b
RIGHT JOIN captures c ON encode(c.sha256,'hex')=b.body_sha
