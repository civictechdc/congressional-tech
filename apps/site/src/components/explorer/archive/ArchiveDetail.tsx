import {dateLabels, recoveryLabel, savedCopy} from '../reader/archive.ts';
import {validUrl} from '../browse/provenance.ts';
import {formatLabel} from './ArchiveFormats.tsx';
import {
  cleanIdentityNote,
  committeeLabel,
  committeeShortLabel,
  congressGovBillUrl,
  congressGovMemberUrl,
  congressGovNominationUrl,
  congressLabel,
  effectiveFormat,
  formatBytes,
  formatDuration,
  formatMeasure,
  formatSubject,
  gpoBillUrl,
  presentDocument,
  spicyRegsUrl,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';

export const keyHex=(value: any)=>typeof value==='string'?value:[...value].map((v:number)=>v.toString(16).padStart(2,'0')).join('');
const day=(value:any)=>value instanceof Date?value.toISOString().slice(0,10):value?String(value).slice(0,10):'';
const mediaTypes:Record<string,string>={
  pdf:'application/pdf',
  xml:'application/xml',
  html:'text/html',
  json:'application/json',
  txt:'text/plain',
  text:'text/plain',
  zip:'application/zip',
  doc:'application/msword',
  docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
};
export const bodyDetail=(record:any,format:string)=>{
  const fmt=String(format??'').toLowerCase();
  return {saved_body:record.body,saved_suffix:record.suffix,saved_bytes:record.size??record.bytes,saved_media_type:mediaTypes[fmt]??'application/octet-stream'};
};

function PublicLink({url,children}:{url:any;children?:any}){
  const target=validUrl(url);return target?<a href={target.href} target="_blank" rel="noreferrer">{children||target.href}</a>:null;
}
function CopyLink({detail,label,rawBase,onOpenSaved}:{detail:any;label:string;rawBase:string;onOpenSaved:(detail:any)=>void}){
  const saved=savedCopy(detail,rawBase),unpack=detail.saved_suffix==='.gz'&&!saved.compressedDownload;
  const size=formatBytes(detail.saved_bytes);
  return <span className="archive-copy-link">
    <a href={saved.url} target="_blank" rel="noreferrer" download={saved.compressedDownload||undefined}
      onClick={unpack?event=>{event.preventDefault();onOpenSaved(detail);}:undefined}>{label}{saved.compressedDownload?' — compressed download (over 100 MB unpacked)':''}</a>
    {size&&<span className="archive-copy-size"> ({size})</span>}
  </span>;
}

export function ArchiveRows({
  rows,
  committeesCatalog,
  onSelect,
}:{
  rows:any[];
  committeesCatalog?:CommitteeCatalogInput;
  onSelect:(row:number)=>void;
}){
  return <ul className="archive-rows">{rows.map(row=>{
    const labels=dateLabels(row,row);
    const presented=presentDocument(row,undefined,undefined,undefined,committeesCatalog);
    return <li key={row.list_row}>
      <div className="archive-row-main">
        {presented.contextParts.length>0&&<span className="archive-row-context">{presented.contextParts.join(' · ')}</span>}
        <button className="archive-document" onClick={()=>onSelect(row.list_row)}>
          <strong>{presented.title}</strong>
          {presented.subtitle&&<span className="archive-document-subtitle">{presented.subtitle}</span>}
        </button>
      </div>
      <span className="archive-row-format">{formatLabel(effectiveFormat(row))}</span>
      <div className="archive-row-dates">
        {labels.document?<span>Document date: {labels.document}</span>:<span>{labels.capture}</span>}
        {labels.removed&&<span className="archive-row-removed">Removed from hearing page</span>}
      </div>
    </li>;
  })}</ul>;
}
export const siteBase = () => {
  const raw = (import.meta.env as any)?.BASE_URL || (globalThis as any).__SITE_BASE_URL__ || '';
  return String(raw).replace(/\/+$/, '');
};

export function HearingDetail({
  meeting,
  committeesCatalog,
  onSelect,
  onCommittee,
  onSubject,
  onWitness,
  onMember,
  onClose,
}:{
  meeting:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onCommittee?:(key:string)=>void;
  onSubject?:(key:string)=>void;
  onWitness?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onClose?:()=>void;
}){
  if(!meeting)return null;
  const base=siteBase();
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
        {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>Close hearing details</button>}
      </div>
      <h2>{meeting.title||`Hearing ${eventId}`}</h2>
      <p className="archive-entity-meta">
        {meeting.meeting_date&&<span><strong>Date:</strong> {day(meeting.meeting_date)}</span>}
        {eventId&&<>
          {meeting.meeting_date&&<span aria-hidden="true"> · </span>}
          <span>Event ID: {eventId}</span>
          <span aria-hidden="true"> · </span>
          <a href={`${base}/dashboard/?meeting=${encodeURIComponent(eventId)}`}>Open in Committee Explorer</a>
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
            <span aria-hidden="true"> · </span>
            <a href={`${base}/dashboard/?committee=${encodeURIComponent(code)}`}>Committee Explorer</a>
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
  </section>;
}

export function CommitteeDetail({
  committee,
  committeesCatalog,
  onSelect,
  onCommittee,
  onHearing,
  onMember,
  onCongressChange,
  onClose,
}:{
  committee:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onCommittee?:(key:string)=>void;
  onHearing?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onCongressChange?:(congress:string)=>void;
  onClose?:()=>void;
}){
  if(!committee)return null;
  const base=siteBase();
  const code=String(committee.committee_key??committee.system_code??'').toLowerCase();
  const displayName=committee.resolved_name||committee.current_name||committee.name||committeeLabel(code,committeesCatalog);
  const subcommittees:any[]=Array.isArray(committee.subcommittees)?committee.subcommittees:[];
  const roster:any[]=Array.isArray(committee.roster)?committee.roster:[];
  const hearings:any[]=Array.isArray(committee.hearings)?committee.hearings:[];
  const namesHistory:any[]=Array.isArray(committee.names)?committee.names:[];
  const congresses:number[]=Array.isArray(committee.roster_congresses)?committee.roster_congresses:[];

  return <section className="archive-entity-card" aria-label="Committee details" data-archive-entity="committee">
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">
          {[
            committee.chamber?String(committee.chamber).charAt(0).toUpperCase()+String(committee.chamber).slice(1):null,
            committee.type||committee.committee_type,
            code.toUpperCase(),
          ].filter(Boolean).join(' · ')}
        </p>
        {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>Clear committee filter</button>}
      </div>
      <h2>{displayName}</h2>
      <p className="archive-entity-meta">
        <span><strong>Documents:</strong> {Number(committee.doc_count??0).toLocaleString()}</span>
        <span aria-hidden="true"> · </span>
        <span><strong>Hearings:</strong> {Number(committee.hearing_count??hearings.length).toLocaleString()}</span>
        {committee.url&&<>
          <span aria-hidden="true"> · </span>
          <PublicLink url={committee.url}>Committee website</PublicLink>
        </>}
        {committee.minority_url&&<>
          <span aria-hidden="true"> · </span>
          <PublicLink url={committee.minority_url}>Minority website</PublicLink>
        </>}
        <span aria-hidden="true"> · </span>
        <a href={`${base}/dashboard/?committee=${encodeURIComponent(code)}`}>Open in Committee Explorer</a>
      </p>
      {committee.parent_key&&<p className="archive-source-meta">
        Parent committee:{' '}
        {onCommittee
          ?<button type="button" className="explorer-text-button" onClick={()=>onCommittee(committee.parent_key)}>
              {committee.parent?.current_name||committeeLabel(committee.parent_key,committeesCatalog)}
            </button>
          :<span>{committee.parent?.current_name||committeeLabel(committee.parent_key,committeesCatalog)}</span>}
      </p>}
    </header>

    {committee.jurisdiction&&<div className="archive-entity-section">
      <h3>Jurisdiction</h3>
      <p>{committee.jurisdiction}</p>
    </div>}

    {namesHistory.length>1&&<div className="archive-entity-section">
      <h3>Historical Names</h3>
      <ul className="archive-entity-list">
        {namesHistory.map((h:any,i:number)=><li key={i}>
          <strong>{h.name}</strong>
          {(h.start||h.end||h.congress)&&<span className="archive-source-meta">
            {' '}({h.congress?`${h.congress}th Congress`:`${h.start||'…'} to ${h.end||'present'}`})
          </span>}
        </li>)}
      </ul>
    </div>}

    {subcommittees.length>0&&<div className="archive-entity-section">
      <h3>Subcommittees ({subcommittees.length})</h3>
      <div className="archive-pill-list">
        {subcommittees.map((sub:any,i:number)=>{
          const subCode=String(typeof sub==='string'?sub:(sub.committee_key??sub.system_code??'')).toLowerCase();
          const subLabel=typeof sub==='object'&&(sub.current_name||sub.name)?(sub.current_name||sub.name):committeeLabel(subCode,committeesCatalog);
          return onCommittee
            ?<button key={subCode||i} type="button" className="archive-measure-pill" onClick={()=>onCommittee(subCode)}>{subLabel}</button>
            :<span key={subCode||i} className="archive-measure-pill">{subLabel}</span>;
        })}
      </div>
    </div>}

    {roster.length>0&&<div className="archive-entity-section">
      <div className="archive-entity-section-header">
        <h3>Roster {committee.active_congress?`(${congressLabel(committee.active_congress)})`:''}</h3>
        {congresses.length>1&&onCongressChange&&<label className="archive-inline-select">
          <span>Congress: </span>
          <select value={committee.active_congress??''} onChange={e=>onCongressChange(e.target.value)}>
            {congresses.map(c=><option key={c} value={c}>{congressLabel(c)}</option>)}
          </select>
        </label>}
      </div>
      <ul className="archive-roster-list">
        {roster.map((member:any,i:number)=>{
          const meta=[member.party,member.state,member.role&&member.role!=='Member'?member.role:null].filter(Boolean).join(', ');
          return <li key={member.bioguide_id||i}>
            {member.bioguide_id&&onMember
              ?<button type="button" className="explorer-text-button" onClick={()=>onMember(String(member.bioguide_id))}><strong>{member.name||member.bioguide_id}</strong></button>
              :<strong>{member.name||member.bioguide_id}</strong>}
            {meta&&<span className="archive-source-meta"> ({meta})</span>}
          </li>;
        })}
      </ul>
    </div>}

    {hearings.length>0&&<div className="archive-entity-section">
      <h3>Hearings ({hearings.length})</h3>
      <ul className="archive-entity-list">
        {hearings.slice(0,15).map((h:any)=>{
          const ev=String(h.event_id??h.meeting_key??'');
          return <li key={ev}>
            {onHearing
              ?<button type="button" className="explorer-text-button" onClick={()=>onHearing(ev)}>{h.title||`Hearing ${ev}`}</button>
              :<span>{h.title||`Hearing ${ev}`}</span>}
            {h.meeting_date&&<span className="archive-source-meta"> · {day(h.meeting_date)}</span>}
          </li>;
        })}
      </ul>
    </div>}
  </section>;
}

export function WitnessDetail({
  witness,
  committeesCatalog,
  onSelect,
  onHearing,
  onCommittee,
  onMember,
  onClose,
}:{
  witness:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onHearing?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onClose?:()=>void;
}){
  if(!witness)return null;
  const organizations:string[]=Array.isArray(witness.organizations)?witness.organizations:witness.organization?[witness.organization]:[];
  const positions:string[]=Array.isArray(witness.positions)?witness.positions:witness.position?[witness.position]:[];
  const appearances:any[]=Array.isArray(witness.appearances)?witness.appearances:[];
  const documents:any[]=Array.isArray(witness.documents)?witness.documents:[];

  return <section className="archive-entity-card" aria-label="Witness details" data-archive-entity="witness">
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">Congressional Witness</p>
        {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>Clear witness filter</button>}
      </div>
      <h2>{witness.name||witness.witness_key}</h2>
      {organizations.length>0&&<p className="archive-entity-meta"><strong>Organizations:</strong> {organizations.join(' · ')}</p>}
      {positions.length>0&&<p className="archive-entity-meta"><strong>Positions:</strong> {positions.join(' · ')}</p>}
      {witness.bioguide_id&&<p className="archive-entity-meta">
        <strong>Member of Congress:</strong>{' '}
        {onMember
          ?<button type="button" className="archive-measure-pill" onClick={()=>onMember(String(witness.bioguide_id))}>
              View Member Profile ({witness.bioguide_id})
            </button>
          :<span>{witness.bioguide_id}</span>}
      </p>}
    </header>

    {appearances.length>0&&<div className="archive-entity-section">
      <h3>Hearing Appearances ({appearances.length})</h3>
      <ul className="archive-entity-list">
        {appearances.map((app:any,i:number)=>{
          const ev=String(app.event_id??app.meeting_key??'');
          const title=app.meeting_title||app.title||`Hearing ${ev}`;
          const role=[app.position,app.organization].filter(Boolean).join(' — ');
          return <li key={ev||i}>
            {ev&&onHearing
              ?<button type="button" className="explorer-text-button" onClick={()=>onHearing(ev)}><strong>{title}</strong></button>
              :<strong>{title}</strong>}
            {app.meeting_date&&<span className="archive-source-meta"> · {day(app.meeting_date)}</span>}
            {app.panel!=null&&<span className="archive-source-meta"> · Panel {String(app.panel)}</span>}
            {role&&<p className="archive-source-meta">{role}</p>}
            {Array.isArray(app.committee_keys)&&app.committee_keys.length>0&&<div className="archive-pill-list">
              {app.committee_keys.map((ck:string)=>onCommittee
                ?<button key={ck} type="button" className="archive-measure-pill" onClick={()=>onCommittee(ck)}>{committeeShortLabel(ck,committeesCatalog,app.meeting_date||app.congress)}</button>
                :<span key={ck} className="archive-measure-pill">{committeeShortLabel(ck,committeesCatalog,app.meeting_date||app.congress)}</span>)}
            </div>}
          </li>;
        })}
      </ul>
    </div>}

    {documents.length>0&&onSelect&&<div className="archive-entity-section">
      <h3>Submitted Documents ({documents.length})</h3>
      <ul className="archive-entity-list">
        {documents.slice(0,20).map((doc:any)=>{
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

export function MemberDetail({
  member,
  committeesCatalog,
  onSelect,
  onHearing,
  onCommittee,
  onSubject,
  onClose,
}:{
  member:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onHearing?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onSubject?:(key:string)=>void;
  onClose?:()=>void;
}){
  if(!member)return null;
  const base=siteBase();
  const bio=String(member.bioguide_id??'');
  const terms:any[]=Array.isArray(member.terms)?member.terms:[];
  const committees:any[]=Array.isArray(member.roster_entries)&&member.roster_entries.length
    ?member.roster_entries
    :Array.isArray(member.committees)?member.committees:[];
  const hearings:any[]=Array.isArray(member.hearings)?member.hearings:[];
  const sponsoredBills:any[]=Array.isArray(member.sponsored_bills)?member.sponsored_bills:[];
  const congressGovUrl=congressGovMemberUrl(bio,member.name);
  const metaParts=[
    member.party,
    member.state?(member.district!=null?`${member.state}-${member.district}`:member.state):null,
    member.chamber?String(member.chamber).charAt(0).toUpperCase()+String(member.chamber).slice(1):null,
    bio?`Bioguide: ${bio}`:null,
  ].filter(Boolean);

  return <section className="archive-entity-card" aria-label="Member details" data-archive-entity="member">
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">{metaParts.join(' · ')||'Member of Congress'}</p>
        {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>Clear member filter</button>}
      </div>
      <h2>{member.name||bio}</h2>
      <p className="archive-entity-meta">
        {member.official_url&&<>
          <PublicLink url={member.official_url}>Official website</PublicLink>
          <span aria-hidden="true"> · </span>
        </>}
        {congressGovUrl&&<>
          <PublicLink url={congressGovUrl}>Congress.gov profile</PublicLink>
          <span aria-hidden="true"> · </span>
        </>}
        <a href={`${base}/dashboard/?q=${encodeURIComponent(member.name||bio)}`}>Open in Committee Explorer</a>
      </p>
    </header>

    {terms.length>0&&<div className="archive-entity-section">
      <h3>Congressional Terms ({terms.length})</h3>
      <ul className="archive-entity-list">
        {terms.map((t:any,i:number)=><li key={i}>
          <strong>{t.congress?congressLabel(t.congress):`${t.start_year||t.start||''}–${t.end_year||t.end||''}`}</strong>
          <span className="archive-source-meta">
            {' '}— {[t.chamber,t.party,t.state?(t.district!=null?`${t.state}-${t.district}`:t.state):null].filter(Boolean).join(', ')}
          </span>
        </li>)}
      </ul>
    </div>}

    {committees.length>0&&<div className="archive-entity-section">
      <h3>Committee Assignments</h3>
      <ul className="archive-entity-list">
        {committees.map((c:any,i:number)=>{
          const code=String(c.committee_key??c.system_code??'').toLowerCase();
          const label=c.name||committeeLabel(code,committeesCatalog,c.congress);
          return <li key={`${code}-${c.congress??i}`}>
            {code&&onCommittee
              ?<button type="button" className="explorer-text-button" onClick={()=>onCommittee(code)}><strong>{label}</strong></button>
              :<strong>{label}</strong>}
            <span className="archive-source-meta">
              {' '}{[c.congress?congressLabel(c.congress):null,c.role||c.title].filter(Boolean).join(' · ')}
            </span>
          </li>;
        })}
      </ul>
    </div>}

    {sponsoredBills.length>0&&<div className="archive-entity-section">
      <h3>Sponsored Legislation ({sponsoredBills.length})</h3>
      <ul className="archive-entity-list">
        {sponsoredBills.map((b:any)=>{
          const sk=String(b.subject_key??b.bill_id??'');
          return <li key={sk}>
            {onSubject
              ?<button type="button" className="explorer-text-button" onClick={()=>onSubject(sk)}>
                  <strong>{formatSubject(sk,b)}</strong>{b.short_title||b.title?` — ${b.short_title||b.title}`:''}
                </button>
              :<span><strong>{formatSubject(sk,b)}</strong>{b.short_title||b.title?` — ${b.short_title||b.title}`:''}</span>}
          </li>;
        })}
      </ul>
    </div>}

    {hearings.length>0&&<div className="archive-entity-section">
      <h3>Hearing Appearances ({hearings.length})</h3>
      <ul className="archive-entity-list">
        {hearings.map((h:any,i:number)=>{
          const ev=String(h.event_id??h.meeting_key??'');
          return <li key={ev||i}>
            {ev&&onHearing
              ?<button type="button" className="explorer-text-button" onClick={()=>onHearing(ev)}>{h.title||`Hearing ${ev}`}</button>
              :<span>{h.title||`Hearing ${ev}`}</span>}
            {h.meeting_date&&<span className="archive-source-meta"> · {day(h.meeting_date)}</span>}
          </li>;
        })}
      </ul>
    </div>}
  </section>;
}

export function SubjectDetail({
  subject,
  committeesCatalog,
  onSelect,
  onHearing,
  onCommittee,
  onMember,
  onSubject,
  onClose,
}:{
  subject:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onHearing?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onSubject?:(key:string)=>void;
  onClose?:()=>void;
}){
  if(!subject)return null;
  const isNom=subject.kind==='nomination'||Boolean(subject.nomination_id)||/^(?:\d+-)?pn-/i.test(String(subject.subject_key??''));
  const key=String(subject.subject_key??subject.bill_id??subject.nomination_id??'');
  const label=formatSubject(key,subject);
  const heading=subject.short_title||subject.title||subject.description||label;
  const congressUrl=isNom?congressGovNominationUrl(subject):congressGovBillUrl(subject);
  const gpoUrl=isNom?null:gpoBillUrl(subject);
  const regsUrl=spicyRegsUrl(label);
  const committees:any[]=Array.isArray(subject.committees)?subject.committees:[];
  const activities:any[]=Array.isArray(subject.committee_activities)?subject.committee_activities:[];
  const cboEstimates:any[]=Array.isArray(subject.cbo_estimates)?subject.cbo_estimates:[];
  const votes:any[]=Array.isArray(subject.votes)?subject.votes:Array.isArray(subject.floor_votes)?subject.floor_votes:[];
  const amendments:any[]=Array.isArray(subject.amendments)?subject.amendments:[];
  const relatedBills:any[]=Array.isArray(subject.related_bills)?subject.related_bills:[];
  const nominees:any[]=Array.isArray(subject.nominees)?subject.nominees:[];
  const hearings:any[]=Array.isArray(subject.hearings)?subject.hearings:[];
  const laws:any[]=Array.isArray(subject.laws)?subject.laws:[];

  const contextParts=[
    congressLabel(subject.congress),
    isNom?'Presidential Nomination':'Legislation',
    label,
    subject.status||subject.stage,
    subject.policy_area,
  ].filter(Boolean);

  return <section className="archive-entity-card" aria-label={isNom?'Nomination details':'Legislation details'} data-archive-entity={isNom?'nomination':'bill'}>
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">{contextParts.join(' · ')}</p>
        {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>Clear subject filter</button>}
      </div>
      <h2>{label}{heading&&heading!==label?` — ${heading}`:''}</h2>
      {subject.short_title&&subject.title&&subject.title!==subject.short_title&&<p className="archive-source-meta">{subject.title}</p>}
      <p className="archive-entity-meta">
        {(subject.introduced_date||subject.received_date)&&<span>
          <strong>{isNom?'Received:':'Introduced:'}</strong> {day(subject.introduced_date||subject.received_date)}
          <span aria-hidden="true"> · </span>
        </span>}
        {subject.sponsor_name&&<span>
          <strong>Sponsor:</strong>{' '}
          {subject.sponsor_bioguide_id&&onMember
            ?<button type="button" className="explorer-text-button" onClick={()=>onMember(String(subject.sponsor_bioguide_id))}>
                {subject.sponsor_name}
              </button>
            :<span>{subject.sponsor_name}</span>}
          {(subject.sponsor_party||subject.sponsor_state)&&` (${[subject.sponsor_party,subject.sponsor_state].filter(Boolean).join('-')})`}
          <span aria-hidden="true"> · </span>
        </span>}
        {subject.organization&&<span>
          <strong>Organization:</strong> {subject.organization}
          <span aria-hidden="true"> · </span>
        </span>}
        {congressUrl&&<>
          <PublicLink url={congressUrl}>Congress.gov</PublicLink>
          <span aria-hidden="true"> · </span>
        </>}
        {gpoUrl&&<>
          <PublicLink url={gpoUrl}>GPO GovInfo</PublicLink>
          <span aria-hidden="true"> · </span>
        </>}
        {regsUrl&&<PublicLink url={regsUrl}>spicy-regs</PublicLink>}
      </p>
      {(subject.latest_action_date||subject.latest_action_text)&&<p className="archive-source-meta">
        <strong>Latest action{subject.latest_action_date?` (${day(subject.latest_action_date)})`:''}:</strong> {subject.latest_action_text||'Recorded'}
      </p>}
      {laws.length>0&&<p className="archive-source-meta">
        <strong>Public Law:</strong> {laws.map((l:any)=>typeof l==='string'?l:`${l.type||'P.L.'} ${l.number||''}`).join(', ')}
      </p>}
    </header>

    {nominees.length>0&&<div className="archive-entity-section">
      <h3>Nominees ({nominees.length})</h3>
      <ul className="archive-entity-list">
        {nominees.map((nom:any,i:number)=><li key={i}>
          <strong>{nom.name||`Part ${nom.ordinal??i+1}`}</strong>
          <span className="archive-source-meta">
            {' '}{[nom.position_title,nom.organization,nom.state,nom.nominee_count?`${nom.nominee_count} nominees`:null].filter(Boolean).join(' — ')}
          </span>
        </li>)}
      </ul>
    </div>}

    {(committees.length>0||activities.length>0)&&<div className="archive-entity-section">
      <h3>Committees &amp; Activities</h3>
      {committees.length>0&&<div className="archive-pill-list">
        {committees.map((c:any,i:number)=>{
          const code=String(typeof c==='string'?c:(c.committee_key??c.system_code??'')).toLowerCase();
          const cLabel=typeof c==='object'&&c.name?c.name:committeeLabel(code,committeesCatalog,subject.congress);
          return code&&onCommittee
            ?<button key={code||i} type="button" className="archive-measure-pill" onClick={()=>onCommittee(code)}>{cLabel}</button>
            :<span key={code||i} className="archive-measure-pill">{cLabel}</span>;
        })}
      </div>}
      {activities.length>0&&<ul className="archive-entity-list">
        {activities.map((act:any,i:number)=>{
          const code=String(act.committee_key??act.system_code??'').toLowerCase();
          return <li key={i}>
            <strong>{act.activity||act.name||'Activity'}</strong>
            {code&&<span className="archive-source-meta"> · {committeeShortLabel(code,committeesCatalog,subject.congress)}</span>}
            {act.date&&<span className="archive-source-meta"> · {day(act.date)}</span>}
          </li>;
        })}
      </ul>}
    </div>}

    {cboEstimates.length>0&&<div className="archive-entity-section">
      <h3>CBO Cost Estimates ({cboEstimates.length})</h3>
      <ul className="archive-entity-list">
        {cboEstimates.map((cbo:any,i:number)=><li key={i}>
          {cbo.url?<PublicLink url={cbo.url}>{cbo.title||`CBO Estimate ${i+1}`}</PublicLink>:<strong>{cbo.title||`CBO Estimate ${i+1}`}</strong>}
          {(cbo.pub_date||cbo.date)&&<span className="archive-source-meta"> · {day(cbo.pub_date||cbo.date)}</span>}
        </li>)}
      </ul>
    </div>}

    {votes.length>0&&<div className="archive-entity-section">
      <h3>Floor Votes ({votes.length})</h3>
      <ul className="archive-entity-list">
        {votes.map((v:any,i:number)=><li key={i}>
          <strong>{[v.chamber,v.roll_number!=null?`Roll #${v.roll_number}`:null,v.result].filter(Boolean).join(' · ')||`Vote ${i+1}`}</strong>
          {v.date&&<span className="archive-source-meta"> · {day(v.date)}</span>}
          {v.question&&<span className="archive-source-meta"> — {v.question}</span>}
          {(v.yea!=null||v.nay!=null)&&<span className="archive-source-meta"> ({v.yea??0}–{v.nay??0})</span>}
          {v.url&&<>
            <span aria-hidden="true"> · </span>
            <PublicLink url={v.url}>Roll call</PublicLink>
          </>}
        </li>)}
      </ul>
    </div>}

    {(subject.amendment_count>0||amendments.length>0)&&<div className="archive-entity-section">
      <h3>Amendments ({subject.amendment_count||amendments.length})</h3>
      {amendments.length>0&&<ul className="archive-entity-list">
        {amendments.slice(0,15).map((amdt:any,i:number)=><li key={amdt.amendment_id||amdt.number||i}>
          <strong>{amdt.type||amdt.amendment_type||'Amdt.'} {amdt.number||amdt.amendment_number||i+1}</strong>
          {amdt.sponsor_name&&<span className="archive-source-meta"> ({amdt.sponsor_name})</span>}
          {(amdt.purpose||amdt.description)&&<span className="archive-source-meta"> — {amdt.purpose||amdt.description}</span>}
        </li>)}
      </ul>}
    </div>}

    {relatedBills.length>0&&<div className="archive-entity-section">
      <h3>Related Legislation ({relatedBills.length})</h3>
      <div className="archive-pill-list">
        {relatedBills.map((rb:any,i:number)=>{
          const rbKey=String(rb.subject_key??rb.bill_id??'');
          const rbLabel=formatSubject(rbKey,rb);
          return rbKey&&onSubject
            ?<button key={rbKey||i} type="button" className="archive-measure-pill" onClick={()=>onSubject(rbKey)}>
                {rbLabel}{rb.relationship||rb.type?` (${rb.relationship||rb.type})`:''}
              </button>
            :<span key={rbKey||i} className="archive-measure-pill">{rbLabel}</span>;
        })}
      </div>
    </div>}

    {hearings.length>0&&<div className="archive-entity-section">
      <h3>Related Hearings ({hearings.length})</h3>
      <ul className="archive-entity-list">
        {hearings.map((h:any)=>{
          const ev=String(h.event_id??h.meeting_key??'');
          return <li key={ev}>
            {onHearing
              ?<button type="button" className="explorer-text-button" onClick={()=>onHearing(ev)}>{h.title||`Hearing ${ev}`}</button>
              :<span>{h.title||`Hearing ${ev}`}</span>}
            {h.meeting_date&&<span className="archive-source-meta"> · {day(h.meeting_date)}</span>}
          </li>;
        })}
      </ul>
    </div>}
  </section>;
}

export function ArchiveDetail({
  entry,
  meetings=[],
  meetingDetails=[],
  versions=[],
  committees=[],
  subjects=[],
  witnesses=[],
  members=[],
  committeesCatalog,
  rawBase,
  onSelect,
  onHearing,
  onMeasure,
  onSubject,
  onCommittee,
  onWitness,
  onMember,
  onOpenSaved,
}:{
  entry:any;
  meetings?:any[];
  meetingDetails?:any[];
  versions?:any[];
  committees?:any[];
  subjects?:any[];
  witnesses?:any[];
  members?:any[];
  committeesCatalog?:CommitteeCatalogInput;
  rawBase:string;
  onSelect:(row:number)=>void;
  onHearing:(key:string)=>void;
  onMeasure?:(key:string)=>void;
  onSubject?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onWitness?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onOpenSaved:(detail:any)=>void;
}){
  const {document,detail,sources,recoveries}=entry,labels=dateLabels(document,detail);
  const catalog=committeesCatalog??committees;
  const presented=presentDocument(document,detail,sources,recoveries,catalog);
  const base=siteBase();
  const congressParam=document.congress?`&congress=${encodeURIComponent(String(document.congress))}`:'';
  const packageId=typeof detail?.package_id==='string'&&/^(?:CHRG|BILLS|CRPT|CDOC|CPRT)-[0-9a-z-]+$/i.test(detail.package_id.trim())?detail.package_id.trim():'';
  const primaryFormat=effectiveFormat(document,detail);
  const primaryDetail=primaryFormat!==String(document.format??'').toLowerCase()&&mediaTypes[primaryFormat]
    ?{...detail,saved_media_type:mediaTypes[primaryFormat]}
    :detail;
  const meetingMap=new Map<string,any>();
  for(const item of meetings)meetingMap.set(String(item.event_id),item);
  for(const item of meetingDetails)meetingMap.set(String(item.event_id),item);
  const meetingLabels=new Map([...meetingMap.entries()].map(([k,item])=>[k,item.title||k]));
  const contextLine=[presented.congress,...presented.committees,...presented.kinds].filter(Boolean).join(' · ');
  const handleSubject=onSubject||onMeasure;

  const subjectMap=new Map<string,any>();
  for(const m of presented.measures)subjectMap.set(m.key,{subject_key:m.key,label:m.label});
  for(const s of subjects){
    const sk=String(s.subject_key??s.bill_id??s.nomination_id??'');
    if(sk)subjectMap.set(sk,{...s,subject_key:sk,label:formatSubject(sk,s)});
  }
  const allMeasures=[...subjectMap.values()];

  const witnessItems:any[]=witnesses.length
    ?witnesses
    :(document.witness_keys??[]).map((wk:string)=>({witness_key:wk,name:wk}));
  const memberItems:any[]=members.length
    ?members
    :(document.bioguide_ids??[]).map((bio:string)=>({bioguide_id:bio,name:bio}));
  const hearingKeys:string[]=[...new Set([
    ...(document.meeting_keys??[]).map(String),
    ...meetingDetails.map((m:any)=>String(m.event_id)),
  ].filter(Boolean))];

  return <article className="archive-detail" data-archive-detail>
    {document.hidden&&<aside role="note" className="archive-notice"><h2>Removed by review</h2><p>{detail.review_note||'This document was removed from the public list.'}</p>{detail.review_decided_at&&<p>Review decided {day(detail.review_decided_at)}</p>}</aside>}
    <header className="archive-detail-header">
      <p className="archive-detail-context">{contextLine||'Archived congressional document'}</p>
      <h2>{presented.title}</h2>
      {presented.subtitle&&<p className="archive-detail-filename">{presented.subtitle}</p>}
    </header>
    <div className="archive-dates">
      {labels.document&&<p><strong>Document date:</strong> {labels.document}</p>}
      <p>{labels.capture}</p>
      {packageId&&<p><strong>GovInfo package:</strong> {packageId} · <a href={`https://www.govinfo.gov/app/details/${encodeURIComponent(packageId)}`} target="_blank" rel="noreferrer">View on GovInfo</a></p>}
      {allMeasures.length>0&&<p className="archive-dates-measures"><strong>Related legislation:</strong> <span className="archive-measure-list">{allMeasures.map(m=>{
        const key=m.subject_key??m.key;
        const text=m.short_title||m.title?`${m.label} (${m.short_title||m.title})`:m.label;
        return handleSubject?<button key={key} type="button" className="archive-measure-pill" onClick={()=>handleSubject(key)}>{text}</button>:<span key={key} className="archive-measure-pill">{text}</span>;
      })}</span></p>}
      {witnessItems.length>0&&<p className="archive-dates-measures">
        <strong>Witnesses:</strong>{' '}
        <span className="archive-measure-list">
          {witnessItems.map((w:any)=>{
            const wk=String(w.witness_key??w.name_key??w.name??'');
            const label=w.organization?`${w.name||wk} (${w.organization})`:(w.name||wk);
            return onWitness
              ?<button key={wk} type="button" className="archive-measure-pill" onClick={()=>onWitness(wk)}>{label}</button>
              :<span key={wk} className="archive-measure-pill">{label}</span>;
          })}
        </span>
      </p>}
      {memberItems.length>0&&<p className="archive-dates-measures">
        <strong>Members:</strong>{' '}
        <span className="archive-measure-list">
          {memberItems.map((m:any)=>{
            const bio=String(m.bioguide_id??'');
            const label=m.party||m.state?`${m.name||bio} (${[m.party,m.state].filter(Boolean).join('-')})`:(m.name||bio);
            return onMember
              ?<button key={bio} type="button" className="archive-measure-pill" onClick={()=>onMember(bio)}>{label}</button>
              :<span key={bio} className="archive-measure-pill">{label}</span>;
          })}
        </span>
      </p>}
      {labels.removed&&<p className="archive-removed-callout">{labels.removed}</p>}
    </div>
    <section><h3>Saved copies</h3>{detail.saved_body?<ul><li><CopyLink detail={primaryDetail} label={`Open saved ${formatLabel(primaryFormat)}`} rawBase={rawBase} onOpenSaved={onOpenSaved}/></li>
      {(detail.alternates??[]).map((alternate:any,i:number)=><li key={i}><CopyLink detail={bodyDetail(alternate,alternate.format)} label={`Open alternate ${formatLabel(alternate.format)}`} rawBase={rawBase} onOpenSaved={onOpenSaved}/></li>)}</ul>:<p>No original saved copy is recorded.</p>}</section>
    {recoveries.length>0&&<section><h3>Recovered and related files</h3><ul>{recoveries.map((recovery:any,i:number)=>{
      const note=cleanIdentityNote(recovery.identity_note);
      return <li key={i}>
        <CopyLink detail={bodyDetail(recovery,primaryFormat)} label={recoveryLabel(recovery.kind)} rawBase={rawBase} onOpenSaved={onOpenSaved}/>
        {note&&<p>{note}</p>}
        {(recovery.imported_at||recovery.recovered_url)&&<p className="archive-source-meta">{recovery.imported_at&&<>Added to the archive {day(recovery.imported_at)}{recovery.recovered_url&&' · '}</>}{recovery.recovered_url&&<PublicLink url={recovery.recovered_url}>Recovery source</PublicLink>}</p>}
      </li>;
    })}</ul></section>}
    {(sources.length>0||recoveries.length===0)&&<section><h3>Sources</h3>{sources.length?<ul>{sources.map((source:any,i:number)=><li key={i}>
      <PublicLink url={source.url}>{source.link_text||source.url}</PublicLink>{source.is_saved&&<span className="archive-saved-tag"> · Saved file</span>}
      {source.member_path&&source.member_path!==document.filename&&<p className="archive-source-meta">File in archive: {source.member_path}</p>}
      {source.listed_on&&<p className="archive-source-meta">Listed on <PublicLink url={source.listed_on}/></p>}
      {source.posted&&<p className="archive-source-meta">Posted {day(source.posted)}</p>}
    </li>)}</ul>:<p>No source address is recorded.</p>}</section>}
    {presented.committeeItems.length>0&&<section><h3>Committees</h3><ul>{presented.committeeItems.map(item=><li key={item.code} className="archive-hearing-row">
      {onCommittee?<button type="button" onClick={()=>onCommittee(item.code)}>{item.label}</button>:<span>{item.label}</span>}
      <span className="archive-hearing-meta"> · <a href={`${base}/dashboard/?committee=${encodeURIComponent(item.code)}${congressParam}`}>Open in Committee Explorer</a></span>
    </li>)}</ul></section>}
    {hearingKeys.length>0&&<section><h3>Hearings</h3><ul>{hearingKeys.map((key:string)=>{
      const m=meetingMap.get(String(key));
      const recs:any[]=Array.isArray(m?.recordings)&&m.recordings.length?m.recordings:Array.isArray(m?.videos)?m.videos:[];
      return <li key={key} className="archive-hearing-row">
        <button onClick={()=>onHearing(key)}>{meetingLabels.get(String(key))||key}</button>
        <span className="archive-hearing-meta"> · <a href={`${base}/dashboard/?meeting=${encodeURIComponent(key)}${congressParam}`}>Open in Committee Explorer</a></span>
        {m?.meeting_date&&<span className="archive-source-meta"><span aria-hidden="true"> · </span>{day(m.meeting_date)}</span>}
        {m?.status&&<span className="archive-source-meta"><span aria-hidden="true"> · </span>{m.status}</span>}
        {recs.length>0&&recs[0]?.url&&<span className="archive-source-meta"><span aria-hidden="true"> · </span><PublicLink url={recs[0].url}>Watch recording</PublicLink></span>}
      </li>;
    })}</ul></section>}
    {versions.some(row=>row.list_row!==document.list_row)&&<section><h3>Other versions</h3><ul>{versions.filter(row=>row.list_row!==document.list_row).map(row=>{
      const ver=presentDocument(row,undefined,undefined,undefined,catalog);
      return <li key={row.list_row}><button onClick={()=>onSelect(row.list_row)}>{ver.title}</button> · {dateLabels(row,row).capture}</li>;
    })}</ul></section>}
  </article>;
}
