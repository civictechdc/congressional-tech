SELECT doc_key,body_hex,arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha
 FROM base_normalized WHERE format='html' AND body_hex IS NOT NULL
