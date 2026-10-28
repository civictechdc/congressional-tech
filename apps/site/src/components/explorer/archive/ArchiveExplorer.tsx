import {useEffect,useState} from 'react';
import {createArchiveClient} from '../reader/archive-client.ts';
import {openSavedBlob} from './saved-tab.ts';
import {ArchiveDetail,ArchiveRows,keyHex} from './ArchiveDetail.tsx';
import {RequestMessage,useRequest,integer} from '../view/request-state.tsx';

const pageSize=30;
type Navigation={text:string;hearing:string;format:string;sort:string;offset:number;key:string};
const readNavigation=():Navigation=>{const q=new URLSearchParams(location.search);return {text:q.get('q')||'',hearing:q.get('hearing')||'',format:q.get('format')||'',sort:q.get('sort')||'',offset:Math.max(0,Number(q.get('offset'))||0),key:q.get('key')||''};};
export default function ArchiveExplorer({pointerUrl,rawBase}:{pointerUrl:string;rawBase:string}){
  const [historyEpoch,setHistoryEpoch]=useState(0);
  const [client,setClient]=useState<ReturnType<typeof createArchiveClient>>();
  const [nav,setNav]=useState<Navigation>({text:'',hearing:'',format:'',sort:'',offset:0,key:''});
  useEffect(()=>{
    setNav(readNavigation());const connection=createArchiveClient(new URL(pointerUrl,location.href).href,new URL(rawBase,location.href).href,()=>location.reload());setClient(connection);
    const pop=()=>{setNav(readNavigation());setHistoryEpoch(value=>value+1);};window.addEventListener('popstate',pop);
    const dispose=()=>connection.dispose();const hide=(event:PageTransitionEvent)=>{if(!event.persisted)dispose();};window.addEventListener('pagehide',hide);
    return ()=>{window.removeEventListener('popstate',pop);window.removeEventListener('pagehide',hide);dispose();};
  },[pointerUrl,rawBase]);
  function navigate(change:Partial<Navigation>,replace=false){
    setNav(previous=>{const next={...previous,...change};const url=new URL(location.href);url.search='';for(const [name,value] of Object.entries({q:next.text,hearing:next.hearing,format:next.format,sort:next.sort,offset:next.offset,key:next.key}))if(value)url.searchParams.set(name,String(value));history[replace?'replaceState':'pushState']({},'',url);return next;});
  }
  return client?<Workspace key={historyEpoch} client={client} nav={nav} navigate={navigate} rawBase={new URL(rawBase,location.href).href}/>:<p role="status">Loading the document archive…</p>;
}
function Workspace({client,nav,navigate,rawBase}:{client:ReturnType<typeof createArchiveClient>;nav:Navigation;navigate:(change:Partial<Navigation>,replace?:boolean)=>void;rawBase:string}){
  const [selection,setSelection]=useState<number|null>(null),[savedError,setSavedError]=useState('');
  const [info,retryInfo]=useRequest(signal=>client.request('info',{},signal),[client]);
  const [rows,retryRows]=useRequest(async signal=>{
    if(/^https?:\/\//i.test(nav.text)){const result=await client.request('lookup',{url:nav.text,query:{meeting_keys:nav.hearing?[nav.hearing]:[],format:nav.format?[nav.format]:[],sort:nav.sort,offset:nav.offset,limit:pageSize}},signal);return {...result,completedQuery:nav.text};}
    const result=await client.request('search',{text:nav.text,meeting_keys:nav.hearing?[nav.hearing]:[],format:nav.format?[nav.format]:[],sort:nav.sort,offset:nav.offset,limit:pageSize},signal);return {...result,completedQuery:nav.text};
  },[client,nav.text,nav.hearing,nav.format,nav.sort,nav.offset]);
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
  const formats=info.status==='ready'?info.value.facets.filter((item:any)=>item.facet==='format'):[];
  return <div className="explorer archive-workspace" data-archive-release={info.status==='ready'?info.value.releaseId:undefined} data-archive-ready={info.status==='ready'?'true':undefined}>
    <form className="archive-search" onSubmit={event=>{event.preventDefault();const data=new FormData(event.currentTarget);filter({text:String(data.get('q')||'')});}}>
      <label>Find documents or paste a publisher address<input type="search" name="q" defaultValue={nav.text} key={nav.text} placeholder="Title, filename, or web address"/></label><button className="explorer-button" type="submit">Search</button>
    </form>
    <div className="archive-filters"><label>Hearing key<input value={nav.hearing} onChange={event=>filter({hearing:event.target.value})} placeholder="For example, 118001"/></label>
      <label>Format<select value={nav.format} onChange={event=>filter({format:event.target.value})}><option value="">All formats</option>{formats.map((item:any)=><option key={item.value} value={item.value}>{String(item.value).toUpperCase()} ({integer(Number(item.count))})</option>)}</select></label>
      <label>Order<select value={nav.sort} onChange={event=>filter({sort:event.target.value})}><option value="">Filename</option><option value="document_date">Document date, newest first</option><option value="first_captured">Capture date, newest first</option></select></label>
    </div>
    {info.status!=='ready'&&<RequestMessage state={info} retry={retryInfo} noun="the archive"/>}
    {savedError&&<p role="alert">{savedError}</p>}
    {selection!==null||nav.key?<div><button className="explorer-button" onClick={close}>← Back to documents</button>{detail.status==='ready'?detail.value&&<ArchiveDetail {...detail.value} rawBase={rawBase} onSelect={select} onHearing={hearing=>filter({hearing})} onOpenSaved={openSaved}/>:<RequestMessage state={detail} retry={retryDetail} noun="this document"/>}</div>:
      rows.status==='ready'?<section aria-label="Document results" data-archive-query={rows.value.completedQuery}><p data-archive-total>{integer(rows.value.total)} documents</p><ArchiveRows rows={rows.value.rows} onSelect={select}/><nav className="explorer-pagination" aria-label="Document pages"><button className="explorer-button" disabled={!nav.offset} onClick={()=>navigate({offset:Math.max(0,nav.offset-pageSize)})}>Previous</button><span>{rows.value.total?integer(nav.offset+1):0}–{integer(Math.min(nav.offset+rows.value.rows.length,rows.value.total))}</span><button className="explorer-button" disabled={rows.value.next===null} onClick={()=>navigate({offset:rows.value.next})}>Next</button></nav></section>:<RequestMessage state={rows} retry={retryRows} noun="document results"/>}
  </div>;
}
