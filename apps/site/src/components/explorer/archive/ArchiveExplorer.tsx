import {useEffect,useRef,useState} from 'react';
import {createArchiveClient} from '../reader/archive-client.ts';
import {openSavedBlob} from './saved-tab.ts';
import {
  ArchiveDetail,
  ArchiveRows,
  CommitteeDetail,
  HearingDetail,
  MemberDetail,
  PersonDetail,
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
import {canonicalKind,mergeKindFacets} from '../reader/kind-synonyms.ts';
import {formatRankedName} from '../reader/archive-entities.ts';

export function RemovedDocumentNotice({removed,onNavigate}:{removed:any;onNavigate?:(key:string)=>void}){
  if(!removed)return null;
  const items:Array<{key:string;label:string}>=Array.isArray(removed.versionItems)&&removed.versionItems.length
    ?removed.versionItems
    :(Array.isArray(removed.versions)?removed.versions.map((key:string)=>({key,label:key})):[]);
  return <p role="status" className="archive-removed-notice">This document is no longer in the archive. It was last published{removed.lastFilename?<> as <strong>{removed.lastFilename}</strong></>:null} in release {String(removed.lastRelease).slice(0,12)}.{items.length?<> Other versions published at the same address: {items.map((item,i)=><span key={item.key}>{i?', ':''}<a href={'?key='+item.key} onClick={onNavigate?event=>{event.preventDefault();onNavigate(item.key);}:undefined}>{item.label}</a></span>)}.</>:null}</p>;
}

const pageSize=30;
const missingResults={status:'error',message:''} as const;
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
  person:string;
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
  person:'',
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
    person:q.get('person')||q.get('person_key')||'',
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
        person:next.person,
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
  const workspaceRef=useRef<HTMLDivElement>(null);
  const [selection,setSelection]=useState<number|null>(null),[savedError,setSavedError]=useState('');
  const [info,retryInfo]=useRequest(signal=>client.request('info',{},signal),[client]);
  const allFacets:any[]=info.status==='ready'?info.value.facets??[]:[];
  const committeesCatalog:any[]=info.status==='ready'?info.value.committees??[]:[];
  const kindSets:string[][]=info.status==='ready'?info.value.kindSynonyms??[]:[];
  const selectedKind=canonicalKind(nav.kind,kindSets);
  const entityCounts:Record<string,number>|undefined=info.status==='ready'?info.value.entityCounts:undefined;
  const totalDocs:number|undefined=info.status==='ready'?info.value.count:undefined;
  const committeeFacets=allFacets.filter(item=>item.facet==='committee_keys');
  const effectiveSort=nav.sort||'document_date';
  const activeTab=nav.tab;
  const isDocTab=activeTab==='documents';
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
      person:nav.person||undefined,
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
    nav.person,
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
    (nav.tab==='witnesses'&&(Boolean(nav.witness)||Boolean(nav.person)))||
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
    const [meeting,subject,witness,person,member,committee]=await Promise.all([
      nav.hearing?client.getMeeting(nav.hearing,signal):Promise.resolve(null),
      nav.subject?client.getSubject(nav.subject,signal).catch(()=>null):Promise.resolve(null),
      nav.witness?client.getWitness(nav.witness,signal).catch(()=>null):Promise.resolve(null),
      nav.person?client.getPerson(nav.person,signal).catch(()=>null):Promise.resolve(null),
      nav.member?client.getMember(nav.member,signal).catch(()=>null):Promise.resolve(null),
      nav.committee?client.getCommittee(nav.committee,{congress:nav.congress||undefined},signal).catch(()=>null):Promise.resolve(null),
    ]);
    return {meeting,subject,witness,person,member,committee};
  },[client,nav.hearing,nav.subject,nav.witness,nav.person,nav.member,nav.committee,nav.congress]);

  const [redirectNote,setRedirectNote]=useState('');
  useEffect(()=>{if(detail.status==='ready'&&detail.value&&detail.value.entry&&detail.value.entry.detail.link_key&&!nav.key){navigate({key:keyHex(detail.value.entry.detail.link_key)},true);setSelection(null);}},[detail]);
  // A retired key with a successor opens the successor; the address bar then names it.
  useEffect(()=>{if(detail.status==='ready'&&detail.value?.redirectedFrom&&detail.value.entry?.detail.link_key){setRedirectNote(`The link you followed (${detail.value.redirectedFrom}) now points to this document.`);navigate({key:keyHex(detail.value.entry.detail.link_key)},true);}},[detail]);
  useEffect(()=>{if(!nav.key)setRedirectNote('');},[nav.key]);
  // An earlier witness key opens its successor; the address bar then names the current key.
  const [witnessRedirect,setWitnessRedirect]=useState<{from:string;to:string}|null>(null);
  useEffect(()=>{const witness=entityView.status==='ready'?entityView.value?.witness:null;if(witness?.redirected_from&&nav.witness.toLowerCase()===witness.redirected_from){setWitnessRedirect({from:witness.redirected_from,to:witness.witness_key});navigate({witness:witness.witness_key},true);}},[entityView]);
  const [personRedirect,setPersonRedirect]=useState<{from:string;to:string}|null>(null);
  useEffect(()=>{const person=entityView.status==='ready'?entityView.value?.person:null;if(person?.redirected_from&&nav.person.toLowerCase()===String(person.redirected_from).toLowerCase()){setPersonRedirect({from:person.redirected_from,to:person.person_key});navigate({person:person.person_key},true);}},[entityView]);
  function witnessNotice(){
    const witness=entityView.status==='ready'?entityView.value?.witness:null;
    if(witness?.retired)return witness.retired.status==='ambiguous'
      ?<p role="status" className="archive-removed-notice">The witness link you followed ({witness.retired.key}) named a witness listing that has since been re-recorded, and more than one current witness matches it: {witness.retired.candidates.map((key:string,i:number)=><span key={key}>{i?', ':''}<a href={'?tab=witnesses&witness='+key} onClick={event=>{event.preventDefault();filter({tab:'witnesses',witness:key});}}>{key}</a></span>)}.</p>
      :<p role="status" className="archive-removed-notice">The witness link you followed ({witness.retired.key}) named a witness listing that has since been re-recorded, and no current witness matches it.</p>;
    if(witnessRedirect&&nav.witness===witnessRedirect.to)return <p role="status" className="archive-redirect-note">The witness link you followed ({witnessRedirect.from}) now points to this witness.</p>;
    return null;
  }
  useEffect(()=>{
    if(typeof window!=='undefined'&&window.scrollY>200){
      workspaceRef.current?.scrollIntoView({block:'start'});
    }
  },[selection,nav.key,nav.tab,nav.offset,nav.hearing,nav.committee,nav.witness,nav.member,nav.subject]);

  const select=(index:number)=>{setSelection(index);navigate({key:''});setSavedError('');};
  const close=()=>{setSelection(null);navigate({key:''});};
  async function openSaved(record:any){
    const tab=window.open('about:blank','_blank');if(tab)tab.opener=null;
    try{const result=await client.request('saved',{...record,saved_body:keyHex(record.saved_body)});if(result.blob){if(!tab)throw new Error('Allow a new tab to open this saved file.');await openSavedBlob(tab,result.blob);}else if(tab)tab.location.href=result.url;}
    catch(error){tab?.close();setSavedError(error instanceof Error?error.message:String(error));}
  }
  const filter=(change:Partial<Navigation>)=>{setSelection(null);navigate({...change,key:'',offset:0});};

  const inspectHearing=(hearing:string)=>filter({tab:'hearings',hearing,committee:'',subject:'',witness:'',person:'',member:''});
  const inspectCommittee=(committee:string)=>filter({tab:'committees',committee,hearing:'',subject:'',witness:'',person:'',member:''});
  const inspectWitness=(witness:string)=>filter({tab:'witnesses',witness,person:'',committee:'',hearing:'',subject:'',member:''});
  const inspectPerson=(person:string)=>filter({tab:'witnesses',person,witness:'',committee:'',hearing:'',subject:'',member:''});
  const inspectMember=(member:string)=>filter({tab:'members',member,committee:'',hearing:'',subject:'',witness:'',person:''});
  const inspectSubject=(subject:string)=>filter({tab:'subjects',subject,committee:'',hearing:'',witness:'',person:'',member:''});

  const clearInspectedEntity=()=>{
    if(nav.tab==='hearings')filter({hearing:''});
    else if(nav.tab==='committees')filter({committee:''});
    else if(nav.tab==='witnesses')filter({witness:'',person:''});
    else if(nav.tab==='members')filter({member:''});
    else if(nav.tab==='subjects')filter({subject:''});
  };

  const congresses=allFacets
    .filter(item=>item.facet==='congress'&&Number(item.value)>=100)
    .sort((a,b)=>Number(b.value)-Number(a.value));
  const committeeGroups=buildCommitteeGroups(committeeFacets,committeesCatalog);
  const kinds=mergeKindFacets(allFacets.filter(item=>item.facet==='document_kind'),kindSets)
    .sort((a,b)=>Number(b.count)-Number(a.count)||String(a.value).localeCompare(String(b.value)));
  const formats=allFacets
    .filter(item=>item.facet==='format')
    .sort((a,b)=>Number(b.count)-Number(a.count)||String(a.value).localeCompare(String(b.value)));

  const activeEntities=entityView.status==='ready'?entityView.value:null;
  const rawHearingTitle=activeEntities?.meeting?.title?String(activeEntities.meeting.title):'';
  const shortHearingTitle=rawHearingTitle.length>60?`${rawHearingTitle.slice(0,60)}…`:rawHearingTitle;

  const activeFilters=[
    nav.text&&{label:`Search: "${nav.text.length>45?`${nav.text.slice(0,45)}…`:nav.text}"`,clear:()=>filter({text:''})},
    nav.congress&&{label:congressLabel(nav.congress)||`Congress ${nav.congress}`,clear:()=>filter({congress:''})},
    nav.chamber&&{label:`Chamber: ${nav.chamber.charAt(0).toUpperCase()+nav.chamber.slice(1)}`,clear:()=>filter({chamber:''})},
    (isDocTab||nav.tab!=='committees')&&nav.committee&&{label:committeeLabel(nav.committee,committeesCatalog,nav.congress||undefined),clear:()=>filter({committee:''})},
    isDocTab&&nav.kind&&{label:documentKindLabel(selectedKind),clear:()=>filter({kind:''})},
    isDocTab&&nav.hearing&&{label:shortHearingTitle?`Hearing: ${shortHearingTitle}`:`Hearing ${nav.hearing}`,clear:()=>filter({hearing:''})},
    isDocTab&&nav.subject&&{label:formatMeasure(nav.subject),clear:()=>filter({subject:''})},
    nav.tab==='subjects'&&nav.subjectKind&&{label:nav.subjectKind==='bills'?'Legislation only':'Nominations only',clear:()=>filter({subjectKind:''})},
    isDocTab&&nav.witness&&{label:activeEntities?.witness?.name?`Witness: ${formatRankedName(activeEntities.witness.name,activeEntities.witness.rank)}`:`Witness ${nav.witness}`,clear:()=>filter({witness:''})},
    isDocTab&&nav.person&&{label:activeEntities?.person?.name?`Person: ${formatRankedName(activeEntities.person.name,activeEntities.person.rank)}`:`Person ${nav.person}`,clear:()=>filter({person:''})},
    isDocTab&&nav.member&&{label:activeEntities?.member?.name?`Member: ${activeEntities.member.name}`:`Member ${nav.member}`,clear:()=>filter({member:''})},
    isDocTab&&nav.format&&{label:formatLabel(nav.format),clear:()=>filter({format:''})},
  ].filter(Boolean) as Array<{label:string;clear:()=>void}>;

  const isDetail=selection!==null||Boolean(nav.key);
  const inspectedEntityValue=!isInspectingEntity||!activeEntities?null:
    nav.tab==='hearings'?activeEntities.meeting:
    nav.tab==='committees'?activeEntities.committee:
    nav.tab==='witnesses'?(nav.person?activeEntities.person:activeEntities.witness):
    nav.tab==='members'?activeEntities.member:
    activeEntities.subject;

  return <div ref={workspaceRef} className="explorer archive-workspace" data-archive-release={info.status==='ready'?info.value.releaseId:undefined} data-archive-ready={info.status==='ready'?'true':undefined}>
    <nav className="explorer-tabs" aria-label="Archive workspaces">
      {ARCHIVE_TABS.map(tabItem=>{
        const count=tabTotalCount(tabItem.key,totalDocs,entityCounts);
        const active=nav.tab===tabItem.key;
        return <button
          key={tabItem.key}
          type="button"
          aria-current={active?'page':undefined}
          data-archive-tab={tabItem.key}
          onClick={()=>{
            setSelection(null);
            navigate({
              tab:tabItem.key,
              key:'',
              offset:0,
              ...(nav.tab==='committees'&&tabItem.key!=='committees'?{committee:''}:{}),
              ...(tabItem.key==='hearings'?{hearing:''}:{}),
              ...(tabItem.key==='committees'?{committee:''}:{}),
              ...(tabItem.key==='witnesses'?{witness:'',person:''}:{}),
              ...(tabItem.key==='members'?{member:''}:{}),
              ...(tabItem.key==='subjects'?{subject:''}:{}),
            });
          }}
        >
          {tabItem.label}{count!==null?<> <span className="explorer-tab-count">({integer(count)})</span></>:''}
        </button>;
      })}
    </nav>
    <form className="archive-search" onSubmit={event=>{
      event.preventDefault();
      const data=new FormData(event.currentTarget);
      filter({
        text:String(data.get('q')||''),
        ...(isInspectingEntity?{
          ...(nav.tab==='hearings'?{hearing:''}:{}),
          ...(nav.tab==='committees'?{committee:''}:{}),
          ...(nav.tab==='witnesses'?{witness:'',person:''}:{}),
          ...(nav.tab==='members'?{member:''}:{}),
          ...(nav.tab==='subjects'?{subject:''}:{}),
        }:{}),
      });
    }}>
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
        <label><span>Document type</span><select value={selectedKind} onChange={event=>filter({kind:event.target.value})}><option value="">All document types</option>{kinds.map((item:any)=><option key={item.value} value={item.value}>{documentKindLabel(item.value)} ({integer(Number(item.count))})</option>)}</select></label>
        <ArchiveFormatFilter options={formats} value={nav.format} onChange={format=>filter({format})}/>
        <label><span>Order</span><select value={effectiveSort} onChange={event=>filter({sort:event.target.value==='document_date'?'':event.target.value})}><option value="document_date">Document date, newest first</option><option value="first_captured">Capture date, newest first</option><option value="filename">Filename (A–Z)</option></select></label>
      </>}
    </div>}
    {!isDetail&&!isInspectingEntity&&activeFilters.length>0&&<div className="archive-active-filters" aria-label="Active filters">
      {activeFilters.map((item,i)=><button key={i} type="button" className="archive-filter-pill" onClick={item.clear}>{item.label} <span aria-hidden="true">×</span></button>)}
      <button type="button" className="explorer-text-button" onClick={()=>filter({text:'',congress:'',chamber:'',committee:'',kind:'',hearing:'',subject:'',subjectKind:'',witness:'',person:'',member:'',format:''})}>Clear filters</button>
    </div>}
    {info.status!=='ready'&&<RequestMessage state={info} retry={retryInfo} noun="the archive"/>}
    {savedError&&<p role="alert" className="explorer-alert">{savedError}</p>}
    {!isDetail&&isDocTab&&activeEntities&&<>
      {nav.hearing&&activeEntities.meeting&&<HearingDetail
        meeting={activeEntities.meeting}
        committeesCatalog={committeesCatalog}
        rawBase={rawBase}
        compact
        onSelect={select}
        onCommittee={inspectCommittee}
        onSubject={inspectSubject}
        onWitness={inspectWitness}
        onMember={inspectMember}
        onPerson={inspectPerson}
        onInspect={()=>inspectHearing(nav.hearing)}
        onClose={()=>filter({hearing:''})}
      />}
      {nav.subject&&activeEntities.subject&&<SubjectDetail
        subject={activeEntities.subject}
        committeesCatalog={committeesCatalog}
        compact
        onSelect={select}
        onHearing={inspectHearing}
        onCommittee={inspectCommittee}
        onMember={inspectMember}
        onSubject={inspectSubject}
        onInspect={()=>inspectSubject(nav.subject)}
        onClose={()=>filter({subject:''})}
      />}
      {nav.witness&&witnessNotice()}
      {nav.witness&&activeEntities.witness&&!activeEntities.witness.retired&&<WitnessDetail
        witness={activeEntities.witness}
        committeesCatalog={committeesCatalog}
        compact
        onSelect={select}
        onHearing={inspectHearing}
        onCommittee={inspectCommittee}
        onMember={inspectMember}
        onPerson={inspectPerson}
        onInspect={()=>inspectWitness(nav.witness)}
        onClose={()=>filter({witness:''})}
      />}
      {nav.person&&activeEntities.person&&<PersonDetail
        person={personRedirect&&nav.person===personRedirect.to?{...activeEntities.person,redirectedFrom:personRedirect.from}:activeEntities.person}
        committeesCatalog={committeesCatalog}
        compact
        onSelect={select}
        onHearing={inspectHearing}
        onWitness={inspectWitness}
        onCommittee={inspectCommittee}
        onMember={inspectMember}
        onPerson={inspectPerson}
        onInspect={()=>inspectPerson(nav.person)}
        onClose={()=>filter({person:''})}
      />}
      {nav.member&&activeEntities.member&&<MemberDetail
        member={activeEntities.member}
        committeesCatalog={committeesCatalog}
        compact
        onSelect={select}
        onHearing={inspectHearing}
        onCommittee={inspectCommittee}
        onSubject={inspectSubject}
        onInspect={()=>inspectMember(nav.member)}
        onClose={()=>filter({member:''})}
      />}
      {nav.committee&&!nav.hearing&&!nav.subject&&!nav.witness&&!nav.person&&!nav.member&&activeEntities.committee&&<CommitteeDetail
        committee={activeEntities.committee}
        committeesCatalog={committeesCatalog}
        compact
        onSelect={select}
        onCommittee={inspectCommittee}
        onHearing={inspectHearing}
        onMember={inspectMember}
        onCongressChange={congress=>filter({congress})}
        onInspect={()=>inspectCommittee(nav.committee)}
        onClose={()=>filter({committee:''})}
      />}
    </>}
    {isDetail?<div className="archive-detail-view"><button type="button" className="explorer-button archive-back-button" onClick={close}>← Back to {isDocTab?'documents':activeTabMeta.noun}</button>{detail.status==='ready'&&detail.value?.removed?<RemovedDocumentNotice removed={detail.value.removed} onNavigate={key=>navigate({key})}/>:detail.status==='ready'?detail.value&&<>{redirectNote&&<p role="status" className="archive-redirect-note">{redirectNote}</p>}<ArchiveDetail entry={detail.value.entry} versions={detail.value.versions} meetings={detail.value.meetings} meetingDetails={detail.value.meetingDetails} relationStates={detail.value.relation_states} committees={detail.value.committees} subjects={detail.value.subjects} witnesses={detail.value.witnesses} members={detail.value.members} committeesCatalog={committeesCatalog} rawBase={rawBase} onSelectedText={(index,signal)=>client.request('selectedText',{index},signal)} onPageMetadata={(index,signal)=>client.request('pageMetadata',{index},signal)} onSelect={select} onHearing={hearing=>filter({hearing})} onMeasure={measure=>filter({subject:measure})} onSubject={subject=>filter({subject})} onCommittee={committee=>filter({committee})} onWitness={witness=>filter({witness})} onMember={member=>filter({member})} onOpenSaved={openSaved}/></>:<RequestMessage state={detail} retry={retryDetail} noun="this document"/>}</div>:
      isDocTab?(
        rows.status==='ready'&&rows.value?<section aria-label="Document results" data-archive-query={rows.value.completedQuery}><div className="archive-results-bar"><p className="archive-total" data-archive-total>{rows.value.total===1?'1 document':`${integer(rows.value.total)} documents`}</p></div>{rows.value.total===0?<p className="explorer-muted">No matching documents found.</p>:<>
          <ArchiveRows rows={rows.value.rows} committeesCatalog={committeesCatalog} sort={effectiveSort} onSelect={select}/>
          <nav className="explorer-pagination" aria-label="Document pages"><button type="button" className="explorer-button" disabled={!nav.offset} onClick={()=>navigate({offset:Math.max(0,nav.offset-pageSize)})}>Previous</button><span>{rows.value.total?integer(nav.offset+1):0}–{integer(Math.min(nav.offset+rows.value.rows.length,rows.value.total))} of {integer(rows.value.total)}</span><button type="button" className="explorer-button" disabled={rows.value.next===null} onClick={()=>navigate({offset:rows.value.next})}>Next</button></nav>
        </>}</section>:<RequestMessage state={rows.status==='ready'?missingResults:rows} retry={retryRows} noun="document results"/>
      ):isInspectingEntity?(
        <div className="archive-detail-view" data-archive-entity-inspector={nav.tab}>
          <button type="button" className="explorer-button archive-back-button" onClick={clearInspectedEntity}>← Back to {activeTabMeta.noun}</button>
          {entityView.status!=='ready'?<RequestMessage state={entityView} retry={retryEntityView} noun={`this ${activeTabMeta.singular}`}/>:!inspectedEntityValue?(
            <p className="explorer-muted">No matching {activeTabMeta.singular} found.</p>
          ):(
            <>
              {nav.tab==='hearings'&&activeEntities?.meeting&&<HearingDetail
                meeting={activeEntities.meeting}
                committeesCatalog={committeesCatalog}
                rawBase={rawBase}
                onSelect={select}
                onCommittee={inspectCommittee}
                onSubject={inspectSubject}
                onWitness={inspectWitness}
                onMember={inspectMember}
                onPerson={inspectPerson}
                onFilterDocuments={()=>filter({tab:'documents',hearing:nav.hearing})}
              />}
              {nav.tab==='committees'&&activeEntities?.committee&&<CommitteeDetail
                committee={activeEntities.committee}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onCommittee={inspectCommittee}
                onHearing={inspectHearing}
                onMember={inspectMember}
                onFilterDocuments={()=>filter({tab:'documents',committee:nav.committee})}
              />}
              {nav.tab==='witnesses'&&nav.witness&&witnessNotice()}
              {nav.tab==='witnesses'&&nav.witness&&activeEntities?.witness&&!activeEntities.witness.retired&&<WitnessDetail
                witness={activeEntities.witness}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onHearing={inspectHearing}
                onCommittee={inspectCommittee}
                onMember={inspectMember}
                onPerson={inspectPerson}
                onFilterDocuments={()=>filter({tab:'documents',witness:nav.witness})}
              />}
              {nav.tab==='witnesses'&&nav.person&&activeEntities?.person&&<PersonDetail
                person={personRedirect&&nav.person===personRedirect.to?{...activeEntities.person,redirectedFrom:personRedirect.from}:activeEntities.person}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onHearing={inspectHearing}
                onWitness={inspectWitness}
                onCommittee={inspectCommittee}
                onMember={inspectMember}
                onPerson={inspectPerson}
                onFilterDocuments={()=>filter({tab:'documents',person:nav.person})}
              />}
              {nav.tab==='members'&&activeEntities?.member&&<MemberDetail
                member={activeEntities.member}
                committeesCatalog={committeesCatalog}
                onSelect={select}
                onHearing={inspectHearing}
                onCommittee={inspectCommittee}
                onSubject={inspectSubject}
                onFilterDocuments={()=>filter({tab:'documents',member:nav.member})}
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
              />}
            </>
          )}
        </div>
      ):(
        entityRows.status==='ready'&&entityRows.value?<section aria-label={`${activeTabMeta.label} results`} data-archive-entity-tab={nav.tab}><div className="archive-results-bar"><p className="archive-total" data-archive-entity-total>{entityRows.value.total===1?`1 ${activeTabMeta.singular}`:`${integer(entityRows.value.total)} ${activeTabMeta.noun}`}</p></div><ArchiveEntityRows tab={activeTab} rows={entityRows.value.rows} committeesCatalog={committeesCatalog} onInspectHearing={inspectHearing} onInspectCommittee={inspectCommittee} onInspectWitness={inspectWitness} onInspectMember={inspectMember} onInspectSubject={inspectSubject}/>{entityRows.value.total>0&&<nav className="explorer-pagination" aria-label={`${activeTabMeta.label} pages`}><button type="button" className="explorer-button" disabled={!nav.offset} onClick={()=>navigate({offset:Math.max(0,nav.offset-pageSize)})}>Previous</button><span>{entityRows.value.total?integer(nav.offset+1):0}–{integer(Math.min(nav.offset+entityRows.value.rows.length,entityRows.value.total))} of {integer(entityRows.value.total)}</span><button type="button" className="explorer-button" disabled={entityRows.value.next===null} onClick={()=>navigate({offset:entityRows.value.next})}>Next</button></nav>}</section>:<RequestMessage state={entityRows.status==='ready'?missingResults:entityRows} retry={retryEntityRows} noun={`${activeTabMeta.noun}`}/>
      )}
  </div>;
}
