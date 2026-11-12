import release from '../../../../../explorer_mcp/server.json';
import {
  committeeLabel,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day} from './ArchiveRows.tsx';
import {formatRankedName} from '../reader/archive-entities.ts';

const repository=release.repository.url;

function unlistedText(item:any):string|null{
  if(item?.listing_status!=='no_longer_listed')return null;
  return item.unlisted_since
    ?`No longer listed by Congress.gov since ${day(item.unlisted_since)}`
    :'No longer listed by Congress.gov';
}

function groupingExplanation(person:any):string{
  switch(person?.grouping_basis){
    case 'bioguide':
      return 'Appearances grouped by official Member of Congress Bioguide ID.';
    case 'name_organization':
      return 'Appearances grouped by exact normalized name and organization (with middle-initial and suffix guards).';
    case 'reviewed':
      return 'Appearances grouped or separated by a reviewed person-identity decision.';
    default:
      return 'Single witness appearance (not merged across hearings because organization or full name was unstated or ambiguous).';
  }
}

export function PersonDetail({
  person,
  committeesCatalog,
  compact,
  onSelect,
  onHearing,
  onWitness,
  onCommittee,
  onMember,
  onPerson,
  onFilterDocuments,
  onInspect,
  onClose,
  closeLabel,
}:{
  person:any;
  committeesCatalog?:CommitteeCatalogInput;
  compact?:boolean;
  onSelect?:(row:number)=>void;
  onHearing?:(key:string)=>void;
  onWitness?:(key:string)=>void;
  onCommittee?:(key:string)=>void;
  onMember?:(bioguideId:string)=>void;
  onPerson?:(personKey:string)=>void;
  onFilterDocuments?:()=>void;
  onInspect?:()=>void;
  onClose?:()=>void;
  closeLabel?:string;
}){
  if(!person)return null;
  if(person.retired){
    const key=String(person.retired.key??person.person_key??'');
    const candidates:string[]=Array.isArray(person.retired.candidates)?person.retired.candidates:[];
    return <section className="archive-entity-card" aria-label="Person details" data-archive-entity="person">
      {person.retired.status==='ambiguous'&&candidates.length>0
        ?<p role="status" className="archive-removed-notice">
            The person link you followed ({key}) named a witness grouping that has since been split across multiple records:{' '}
            {candidates.map((cand:string,i:number)=><span key={cand}>
              {i>0&&', '}
              {onPerson
                ?<button type="button" className="explorer-text-button" onClick={()=>onPerson(cand)}>{cand}</button>
                :<code>{cand}</code>}
            </span>)}.
          </p>
        :<p role="status" className="archive-removed-notice">
            The person link you followed ({key}) named a witness grouping that is no longer active in this release.
          </p>}
    </section>;
  }

  const redirectedFrom:string|null=person.redirectedFrom??person.redirected_from??null;
  const displayName=formatRankedName(person.name,person.rank)||person.person_key;
  const nameVariants:string[]=Array.isArray(person.name_variants)?person.name_variants:[];
  const alternateNames=nameVariants.filter(n=>n&&n!==person.name&&n!==displayName);
  const ranks:string[]=Array.isArray(person.ranks)?person.ranks.map(String).filter(Boolean):(person.rank?[String(person.rank)]:[]);
  const organizations:string[]=Array.isArray(person.organizations)&&person.organizations.length
    ?person.organizations
    :person.organization?[String(person.organization)]:[];
  const positions:string[]=Array.isArray(person.positions)?person.positions:[];
  const appearances:any[]=Array.isArray(person.appearances)?person.appearances:[];
  const documents:any[]=Array.isArray(person.documents)?person.documents:[];
  const shownAppearances=compact?appearances.slice(0,5):appearances;
  const issuesUrl=`${repository.replace(/\/+$/,'')}/issues`;

  return <section className="archive-entity-card" aria-label="Person details" data-archive-entity="person">
    {redirectedFrom&&<p role="status" className="archive-redirect-note">
      The person link you followed ({redirectedFrom}) now points to this person.
    </p>}
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">Witness Person Profile</p>
        <div className="archive-pill-list">
          {onInspect&&<button type="button" className="archive-measure-pill" onClick={onInspect}>Open full profile →</button>}
          {onFilterDocuments&&<button type="button" className="archive-measure-pill" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose&&<button type="button" className="archive-measure-pill" onClick={onClose}>{closeLabel||'Close person profile'}</button>}
        </div>
      </div>
      <h2>{displayName}</h2>
      {alternateNames.length>0&&<p className="archive-entity-meta"><strong>Recorded names:</strong> {alternateNames.join(' · ')}</p>}
      {ranks.length>1&&<p className="archive-entity-meta"><strong>Recorded ranks:</strong> {ranks.join(' · ')}</p>}
      {person.credentials&&<p className="archive-entity-meta"><strong>Credentials:</strong> {person.credentials}</p>}
      {organizations.length>0&&<p className="archive-entity-meta"><strong>Organizations:</strong> {organizations.join(' · ')}</p>}
      {positions.length>0&&<p className="archive-entity-meta"><strong>Positions:</strong> {positions.join(' · ')}</p>}
      {(person.first_seen_date||person.last_seen_date)&&<p className="archive-entity-meta">
        <strong>Appearances recorded:</strong>{' '}
        {person.first_seen_date&&person.last_seen_date&&day(person.first_seen_date)!==day(person.last_seen_date)
          ?`${day(person.first_seen_date)} to ${day(person.last_seen_date)}`
          :day(person.first_seen_date||person.last_seen_date)}
      </p>}
      {person.bioguide_id&&<p className="archive-entity-meta">
        <strong>Member of Congress:</strong>{' '}
        {onMember
          ?<button type="button" className="archive-measure-pill" onClick={()=>onMember(String(person.bioguide_id))}>
              View Member Profile ({person.bioguide_id})
            </button>
          :<span>{person.bioguide_id}</span>}
      </p>}
      <p className="archive-source-meta">{groupingExplanation(person)}</p>
    </header>

    {appearances.length>0&&<div className="archive-entity-section">
      <h3>Hearing Appearances ({appearances.length})</h3>
      <ul className="archive-entity-list">
        {shownAppearances.map((app:any,i:number)=>{
          const ev=String(app.event_id??app.meeting_key??'').trim();
          const cleanTitle=String(app.meeting_title||app.title||'').trim().replace(/^[-–—]+\s+/,'').trim();
          const title=cleanTitle||(app.package_id?`Hearing Print ${app.package_id}`:(ev?`Hearing ${ev}`:(app.occasion||'Recorded Hearing Appearance')));
          const appName=formatRankedName(app.name,app.rank);
          const role=[appName&&appName!==displayName&&app.name!==person.name?`Listed as ${appName}`:null,app.position,app.organization].filter(Boolean).join(' — ');
          const unlisted=unlistedText(app);
          return <li key={app.witness_key||ev||i}>
            {ev&&onHearing
              ?<button type="button" className="explorer-text-button" onClick={()=>onHearing(ev)}><strong>{title}</strong></button>
              :app.package_id
                ?<PublicLink url={`https://www.govinfo.gov/app/details/${encodeURIComponent(String(app.package_id))}`}><strong>{title}</strong></PublicLink>
                :<strong>{title}</strong>}
            {app.meeting_date&&<span className="archive-source-meta"> · {day(app.meeting_date)}</span>}
            {app.witness_key&&onWitness&&<>
              <span aria-hidden="true"> · </span>
              <button type="button" className="archive-measure-pill" onClick={()=>onWitness(String(app.witness_key))}>Appearance</button>
            </>}
            {unlisted&&<span className="archive-source-meta"> · {unlisted}</span>}
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

    <footer className="archive-entity-section">
      <p className="archive-source-meta">
        Spot a wrong merge or split?{' '}
        <a href={issuesUrl} target="_blank" rel="noreferrer">Report a grouping correction on GitHub Issues</a>{' '}
        (reports are public).
      </p>
    </footer>
  </section>;
}
