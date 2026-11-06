import {
  committeeLabel,
  congressLabel,
  formatChamber,
  formatDuration,
  formatMeetingType,
  formatSubject,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, RelationNotice, day} from './ArchiveRows.tsx';
import {savedCopy} from '../reader/archive.ts';
import {transcriptSourceLabel} from '../reader/archive-entities.ts';

function savedCaptionUrl(track: any, rawBase?: string) {
  if (rawBase && track?.sha256) {
    try {
      return savedCopy({saved_body: track.sha256, saved_suffix: track.suffix}, rawBase).url;
    } catch {
      // The original link remains available if the saved identity is invalid.
    }
  }
}

function RecordingObservations({observations}:{observations:any[]}){
  return <ul className="archive-entity-list">
    {observations.map((obs:any)=>{
      const youtube=/^youtube:([a-zA-Z0-9_-]+)$/.exec(obs.video_key??'');
      const url=obs.url||(youtube?`https://www.youtube.com/watch?v=${youtube[1]}`:null);
      const scope=obs.meeting_link?.scope;
      const label=scope==='package_context'?'Related package recording evidence'
        :scope==='event'?'Recording evidence for this event':'Original recording observation';
      const describe=[obs.status,obs.decision,obs.recording_scope].filter(Boolean).map(v=>String(v).replaceAll('_',' ')).join(' · ');
      return <li key={obs.match_id}>
        {url?<PublicLink url={url}>{label}</PublicLink>:<strong>{label}</strong>}
        {describe&&<span className="archive-source-meta"> · {describe}</span>}
        {obs.package_id&&<p className="archive-source-meta"><PublicLink url={`https://www.govinfo.gov/app/details/${encodeURIComponent(obs.package_id)}`}>{obs.package_id}</PublicLink></p>}
        {obs.note&&<p className="archive-source-meta">{obs.note}</p>}
        {obs.source_ref&&<p className="archive-source-meta">Source <code>{obs.source_ref}</code></p>}
      </li>;
    })}
  </ul>;
}

export function HearingDetail({
  meeting,
  committeesCatalog,
  rawBase,
  compact,
  onSelect,
  onCommittee,
  onSubject,
  onWitness,
  onMember,
  onFilterDocuments,
  onInspect,
  onClose,
  closeLabel,
}:{
  meeting:any;
  committeesCatalog?:CommitteeCatalogInput;
  rawBase?:string;
  compact?:boolean;
  onSelect?:(row:number)=>void;
  onCommittee?:(key:string)=>void;
  onSubject?:(key:string)=>void;
  onWitness?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onFilterDocuments?:()=>void;
  onInspect?:()=>void;
  onClose?:()=>void;
  closeLabel?:string;
}){
  if(!meeting)return null;
  const eventId=String(meeting.event_id??meeting.meeting_key??'');
  const dateOrCongress=meeting.meeting_date||meeting.congress;
  const committeeItems:any[]=Array.isArray(meeting.committees)&&meeting.committees.length
    ?meeting.committees
    :(meeting.committee_keys??[]).map((code:string)=>({
        committee_key:code,
        system_code:code,
        name:committeeLabel(code,committeesCatalog,dateOrCongress),
      }));
  const subjects:any[]=Array.isArray(meeting.subjects)&&meeting.subjects.length
    ?meeting.subjects
    :(meeting.subject_keys??[]).map((sk:string)=>({subject_key:sk}));
  const recordings:any[]=Array.isArray(meeting.videos)&&meeting.videos.length
    ?meeting.videos
    :Array.isArray(meeting.recordings)?meeting.recordings:[];
  const observations:any[]=meeting.recording_observations??[];
  const transcripts:any[]=Array.isArray(meeting.transcripts)?meeting.transcripts:[];
  const sittings:any[]=Array.isArray(meeting.sittings)?meeting.sittings:[];
  const witnesses:any[]=Array.isArray(meeting.witnesses)?meeting.witnesses:[];
  const publisherDocuments:any[]=meeting.document_references??[];
  const documents:any[]=Array.isArray(meeting.documents)?meeting.documents:[];
  const contextParts=[
    congressLabel(meeting.congress),
    formatChamber(meeting.chamber),
    formatMeetingType(meeting.meeting_type),
    (meeting.publisher_status??meeting.status)?`Publisher status: ${meeting.publisher_status??meeting.status}`:null,
    `Outcome: ${meeting.outcome??'evidence unavailable in this release'}`,
  ].filter(Boolean);
  const publisherStatuses:any[]=meeting.publisher_status_observations??[];
  const relation=meeting.relation_states??{};
  const coverage=meeting.coverage??{};
  const witnessCount=witnesses.filter(w=>!['statement_for_record','member_statement'].includes(w.witness_type)).length;
  const shownWitnesses=compact?witnesses.slice(0,6):witnesses;

  return <section className="archive-entity-card" aria-label="Hearing details" data-archive-entity="hearing">
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">{contextParts.join(' · ')||'Congressional Hearing'}</p>
        <div className="archive-pill-list">
          {onInspect&&<button type="button" className="archive-measure-pill" onClick={onInspect}>Open full profile →</button>}
          {onFilterDocuments&&<button type="button" className="archive-measure-pill" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose&&<button type="button" className="archive-measure-pill" onClick={onClose}>{closeLabel||'Close hearing details'}</button>}
        </div>
      </div>
      {meeting.outcome_reason&&<p className="archive-entity-meta">{meeting.outcome_reason}</p>}
      {meeting.outcome_basis&&<p className="archive-entity-meta">Outcome evidence: {meeting.outcome_basis.replaceAll('_',' ')}{meeting.outcome_source_reference?` · ${meeting.outcome_source_reference}`:''}</p>}
      {publisherStatuses.length>0&&<details><summary>Publisher status observations ({publisherStatuses.length})</summary><ul>{publisherStatuses.map((obs:any,i:number)=><li key={i}>{obs.source}: {obs.status} · {day(obs.meeting_date)}{obs.record_sha?` · source ${obs.record_sha}`:''}</li>)}</ul></details>}
      <h2>{meeting.title||`Hearing ${eventId}`}</h2>
      <p className="archive-entity-meta">
        {meeting.meeting_date&&<span><strong>Date:</strong> {day(meeting.meeting_date)}</span>}
        {eventId&&<>
          {meeting.meeting_date&&<span aria-hidden="true"> · </span>}
          <span>Event ID: {eventId}</span>
        </>}
      </p>
    </header>

    <RelationNotice label="Committee details" state={relation.committees}/>
    <RelationNotice label="Bill details" state={relation.bills}/>
    <RelationNotice label="Nomination details" state={relation.nominations}/>
    <RelationNotice label="Coverage details" state={relation.coverage}/>
    <RelationNotice label="Recordings" state={relation.recordings} coverage={coverage.recording}/>
    <RelationNotice label="Witnesses" state={relation.witnesses} coverage={coverage.witnesses}/>
    <RelationNotice label="Hearing documents" coverage={coverage.documents}/>
    <RelationNotice label="Transcripts" coverage={coverage.transcript}/>

    {committeeItems.length>0&&<div className="archive-entity-section">
      <h3>Committees</h3>
      <div className="archive-pill-list">
        {committeeItems.map((c:any)=>{
          const code=String(c.committee_key??c.system_code??'').toLowerCase();
          const label=c.resolved_name||c.name||committeeLabel(code,committeesCatalog,dateOrCongress);
          return <span key={code} className="archive-pill-group">
            {onCommittee
              ?<button type="button" className="archive-measure-pill" onClick={()=>onCommittee(code)}>{label}</button>
              :<span className="archive-measure-pill">{label}</span>}
          </span>;
        })}
      </div>
    </div>}

    {sittings.length>0&&<div className="archive-entity-section">
      <h3>Sittings &amp; Location</h3>
      <ul className="archive-entity-list">
        {sittings.map((s:any,i:number)=>{
          const bldgRoom=[s.building,s.room].filter(Boolean).join(' ');
          const loc=s.place||[bldgRoom,s.location,s.address].filter(Boolean).join(', ');
          const when=s.datetime||s.date||s.start_time||s.start||'';
          return <li key={i}>
            {when&&<strong>{String(when)}</strong>}
            {when&&loc&&' — '}
            {loc&&<span>{loc}</span>}
          </li>;
        })}
      </ul>
    </div>}

    {subjects.length>0&&<div className="archive-entity-section">
      <h3>Subjects (Bills &amp; Nominations)</h3>
      <div className="archive-pill-list">
        {subjects.map((sub:any)=>{
          const key=String(sub.subject_key??sub.bill_id??sub.nomination_id??'');
          const label=formatSubject(key,sub);
          const title=sub.short_title||sub.title||sub.description||'';
          return <span key={key} className="archive-subject-item">
            {onSubject
              ?<button type="button" className="archive-measure-pill" onClick={()=>onSubject(key)}>
                  {label}{title?` — ${title}`:''}
                </button>
              :<span className="archive-measure-pill">{label}{title?` — ${title}`:''}</span>}
          </span>;
        })}
      </div>
    </div>}

    {recordings.length>0&&<div className="archive-entity-section">
      <h3>Video Recordings</h3>
      <ul className="archive-entity-list">
        {recordings.map((rec:any,i:number)=>{
          const duration=formatDuration(rec.duration_s);
          const label=rec.title||rec.source||rec.video_key||`Recording ${i+1}`;
          const rawTracks:any[]=Array.isArray(rec.tracks)?rec.tracks:Array.isArray(rec.transcripts)?rec.transcripts:[];
          const seenTracks=new Set<string>();
          const tracks=rawTracks.filter((t:any)=>{
            const k=String(typeof t==='string'?t:(t?.sha256||t?.url||[t?.label,t?.language,t?.format,t?.production].filter(Boolean).join(' · ')));
            if(!k||seenTracks.has(k))return false;
            seenTracks.add(k);
            return true;
          });
          return <li key={rec.video_key||rec.video_id||i} data-recording-key={rec.video_key||undefined}>
            {rec.url?<PublicLink url={rec.url}>{label}</PublicLink>:<strong>{label}</strong>}
            {rec.source&&<span className="archive-source-meta"> ({rec.source}{duration?`, ${duration}`:''})</span>}
            {!rec.source&&duration&&<span className="archive-source-meta"> ({duration})</span>}
            {tracks.length>0&&<span className="archive-source-meta">
              <span aria-hidden="true"> · </span>
              Captions: {tracks.map((t:any,ti:number)=>{
                const tLabel=typeof t==='string'?t:([t.label,t.language,t.format,t.production].filter(Boolean).join(' · ')||'Captions');
                const savedUrl=savedCaptionUrl(t,rawBase);
                const url=savedUrl||t?.url;
                const savedPlaylist=savedUrl&&t?.format==='m3u8';
                return <span key={ti}>
                  {ti>0&&', '}
                  {url?<PublicLink url={url} download={Boolean(savedPlaylist)}>{savedPlaylist?'Download saved HLS playlist':tLabel}</PublicLink>:<span>{tLabel}</span>}
                  {savedPlaylist&&<span> ({tLabel}). Playback is unavailable here.</span>}
                </span>;
              })}
            </span>}
          </li>;
        })}
      </ul>
    </div>}

    <RelationNotice label="Recording associations" state={meeting.recording_associations_state}/>
    {meeting.recording_associations_state==='ready'&&!observations.length&&
      <p className="archive-source-meta">The archive lists no supported recording associations for this hearing.</p>}
    {observations.length>0&&<div className="archive-entity-section">
      <h3>Recording evidence</h3>
      <RecordingObservations observations={observations}/>
    </div>}

    {(meeting.original_package_observations??[]).map((group:any)=><details key={group.package_id} className="archive-entity-section">
      <summary>Original package observations for {group.package_id}</summary>
      <p className="archive-source-meta">These observations describe the package. Hearing associations are unavailable in this release.</p>
      <RecordingObservations observations={group.observations}/>
    </details>)}

    {transcripts.length>0&&<div className="archive-entity-section">
      <h3>Transcripts and captions</h3>
      <ul className="archive-entity-list">
        {transcripts.map((tr:any,i:number)=>{
          const sourceLabel=transcriptSourceLabel(tr);
          const label=tr.title||tr.jacket_number||tr.package_id||(tr.source==='captions'?tr.video_key:null)||`${sourceLabel} ${i+1}`;
          const sourceContext=[sourceLabel,...(tr.source==='captions'
            ?[tr.language,...(Array.isArray(tr.formats)?tr.formats:[]),tr.production]:[])].filter(Boolean).join(' · ');
          const hasRow=tr.list_row!=null&&Number.isSafeInteger(Number(tr.list_row));
          return <li key={tr.jacket_number||i}>
            {hasRow&&onSelect
              ?<button type="button" className="explorer-text-button" onClick={()=>onSelect(Number(tr.list_row))}>{label}</button>
              :tr.url?<PublicLink url={tr.url}>{label}</PublicLink>
                :tr.package_id?<PublicLink url={`https://www.govinfo.gov/app/details/${encodeURIComponent(tr.package_id)}`}>{label}</PublicLink>:<span>{label}</span>}
            {tr.jacket_number&&tr.title&&<span className="archive-source-meta"> (Jacket {tr.jacket_number})</span>}
            <span className="archive-source-meta"> · {sourceContext}</span>
          </li>;
        })}
      </ul>
    </div>}

    {witnesses.length>0&&<div className="archive-entity-section">
      <h3>{witnessCount===witnesses.length?`Witnesses (${witnessCount})`:`Witnesses and statements (${witnessCount} witnesses)`}</h3>
      <ul className="archive-witness-list">
        {shownWitnesses.map((w:any,i:number)=>{
          const wKey=w.witness_key||w.name_key||'';
          const roleParts=[w.position,w.organization,w.on_behalf_of?`on behalf of ${w.on_behalf_of}`:null].filter(Boolean);
          const docs:any[]=Array.isArray(w.documents)?w.documents:[];
          return <li key={`${wKey}-${i}`} className="archive-witness-item">
            <div className="archive-witness-header">
              {w.panel!=null&&<span className="archive-witness-panel">Panel {String(w.panel)}: </span>}
              {wKey&&onWitness
                ?<button type="button" className="explorer-text-button archive-entity-link" onClick={()=>onWitness(String(wKey))}><strong>{w.name||wKey}</strong></button>
                :<strong>{w.name||wKey}</strong>}
              {w.bioguide_id&&onMember&&<>
                <span aria-hidden="true"> · </span>
                <button type="button" className="archive-measure-pill" onClick={()=>onMember(String(w.bioguide_id))}>Member ({w.bioguide_id})</button>
              </>}
            </div>
            {w.witness_type==='statement_for_record'&&<p className="archive-source-meta">Statement for the record</p>}
            {w.witness_type==='member_statement'&&<p className="archive-source-meta">Member statement</p>}
            {roleParts.length>0&&<p className="archive-source-meta">{roleParts.join(' — ')}</p>}
            {docs.length>0&&onSelect&&<div className="archive-witness-docs">
              <span className="archive-source-meta">Submitted documents: </span>
              {docs.map((doc:any,di:number)=>{
                const pres=presentDocument(doc,undefined,undefined,undefined,committeesCatalog);
                return <span key={doc.list_row}>
                  {di>0&&<span aria-hidden="true"> · </span>}
                  <button type="button" className="explorer-text-button" onClick={()=>onSelect(doc.list_row)}>{pres.title}</button>
                </span>;
              })}
            </div>}
          </li>;
        })}
      </ul>
    </div>}

    {!compact&&publisherDocuments.length>0&&<div className="archive-entity-section">
      <h3>Documents listed by Congress.gov</h3>
      <ul className="archive-entity-list">
        {publisherDocuments.map((ref:any)=><li key={`${ref.collection}-${ref.ordinal}`}>
          <PublicLink url={ref.url}>{ref.name||ref.description||ref.url}</PublicLink>
          <span className="archive-source-meta"> · {ref.collection==='witnessDocuments'?'Witness document':'Meeting document'}
            {ref.role&&` · ${ref.role}`}
            {ref.format&&` · Publisher format ${ref.format}`}
          </span>
          {ref.description&&ref.name&&<p className="archive-source-meta">{ref.description}</p>}
        </li>)}
      </ul>
    </div>}

    {!compact&&documents.length>0&&onSelect&&<div className="archive-entity-section">
      <h3>Hearing Documents ({documents.length})</h3>
      <ul className="archive-entity-list">
        {documents.slice(0,25).map((doc:any)=>{
          const pres=presentDocument(doc,undefined,undefined,undefined,committeesCatalog);
          return <li key={doc.list_row}>
            <button type="button" className="explorer-text-button" onClick={()=>onSelect(doc.list_row)}>{pres.title}</button>
            <span className="archive-source-meta">
              {doc.document_date?` · ${day(doc.document_date)}`:''}
              {pres.kinds[0]?` · ${pres.kinds[0]}`:''}
              {pres.format?` (${pres.format})`:''}
            </span>
          </li>;
        })}
      </ul>
    </div>}
  </section>;
}
