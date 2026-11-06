"""Typed unknown observation for releases without qualified meeting evidence."""

_TIME = "arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))')"
_EVIDENCE = f"""named_struct('source_url',cast(NULL AS VARCHAR),'retrieved_at',{_TIME},
 'receipt_key',cast(NULL AS VARCHAR),'receipt_line',cast(NULL AS INT),'capture_index',cast(NULL AS INT),
 'body_sha256',cast(NULL AS VARCHAR),'meeting_parser_version',cast(NULL AS VARCHAR),
 'proof_parser_version',cast(NULL AS VARCHAR))"""
UNKNOWN_OBSERVATION = f"""named_struct('state','unknown','coverage','unknown',
 'successful_read',CASE WHEN false THEN {_EVIDENCE} END,
 'latest_attempt',CASE WHEN false THEN named_struct('evidence',{_EVIDENCE},
  'state',cast(NULL AS VARCHAR),'outcome',cast(NULL AS VARCHAR),'http_status',cast(NULL AS INT)) END,
 'listing',CASE WHEN false THEN {_EVIDENCE} END,'has_undated_attempt',false)"""
EMPTY_OBSERVATIONS = f"""SELECT cast(NULL AS INT) AS congress,cast(NULL AS VARCHAR) AS chamber,
 cast(NULL AS BIGINT) AS event_id,o['state'] AS state,o['coverage'] AS coverage,
 o['successful_read'] AS successful_read,o['latest_attempt'] AS latest_attempt,
 o['listing'] AS listing,o['has_undated_attempt'] AS has_undated_attempt
 FROM (SELECT {UNKNOWN_OBSERVATION} AS o) WHERE false"""
