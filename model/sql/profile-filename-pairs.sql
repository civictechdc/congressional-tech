-- Source IDs can share one filename/URL pair across body versions.
SELECT DISTINCT filename,coalesce(source_url,'') AS source_url FROM source_files
