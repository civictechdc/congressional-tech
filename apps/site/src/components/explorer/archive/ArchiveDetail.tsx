import {dateLabels, recoveryLabel, savedCopy} from '../reader/archive.ts';
import {validUrl} from '../browse/provenance.ts';

export const keyHex=(value: any)=>typeof value==='string'?value:[...value].map((v:number)=>v.toString(16).padStart(2,'0')).join('');
const day=(value:any)=>value instanceof Date?value.toISOString().slice(0,10):value?String(value).slice(0,10):'';
const text=(value:any)=>String(value??'');
const mediaTypes:Record<string,string>={pdf:'application/pdf',xml:'application/xml',html:'text/html',json:'application/json',txt:'text/plain',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'};
export const bodyDetail=(record:any,format:string)=>({saved_body:record.body,saved_suffix:record.suffix,saved_bytes:record.size??record.bytes,saved_media_type:mediaTypes[format]??'application/octet-stream'});

function PublicLink({url,children}:{url:any;children?:any}){
  const target=validUrl(url);return target?<a href={target.href} target="_blank" rel="noreferrer">{children||target.href}</a>:null;
}
function CopyLink({detail,label,rawBase,onOpenSaved}:{detail:any;label:string;rawBase:string;onOpenSaved:(detail:any)=>void}){
  const saved=savedCopy(detail,rawBase),unpack=detail.saved_suffix==='.gz'&&!saved.compressedDownload;
  return <a href={saved.url} target="_blank" rel="noreferrer" download={saved.compressedDownload||undefined}
    onClick={unpack?event=>{event.preventDefault();onOpenSaved(detail);}:undefined}>{label}{saved.compressedDownload?' — compressed download (over 100 MB unpacked)':''}</a>;
}
export function ArchiveRows({rows,onSelect}:{rows:any[];onSelect:(row:number)=>void}){
  return <ul className="archive-rows">{rows.map(row=>{
    const labels=dateLabels(row,row);return <li key={row.list_row}>
      <button className="archive-document" onClick={()=>onSelect(row.list_row)}><strong>{row.title||row.filename}</strong>{row.title&&<span>{row.filename}</span>}</button>
      <span className="archive-row-format">{text(row.format).toUpperCase()}</span>
      <div className="archive-row-dates">{labels.document&&<span>Document date: {labels.document}</span>}<span>{labels.capture}</span></div>
    </li>;
  })}</ul>;
}
export function ArchiveDetail({entry,meetings=[],versions=[],rawBase,onSelect,onHearing,onOpenSaved}:{entry:any;meetings?:any[];versions?:any[];rawBase:string;onSelect:(row:number)=>void;onHearing:(key:string)=>void;onOpenSaved:(detail:any)=>void}){
  const {document,detail,sources,recoveries}=entry,labels=dateLabels(document,detail);
  const meetingLabels=new Map(meetings.map(item=>[String(item.event_id),item.title||String(item.event_id)]));
  return <article className="archive-detail" data-archive-detail>
    {document.hidden&&<aside role="note" className="archive-notice"><h2>Removed by review</h2><p>{detail.review_note||'This document was removed from the public list.'}</p>{detail.review_decided_at&&<p>Review decided {day(detail.review_decided_at)}</p>}</aside>}
    <header><p className="eyebrow">Archived document</p><h2>{document.title||document.filename}</h2>{document.title&&<p>{document.filename}</p>}</header>
    <div className="archive-dates"><p>{labels.capture}</p>{labels.document&&<p>Document date: {labels.document}</p>}{labels.removed&&<p>{labels.removed}</p>}</div>
    <section><h3>Saved copies</h3>{detail.saved_body?<ul><li><CopyLink detail={detail} label={`Open saved ${text(document.format).toUpperCase()}`} rawBase={rawBase} onOpenSaved={onOpenSaved}/></li>
      {(detail.alternates??[]).map((alternate:any,i:number)=><li key={i}><CopyLink detail={bodyDetail(alternate,alternate.format)} label={`Open alternate ${text(alternate.format).toUpperCase()}`} rawBase={rawBase} onOpenSaved={onOpenSaved}/></li>)}</ul>:<p>No original saved copy is recorded.</p>}</section>
    {recoveries.length>0&&<section><h3>Recovered and related files</h3><ul>{recoveries.map((recovery:any,i:number)=><li key={i}>
      <CopyLink detail={bodyDetail(recovery,document.format)} label={recoveryLabel(recovery.kind)} rawBase={rawBase} onOpenSaved={onOpenSaved}/>
      {recovery.identity_note&&<p>{recovery.identity_note}</p>}<p>Added to the archive {day(recovery.imported_at)}{recovery.recovered_url&&<> · <PublicLink url={recovery.recovered_url}>Recovery source</PublicLink></>}</p>
    </li>)}</ul></section>}
    <section><h3>Sources</h3>{sources.length?<ul>{sources.map((source:any,i:number)=><li key={i}>
      <PublicLink url={source.url}>{source.link_text||source.url}</PublicLink>{source.is_saved&&<span> · Saved file</span>}
      {source.member_path&&<p>File in archive: {source.member_path}</p>}{source.listed_on&&<p>Listed on <PublicLink url={source.listed_on}/></p>}
      {source.posted&&<p>Posted {day(source.posted)}</p>}
    </li>)}</ul>:<p>No source address is recorded.</p>}</section>
    {(document.meeting_keys??[]).length>0&&<section><h3>Hearings</h3><ul>{document.meeting_keys.map((key:string)=><li key={key}><button onClick={()=>onHearing(key)}>{meetingLabels.get(String(key))||key}</button></li>)}</ul></section>}
    {versions.some(row=>row.list_row!==document.list_row)&&<section><h3>Other versions</h3><ul>{versions.filter(row=>row.list_row!==document.list_row).map(row=><li key={row.list_row}><button onClick={()=>onSelect(row.list_row)}>{row.title||row.filename}</button> · {dateLabels(row,row).capture}</li>)}</ul></section>}
  </article>;
}
