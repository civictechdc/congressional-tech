import {integer} from '../view/request-state.tsx';

const labels=new Map(Object.entries({
  "application/javascript":"JavaScript file",
  "application/rss+xml":"RSS feed (XML)",
  "application/x-mpegurl":"HLS playlist (MPEGURL)",
  "application/x-octet-stream":"Binary file (type unspecified)",
  "aspx":"ASP.NET page (ASPX)",
  "cfm":"ColdFusion page (CFM)",
  "challenge_html":"Access-check page (not document content)",
  "csv":"Table (CSV)",
  "doc":"Word document (DOC)",
  "docx":"Word document (DOCX)",
  "html":"Web page (HTML)",
  "html_requires_document_discovery":"Page awaiting document discovery",
  "jpeg":"JPEG image",
  "json":"JSON",
  "legacy_office":"Legacy Office file",
  "m3u8":"HLS playlist (M3U8)",
  "mp3":"MP3 audio",
  "mp4":"MP4 video",
  "pdf":"PDF",
  "png":"PNG image",
  "ppt":"Presentation (PPT)",
  "pptx":"Presentation (PPTX)",
  "rtf":"Rich text (RTF)",
  "text/calendar":"Calendar (iCalendar)",
  "text/vtt":"Captions (WebVTT)",
  "txt":"Plain text (TXT)",
  "unrecognized_body":"Unrecognized response body",
  "video/x-ms-asf":"Windows Media (ASF)",
  "video/x-ms-wmv":"Windows Media video (WMV)",
  "video/x-ms-wvx":"Windows Media playlist (WVX)",
  "xls":"Spreadsheet (XLS)",
  "xlsx":"Spreadsheet (XLSX)",
  "xml":"XML",
  "zip":"ZIP archive",
  "zip_or_office":"ZIP or Office file (unconfirmed)",
  "text":"Plain text",
  "vtt":"Captions (VTT)",
  "image":"Image",
  "other":"Other file type",
  "empty":"Empty response",
  "warc":"Web archive (WARC)",
  "application/octet-stream":"Binary file (type unspecified)",
}));
const responseStates=new Set(['challenge_html','html_requires_document_discovery','unrecognized_body','empty']);

export function formatLabel(value:unknown){
  const raw=typeof value==='string'?value.trim():'';
  return labels.get(raw.toLowerCase())??(raw?`Other format (${raw})`:'Format not recorded');
}

type FormatOption={value:string;count:number};
export function ArchiveFormatFilter({options,value,onChange}:{options:FormatOption[];value:string;onChange:(value:string)=>void}){
  const isState=(item:FormatOption)=>responseStates.has(item.value.trim().toLowerCase());
  const formats=options.filter(item=>!isState(item)),states=options.filter(isState);
  const option=(item:FormatOption)=><option key={item.value} value={item.value}>{formatLabel(item.value)} ({integer(Number(item.count))})</option>;
  return <label><span>Format</span><select value={value} onChange={event=>onChange(event.target.value)}>
    <option value="">All formats</option>
    {formats.length>0&&<optgroup label="File formats">{formats.map(option)}</optgroup>}
    {states.length>0&&<optgroup label="Recorded response states">{states.map(option)}</optgroup>}
  </select></label>;
}
