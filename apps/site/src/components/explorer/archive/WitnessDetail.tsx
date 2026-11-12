import {
  committeeLabel,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day} from './ArchiveRows.tsx';
import {witnessLabel, witnessMember, witnessRecordEntryLabel} from '../reader/archive-entities.ts';

function unlistedText(item:any):string|null{
  if(item?.listing_status!=='no_longer_listed')return null;
  return item.unlisted_since
    ?`No longer listed by Congress.gov since ${day(item.unlisted_since)}`
    :'No longer listed by Congress.gov';
}

export function WitnessDetail({
  witness,
  committeesCatalog,
  compact,
  onSelect,
  onHearing,
  onCommittee,
  onMember,
  onPerson,
  onFilterDocuments,
  onInspect,
  onClose,
  closeLabel,
}:{
  witness:any;
  committeesCatalog?:CommitteeCatalogInput;
  compact?:boolean;
  onSelect?:(row:number)=>void;
  onHearing?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onPerson?:(personKey:string)=>void;
  onFilterDocuments?:()=>void;
  onInspect?:()=>void;
  onClose?:()=>void;
  closeLabel?:string;
}){
  if(!witness)return null;
  const organizations:string[]=Array.isArray(witness.organizations)?witness.organizations:witness.organization?[witness.organization]:[];
  const positions:string[]=Array.isArray(witness.positions)?witness.positions:witness.position?[witness.position]:[];
  const appearances:any[]=Array.isArray(witness.appearances)?witness.appearances:[];
  const documents:any[]=Array.isArray(witness.documents)?witness.documents:[];
  const shownAppearances=compact?appearances.slice(0,5):appearances;
  const recordLabel=witnessRecordEntryLabel(witness.witness_type);
  const named=witnessMember(witness);
  const witnessUnlisted=unlistedText(witness);

  return <section className="archive-entity-card" aria-label={recordLabel||'Witness details'} data-archive-entity="witness">
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">{recordLabel||'Congressional Witness'}</p>
        <div className="archive-pill-list">
          {witness.person_key&&onPerson&&<button type="button" className="archive-measure-pill" onClick={()=>onPerson(String(witness.person_key))}>Person page →</button>}
          {onInspect&&<button type="button" className="archive-measure-pill" onClick={onInspect}>Open full profile →</button>}
          {onFilterDocuments&&<button type="button" className="archive-measure-pill" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose&&<button type="button" className="archive-measure-pill" onClick={onClose}>{closeLabel||'Clear witness filter'}</button>}
        </div>
      </div>
      <h2>{witnessLabel(witness)}</h2>
      {witnessUnlisted&&<p className="archive-source-meta">{witnessUnlisted}</p>}
      {witness.credentials&&<p className="archive-entity-meta"><strong>Credentials:</strong> {witness.credentials}</p>}
      {organizations.length>0&&<p className="archive-entity-meta"><strong>Organizations:</strong> {organizations.join(' · ')}</p>}
      {positions.length>0&&<p className="archive-entity-meta"><strong>Positions:</strong> {positions.join(' · ')}</p>}
      {named&&<p className="archive-entity-meta">
        <strong>Member of Congress:</strong>{' '}
        {onMember
          ?<button type="button" className="archive-measure-pill" onClick={()=>onMember(named.bioguide_id)}>
              View Member Profile ({named.name_matched?`${named.bioguide_id}, name-matched`:named.bioguide_id})
            </button>
          :<span>{named.name_matched?`${named.bioguide_id} (name-matched)`:named.bioguide_id}</span>}
      </p>}
    </header>

    {appearances.length>0&&<div className="archive-entity-section">
      <h3>{recordLabel?'Related Hearings':'Hearing Appearances'} ({appearances.length})</h3>
      <ul className="archive-entity-list">
        {shownAppearances.map((app:any,i:number)=>{
          const ev=String(app.event_id??app.meeting_key??'').trim();
          const cleanTitle=String(app.meeting_title||app.title||'').trim().replace(/^[-–—]+\s+/,'').trim();
          const title=cleanTitle||(app.package_id?`Hearing Print ${app.package_id}`:(ev?`Hearing ${ev}`:(app.occasion||'Recorded Hearing Appearance')));
          const role=[app.position,app.organization,app.on_behalf_of?`on behalf of ${app.on_behalf_of}`:null].filter(Boolean).join(' — ');
          const appUnlisted=unlistedText(app);
          return <li key={ev||app.package_id||i}>
            {ev&&onHearing
              ?<button type="button" className="explorer-text-button" onClick={()=>onHearing(ev)}><strong>{title}</strong></button>
              :app.package_id
                ?<PublicLink url={`https://www.govinfo.gov/app/details/${encodeURIComponent(String(app.package_id))}`}><strong>{title}</strong></PublicLink>
                :<strong>{title}</strong>}
            {app.meeting_date&&<span className="archive-source-meta"> · {day(app.meeting_date)}</span>}
            {app.panel!=null&&<span className="archive-source-meta"> · Panel {String(app.panel)}</span>}
            {appUnlisted&&<span className="archive-source-meta"> · {appUnlisted}</span>}
            {role&&<p className="archive-source-meta">{role}</p>}
            {Array.isArray(app.committee_keys)&&app.committee_keys.length>0&&<div className="archive-pill-list">
              {app.committee_keys.map((ck:string)=>onCommittee
                ?<button key={ck} type="button" className="archive-measure-pill" onClick={()=>onCommittee(ck)}>{committeeLabel(ck,committeesCatalog,app.meeting_date||app.congress)}</button>
                :<span key={ck} className="archive-measure-pill">{committeeLabel(ck,committeesCatalog,app.meeting_date||app.congress)}</span>)}
            </div>}
          </li>;
        })}
      </ul>
    </div>}

    {!compact&&documents.length>0&&onSelect&&<div className="archive-entity-section">
      <h3>Submitted Documents ({documents.length})</h3>
      <ul className="archive-entity-list">
        {documents.slice(0,20).map((doc:any)=>{
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
