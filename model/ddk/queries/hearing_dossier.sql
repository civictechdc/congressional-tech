SELECT m.event_id,m.chamber,m.meeting_date,m.title,m.committees,m.subject_keys,m.transcripts,
  coalesce((SELECT list(struct_pack(witness_key:=w.witness_key,name:=w.name,position:=w.position,organization:=w.organization,panel:=w.panel,display_order:=w.display_order) ORDER BY w.panel_order NULLS LAST,w.display_order NULLS LAST,w.witness_key) FROM witnesses w WHERE w.event_id=m.event_id AND w.superseded_by IS NULL),[]) AS witnesses,
  coalesce((SELECT list(struct_pack(list_row:=l.list_row,filename:=l.filename,title:=l.title,document_kind:=l.document_kind,link_key:=lower(hex(d.link_key))) ORDER BY l.list_row) FROM "list" l JOIN detail d USING (list_row) WHERE NOT coalesce(l.hidden,false) AND list_contains(l.meeting_keys,CAST(m.event_id AS VARCHAR))),[]) AS documents,
  coalesce((SELECT list(r ORDER BY r.match_id) FROM (
   SELECT match_id,subject_kind,subject_id,event_id,package_id,video_key,url,basis,decision,score,recording_scope,status,note,source_ref,
    list_filter(meeting_links,lambda l:l.event_id=m.event_id) AS meeting_links
   FROM recording_matches
   WHERE list_contains(list_transform(meeting_links,lambda l:l.event_id),m.event_id)
   ORDER BY match_id LIMIT 100
  ) r),[]) AS recordings
FROM meetings m WHERE m.event_id=?