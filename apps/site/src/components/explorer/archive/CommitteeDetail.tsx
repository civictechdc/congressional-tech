import {
  committeeLabel,
  congressLabel,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day} from './ArchiveRows.tsx';

export function CommitteeDetail({
  committee,
  committeesCatalog,
  onSelect,
  onCommittee,
  onHearing,
  onMember,
  onCongressChange,
  onFilterDocuments,
  onClose,
  closeLabel,
}:{
  committee:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onCommittee?:(key:string)=>void;
  onHearing?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onCongressChange?:(congress:string)=>void;
  onFilterDocuments?:()=>void;
  onClose?:()=>void;
  closeLabel?:string;
}){
  if(!committee)return null;
  const code=String(committee.committee_key??committee.system_code??'').toLowerCase();
  const displayName=committee.resolved_name||committee.current_name||committee.name||committeeLabel(code,committeesCatalog);
  const subcommittees:any[]=Array.isArray(committee.subcommittees)?committee.subcommittees:[];
  const roster:any[]=Array.isArray(committee.roster)?committee.roster:[];
  const hearings:any[]=Array.isArray(committee.hearings)?committee.hearings:[];
  const namesHistory:any[]=Array.isArray(committee.names)?committee.names:[];
  const congresses:number[]=Array.isArray(committee.roster_congresses)?committee.roster_congresses:[];
  const documents:any[]=Array.isArray(committee.documents)?committee.documents:[];

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
        <div className="archive-pill-list">
          {onFilterDocuments&&<button type="button" className="explorer-text-button" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>{closeLabel||'Clear committee filter'}</button>}
        </div>
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

    {documents.length>0&&onSelect&&<div className="archive-entity-section">
      <h3>Recent Committee Documents ({documents.length})</h3>
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
