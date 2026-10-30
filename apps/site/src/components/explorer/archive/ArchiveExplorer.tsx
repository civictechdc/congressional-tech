import {useEffect,useState} from 'react';
import {createArchiveClient} from '../reader/archive-client.ts';
import {openSavedBlob} from './saved-tab.ts';
import {ArchiveDetail,ArchiveRows,keyHex} from './ArchiveDetail.tsx';
import {ArchiveFormatFilter,formatLabel} from './ArchiveFormats.tsx';
import {
  buildCommitteeGroups,
  committeeLabel,
  congressLabel,
  congressOptionLabel,
  documentKindLabel,
  expandCommitteeKeys,
} from './archive-metadata.ts';
import {RequestMessage,useRequest,integer} from '../view/request-state.tsx';

const pageSize=30;
type Navigation={
  text:string;
  congress:string;
  committee:string;
  kind:string;
  hearing:string;
  format:string;
  sort:string;
  offset:number;
  key:string;
};
const emptyNavigation:Navigation={text:'',congress:'',committee:'',kind:'',hearing:'',format:'',sort:'',offset:0,key:''};
const readNavigation=():Navigation=>{
  const q=new URLSearchParams(location.search);
  return {
    text:q.get('q')||'',
    congress:q.get('congress')||'',
    committee:q.get('committee')||'',
    kind:q.get('kind')||'',
    hearing:q.get('hearing')||q.get('meeting')||'',
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
    setNav(readNavigation());const connection=createArchiveClient(new URL(pointerUrl,location.href).href,new URL(rawBase,location.href).href,()=>location.reload());setClient(connection);
    const pop=()=>{setNav(readNavigation());setHistoryEpoch(value=>value+1);};window.addEventListener('popstate',pop);
    const dispose=()=>connection.dispose();const hide=(event:PageTransitionEvent)=>{if(!event.persisted)dispose();};window.addEventListener('pagehide',hide);
    return ()=>{window.removeEventListener('popstate',pop);window.removeEventListener('pagehide',hide);dispose();};
  },[pointerUrl,rawBase]);
  function navigate(change:Partial<Navigation>,replace=false){
    setNav(previous=>{
      const next={...previous,...change};
      const url=new URL(location.href);
      url.search='';
      for(const [name,value] of Object.entries({
        q:next.text,
        congress:next.congress,
        committee:next.committee,
        kind:next.kind,
        hearing:next.hearing,
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
  const committeeFacets=allFacets.filter(item=>item.facet==='committee_keys');
  const effectiveSort=nav.sort||'document_date';
  const [rows,retryRows]=useRequest(async signal=>{
    const committeeKeys=nav.committee?expandCommitteeKeys(nav.committee,committeeFacets):[];
    const filterArgs={
      congress:nav.congress?[Number(nav.congress)]:[],
      committee_keys:committeeKeys,
      document_kind:nav.kind?[nav.kind]:[],
      meeting_keys:nav.hearing?[nav.hearing]:[],
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
  },[client,nav.text,nav.congress,nav.committee,nav.kind,nav.hearing,nav.format,effectiveSort,nav.offset,nav.committee?committeeFacets.length:0]);
  const [detail,retryDetail]=useRequest(signal=>selection!==null||nav.key?client.request('entry',nav.key?{key:nav.key}:{index:selection},signal):Promise.resolve(null),[client,nav.key,selection]);
  useEffect(()=>{if(detail.status==='ready'&&detail.value&&detail.value.entry.detail.link_key&&!nav.key){navigate({key:keyHex(detail.value.entry.detail.link_key)},true);setSelection(null);}},[detail]);
  const select=(index:number)=>{setSelection(index);navigate({key:''});setSavedError('');};
  const close=()=>{setSelection(null);navigate({key:''});};
  async function openSaved(record:any){
    const tab=window.open('about:blank','_blank');if(tab)tab.opener=null;
    try{const result=await client.request('saved',{...record,saved_body:keyHex(record.saved_body)});if(result.blob){if(!tab)throw new Error('Allow a new tab to open this saved file.');await openSavedBlob(tab,result.blob);}else if(tab)tab.location.href=result.url;}
    catch(error){tab?.close();setSavedError(error instanceof Error?error.message:String(error));}
  }
  const filter=(change:Partial<Navigation>)=>{setSelection(null);navigate({...change,key:'',offset:0});};

  const congresses=allFacets
    .filter(item=>item.facet==='congress'&&Number(item.value)>=100)
    .sort((a,b)=>Number(b.value)-Number(a.value));
  const committeeGroups=buildCommitteeGroups(committeeFacets);
  const kinds=allFacets
    .filter(item=>item.facet==='document_kind')
    .sort((a,b)=>Number(b.count)-Number(a.count)||String(a.value).localeCompare(String(b.value)));
  const formats=allFacets
    .filter(item=>item.facet==='format')
    .sort((a,b)=>Number(b.count)-Number(a.count)||String(a.value).localeCompare(String(b.value)));

  const activeFilters=[
    nav.congress&&{label:congressLabel(nav.congress)||`Congress ${nav.congress}`,clear:()=>filter({congress:''})},
    nav.committee&&{label:committeeLabel(nav.committee),clear:()=>filter({committee:''})},
    nav.kind&&{label:documentKindLabel(nav.kind),clear:()=>filter({kind:''})},
    nav.hearing&&{label:`Hearing ${nav.hearing}`,clear:()=>filter({hearing:''})},
    nav.format&&{label:formatLabel(nav.format),clear:()=>filter({format:''})},
  ].filter(Boolean) as Array<{label:string;clear:()=>void}>;

  const isDetail=selection!==null||Boolean(nav.key);

  return <div className="explorer archive-workspace" data-archive-release={info.status==='ready'?info.value.releaseId:undefined} data-archive-ready={info.status==='ready'?'true':undefined}>
    <form className="archive-search" onSubmit={event=>{event.preventDefault();const data=new FormData(event.currentTarget);filter({text:String(data.get('q')||'')});}}>
      <label><span>Search documents, legislation, or paste a URL</span><input type="search" name="q" defaultValue={nav.text} key={nav.text} placeholder="Title, bill (e.g. H.R. 475), filename, or https:// address"/></label>
      <button className="explorer-button archive-search-button" type="submit">Search</button>
    </form>
    {!isDetail&&<div className="archive-filters">
      <label><span>Congress</span><select value={nav.congress} onChange={event=>filter({congress:event.target.value})}><option value="">All congresses</option>{congresses.map((item:any)=><option key={item.value} value={item.value}>{congressOptionLabel(item.value)} ({integer(Number(item.count))})</option>)}</select></label>
      <label><span>Committee</span><select value={nav.committee} onChange={event=>filter({committee:event.target.value})}><option value="">All committees</option>
        {committeeGroups.primary.length>0&&<optgroup label="Committees">{committeeGroups.primary.map(item=><option key={item.value} value={item.value}>{item.label} ({integer(item.count)})</option>)}</optgroup>}
        {committeeGroups.subItems.length>0&&<optgroup label="Subcommittees">{committeeGroups.subItems.map(item=><option key={item.value} value={item.value}>{item.label} ({integer(item.count)})</option>)}</optgroup>}
      </select></label>
      <label><span>Document type</span><select value={nav.kind} onChange={event=>filter({kind:event.target.value})}><option value="">All document types</option>{kinds.map((item:any)=><option key={item.value} value={item.value}>{documentKindLabel(item.value)} ({integer(Number(item.count))})</option>)}</select></label>
      <ArchiveFormatFilter options={formats} value={nav.format} onChange={format=>filter({format})}/>
      <label><span>Order</span><select value={effectiveSort} onChange={event=>filter({sort:event.target.value==='document_date'?'':event.target.value})}><option value="document_date">Document date, newest first</option><option value="first_captured">Capture date, newest first</option><option value="filename">Filename (A–Z)</option></select></label>
    </div>}
    {!isDetail&&activeFilters.length>0&&<div className="archive-active-filters" aria-label="Active filters">
      {activeFilters.map((item,i)=><button key={i} type="button" className="archive-filter-pill" onClick={item.clear}>{item.label} <span aria-hidden="true">×</span></button>)}
      <button type="button" className="explorer-text-button" onClick={()=>filter({text:'',congress:'',committee:'',kind:'',hearing:'',format:''})}>Clear filters</button>
    </div>}
    {info.status!=='ready'&&<RequestMessage state={info} retry={retryInfo} noun="the archive"/>}
    {savedError&&<p role="alert" className="explorer-alert">{savedError}</p>}
    {isDetail?<div className="archive-detail-view"><button className="explorer-button archive-back-button" onClick={close}>← Back to documents</button>{detail.status==='ready'?detail.value&&<ArchiveDetail {...detail.value} rawBase={rawBase} onSelect={select} onHearing={hearing=>filter({hearing})} onMeasure={measure=>filter({text:measure})} onOpenSaved={openSaved}/>:<RequestMessage state={detail} retry={retryDetail} noun="this document"/>}</div>:
      rows.status==='ready'?<section aria-label="Document results" data-archive-query={rows.value.completedQuery}><div className="archive-results-bar"><p className="archive-total" data-archive-total>{integer(rows.value.total)} documents</p></div><ArchiveRows rows={rows.value.rows} onSelect={select}/><nav className="explorer-pagination" aria-label="Document pages"><button className="explorer-button" disabled={!nav.offset} onClick={()=>navigate({offset:Math.max(0,nav.offset-pageSize)})}>Previous</button><span>{rows.value.total?integer(nav.offset+1):0}–{integer(Math.min(nav.offset+rows.value.rows.length,rows.value.total))} of {integer(rows.value.total)}</span><button className="explorer-button" disabled={rows.value.next===null} onClick={()=>navigate({offset:rows.value.next})}>Next</button></nav></section>:<RequestMessage state={rows} retry={retryRows} noun="document results"/>}
  </div>;
}
