import {dateLabels, recoveryLabel, savedCopy} from '../reader/archive.ts';
import {formatLabel} from './ArchiveFormats.tsx';
import {
  cleanIdentityNote,
  effectiveFormat,
  formatBytes,
  formatSubject,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {ArchiveRows, PublicLink, day, siteBase} from './ArchiveRows.tsx';
import {HearingDetail} from './HearingDetail.tsx';
import {CommitteeDetail} from './CommitteeDetail.tsx';
import {WitnessDetail} from './WitnessDetail.tsx';
import {MemberDetail} from './MemberDetail.tsx';
import {SubjectDetail} from './SubjectDetail.tsx';

export {
  ArchiveRows,
  HearingDetail,
  CommitteeDetail,
  WitnessDetail,
  MemberDetail,
  SubjectDetail,
  siteBase,
};

export const keyHex=(value: any)=>typeof value==='string'?value:[...value].map((v:number)=>v.toString(16).padStart(2,'0')).join('');
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

function CopyLink({detail,label,rawBase,onOpenSaved}:{detail:any;label:string;rawBase:string;onOpenSaved:(detail:any)=>void}){
  const saved=savedCopy(detail,rawBase),unpack=detail.saved_suffix==='.gz'&&!saved.compressedDownload;
  const size=formatBytes(detail.saved_bytes);
  return <span className="archive-copy-link">
    <a href={saved.url} target="_blank" rel="noreferrer" download={saved.compressedDownload||undefined}
      onClick={unpack?event=>{event.preventDefault();onOpenSaved(detail);}:undefined}>{label}{saved.compressedDownload?' — compressed download (over 100 MB unpacked)':''}</a>
    {size&&<span className="archive-copy-size"> ({size})</span>}
  </span>;
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
  const packageId=typeof detail?.package_id==='string'&&/^(?:(?:CHRG|CRPT|CDOC|CPRT)-[0-9a-z-]+|BILLS-\d{3}(?:hr|s|hjres|sjres|hconres|sconres|hres|sres)\d+[a-z0-9]*)$/i.test(detail.package_id.trim())?detail.package_id.trim():'';
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
      {source.listed_on&&source.listed_on!==source.url&&<p className="archive-source-meta">Listed on <PublicLink url={source.listed_on}/></p>}
      {source.posted&&<p className="archive-source-meta">Posted {day(source.posted)}</p>}
    </li>)}</ul>:<p>No source address is recorded.</p>}</section>}
    {presented.committeeItems.length>0&&<section><h3>Committees</h3><ul>{presented.committeeItems.map(item=><li key={item.code} className="archive-hearing-row">
      {onCommittee?<button type="button" onClick={()=>onCommittee(item.code)}>{item.label}</button>:<span>{item.label}</span>}
    </li>)}</ul></section>}
    {hearingKeys.length>0&&<section><h3>Hearings</h3><ul>{hearingKeys.map((key:string)=>{
      const m=meetingMap.get(String(key));
      const recs:any[]=Array.isArray(m?.recordings)&&m.recordings.length?m.recordings:Array.isArray(m?.videos)?m.videos:[];
      return <li key={key} className="archive-hearing-row">
        <button type="button" onClick={()=>onHearing(key)}>{meetingLabels.get(String(key))||key}</button>
        {m?.meeting_date&&<span className="archive-source-meta"><span aria-hidden="true"> · </span>{day(m.meeting_date)}</span>}
        {m?.status&&<span className="archive-source-meta"><span aria-hidden="true"> · </span>{m.status}</span>}
        {recs.length>0&&recs[0]?.url&&<span className="archive-source-meta"><span aria-hidden="true"> · </span><PublicLink url={recs[0].url}>Watch recording</PublicLink></span>}
      </li>;
    })}</ul></section>}
    {versions.some(row=>row.list_row!==document.list_row)&&<section><h3>Other versions</h3><ul>{versions.filter(row=>row.list_row!==document.list_row).map(row=>{
      const ver=presentDocument(row,undefined,undefined,undefined,catalog);
      return <li key={row.list_row}><button type="button" onClick={()=>onSelect(row.list_row)}>{ver.title}</button> · {dateLabels(row,row).capture}{ver.format?` · ${ver.format}`:''}</li>;
    })}</ul></section>}
  </article>;
}
