import {useEffect,useState} from 'react';
import {createArchiveClient} from '../reader/archive-client.ts';
import {openSavedBlob} from './saved-tab.ts';
import {
  ArchiveDetail,
  ArchiveRows,
  CommitteeDetail,
  HearingDetail,
  MemberDetail,
  SubjectDetail,
  WitnessDetail,
  keyHex,
} from './ArchiveDetail.tsx';
import {
  ARCHIVE_TABS,
  ArchiveEntityRows,
  normalizeArchiveTab,
  tabTotalCount,
  type ArchiveTab,
} from './ArchiveEntityBrowse.tsx';
import {ArchiveFormatFilter,formatLabel} from './ArchiveFormats.tsx';
import {
  buildCommitteeGroups,
  committeeLabel,
  congressLabel,
  congressOptionLabel,
  documentKindLabel,
  expandCommitteeKeys,
  formatMeasure,
} from './archive-metadata.ts';
import {RequestMessage,useRequest,integer} from '../view/request-state.tsx';

const pageSize=30;
export type Navigation={
  tab:ArchiveTab;
  text:string;
  congress:string;
  chamber:string;
  committee:string;
  kind:string;
  hearing:string;
  subject:string;
  subjectKind:string;
  witness:string;
  member:string;
  format:string;
  sort:string;
  offset:number;
  key:string;
};
const emptyNavigation:Navigation={
  tab:'documents',
  text:'',
  congress:'',
  chamber:'',
  committee:'',
  kind:'',
  hearing:'',
  subject:'',
  subjectKind:'',
  witness:'',
  member:'',
  format:'',
  sort:'',
  offset:0,
  key:'',
};
export const readArchiveNavigation=(search:string=location.search):Navigation=>{
  const q=new URLSearchParams(search);
  return {
    tab:normalizeArchiveTab(q.get('tab')),
    text:q.get('q')||'',
    congress:q.get('congress')||'',
    chamber:q.get('chamber')||'',
    committee:q.get('committee')||q.get('committee_key')||'',
    kind:q.get('kind')||'',
    hearing:q.get('hearing')||q.get('meeting')||q.get('event_id')||'',
    subject:q.get('subject')||q.get('bill')||q.get('nomination')||q.get('measure')||'',
    subjectKind:q.get('subject_kind')||'',
    witness:q.get('witness')||q.get('witness_key')||'',
    member:q.get('member')||q.get('bioguide_id')||'',
    format:q.get('format')||'',
    sort:q.get('sort')||'',
    offset:Math.max(0,Number(q.get('offset'))||0),
    key:q.get('key')||'',
  };
};

export default function ArchiveExplorer({pointerUrl,rawBase}:{pointerUrl:string;rawBase:string}){
  const [historyEpoch,setHistoryEpoch]=useState(0);
  const [client,setClient]=useState<ReturnType<typeof createArchiveClient>>();
  const [nav,setNav]=useState<Navigation>(emptyNavigation);
  useEffect(()=>{
    setNav(readArchiveNavigation());const connection=createArchiveClient(new URL(pointerUrl,location.href).href,new URL(rawBase,location.href).href,()=>location.reload());setClient(connection);
    const pop=()=>{setNav(readArchiveNavigation());setHistoryEpoch(value=>value+1);};window.addEventListener('popstate',pop);
    const dispose=()=>connection.dispose();const hide=(event:PageTransitionEvent)=>{if(!event.persisted)dispose();};window.addEventListener('pagehide',hide);
    return ()=>{window.removeEventListener('popstate',pop);window.removeEventListener('pagehide',hide);dispose();};
  },[pointerUrl,rawBase]);
  function navigate(change:Partial<Navigation>,replace=false){
    setNav(previous=>{
      const next={...previous,...change};
      const url=new URL(location.href);
      url.search='';
      for(const [name,value] of Object.entries({
        tab:next.tab==='documents'?'':next.tab,
        q:next.text,
        congress:next.congress,
        chamber:next.chamber,
        committee:next.committee,
        kind:next.kind,
        hearing:next.hearing,
        subject:next.subject,
        subject_kind:next.subjectKind,
        witness:next.witness,
        member:next.member,
        format:next.format,
        sort:next.sort,
        offset:next.offset,
        key:next.key,
      }))if(value)url.searchParams.set(name,String(value));
      history[replace?'replaceState':'pushState']({},'',url);
      return next;
    });
  }
  return client?<Workspace key={historyEpoch} client={client} nav={nav} navigate={navigate} rawBase={new URL(rawBase,location.href).href}/>:<p role="status">Loading the document archive…</p>;
}

function Workspace({client,nav,navigate,rawBase}:{client:ReturnType<typeof createArchiveClient>;nav:Navigation;navigate:(change:Partial<Navigation>,replace?:boolean)=>void;rawBase:string}){
  const [selection,setSelection]=useState<number|null>(null),[savedError,setSavedError]=useState('');
  const [info,retryInfo]=useRequest(signal=>client.request('info',{},signal),[client]);
  const allFacets:any[]=info.status==='ready'?info.value.facets??[]:[];
  const committeesCatalog:any[]=info.status==='ready'?info.value.committees??[]:[];
  const entityCounts:Record<string,number>|undefined=info.status==='ready'?info.value.entityCounts:undefined;
  const totalDocs:number|undefined=info.status==='ready'?info.value.count:undefined;
  const committeeFacets=allFacets.filter(item=>item.facet==='committee_keys');
  const effectiveSort=nav.sort||'document_date';
  const isDocTab=nav.tab==='documents';
  const activeTabMeta=ARCHIVE_TABS.find(item=>item.key===nav.tab)??ARCHIVE_TABS[0];

  const [rows,retryRows]=useRequest(async signal=>{
    if(!isDocTab)return null;
    const committeeKeys=nav.committee?expandCommitteeKeys(nav.committee,committeeFacets,committeesCatalog):[];
    const filterArgs={
      congress:nav.congress?[Number(nav.congress)]:[],
      committee_keys:committeeKeys,
      document_kind:nav.kind?[nav.kind]:[],
      meeting_keys:nav.hearing?[nav.hearing]:[],
      subject:nav.subject||undefined,
      witness:nav.witness||undefined,
      member:nav.member||undefined,
      format:nav.format?[nav.format]:[],
      sort:effectiveSort,
      offset:nav.offset,
      limit:pageSize,
    };
    const trimmed=nav.text.trim();
    if(/^https?:\/\//i.test(trimmed)){
      const result=await client.request('lookup',{url:trimmed,query:filterArgs},signal);
      return {...result,completedQuery:nav.text};
    }
    const result=await client.request('search',{text:nav.text,...filterArgs},signal);
    return {...result,completedQuery:nav.text};
  },[
    client,
    isDocTab,
    nav.text,
    nav.congress,
    nav.committee,
    nav.kind,
    nav.hearing,
    nav.subject,
    nav.witness,
    nav.member,
    nav.format,
    effectiveSort,
    nav.offset,
    nav.committee?committeeFacets.length:0,
  ]);

  const entityBrowseKind=nav.tab==='hearings'
    ?'meetings'
    :nav.tab==='committees'
      ?'committees'
      :nav.tab==='witnesses'
        ?'witnesses'
        :nav.tab==='members'
          ?'members'
          :nav.subjectKind==='bills'
            ?'bills'
            :nav.subjectKind==='nominations'
              ?'nominations'
              :'subjects';

  const isInspectingEntity=!isDocTab&&(
    (nav.tab==='hearings'&&Boolean(nav.hearing))||
    (nav.tab==='committees'&&Boolean(nav.committee))||
    (nav.tab==='witnesses'&&Boolean(nav.witness))||
    (nav.tab==='members'&&Boolean(nav.member))||
    (nav.tab==='subjects'&&Boolean(nav.subject))
  );

  const [entityRows,retryEntityRows]=useRequest(async signal=>{
    if(isDocTab||isInspectingEntity)return null;
    return client.listEntities(entityBrowseKind,{
      q:nav.text||undefined,
      congress:nav.congress||undefined,
      chamber:nav.chamber||undefined,
      committee:nav.tab==='committees'?undefined:nav.committee||undefined,
      offset:nav.offset,
      limit:pageSize,
    },signal);
  },[
    client,
    isDocTab,
    isInspectingEntity,
    entityBrowseKind,
    nav.text,
    nav.congress,
    nav.chamber,
    nav.committee,
    nav.offset,
  ]);

  const [detail,retryDetail]=useRequest(signal=>selection!==null||nav.key?client.request('entry',nav.key?{key:nav.key}:{index:selection},signal):Promise.resolve(null),[client,nav.key,selection]);
  const [entityView,retryEntityView]=useRequest(async signal=>{
    const [meeting,subject,witness,member,committee]=await Promise.all([
      nav.hearing?client.getMeeting(nav.hearing,signal).catch(()=>null):Promise.resolve(null),
      nav.subject?client.getSubject(nav.subject,signal).catch(()=>null):Promise.resolve(null),
      nav.witness?client.getWitness(nav.witness,signal).catch(()=>null):Promise.resolve(null),
      nav.member?client.getMember(nav.member,signal).catch(()=>null):Promise.resolve(null),
      nav.committee?client.getCommittee(nav.committee,{congress:nav.congress||undefined},signal).catch(()=>null):Promise.resolve(null),
    ]);
    return {meeting,subject,witness,member,committee};
  },[client,nav.hearing,nav.subject,nav.witness,nav.member,nav.committee,nav.congress]);

  useEffect(()=>{if(detail.status==='ready'&&detail.value&&detail.value.entry.detail.link_key&&!nav.key){navigate({key:keyHex(detail.value.entry.detail.link_key)},true);setSelection(null);}},[detail]);
  const select=(index:number)=>{setSelection(index);navigate({key:''});setSavedError('');};
  const close=()=>{setSelection(null);navigate({key:''});};
  async function openSaved(record:any){
    const tab=window.open('about:blank','_blank');if(tab)tab.opener=null;
    try{const result=await client.request('saved',{...record,saved_body:keyHex(record.saved_body)});if(result.blob){if(!tab)throw new Error('Allow a new tab to open this saved file.');await openSavedBlob(tab,result.blob);}else if(tab)tab.location.href=result.url;}
    catch(error){tab?.close();setSavedError(error instanceof Error?error.message:String(error));}
  }
  const filter=(change:Partial<Navigation>)=>{setSelection(null);navigate({...change,key:'',offset:0});};

  const inspectHearing=(hearing:string)=>filter({tab:'hearings',hearing,subject:'',witness:'',member:''});
  const inspectCommittee=(committee:string)=>filter({tab:'committees',committee,hearing:'',subject:'',witness:'',member:''});
  const inspectWitness=(witness:string)=>filter({tab:'witnesses',witness,hearing:'',subject:'',member:''});
  const inspectMember=(member:string)=>filter({tab:'members',member,hearing:'',subject:'',witness:''});
  const inspectSubject=(subject:string)=>filter({tab:'subjects',subject,hearing:'',witness:'',member:''});

  const clearInspectedEntity=()=>{
    if(nav.tab==='hearings')filter({hearing:''});
    else if(nav.tab==='committees')filter({committee:''});
    else if(nav.tab==='witnesses')filter({witness:''});
    else if(nav.tab==='members')filter({member:''});
    else if(nav.tab==='subjects')filter({subject:''});
  };

  const congresses=allFacets
    .filter(item=>item.facet==='congress'&&Number(item.value)>=100)
    .sort((a,b)=>Number(b.value)-Number(a.value));
  const committeeGroups=buildCommitteeGroups(committeeFacets,committeesCatalog);
  const kinds=allFacets
    .filter(item=>item.facet==='document_kind')
    .sort((a,b)=>Number(b.count)-Number(a.count)||String(a.value).localeCompare(String(b.value)));
  const formats=allFacets
    .filter(item=>item.facet==='format')
    .sort((a,b)=>Number(b.count)-Number(a.count)||String(a.value).localeCompare(String(b.value)));

  const activeEntities=entityView.status==='ready'?entityView.value:null;

  const activeFilters=[
    nav.congress&&{label:congressLabel(nav.congress)||`Congress ${nav.congress}`,clear:()=>filter({congress:''})},
    nav.chamber&&{label:`Chamber: ${nav.chamber.charAt(0).toUpperCase()+nav.chamber.slice(1)}`,clear:()=>filter({chamber:''})},
    (isDocTab||nav.tab!=='committees')&&nav.committee&&{label:committeeLabel(nav.committee,committeesCatalog,nav.congress||undefined),clear:()=>filter({committee:''})},
    isDocTab&&nav.kind&&{label:documentKindLabel(nav.kind),clear:()=>filter({kind:''})},
    isDocTab&&nav.hearing&&{label:activeEntities?.meeting?.title?`Hearing: ${activeEntities.meeting.title}`:`Hearing ${nav.hearing}`,clear:()=>filter({hearing:''})},
    isDocTab&&nav.subject&&{label:formatMeasure(nav.subject),clear:()=>filter({subject:''})},
    nav.tab==='subjects'&&nav.subjectKind&&{label:nav.subjectKind==='bills'?'Legislation only':'Nominations only',clear:()=>filter({subjectKind:''})},
    isDocTab&&nav.witness&&{label:activeEntities?.witness?.name?`Witness: ${activeEntities.witness.name}`:`Witness ${nav.witness}`,clear:()=>filter({witness:''})},
    isDocTab&&nav.member&&{label:activeEntities?.member?.name?`Member: ${activeEntities.member.name}`:`Member ${nav.member}`,clear:()=>filter({member:''})},
    isDocTab&&nav.format&&{label:formatLabel(nav.format),clear:()=>filter({format:''})},
  ].filter(Boolean) as Array<{label:string;clear:()=>void}>;

  const isDetail=selection!==null||Boolean(nav.key);

  return <div className="explorer archive-workspace" data-archive-release={info.status==='ready'?info.value.releaseId:undefined} data-archive-ready={info.status==='ready'?'true':undefined}>
    <nav className="explorer-tabs" aria-label="Archive workspaces" style={{display:'flex',flexWrap:'wrap',gap:'0.5rem',marginBottom:'0.75rem'}}>
      {ARCHIVE_TABS.map(tabItem=>{
        const count=tabTotalCount(tabItem.key,totalDocs,entityCounts);
        const active=nav.tab===tabItem.key;
        return <button
          key={tabItem.key}
          type="button"
          className="explorer-button"
          aria-current={active?'page':undefined}
          data-archive-tab={tabItem.key}
          onClick={()=>{
            setSelection(null);
            navigate({
              tab:tabItem.key,
              key:'',
              offset:0,
              ...(tabItem.key==='hearings'?{hearing:''}:{}),
              ...(tabItem.key==='committees'?{committee:''}:{}),
              ...(tabItem.key==='witnesses'?{witness:''}:{}),
              ...(tabItem.key==='members'?{member:''}:{}),
              ...(tabItem.key==='subjects'?{subject:''}:{}),
            });
          }}
        >
          {tabItem.label}{count!==null?` (${integer(count)})`:''}
        </button>;
      })}
    </nav>
    <form className="archive-search" onSubmit={event=>{event.preventDefault();const data=new FormData(event.currentTarget);filter({text:String(data.get('q')||'')});}}>
      <label>
        <span>{isDocTab?'Search documents, legislation, or paste a URL':`Search ${activeTabMeta.noun}`}</span>
        <input
          type="search"
          name="q"
          defaultValue={nav.text}
          key={`${nav.tab}:${nav.text}`}
          placeholder={isDocTab?'Title, bill (e.g. H.R. 475), filename, or https:// address':`Filter ${activeTabMeta.noun} by name, title, or identifier`}
        />
      </label>
      <button className="explorer-button archive-search-button" type="submit">Search</button>
    </form>
    {!isDetail&&!isInspectingEntity&&<div className="archive-filters">
      <label><span>Congress</span><select value={nav.congress} onChange={event=>filter({congress:event.target.value})}><option value="">All congresses</option>{congresses.map((item:any)=><option key={item.value} value={item.value}>{congressOptionLabel(item.value)} ({integer(Number(item.count))})</option>)}</select></label>
      {(nav.tab==='hearings'||nav.tab==='committees'||nav.tab==='members')&&<label><span>Chamber</span><select value={nav.chamber} onChange={event=>filter({chamber:event.target.value})}><option value="">All chambers</option><option value="house">House</option><option value="senate">Senate</option><option value="joint">Joint</option></select></label>}
      {nav.tab==='subjects'&&<label><span>Subject type</span><select value={nav.subjectKind} onChange={event=>filter({subjectKind:event.target.value})}><option value="">Bills &amp; nominations</option><option value="bills">Bills &amp; resolutions</option><option value="nominations">Presidential nominations</option></select></label>}
      {nav.tab!=='committees'&&<label><span>Committee</span><select value={nav.committee} onChange={event=>filter({committee:event.target.value})}><option value="">All committees</option>
        {committeeGroups.primary.length>0&&<optgroup label="Committees">{committeeGroups.primary.map(item=><option key={item.value} value={item.value}>{item.label} ({integer(item.count)})</option>)}</optgroup>}
        {committeeGroups.subItems.length>0&&<optgroup label="Subcommittees">{committeeGroups.subItems.map(item=><option key={item.value} value={item.value}>{item.label} ({integer(item.count)})</option>)}</optgroup>}
      </select></label>}
      {isDocTab&&<>
        <label><span>Document type</span><select value={nav.kind} onChange={event=>filter({kind:event.target.value})}><option value="">All document types</option>{kinds.map((item:any)=><option key={item.value} value={item.value}>{documentKindLabel(item.value)} ({integer(Number(item.count))})</option>)}</select></label>
        <ArchiveFormatFilter options={formats} value={nav.format} onChange={format=>filter({format})}/>
        <label><span>Order</span><select value={effectiveSort} onChange={event=>filter({sort:event.target.value==='document_date'?'':event.target.value})}><option value="document_date">Document date, newest first</option><option value="first_captured">Capture date, newest first</option><option value="filename">Filename (A–Z)</option></select></label>
      </>}
    </div>}
    {!isDetail&&!isInspectingEntity&&activeFilters.length>0&&<div className="archive-active-filters" aria-label="Active filters">
      {activeFilters.map((item,i)=><button key={i} type="button" className="archive-filter-pill" onClick={item.clear}>{item.label} <span aria-hidden="true">×</span></button>)}
      <button type="button" className="explorer-text-button" onClick={()=>filter({text:'',congress:'',chamber:'',committee:'',kind:'',hearing:'',subject:'',subjectKind:'',witness:'',member:'',format:''})}>Clear filters</button>
    </div>}
    {info.status!=='ready'&&<RequestMessage state={info} retry={retryInfo} noun="the archive"/>}
    {savedError&&<p role="alert" className="explorer-alert">{savedError}</p>}
    {!isDetail&&isDocTab&&activeEntities&&<>
      {nav.hearing&&activeEntities.meeting&&<HearingDetail
        meeting={activeEntities.meeting}
        committeesCatalog={committeesCatalog}
        onSelect={select}
        onCommittee={committee=>filter({committee})}
        onSubject={subject=>filter({subject})}
        onWitness={witness=>filter({witness})}
        onMember={member=>filter({member})}
        onClose={()=>filter({hearing:''})}
      />}
      {nav.subject&&activeEntities.subject&&<SubjectDetail
        subject={activeEntities.subject}
        committeesCatalog={committeesCatalog}
        onSelect={select}
        onHearing={hearing=>filter({hearing})}
        onCommittee={committee=>filter({committee})}
        onMember={member=>filter({member})}
        onSubject={subject=>filter({subject})}
        onClose={()=>filter({subject:''})}
      />}
      {nav.witness&&activeEntities.witness&&<WitnessDetail
        witness={activeEntities.witness}
        committeesCatalog={committeesCatalog}
        onSelect={select}
        onHearing={hearing=>filter({hearing})}
        onCommittee={committee=>filter({committee})}
        onMember={member=>filter({member})}
        onClose={()=>filter({witness:''})}
      />}
      {nav.member&&activeEntities.member&&<MemberDetail
        member={activeEntities.member}
        committeesCatalog={committeesCatalog}
        onSelect={select}
        onHearing={hearing=>filter({hearing})}
        onCommittee={committee=>filter({committee})}
        onSubject={subject=>filter({subject})}
        onClose={()=>filter({member:''})}
      />}
      {nav.committee&&!nav.hearing&&!nav.subject&&!nav.witness&&!nav.member&&activeEntities.committee&&<CommitteeDetail
        committee={activeEntities.committee}
        committeesCatalog={committeesCatalog}
        onSelect={select}
        onCommittee={committee=>filter({committee})}
        onHearing={hearing=>filter({hearing})}
        onMember={member=>filter({member})}
        onCongressChange={congress=>filter({congress})}
        onClose={()=>filter({committee:''})}
      />}
    </>}
    {isDetail?<div className="archive-detail-view"><button className="explorer-button archive-back-button" onClick={close}>← Back to {isDocTab?'documents':activeTabMeta.noun}</button>{detail.status==='ready'?detail.value&&<ArchiveDetail entry={detail.value.entry} versions={detail.value.versions} meetings={detail.value.meetings} meetingDetails={detail.value.meetingDetails} committees={detail.value.committees} subjects={detail.value.subjects} witnesses={detail.value.witnesses} members={detail.value.members} committeesCatalog={committeesCatalog} rawBase={rawBase} onSelect={select} onHearing={hearing=>filter({hearing})} onMeasure={measure=>filter({subject:measure})} onSubject={subject=>filter({subject})} onCommittee={committee=>filter({committee})} onWitness={witness=>filter({witness})} onMember={member=>filter({member})} onOpenSaved={openSaved}/>:<RequestMessage state={detail} retry={retryDetail} noun="this document"/>}</div>:
      isDocTab?(
        rows.status==='ready'&&rows.value?<section aria-label="Document results" data-archive-query={rows.value.completedQuery}><div className="archive-results-bar"><p className="archive-total" data-archive-total>{integer(rows.value.total)} documents</p></div><ArchiveRows rows={rows.value.rows} committeesCatalog={committeesCatalog} onSelect={select}/><nav className="explorer-pagination" aria-label="Document pages"><button className="explorer-button" disabled={!nav.offset} onClick={()=>navigate({offset:Math.max(0,nav.offset-pageSize)})}>Previous</button><span>{rows.value.total?integer(nav.offset+1):0}–{integer(Math.min(nav.offset+rows.value.rows.length,rows.value.total))} of {integer(rows.value.total)}</span><button className="explorer-button" disabled={rows.value.next===null} onClick={()=>navigate({offset:rows.value.next})}>Next</button></nav></section>:<RequestMessage state={rows} retry={retryRows} noun="document results"/>
      ):isInspectingEntity?(
        <div className="archive-detail-view" data-archive-entity-inspector={nav.tab}>
          <button type="button" className="explorer-button archive-back-button" onClick={clearInspectedEntity}>← Back to {activeTabMeta.noun}</button>
          {entityView.status!=='ready'?<RequestMessage state={entityView} retry={retryEntityView} noun={`this ${activeTabMeta.singular}`}/>:(
            <>
              {nav.tab==='hearings'&&activeEntities?.meeting&&<HearingDetail
                meeting={activeEntities.meeting}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onCommittee={inspectCommittee}
                onSubject={inspectSubject}
                onWitness={inspectWitness}
                onMember={inspectMember}
                onFilterDocuments={()=>filter({tab:'documents',hearing:nav.hearing})}
                onClose={clearInspectedEntity}
              />}
              {nav.tab==='committees'&&activeEntities?.committee&&<CommitteeDetail
                committee={activeEntities.committee}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onCommittee={inspectCommittee}
                onHearing={inspectHearing}
                onMember={inspectMember}
                onCongressChange={congress=>filter({congress})}
                onFilterDocuments={()=>filter({tab:'documents',committee:nav.committee})}
                onClose={clearInspectedEntity}
              />}
              {nav.tab==='witnesses'&&activeEntities?.witness&&<WitnessDetail
                witness={activeEntities.witness}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onHearing={inspectHearing}
                onCommittee={inspectCommittee}
                onMember={inspectMember}
                onFilterDocuments={()=>filter({tab:'documents',witness:nav.witness})}
                onClose={clearInspectedEntity}
              />}
              {nav.tab==='members'&&activeEntities?.member&&<MemberDetail
                member={activeEntities.member}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onHearing={inspectHearing}
                onCommittee={inspectCommittee}
                onSubject={inspectSubject}
                onFilterDocuments={()=>filter({tab:'documents',member:nav.member})}
                onClose={clearInspectedEntity}
              />}
              {nav.tab==='subjects'&&activeEntities?.subject&&<SubjectDetail
                subject={activeEntities.subject}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onHearing={inspectHearing}
                onCommittee={inspectCommittee}
                onMember={inspectMember}
                onSubject={inspectSubject}
                onFilterDocuments={()=>filter({tab:'documents',subject:nav.subject})}
                onClose={clearInspectedEntity}
              />}
            </>
          )}
        </div>
      ):(
        entityRows.status==='ready'&&entityRows.value?<section aria-label={`${activeTabMeta.label} results`} data-archive-entity-tab={nav.tab}><div className="archive-results-bar"><p className="archive-total" data-archive-entity-total>{integer(entityRows.value.total)} {activeTabMeta.noun}</p></div><ArchiveEntityRows tab={nav.tab} rows={entityRows.value.rows} committeesCatalog={committeesCatalog} onInspectHearing={inspectHearing} onInspectCommittee={inspectCommittee} onInspectWitness={inspectWitness} onInspectMember={inspectMember} onInspectSubject={inspectSubject}/><nav className="explorer-pagination" aria-label={`${activeTabMeta.label} pages`}><button className="explorer-button" disabled={!nav.offset} onClick={()=>navigate({offset:Math.max(0,nav.offset-pageSize)})}>Previous</button><span>{entityRows.value.total?integer(nav.offset+1):0}–{integer(Math.min(nav.offset+entityRows.value.rows.length,entityRows.value.total))} of {integer(entityRows.value.total)}</span><button className="explorer-button" disabled={entityRows.value.next===null} onClick={()=>navigate({offset:entityRows.value.next})}>Next</button></nav></section>:<RequestMessage state={entityRows} retry={retryEntityRows} noun={`${activeTabMeta.noun}`}/>
      )}
  </div>;
}
