import {
  committeeLabel,
  congressLabel,
  formatDuration,
  formatSubject,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day} from './ArchiveRows.tsx';

export function HearingDetail({
  meeting,
  committeesCatalog,
  onSelect,
  onCommittee,
  onSubject,
  onWitness,
  onMember,
  onFilterDocuments,
  onClose,
  closeLabel,
}:{
  meeting:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onCommittee?:(key:string)=>void;
  onSubject?:(key:string)=>void;
  onWitness?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onFilterDocuments?:()=>void;
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
  const transcripts:any[]=Array.isArray(meeting.transcripts)?meeting.transcripts:[];
  const sittings:any[]=Array.isArray(meeting.sittings)?meeting.sittings:[];
  const witnesses:any[]=Array.isArray(meeting.witnesses)?meeting.witnesses:[];
  const documents:any[]=Array.isArray(meeting.documents)?meeting.documents:[];
  const contextParts=[
    congressLabel(meeting.congress),
    meeting.chamber?String(meeting.chamber).charAt(0).toUpperCase()+String(meeting.chamber).slice(1):null,
    meeting.meeting_type?String(meeting.meeting_type):null,
    meeting.status?`Status: ${meeting.status}`:null,
  ].filter(Boolean);

  return <section className="archive-entity-card" aria-label="Hearing details" data-archive-entity="hearing">
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">{contextParts.join(' · ')||'Congressional Hearing'}</p>
        <div className="archive-pill-list">
          {onFilterDocuments&&<button type="button" className="explorer-text-button" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>{closeLabel||'Close hearing details'}</button>}
        </div>
      </div>
      <h2>{meeting.title||`Hearing ${eventId}`}</h2>
      <p className="archive-entity-meta">
        {meeting.meeting_date&&<span><strong>Date:</strong> {day(meeting.meeting_date)}</span>}
        {eventId&&<>
          {meeting.meeting_date&&<span aria-hidden="true"> · </span>}
          <span>Event ID: {eventId}</span>
        </>}
      </p>
    </header>

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
          const loc=[s.building,s.room,s.location,s.address].filter(Boolean).join(' ');
          const when=s.datetime||s.date||s.start_time||'';
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
          const tracks:any[]=Array.isArray(rec.tracks)?rec.tracks:Array.isArray(rec.transcripts)?rec.transcripts:[];
          return <li key={rec.video_key||rec.video_id||i}>
            {rec.url?<PublicLink url={rec.url}>{rec.title||rec.source||`Recording ${i+1}`}</PublicLink>:<strong>{rec.title||rec.source||`Recording ${i+1}`}</strong>}
            {rec.source&&<span className="archive-source-meta"> ({rec.source}{duration?`, ${duration}`:''})</span>}
            {!rec.source&&duration&&<span className="archive-source-meta"> ({duration})</span>}
            {tracks.length>0&&<span className="archive-source-meta">
              <span aria-hidden="true"> · </span>
              Captions: {tracks.map((t:any,ti:number)=><span key={ti}>
                {ti>0&&', '}
                {t.url?<PublicLink url={t.url}>{t.label||t.language||'Captions'}</PublicLink>:<span>{t.label||t.language||'Captions'}</span>}
              </span>)}
            </span>}
          </li>;
        })}
      </ul>
    </div>}

    {transcripts.length>0&&<div className="archive-entity-section">
      <h3>Official Transcripts</h3>
      <ul className="archive-entity-list">
        {transcripts.map((tr:any,i:number)=>{
          const label=tr.title||tr.jacket_number||`Transcript ${i+1}`;
          const hasRow=tr.list_row!=null&&Number.isSafeInteger(Number(tr.list_row));
          return <li key={tr.jacket_number||i}>
            {hasRow&&onSelect
              ?<button type="button" className="explorer-text-button" onClick={()=>onSelect(Number(tr.list_row))}>{label}</button>
              :tr.url?<PublicLink url={tr.url}>{label}</PublicLink>:<span>{label}</span>}
            {tr.jacket_number&&tr.title&&<span className="archive-source-meta"> (Jacket {tr.jacket_number})</span>}
          </li>;
        })}
      </ul>
    </div>}

    {witnesses.length>0&&<div className="archive-entity-section">
      <h3>Witnesses ({witnesses.length})</h3>
      <ul className="archive-witness-list">
        {witnesses.map((w:any,i:number)=>{
          const wKey=w.witness_key||w.name_key||'';
          const roleParts=[w.position,w.organization,w.on_behalf_of?`on behalf of ${w.on_behalf_of}`:null].filter(Boolean);
          const docs:any[]=Array.isArray(w.documents)?w.documents:[];
          return <li key={wKey||i} className="archive-witness-item">
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

    {documents.length>0&&onSelect&&<div className="archive-entity-section">
      <h3>Hearing Documents ({documents.length})</h3>
      <ul className="archive-entity-list">
        {documents.slice(0,25).map((doc:any)=>{
          const pres=presentDocument(doc,undefined,undefined,undefined,committeesCatalog);
          return <li key={doc.list_row}>
            <button type="button" className="explorer-text-button" onClick={()=>onSelect(doc.list_row)}>{pres.title}</button>
            {doc.document_date&&<span className="archive-source-meta"> · {day(doc.document_date)}</span>}
          </li>;
        })}
      </ul>
    </div>}
  </section>;
}
