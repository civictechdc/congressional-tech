# Literal media and server-endpoint suffixes

Decision: recognize MP3, MP4, M3U8, ASPX and CFM suffixes as literal filename
extensions without deriving content type, successful retrieval or availability.
The full 333,368-name scan found ten basenames with those suffixes: four ASPX,
three MP4, one MP3, one CFM and one M3U8. All other alphabetic-looking final
suffixes were already recognized by the literal extension reader.

Retained receipts show video/mp4 and audio/mpeg headers for the media links;
full video/audio downloads were deferred and remain deferred. The M3U8 response
was empty despite its playlist media type. Download.aspx returns an attachment
named 20220307.xml. Index.cfm serves files through a query-based handler; ASPX
also includes calendars and error endpoints. Thus a literal suffix is not a
verified content format or an identity. Do not fetch replacements.

Before editing the reader, retain accepted output for each of the ten names and
for its suffix-free stem. Use the existing extension-observation shape as the
expected new observation. The candidate must equal this pre-recorded expected
result: original strict results and pieces, one exposed suffix, and the accepted
reader's output on the unchanged stem. The numeric tails of South Asia UAP 1/2
remain generic-ID fallback assumptions, not asserted media-part numbers.

Only extend the existing extension recognizer; do not create a separate parser
or change canonical House extension enums. Tests cover case, stacked extensions,
query text, strict/typed boundaries, absent/unsupported/dangling suffixes, and
preservation of dates and labels. Compare all names against report-subjects,
the frozen native/strict baseline and the ten pre-recorded expected results.
Require all other complete outputs to remain exact. Review native fallback
changes individually; raw fields must be accounted for, not silently waived.

Run focused/full tests, full typed-adapter comparison, corpus checks, native
omission/fallback audit and source-hash checks. Retain failed trials. No new
dependencies/downloads; full runs are bounded to 30 minutes. These reused inputs
are development evidence, not unseen semantic accuracy evidence.
