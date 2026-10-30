import {
  committeeLabel,
  congressGovMemberUrl,
  congressLabel,
  formatSubject,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day} from './ArchiveRows.tsx';

export function MemberDetail({
  member,
  committeesCatalog,
  onSelect,
  onHearing,
  onCommittee,
  onSubject,
  onFilterDocuments,
  onClose,
  closeLabel,
}:{
  member:any;
  committeesCatalog?:CommitteeCatalogInput;
  onSelect?:(row:number)=>void;
  onHearing?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onSubject?:(key:string)=>void;
  onFilterDocuments?:()=>void;
  onClose?:()=>void;
  closeLabel?:string;
}){
  if(!member)return null;
  const bio=String(member.bioguide_id??'');
  const terms:any[]=Array.isArray(member.terms)?member.terms:[];
  const committees:any[]=Array.isArray(member.roster_entries)&&member.roster_entries.length
    ?member.roster_entries
    :Array.isArray(member.committees)?member.committees:[];
  const hearings:any[]=Array.isArray(member.hearings)?member.hearings:[];
  const sponsoredBills:any[]=Array.isArray(member.sponsored_bills)?member.sponsored_bills:[];
  const documents:any[]=Array.isArray(member.documents)?member.documents:[];
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
        <div className="archive-pill-list">
          {onFilterDocuments&&<button type="button" className="explorer-text-button" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose&&<button type="button" className="explorer-text-button" onClick={onClose}>{closeLabel||'Clear member filter'}</button>}
        </div>
      </div>
      <h2>{member.name||bio}</h2>
      {(member.official_url||congressGovUrl)&&<p className="archive-entity-meta">
        {member.official_url&&<PublicLink url={member.official_url}>Official website</PublicLink>}
        {member.official_url&&congressGovUrl&&<span aria-hidden="true"> · </span>}
        {congressGovUrl&&<PublicLink url={congressGovUrl}>Congress.gov profile</PublicLink>}
      </p>}
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

    {documents.length>0&&onSelect&&<div className="archive-entity-section">
      <h3>Related Documents ({documents.length})</h3>
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
