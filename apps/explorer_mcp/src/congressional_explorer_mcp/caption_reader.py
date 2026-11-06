"""Read timestamped captions from verified retained files, never publisher addresses.

HLS WebVTT timing follows RFC 8216 section 3.5. Local timestamps and the MPEG
mapping remain explicit; they are not an inferred elapsed time from the hearing.
"""
import base64
from functools import partial
from hashlib import sha256
import json
import re
import time
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import anyio

from .body_reader import _load_or_extract_pages, _check_deadline
from .citations import text_citation
from .models import ExplorerError, MAX_BYTES
from .release import encoded

MAX_CAPTION_BYTES = 32 << 20
MAX_SEGMENTS_PER_CALL = 32
CAPTION_READER_VERSION = 'archive-cues-v1'


def _seconds(value):
    parts=value.replace(',','.').split(':')
    if len(parts) not in (2,3) or not re.fullmatch(r'(?:[0-9]{2,}:)?[0-5][0-9]:[0-5][0-9][.][0-9]{3}',value.replace(',','.')):
        raise ExplorerError('Unsupported or invalid caption timestamp')
    return sum(float(part)*60**i for i,part in enumerate(reversed(parts)))


def cue_rows(text, fmt):
    """Yield original cues in source order, retaining identifiers, settings and local time."""
    text=text.replace('\r\n','\n').replace('\r','\n').lstrip('\ufeff')
    if fmt=='ttml':
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ExplorerError('TTML entity declarations are unsupported')
        root=ET.fromstring(text)
        for parent in root.iter():
            if parent.tag.split('}')[-1]!='p' and any(name in parent.attrib for name in ('begin','end','dur')):
                raise ExplorerError('Relative TTML timing requires an unsupported parent timing context')
        for p in root.iter():
            if p.tag.split('}')[-1]!='p':
                continue
            start,end=p.get('begin'),p.get('end')
            if start is None or end is None:
                raise ExplorerError('TTML cue requires explicit begin and end')
            def seconds(value):
                return float(value[:-1]) if re.fullmatch(r'[0-9]+(?:[.][0-9]+)?s',value) else _seconds(value)
            def paragraph(node):
                parts=[node.text or '']
                for child in node:
                    parts.append('\n' if child.tag.split('}')[-1]=='br' else paragraph(child))
                    parts.append(child.tail or '')
                return ''.join(parts)
            start_seconds,end_seconds=seconds(start),seconds(end)
            if end_seconds<start_seconds:
                raise ExplorerError('Caption cue ends before it starts')
            yield dict(start=start,end=end,start_seconds=start_seconds,end_seconds=end_seconds,text=paragraph(p))
        return
    if fmt not in ('vtt','srt'):
        raise ExplorerError(f'Unsupported caption format {fmt!r}')
    blocks=re.finditer(r'(?:\A|\n\n+)([^\n](?:.*?))(?=\n\n+|\Z)',text,re.DOTALL)
    header=next(blocks,None) if fmt=='vtt' else None
    if fmt=='vtt' and (header is None or not re.match(r'WEBVTT(?:[ \t\n]|$)',header[1]) or '-->' in header[1]):
        raise ExplorerError('Invalid or unseparated WebVTT header')
    timestamp_map=None
    if header:
        mapping=re.search(r'^X-TIMESTAMP-MAP=(.+)$',header[1],re.MULTILINE)
        if mapping:
            attrs=dict(item.split(':',1) for item in mapping[1].split(','))
            local,mpeg=attrs.get('LOCAL'),attrs.get('MPEGTS')
            if local is None or mpeg is None or not mpeg.isdigit() or not 0<=int(mpeg)<2**33:
                raise ExplorerError('Invalid WebVTT timestamp map')
            timestamp_map=dict(local=local,mpegts=int(mpeg),timescale=90000)
    for block in blocks:
        lines=block[1].splitlines()
        if fmt=='vtt' and re.match(r'^(?:NOTE|STYLE|REGION)(?:\s|$)',lines[0]):
            continue
        timing_index=0 if '-->' in lines[0] else 1
        if len(lines)<=timing_index:
            raise ExplorerError('Invalid caption cue')
        match=re.fullmatch(r'(\S+)[ \t]+-->[ \t]+(\S+)(?:[ \t]+(.*))?',lines[timing_index])
        if not match:
            raise ExplorerError('Invalid caption cue timing')
        start,end=_seconds(match[1]),_seconds(match[2])
        if end<start:
            raise ExplorerError('Caption cue ends before it starts')
        row=dict(start=match[1],end=match[2],start_seconds=start,end_seconds=end,
                 text='\n'.join(lines[timing_index+1:]),identifier=lines[0] if timing_index else None,settings=match[3] or '')
        if timestamp_map:
            row['timestamp_map']=timestamp_map
            row['mpeg_start_seconds']=start-_seconds(timestamp_map['local'])+timestamp_map['mpegts']/90000
            row['mpeg_end_seconds']=end-_seconds(timestamp_map['local'])+timestamp_map['mpegts']/90000
        yield row


def caption_cursor(reference, segment, cue, position):
    return base64.urlsafe_b64encode(encoded(dict(reference=reference,segment=segment,cue=cue,position=position))).decode()


def _position(query,target):
    if not query.cursor:
        return (1 if target['format']=='m3u8' else 0),0,0,query.offset
    if query.offset:
        raise ExplorerError('Use either a caption cursor or an offset')
    try:
        value=json.loads(base64.urlsafe_b64decode(query.cursor))
        if value['reference']!=target['reference'] or any(type(value[k]) is not int or value[k]<0 for k in ('segment','cue','position')):
            raise ValueError()
        return value['segment'],value['cue'],value['position'],0
    except (ValueError,KeyError,TypeError):
        raise ExplorerError('Caption cursor belongs to another source or release') from None


def _playlist(text):
    lines=[line.strip() for line in text.lstrip('\ufeff').splitlines()]
    if not lines or lines[0]!='#EXTM3U':
        raise ExplorerError('Invalid retained subtitle playlist')
    unsupported=('#EXT-X-KEY:', '#EXT-X-BYTERANGE:', '#EXT-X-MAP:', '#EXT-X-STREAM-INF:', '#EXT-X-MEDIA:')
    if any(line.startswith(unsupported) for line in lines):
        raise ExplorerError('This playlist needs encryption, byte ranges, initialization data, or a child playlist; subtitle media playlists are supported')
    return [line for line in lines[1:] if line and not line.startswith('#')], '#EXT-X-ENDLIST' in lines


async def read_caption_page(target, query, load_resources, *, data_dir=None,timeout=10.0):
    deadline=time.monotonic()+timeout
    segment,cue_offset,position,skip=_position(query,target)
    result=dict(release_id=target['release_id'],event_id=target['reference'].get('event_id'),source=target,
                rows=[],offset=query.offset,has_more=False,missing_resources=[],state='available',
                reader_version=CAPTION_READER_VERSION)
    spent=0
    async def read(resource):
        nonlocal spent
        _check_deadline(deadline)
        pages,_,_,_ = await anyio.to_thread.run_sync(partial(_load_or_extract_pages,resource,
            data_dir=data_dir,timeout=max(.05,deadline-time.monotonic()),max_bytes=MAX_CAPTION_BYTES-spent,deadline=deadline),abandon_on_cancel=True)
        text='\n\n'.join(pages)
        spent+=len(text.encode())
        if spent>MAX_CAPTION_BYTES:
            raise ExplorerError('Caption page exceeds its verified-body byte budget')
        return text
    root_text=await read(target)
    try:
        playlist,is_final=_playlist(root_text) if target['format']=='m3u8' else (None,True)
    except ExplorerError as error:
        result.update(state='unavailable',coverage='unknown',reason=str(error))
        return result
    result['coverage']='complete_snapshot' if is_final else 'partial_live_snapshot'
    if playlist is not None:
        info=await load_resources(0,1)
        if not info['available'] or not info['rows']:
            result.update(state='unavailable',coverage='unknown',reason=info.get('reason','Retained playlist resource map is missing'))
            return result
        root=info['rows'][0]
        if root['ordinal']!=0 or root['saved_body']!=target['saved_body']:
            raise ExplorerError('Published playlist root differs from the cited source')
        if info.get('resource_count')!=len(playlist)+1:
            raise ExplorerError('Retained playlist resource map does not match the verified declarations')
        if info.get('missing_count',0):
            result['coverage']='partial'
        if not 1<=segment<=len(playlist)+1:
            raise ExplorerError('Caption cursor is outside this playlist')
        result.update(segment_count=len(playlist),missing_resource_count=info.get('missing_count',0),playlist_source_url=root['source_url'])
    elif segment!=0:
        raise ExplorerError('Caption cursor is outside this direct caption file')
    resources_seen=0
    done=False
    while not done and resources_seen<MAX_SEGMENTS_PER_CALL:
        _check_deadline(deadline)
        if playlist is None:
            resource=target
            text=root_text
        else:
            if segment>len(playlist):
                done=True; break
            page=await load_resources(segment,1)
            if not page['rows'] or page['rows'][0]['ordinal']!=segment:
                raise ExplorerError('Retained playlist resource map omits a declared segment')
            resource=page['rows'][0]
            if resource['declared_uri']!=playlist[segment-1] or resource['source_url']!=urljoin(root['source_url'],playlist[segment-1]):
                raise ExplorerError('Published segment location differs from the verified playlist')
            if resource['status']!='retained' or not resource['saved_body']:
                result['missing_resources'].append(dict(ordinal=segment,source_url=resource['source_url'],reason='not_retained'))
                result['coverage']='partial'; segment+=1; cue_offset=0; resources_seen+=1
                continue
            try:
                text=await read(resource)
            except ExplorerError as error:
                result['missing_resources'].append(dict(ordinal=segment,source_url=resource['source_url'],reason=str(error)))
                result['coverage']='partial'; segment+=1; cue_offset=0; resources_seen+=1
                continue
        resources_seen+=1
        exhausted=True
        try:
            for index,cue in enumerate(cue_rows(text,resource['format'])):
                if index<cue_offset:
                    continue
                if skip:
                    skip-=1; position+=1; continue
                citation_target=dict(target,reader_version=CAPTION_READER_VERSION)
                cue.update(resource_ordinal=segment,cue_index=index,segment_body=resource['saved_body'])
                cue['citation']=text_citation(citation_target,dict(kind='caption_cue',resource_ordinal=segment,cue_index=index,
                    segment_body=resource['saved_body'],start=cue['start'],end=cue['end']),cue['text'])
                if len(result['rows'])>=query.limit or len(encoded(result))+len(encoded(cue))>MAX_BYTES-4096:
                    if not result['rows']:
                        raise ExplorerError('Caption cue exceeds response budget; open the retained source file')
                    cue_offset=index; exhausted=False; break
                result['rows'].append(cue); position+=1
        except (ExplorerError,ET.ParseError) as error:
            result['missing_resources'].append(dict(ordinal=segment,reason=str(error)))
            result['coverage']='partial'
        if not exhausted:
            break
        if playlist is None:
            done=True
        else:
            segment+=1; cue_offset=0
    if not done and playlist is not None and segment>len(playlist):
        done=True
    result['has_more']=not done
    if not done:
        result['next_cursor']=caption_cursor(target['reference'],segment,cue_offset,position)
    result['next_offset']=position if not done else None
    result['verification']='The root and returned cue bodies were SHA-256 verified. Unread segment bodies have not been checked by this call.'
    if result['missing_resources']:
        result['state']='partial' if result['rows'] else 'unavailable'
    elif not result['rows'] and done and position==0 and not query.offset:
        result.update(state='unavailable',coverage='unknown',reason='Retained source contains no readable caption cues')
    return result
