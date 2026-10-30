import {dateLabels} from '../reader/archive.ts';
import {validUrl} from '../browse/provenance.ts';
import {formatLabel} from './ArchiveFormats.tsx';
import {
  effectiveFormat,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';

export const day=(value:any)=>value instanceof Date?value.toISOString().slice(0,10):value?String(value).slice(0,10):'';

export const siteBase = () => {
  const raw = (import.meta.env as any)?.BASE_URL || (globalThis as any).__SITE_BASE_URL__ || '';
  return String(raw).replace(/\/+$/, '');
};

export function PublicLink({url,children}:{url:any;children?:any}){
  const target=validUrl(url);return target?<a href={target.href} target="_blank" rel="noreferrer">{children||target.href}</a>:null;
}

export function ArchiveRows({
  rows,
  committeesCatalog,
  sort,
  onSelect,
}:{
  rows:any[];
  committeesCatalog?:CommitteeCatalogInput;
  sort?:string;
  onSelect:(row:number)=>void;
}){
  return <ul className="archive-rows">{rows.map(row=>{
    const labels=dateLabels(row,row);
    const presented=presentDocument(row,undefined,undefined,undefined,committeesCatalog);
    const showCapturedFirst=sort==='first_captured'&&Boolean(row.first_captured);
    const rawFormat=String(row.format??'').trim().toLowerCase();
    const effFormat=effectiveFormat(row);
    const rowFormatLabel=rawFormat==='other'&&effFormat&&effFormat!=='other'
      ?`${formatLabel('other')} (${formatLabel(effFormat)})`
      :formatLabel(effFormat);
    const hasMultipleVersions=Array.isArray(row.version_keys)&&row.version_keys.length>0;
    return <li key={row.list_row}>
      <div className="archive-row-main">
        {presented.contextParts.length>0&&<span className="archive-row-context">{presented.contextParts.join(' · ')}</span>}
        <button type="button" className="archive-document" onClick={()=>onSelect(row.list_row)}>
          <strong>{presented.title}</strong>
          {presented.subtitle&&<span className="archive-document-subtitle">{presented.subtitle}</span>}
        </button>
      </div>
      <span className="archive-row-format">{rowFormatLabel}</span>
      <div className="archive-row-dates">
        {showCapturedFirst
          ?<span>Captured {day(row.first_captured)}</span>
          :(labels.document?<span>Document date: {labels.document}</span>:<span>{labels.capture}</span>)}
        {hasMultipleVersions&&<span className="archive-row-versions">Multiple versions</span>}
        {labels.removed&&<span className="archive-row-removed">Removed from hearing page</span>}
      </div>
    </li>;
  })}</ul>;
}
