/** Preserve raw-file isolation after decompression creates a site-origin Blob. */
export async function openSavedBlob(tab:Window,blob:Blob){
  tab.opener=null;
  if(blob.type.split(';')[0].toLowerCase()==='application/pdf'){const url=URL.createObjectURL(blob);tab.location.href=url;setTimeout(()=>URL.revokeObjectURL(url),60_000);}
  else{
    tab.document.title='Saved copy';tab.document.body.replaceChildren();
    const download=tab.document.createElement('button');download.textContent='Download saved copy';download.onclick=()=>{const url=URL.createObjectURL(new Blob([blob],{type:'application/octet-stream'})),link=tab.document.createElement('a');link.href=url;link.download='saved-copy';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
    const frame=tab.document.createElement('iframe');frame.setAttribute('sandbox','');frame.referrerPolicy='no-referrer';frame.title='Archived file';frame.style.cssText='display:block;width:100%;height:90vh;border:0';
    const contents=await blob.text();let content=contents;
    if(blob.type.split(';')[0].toLowerCase()!=='text/html'){
      const pre=tab.document.createElement('pre');pre.textContent=contents;content=pre.outerHTML;
    }
    frame.srcdoc=`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">${content}`;
    tab.document.body.append(download,frame);
  }
}
