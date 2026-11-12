-- States rank present > unresolved > empty > unknown > not_stated. unknown, never not_stated, where held
-- evidence is not yet linked. A Senate meeting is unknown for documents and witnesses until the Senate
-- committee-page links land (ct-gi01 R2): those pages are held but not linked to meetings. Remove the
-- senate_page_links_pending arms then; old page decisions came from the distrusted old matcher.
WITH observations AS (
 SELECT unnest(meeting_links) AS link,basis,status,decision,recording_scope,video_key,coalesce(video_key,url) AS ref
 FROM recording_matches_export
), recording_links AS (
 SELECT link['event_id'] AS event_id,link['scope'] AS scope,basis,status,decision,recording_scope,video_key,ref
 FROM observations
), recording_refs AS (
 -- Each locator counts once, even if independent observations cite it.
 SELECT m.event_id,m.ref,
  bool_or(m.scope='event' AND ((m.status='asserted' AND coalesce(r.recording_scope,'unknown')<>'excerpt') OR (m.status='decided' AND m.recording_scope='full'))) AS full_recording,
  bool_or(m.scope='event' AND ((m.status='asserted' AND r.recording_scope='excerpt') OR (m.status='decided' AND m.recording_scope='excerpt'))) AS excerpt,
  bool_or(m.scope='event' AND m.status='claimed') AS claimed,
  bool_or(m.scope='event' AND m.basis='curated' AND m.status='decided' AND m.decision='not_public') AS not_public,
  bool_or(m.scope='event' AND m.basis='curated' AND m.status='decided' AND m.decision='no_video_found') AS confirmed_absent,
  bool_or(m.status IN ('unresolved','conflicting')) AS disputed,
  bool_or(m.scope='package_context') AS package_context,
  bool_or(m.scope='event' AND m.video_key IS NOT NULL) AS has_video_record,
  bool_or(m.scope='event' AND (v.has_caption OR coalesce(array_length(r.tracks),0)>0)) AS has_captions
 FROM recording_links m
 LEFT JOIN videos_export v ON m.video_key=v.video_key
 LEFT JOIN recordings_export r ON m.video_key=r.video_key
 GROUP BY m.event_id,m.ref
), recording_levels AS (
 SELECT event_id,count(CASE WHEN full_recording THEN ref END) AS full_n,
  count(CASE WHEN excerpt THEN ref END) AS excerpt_n,
  count(CASE WHEN claimed THEN ref END) AS claimed_n,
  bool_or(not_public) AS not_public,bool_or(confirmed_absent) AS confirmed_absent,
  bool_or(disputed) AS disputed,bool_or(package_context) AS package_context,
  bool_or(has_video_record) AS has_video_record,
  count(CASE WHEN has_captions THEN ref END) AS caption_n
 FROM recording_refs GROUP BY event_id
), recording_rows AS (
 SELECT e.event_id,'recording' AS aspect,
  CASE WHEN l.full_n>0 THEN 'present' WHEN l.excerpt_n>0 THEN 'partial' WHEN l.claimed_n>0 THEN 'claimed'
       WHEN l.disputed THEN 'unresolved' WHEN l.not_public THEN 'not_public'
       WHEN l.confirmed_absent THEN 'confirmed_absent' WHEN l.package_context THEN 'unresolved' ELSE 'unknown' END AS state,
  CASE WHEN l.full_n>0 OR l.excerpt_n>0 OR l.claimed_n>0 THEN 'recording_matches'
       WHEN l.disputed OR l.not_public OR l.confirmed_absent THEN 'recording_decisions'
       WHEN l.package_context THEN 'recording_matches' ELSE 'none' END AS basis,
  cast(coalesce(nullif(l.full_n,0),nullif(l.excerpt_n,0),nullif(l.claimed_n,0),0) AS INT) AS count,
  l.has_video_record,l.caption_n,
  CASE WHEN l.full_n>0 THEN NULL WHEN l.excerpt_n>0 THEN 'excerpts_only' WHEN l.claimed_n>0 THEN 'video_text_only'
       WHEN l.disputed THEN 'recording_decision_unresolved_or_conflicting'
       WHEN l.not_public OR l.confirmed_absent THEN NULL
       WHEN l.package_context THEN 'package_context_only' END AS reason
 FROM meetings_export e LEFT JOIN recording_levels l ON e.event_id=l.event_id
), mods_named AS (
 SELECT DISTINCT event_id FROM (SELECT unnest(named_meetings) AS event_id FROM package_mods_facts) WHERE event_id IS NOT NULL
), transcript_sources AS (
 SELECT event_id,array_to_string(array_sort(array_agg(DISTINCT source)),',') AS sources
 FROM (SELECT event_id,unnest(transcripts)['source'] AS source FROM meetings_export) GROUP BY event_id
), transcript_rows AS (
 SELECT e.event_id,'transcript' AS aspect,
  CASE WHEN coalesce(array_length(e.transcripts),0)>0 THEN 'present'
       WHEN coalesce(array_length(r.transcript_jackets),0)>0 THEN 'unresolved'
       WHEN n.event_id IS NOT NULL THEN 'unknown' ELSE 'not_stated' END AS state,
  'meetings.transcripts' AS basis,cast(coalesce(array_length(e.transcripts),0) AS INT) AS count,
  -- Present names its sources (ct-1i4q): printed_hearing, committee_transcript and captions, sorted.
  CASE WHEN coalesce(array_length(e.transcripts),0)>0 THEN ts.sources
   WHEN coalesce(array_length(r.transcript_jackets),0)=0 AND n.event_id IS NOT NULL THEN 'package_names_meeting_unlinked' END AS reason
 FROM meetings_export e LEFT JOIN meetings_resolved r ON e.event_id=r.event_id LEFT JOIN mods_named n ON e.event_id=n.event_id
 LEFT JOIN transcript_sources ts ON e.event_id=ts.event_id
), document_counts AS (
 SELECT event_id,count(*) AS n FROM (SELECT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered WHERE meeting_keys IS NOT NULL) GROUP BY event_id
), stated_documents AS (
 SELECT DISTINCT event_id FROM meeting_document_urls
), witness_counts AS (
 -- Superseded rows point to the selected person; record material and sitting Members (ct-kw85) contribute no witness count.
 SELECT event_id,count(*) AS n FROM witnesses_export WHERE event_id IS NOT NULL AND name IS NOT NULL AND superseded_by IS NULL
  AND coalesce(witness_type,'') NOT IN ('statement_for_record','member_statement','record_material','member_appearance') GROUP BY event_id
), witness_states AS (
 SELECT event_id,max(CASE WHEN collection_state='unresolved' THEN 2 WHEN collection_state='empty' THEN 1 ELSE 0 END) AS rank
 FROM (
  SELECT event_id,CASE WHEN status<>'completed' OR collection_state IN ('failed','unrecognized') THEN 'unresolved'
    ELSE coalesce(nullif(trim(collection_state),''),CASE WHEN coalesce(array_length(appearances),0)>0 THEN 'present' ELSE 'empty' END) END AS collection_state
  FROM selected_appearance_records r
  UNION ALL
  SELECT DISTINCT event_id,'present' AS collection_state FROM witnesses_export WHERE event_id IS NOT NULL
 ) WHERE event_id IS NOT NULL GROUP BY event_id
), document_rows AS (
 SELECT e.event_id,'documents' AS aspect,
  CASE WHEN d.n IS NOT NULL THEN 'present' WHEN s.event_id IS NOT NULL THEN 'unresolved'
       WHEN e.chamber='senate' AND ws.event_id IS NULL THEN 'unknown' ELSE 'not_stated' END AS state,
  'list.meeting_keys' AS basis,cast(coalesce(d.n,0) AS INT) AS count,
  CASE WHEN d.n IS NOT NULL THEN NULL WHEN s.event_id IS NOT NULL THEN 'stated_documents_not_held'
       WHEN e.chamber='senate' AND ws.event_id IS NULL THEN 'senate_page_links_pending' END AS reason
 FROM meetings_export e LEFT JOIN document_counts d ON e.event_id=d.event_id LEFT JOIN stated_documents s ON e.event_id=s.event_id
  LEFT JOIN witness_states ws ON e.event_id=ws.event_id
), linked_packages AS (
 -- The prints a meeting's jacket links, less these publisher jacket references to different same-day proceedings.
 SELECT l.event_id,l.package_id FROM (VALUES
  (105990,'CHRG-115hhrg27490'), (106820,'CHRG-115hhrg29991'),
  (110525,'CHRG-116hhrg43523'), (111173,'CHRG-117hhrg47471'),
  (117523,'CHRG-118hhrg56208'), (329023,'CHRG-117shrg45981')
 ) AS unrelated(event_id,package_id)
 RIGHT ANTI JOIN meeting_transcript_links l ON l.event_id=unrelated.event_id AND l.package_id=unrelated.package_id
), unattached_package_witnesses AS (
 -- A linked package holds witnesses that no raw record ties to this meeting alone (ct-dx22).
 SELECT DISTINCT l.event_id FROM linked_packages l
 JOIN witnesses_export w ON w.package_id=l.package_id AND w.event_id IS NULL AND w.name IS NOT NULL
  AND coalesce(w.witness_type,'') NOT IN ('statement_for_record','member_statement','record_material','member_appearance')
), member_only AS (
 -- The people a meeting lists are sitting Members (ct-kw85), perhaps with record entries: shown Member rows on its own
 -- list, or tied to no meeting on a print it links, and no outside witness on either (none counted, none unattached):
 -- empty, not unstated, whatever the print's rows were before. A nomination hearing's list that names only Members
 -- left its nominee out: unknown, not empty.
 SELECT DISTINCT m.event_id FROM unattached_package_witnesses u RIGHT ANTI JOIN (
  SELECT event_id FROM witnesses_export WHERE event_id IS NOT NULL AND name IS NOT NULL AND superseded_by IS NULL
   AND witness_type='member_appearance'
  UNION ALL
  SELECT l.event_id FROM linked_packages l JOIN witnesses_export w ON w.package_id=l.package_id AND w.event_id IS NULL
   AND w.name IS NOT NULL AND w.superseded_by IS NULL AND w.witness_type='member_appearance'
 ) m ON m.event_id=u.event_id
), witness_rows AS (
 SELECT e.event_id,'witnesses' AS aspect,
  CASE WHEN c.n IS NOT NULL THEN 'present' WHEN s.rank=2 THEN 'unresolved'
       WHEN mo.event_id IS NOT NULL AND regexp_like(e.title,'nominat','i') THEN 'unknown'
       WHEN mo.event_id IS NOT NULL OR s.rank=1 THEN 'empty'
       WHEN u.event_id IS NOT NULL OR (e.chamber='senate' AND s.event_id IS NULL) THEN 'unknown' ELSE 'not_stated' END AS state,
  'appearance_records' AS basis,cast(coalesce(c.n,0) AS INT) AS count,
  CASE WHEN c.n IS NOT NULL OR s.rank=2 THEN NULL
       WHEN mo.event_id IS NOT NULL AND regexp_like(e.title,'nominat','i') THEN 'nominee_not_listed'
       WHEN mo.event_id IS NOT NULL THEN 'member_appearances_only'
       WHEN s.rank=1 THEN NULL WHEN u.event_id IS NOT NULL THEN 'package_witnesses_unattached'
       WHEN e.chamber='senate' AND s.event_id IS NULL THEN 'senate_page_links_pending' END AS reason
 FROM meetings_export e LEFT JOIN witness_counts c ON e.event_id=c.event_id LEFT JOIN witness_states s ON e.event_id=s.event_id
  LEFT JOIN unattached_package_witnesses u ON e.event_id=u.event_id LEFT JOIN member_only mo ON e.event_id=mo.event_id
), recording_and_caption_rows AS (
 SELECT event_id,unnest(make_array(
  named_struct('aspect',aspect,'state',state,'basis',basis,'count',count,'reason',reason),
  named_struct('aspect','captions',
   'state',CASE WHEN caption_n>0 THEN 'present' WHEN has_video_record THEN 'unknown'
        WHEN state IN ('confirmed_absent','not_public') THEN 'not_stated' ELSE 'unknown' END,
   'basis','videos.has_caption,recordings.tracks','count',cast(coalesce(caption_n,0) AS INT),
   'reason',CASE WHEN caption_n>0 OR has_video_record OR state IN ('confirmed_absent','not_public') THEN NULL
        WHEN state IN ('present','partial','claimed') THEN 'recording_without_video_record'
        ELSE 'recording_link_pending' END)
 )) AS item FROM recording_rows
)
SELECT event_id,item['aspect'] AS aspect,item['state'] AS state,item['basis'] AS basis,item['count'] AS count,item['reason'] AS reason
FROM recording_and_caption_rows
UNION ALL SELECT event_id,aspect,state,basis,count,reason FROM transcript_rows
UNION ALL SELECT event_id,aspect,state,basis,count,reason FROM document_rows
UNION ALL SELECT event_id,aspect,state,basis,count,reason FROM witness_rows
