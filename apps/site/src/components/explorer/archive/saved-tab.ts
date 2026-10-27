/** Preserve raw-file isolation after decompression creates a site-origin Blob. */
export async function openSavedBlob(tab:Window,blob:Blob){
  tab.opener=null;
  const url=URL.createObjectURL(blob);
  if(blob.type.split(';')[0].toLowerCase()==='application/pdf')tab.location.href=url;
  else{
    tab.document.title='Saved copy';tab.document.body.replaceChildren();
    const download=tab.document.createElement('a');download.href=url;download.download='saved-copy';download.textContent='Download saved copy';
    const frame=tab.document.createElement('iframe');frame.setAttribute('sandbox','');frame.referrerPolicy='no-referrer';frame.title='Archived file';frame.style.cssText='display:block;width:100%;height:90vh;border:0';
    const contents=await blob.text();let content=contents;
    if(blob.type.split(';')[0].toLowerCase()!=='text/html'){
      const pre=tab.document.createElement('pre');pre.textContent=contents;content=pre.outerHTML;
    }
    frame.srcdoc=`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">${content}`;
    tab.document.body.append(download,frame);
  }
  setTimeout(()=>URL.revokeObjectURL(url),60_000);
}
