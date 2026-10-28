SELECT source_id,unnest(committee_code) AS code FROM source_filename_readings WHERE status='completed'
