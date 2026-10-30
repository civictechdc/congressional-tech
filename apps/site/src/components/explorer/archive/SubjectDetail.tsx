import {
  committeeLabel,
  congressGovBillUrl,
  congressGovNominationUrl,
  congressLabel,
  formatAmendmentId,
  formatBillStage,
  formatChamber,
  formatSubject,
  gpoBillUrl,
  presentDocument,
  spicyRegsUrl,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day} from './ArchiveRows.tsx';

export function SubjectDetail({
  subject,
  committeesCatalog,
  compact,
  onSelect,
  onHearing,
  onCommittee,
  onMember,
  onSubject,
  onFilterDocuments,
  onInspect,
  onClose,
  closeLabel,
}:{
  subject:any;
  committeesCatalog?:CommitteeCatalogInput;
  compact?:boolean;
  onSelect?:(row:number)=>void;
  onHearing?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onSubject?:(key:string)=>void;
  onFilterDocuments?:()=>void;
  onInspect?:()=>void;
  onClose?:()=>void;
  closeLabel?:string;
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
  const documents:any[]=Array.isArray(subject.documents)?subject.documents:[];
  const sponsorDisplay=subject.sponsor_name||subject.sponsor_bioguide_id||'';

  const contextParts=[
    congressLabel(subject.congress),
    isNom?'Presidential Nomination':'Legislation',
    label,
    formatBillStage(subject.status||subject.stage),
    subject.policy_area,
  ].filter(Boolean);

  return <section className="archive-entity-card" aria-label={isNom?'Nomination details':'Legislation details'} data-archive-entity={isNom?'nomination':'bill'}>
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">{contextParts.join(' · ')}</p>
        <div className="archive-pill-list">
          {onInspect&&<button type="button" className="archive-measure-pill" onClick={onInspect}>Open full profile →</button>}
          {onFilterDocuments&&<button type="button" className="archive-measure-pill" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose&&<button type="button" className="archive-measure-pill" onClick={onClose}>{closeLabel||'Clear subject filter'}</button>}
        </div>
      </div>
      <h2>{label}{heading&&heading!==label?` — ${heading}`:''}</h2>
      {subject.short_title&&subject.title&&subject.title!==subject.short_title&&<p className="archive-source-meta">{subject.title}</p>}
      <p className="archive-entity-meta">
        {(subject.introduced_date||subject.received_date)&&<span>
          <strong>{isNom?'Received:':'Introduced:'}</strong> {day(subject.introduced_date||subject.received_date)}
        </span>}
        {sponsorDisplay&&<span>
          {(subject.introduced_date||subject.received_date)&&<span aria-hidden="true"> · </span>}
          <strong>Sponsor:</strong>{' '}
          {subject.sponsor_bioguide_id&&onMember
            ?<button type="button" className="explorer-text-button" onClick={()=>onMember(String(subject.sponsor_bioguide_id))}>
                {sponsorDisplay}
              </button>
            :<span>{sponsorDisplay}</span>}
          {(subject.sponsor_party||subject.sponsor_state)&&` (${[subject.sponsor_party,subject.sponsor_state].filter(Boolean).join('-')})`}
        </span>}
        {subject.organization&&<span>
          {((subject.introduced_date||subject.received_date)||sponsorDisplay)&&<span aria-hidden="true"> · </span>}
          <strong>Organization:</strong> {subject.organization}
        </span>}
      </p>
      {(congressUrl||gpoUrl||regsUrl)&&<div className="archive-pill-list">
        {congressUrl&&<a className="archive-measure-pill" href={congressUrl} target="_blank" rel="noreferrer">Congress.gov</a>}
        {gpoUrl&&<a className="archive-measure-pill" href={gpoUrl} target="_blank" rel="noreferrer">GPO GovInfo</a>}
        {regsUrl&&<a className="archive-measure-pill" href={regsUrl} target="_blank" rel="noreferrer">spicy-regs</a>}
      </div>}
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
        {(compact?nominees.slice(0,5):nominees).map((nom:any,i:number)=><li key={i}>
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
      {!compact&&activities.length>0&&<ul className="archive-entity-list">
        {activities.map((act:any,i:number)=>{
          const code=String(act.committee_key??act.system_code??'').toLowerCase();
          return <li key={i}>
            <strong>{act.activity||act.name||'Activity'}</strong>
            {code&&<span className="archive-source-meta"> · {committeeLabel(code,committeesCatalog,subject.congress)}</span>}
            {act.date&&<span className="archive-source-meta"> · {day(act.date)}</span>}
          </li>;
        })}
      </ul>}
    </div>}

    {cboEstimates.length>0&&<div className="archive-entity-section">
      <h3>CBO Cost Estimates ({cboEstimates.length})</h3>
      <ul className="archive-entity-list">
        {cboEstimates.map((cbo:any,i:number)=>{
          const cboUrl=cbo.url||(cbo.publication_id?`https://www.cbo.gov/publication/${cbo.publication_id}`:null);
          const cboLabel=cbo.description||cbo.title||`CBO Estimate ${i+1}`;
          const cboDate=day(cbo.pub_date||cbo.date||cbo.published_date);
          return <li key={i}>
            {cboUrl?<PublicLink url={cboUrl}>{cboLabel}</PublicLink>:<strong>{cboLabel}</strong>}
            {cboDate&&<span className="archive-source-meta"> · {cboDate}</span>}
          </li>;
        })}
      </ul>
    </div>}

    {!compact&&votes.length>0&&<div className="archive-entity-section">
      <h3>Floor Votes ({votes.length})</h3>
      <ul className="archive-entity-list">
        {votes.map((v:any,i:number)=><li key={i}>
          <strong>{[formatChamber(v.chamber)||v.chamber,v.roll_number!=null?`Roll #${v.roll_number}`:null,v.result].filter(Boolean).join(' · ')||`Vote ${i+1}`}</strong>
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

    {!compact&&(subject.amendment_count>0||amendments.length>0)&&<div className="archive-entity-section">
      <h3>Amendments ({subject.amendment_count||amendments.length})</h3>
      {amendments.length>0&&<ul className="archive-entity-list">
        {amendments.slice(0,15).map((amdt:any,i:number)=>{
          const amdtLabel=amdt.amendment_id
            ?formatAmendmentId(amdt.amendment_id)
            :`${amdt.type||amdt.amendment_type||'Amdt.'} ${amdt.number||amdt.amendment_number||i+1}`;
          const amdtSponsor=amdt.sponsor_name||amdt.sponsor_bioguide_id||'';
          return <li key={amdt.amendment_id||amdt.number||i}>
            <strong>{amdtLabel}</strong>
            {amdtSponsor&&<span className="archive-source-meta">
              {' ('}
              {amdt.sponsor_bioguide_id&&onMember
                ?<button type="button" className="explorer-text-button" onClick={()=>onMember(String(amdt.sponsor_bioguide_id))}>{amdtSponsor}</button>
                :amdtSponsor}
              {')'}
            </span>}
            {(amdt.purpose||amdt.description)&&<span className="archive-source-meta"> — {amdt.purpose||amdt.description}</span>}
          </li>;
        })}
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

    {!compact&&hearings.length>0&&<div className="archive-entity-section">
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

    {!compact&&documents.length>0&&onSelect&&<div className="archive-entity-section">
      <h3>Archived Documents ({documents.length})</h3>
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
