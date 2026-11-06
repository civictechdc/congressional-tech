"""Resolve a citation without changing the evidence it names."""
from functools import partial
from hashlib import sha256
import re

import anyio
from fastmcp.exceptions import ToolError

from .body_reader import read_document_body
from .caption_reader import caption_cursor
from .citations import CITATION_VERSION, TEXT_READER_VERSION, validate_witness_claim
from .hearing_models import TranscriptQuery
from .models import DocumentQuery, ExplorerError


async def resolve_passage(citation,call,caption_read,*,data_dir=None,timeout=10.0):
    if not isinstance(citation,dict) or citation.get('version')!=CITATION_VERSION:
        raise ExplorerError('Unsupported citation version')
    source=citation.get('source')
    location=citation.get('location')
    if not isinstance(source,dict) or not isinstance(location,dict) or not re.fullmatch('[a-f0-9]{64}',citation.get('text_sha256','')):
        raise ExplorerError('Invalid passage citation')
    # This cheap selected-release check also initializes a lazily prepared server.
    selected=await call('overview',{})
    current=selected['release_id']
    if source.get('release_id')!=current:
        return dict(state='unavailable',reason='Citation belongs to another pinned release',citation=citation,selected_release_id=current)
    try:
        if isinstance(selected.get('corpus_text_index'),dict):
            retained=await call('resolve_index_citation',dict(citation=citation))
            if retained.get('state') in ('resolved','different_source'):
                return retained
        if location.get('kind')=='caption_cue':
            if 'event_id' in source:
                hearing_reference=dict(source)
                hearing_reference.pop('video_key',None)
                query=TranscriptQuery(**hearing_reference,limit=1)
                target=(await call('transcript_inventory',query.model_dump()))['target']
            else:
                target=await call('caption_source_target',source)
                query=TranscriptQuery(event_id=0,release_id=current,kind='captions',source_id=source['source_id'],limit=1)
            if source.get('video_key') is not None and source['video_key']!=target['video_key']:
                return dict(state='different_source',reason='Caption recording differs',citation=citation)
            if target['saved_body']!=citation.get('saved_body'):
                return dict(state='different_source',reason='Caption root body differs',citation=citation)
            validate_witness_claim(target,citation.get('witness_key'),citation.get('witness_attribution'))
            if isinstance(selected.get('corpus_text_index'),dict):
                retained=await call('resolve_index_citation',dict(citation=citation,source=target))
                if retained.get('state') in ('resolved','different_source'):
                    return retained
            query.cursor=caption_cursor(target['reference'],location['resource_ordinal'],location['cue_index'],0)
            result=await caption_read(target,query)
            rows=result['rows']
            if not rows:
                return dict(state='unavailable',reason='Cited cue could not be read',citation=citation,details=result)
            row=rows[0]
            reading_citation=row.get('citation') or {}
            if any(row.get(key)!=location.get(key) for key in ('resource_ordinal','cue_index','segment_body','start','end')):
                return dict(state='different_source',reason='Caption resource or cue location differs',citation=citation)
            text=row['text']
            if 'offset' in location or 'length' in location:
                offset,length=location.get('offset',0),location.get('length')
                if type(offset) is not int or type(length) is not int or offset<0 or not 0<=length<=65536:
                    raise ExplorerError('Invalid caption passage offset or length')
                text=text[offset:offset+length]
            reader_version=result['reader_version']
        else:
            kind=location.get('kind')
            if kind not in ('body_text','selected_text'):
                raise ExplorerError('Unsupported citation location')
            length=location['length']
            if type(length) is not int or not 0<=length<=65536:
                raise ExplorerError('Invalid citation passage length')
            query=DocumentQuery(**source,section='text' if kind=='body_text' else 'selected_text',page=location.get('page'),
                                offset=location['offset'],max_chars=max(1,length))
            target=await call('document_body_target',query.model_dump())
            if target.get('saved_body')!=citation.get('saved_body'):
                return dict(state='different_source',reason='Published document body differs from the cited body',citation=citation,source=target['reference'])
            validate_witness_claim(target,citation.get('witness_key'),citation.get('witness_attribution'))
            if kind=='body_text':
                result=await anyio.to_thread.run_sync(partial(read_document_body,target,query,data_dir=data_dir,timeout=timeout),abandon_on_cancel=True)
                reader_version=TEXT_READER_VERSION
            else:
                result=await call('get_document',query.model_dump())
                if result.get('selector')!=location.get('selector') or result.get('text_sha256')!=location.get('selected_text_sha256'):
                    return dict(state='different_source',reason='Publisher-selected block differs',citation=citation)
                reader_version=result['reader_version']
            text=result['text'][:length]
            reading_citation=result.get('citation') or {}
        if reader_version!=citation.get('reader_version'):
            return dict(state='different_source',reason='Text reading version differs',citation=citation)
        for field in ('extraction_definition','reading_definition','backend'):
            if citation.get(field) is not None:
                if reading_citation.get(field) is None:
                    return dict(state='unavailable',reason='The original retained reading is unavailable',citation=citation)
                if citation[field]!=reading_citation[field]:
                    return dict(state='different_source',reason='Retained reading or backend differs',citation=citation)
        if sha256(text.encode()).hexdigest()!=citation['text_sha256']:
            return dict(state='different_source',reason='Text at the cited location differs',citation=citation)
        return dict(state='resolved',citation=citation,text=text,source=source,location=location)
    except (ExplorerError,ToolError) as error:
        return dict(state='unavailable',reason=str(error),citation=citation)
