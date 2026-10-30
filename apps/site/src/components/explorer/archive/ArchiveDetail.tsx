import {dateLabels, recoveryLabel, savedCopy} from '../reader/archive.ts';
import {validUrl} from '../browse/provenance.ts';
import {formatLabel} from './ArchiveFormats.tsx';
import {cleanIdentityNote, effectiveFormat, formatBytes, presentDocument} from './archive-metadata.ts';

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
export function ArchiveRows({rows,onSelect}:{rows:any[];onSelect:(row:number)=>void}){
  return <ul className="archive-rows">{rows.map(row=>{
    const labels=dateLabels(row,row);
    const presented=presentDocument(row);
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

export function ArchiveDetail({entry,meetings=[],versions=[],rawBase,onSelect,onHearing,onCommittee,onMeasure,onOpenSaved}:{entry:any;meetings?:any[];versions?:any[];rawBase:string;onSelect:(row:number)=>void;onHearing:(key:string)=>void;onCommittee?:(code:string)=>void;onMeasure?:(key:string)=>void;onOpenSaved:(detail:any)=>void}){
  const {document,detail,sources,recoveries}=entry,labels=dateLabels(document,detail);
  const presented=presentDocument(document,detail,sources,recoveries);
  const base=siteBase();
  const congressParam=document.congress?`&congress=${encodeURIComponent(String(document.congress))}`:'';
  const packageId=typeof detail?.package_id==='string'&&/^(?:CHRG|BILLS|CRPT|CDOC|CPRT)-[0-9a-z-]+$/i.test(detail.package_id.trim())?detail.package_id.trim():'';
  const primaryFormat=effectiveFormat(document,detail);
  const primaryDetail=primaryFormat!==String(document.format??'').toLowerCase()&&mediaTypes[primaryFormat]
    ?{...detail,saved_media_type:mediaTypes[primaryFormat]}
    :detail;
  const meetingLabels=new Map(meetings.map(item=>[String(item.event_id),item.title||String(item.event_id)]));
  const contextLine=[presented.congress,...presented.committees,...presented.kinds].filter(Boolean).join(' · ');
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
      {presented.measures.length>0&&<p className="archive-dates-measures"><strong>Related legislation:</strong> <span className="archive-measure-list">{presented.measures.map(m=>onMeasure?<button key={m.key} type="button" className="archive-measure-pill" onClick={()=>onMeasure(m.key)}>{m.label}</button>:<span key={m.key} className="archive-measure-pill">{m.label}</span>)}</span></p>}
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
    {(document.meeting_keys??[]).length>0&&<section><h3>Hearings</h3><ul>{document.meeting_keys.map((key:string)=><li key={key} className="archive-hearing-row">
      <button onClick={()=>onHearing(key)}>{meetingLabels.get(String(key))||key}</button>
      <span className="archive-hearing-meta"> · <a href={`${base}/dashboard/?meeting=${encodeURIComponent(key)}${congressParam}`}>Open in Committee Explorer</a></span>
    </li>)}</ul></section>}
    {versions.some(row=>row.list_row!==document.list_row)&&<section><h3>Other versions</h3><ul>{versions.filter(row=>row.list_row!==document.list_row).map(row=>{
      const ver=presentDocument(row);
      return <li key={row.list_row}><button onClick={()=>onSelect(row.list_row)}>{ver.title}</button> · {dateLabels(row,row).capture}</li>;
    })}</ul></section>}
  </article>;
}
