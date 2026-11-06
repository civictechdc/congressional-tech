"""Bounded hearing reads over the published relationships; no producer reconstruction."""
from .hearing_models import HearingBundleQuery, TranscriptQuery
from .models import ExplorerError, MAX_BYTES
from .release import encoded, quote


class HearingReader:
    def _hearing(self, query):
        if query.release_id is not None and query.release_id != self.release_id:
            raise ExplorerError('Hearing reference belongs to another release; select its pinned release')
        self.require('meetings')
        fields = [name for name, kind in self.schemas['meetings'].items() if '[]' not in kind and not kind.startswith(('STRUCT', 'MAP'))]
        found = self.rows('SELECT '+','.join(map(quote, fields))+' FROM meetings WHERE event_id=?', [query.event_id], limit=1)['rows']
        if not found:
            raise ExplorerError('Meeting is absent from this release')
        return found[0]

    def _transcript_sql(self):
        labelled = 'source' in self.schemas['meetings'].get('transcripts', '')
        kind = "CASE t.source WHEN 'printed_hearing' THEN 'official' WHEN 'committee_transcript' THEN 'committee' END" if labelled else "'official'"
        document = f'''SELECT {kind} AS kind,d.package_id,lower(hex(d.link_key)) AS link_key,
          lower(hex(d.saved_body)) AS saved_body,d.saved_suffix,l.format,l.filename,l.title,l.saved_kind,
          d.saved_media_type,d.saved_bytes,l.witness_keys,NULL::VARCHAR AS video_key,NULL::VARCHAR AS language,
          NULL::VARCHAR AS production,'event' AS association_scope,'meetings.transcripts' AS association_basis
          FROM meetings m,unnest(m.transcripts) u(t),parameters p,"list" l JOIN detail d USING(list_row)
          WHERE m.event_id=p.event_id AND t.list_row=l.list_row AND NOT coalesce(l.hidden,false)
            AND {kind} IS NOT NULL'''
        if 'recordings' not in self.schemas:
            return f'WITH parameters AS (SELECT ?::BIGINT AS event_id) SELECT DISTINCT * FROM ({document})'
        observations = ''
        if 'meeting_links' in self.schemas.get('recording_matches', {}):
            observations = '''UNION ALL SELECT rm.video_key,ml.scope,ml.basis
              FROM recording_matches rm,unnest(rm.meeting_links) u(ml),parameters p
              WHERE ml.event_id=p.event_id AND rm.video_key IS NOT NULL'''
        return f'''WITH parameters AS (SELECT ?::BIGINT AS event_id),related AS (
          SELECT r.video_key,'event' AS scope,'recordings.event_ids' AS basis FROM recordings r,parameters p
          WHERE list_contains(r.event_ids,p.event_id) {observations}
        ), associations AS (
          SELECT video_key,CASE WHEN bool_or(scope='event') THEN 'event' ELSE 'package_context' END AS scope,
          string_agg(DISTINCT basis,',' ORDER BY basis) AS basis FROM related GROUP BY video_key
        ), caption_tracks AS (
          SELECT r.video_key,t.*,a.scope,a.basis FROM associations a JOIN recordings r USING(video_key),unnest(r.tracks) u(t)
          WHERE t.body IS NOT NULL AND lower(hex(t.body))<>'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
            AND t.format IN ('vtt','srt','ttml','m3u8')
        ), sources AS ({document} UNION ALL
          SELECT 'captions',NULL,NULL,lower(hex(t.body)),t.suffix,t.format,NULL,NULL,'original',NULL,NULL,
            []::VARCHAR[],t.video_key,t.language,t.production,t.scope,t.basis FROM caption_tracks t
          WHERE t.format='m3u8' OR NOT EXISTS (SELECT 1 FROM caption_tracks p
            WHERE p.video_key=t.video_key AND p.production IS NOT DISTINCT FROM t.production AND p.format='m3u8')
        ) SELECT DISTINCT * FROM sources'''

    def _source_page(self, query, *, offset=0, limit=25):
        # Source identity uses the published body and occurrence, never a title/name guess.
        sql = '''SELECT *,sha256(CASE WHEN kind='captions' THEN
            'captions:'||video_key||':'||saved_body||':'||coalesce(language,'')||':'||coalesce(production,'')
            ELSE kind||':'||link_key END) AS source_id FROM ('''+self._transcript_sql()+')'
        conditions, args = [], [query.event_id]
        if query.kind:
            conditions.append('kind=?'); args.append(query.kind)
        if query.source_id:
            conditions.append('source_id=?'); args.append(query.source_id)
        if conditions:
            sql = 'SELECT * FROM ('+sql+') WHERE '+' AND '.join(conditions)
        result = self.rows(sql+' ORDER BY kind,source_id OFFSET ?', [*args, offset], limit=limit)
        result.pop('columns')
        for row in result['rows']:
            row['reference'] = dict(release_id=self.release_id,event_id=query.event_id,kind=row['kind'],source_id=row['source_id'])
            if row['link_key']:
                row['document_reference'] = dict(release_id=self.release_id,link_key=row['link_key'])
            row['saved_url'] = self.file_url(row['saved_body'],row['saved_suffix'])
            row['provenance'] = dict(basis=row['association_basis'],scope=row['association_scope'],
                                     package_id=row['package_id'],video_key=row['video_key'])
        if result['has_more']:
            result['next_offset'] = offset+len(result['rows'])
        return result

    def transcript_inventory(self, value):
        query = TranscriptQuery.model_validate(value)
        self._hearing(query)
        result = self._source_page(query,offset=query.offset if not query.source_id else 0,limit=query.limit if not query.source_id else 2)
        result.update(release_id=self.release_id,event_id=query.event_id,
                      state='available' if result['rows'] else 'not_found',
                      note='Choose source_id to read one source. An empty inventory does not establish that no transcript exists.')
        result['availability']=dict(official='available',
            committee='available' if 'source' in self.schemas['meetings'].get('transcripts','') else 'unavailable',
            captions='available' if 'recordings' in self.schemas else 'unavailable')
        if query.kind and result['availability'][query.kind]=='unavailable':
            result['state']='unavailable'
        if query.source_id:
            if len(result['rows']) != 1:
                raise ExplorerError('Transcript source is absent or ambiguous in this release')
            target = result['rows'][0]
            target.update(release_id=self.release_id,archive_origin=self.selection.get('archive_origin'))
            result['target'] = target
        return result

    def caption_resource_page(self, value):
        if 'caption_resources' not in self.schemas:
            return dict(rows=[],has_more=False,available=False,reason='Retained playlist resources are not published in this release')
        # The server passes its already-resolved target; the public tool never accepts a URL/body.
        source = value['source']
        if source.get('release_id')!=self.release_id or source.get('kind')!='captions':
            raise ExplorerError('Caption source is not bound to this release')
        result = self.rows('''SELECT video_key,lower(hex(track_body)) AS track_body,ordinal,source_url,declared_uri,
            lower(hex(body)) AS saved_body,suffix AS saved_suffix,format,parser_version,status
            FROM caption_resources WHERE video_key=? AND track_body=unhex(?) AND ordinal>=?
            ORDER BY ordinal''', [source['video_key'],source['saved_body'],value.get('ordinal',0)],limit=min(value.get('limit',25),100))
        result.pop('columns')
        for row in result['rows']:
            row.update(saved_url=self.file_url(row['saved_body'],row['saved_suffix']),archive_origin=self.selection.get('archive_origin'))
        result['available']=True
        if value.get('ordinal',0)==0:
            summary=self.db.execute('''SELECT count(*),count(*) FILTER(WHERE status='missing')
                FROM caption_resources WHERE video_key=? AND track_body=unhex(?)''',[source['video_key'],source['saved_body']]).fetchall()[0]
            result.update(resource_count=summary[0],missing_count=summary[1])
        return result

    def caption_source_target(self, value):
        """Resolve a selected root directly, including recordings with no meeting association."""
        if value.get('release_id')!=self.release_id:
            raise ExplorerError('Caption reference belongs to another release')
        self.require('recordings')
        from .models import exact_scalar
        video=exact_scalar(value.get('video_key'),'VARCHAR','video_key')
        rows=self.rows('''SELECT r.video_key,lower(hex(t.body)) AS saved_body,t.suffix AS saved_suffix,t.format,t.language,t.production
            FROM recordings r,unnest(r.tracks) u(t) WHERE r.video_key=? AND t.body IS NOT NULL
            AND sha256('captions:'||r.video_key||':'||lower(hex(t.body))||':'||coalesce(t.language,'')||':'||coalesce(t.production,''))=?''',
            [video,value.get('source_id')],limit=2)
        found=rows['rows']
        if len(found)!=1:
            raise ExplorerError('Caption root is absent or ambiguous in this release')
        target=found[0]
        target.update(release_id=self.release_id,kind='captions',source_id=value['source_id'],reference=dict(
            release_id=self.release_id,kind='captions',source_id=value['source_id'],video_key=video),
            archive_origin=self.selection.get('archive_origin'),saved_url=self.file_url(target['saved_body'],target['saved_suffix']),
            saved_kind='original',witness_keys=[])
        return target

    def get_hearing_bundle(self, value):
        query = HearingBundleQuery.model_validate(value)
        meeting = self._hearing(query)
        result = dict(release_id=self.release_id,event_id=query.event_id,sections={})

        def section(name, table, sql=None, args=()):
            if name not in query.include:
                return
            if table not in self.schemas:
                result['sections'][name]=dict(state='unavailable',missing_tables=[table],rows=[])
                return
            offset=query.offsets.get(name,0)
            page=self.rows(sql+' OFFSET ?',[*args,offset],limit=query.limit)
            page.pop('columns')
            page.update(state='present' if page['rows'] else 'unknown',offset=offset)
            if page['has_more']:
                page['next']=dict(event_id=query.event_id,release_id=self.release_id,include=[name],limit=query.limit,offsets={name:offset+len(page['rows'])})
            result['sections'][name]=page

        if 'meeting' in query.include:
            result['sections']['meeting']=dict(state='present',rows=[meeting],has_more=False)
        section('committees','committees', '''SELECT c.*,mc.role FROM meetings m,unnest(m.committees) u(mc),committees c
            WHERE m.event_id=? AND mc.system_code=c.system_code ORDER BY c.system_code,mc.role''',[query.event_id])
        section('witnesses','witnesses', '''SELECT * FROM witnesses WHERE event_id=? AND superseded_by IS NULL
            ORDER BY panel_order NULLS LAST,display_order NULLS LAST,witness_key''',[query.event_id])
        section('prepared_testimony','documents', '''SELECT '''+self.document_summary+''',l.witness_keys FROM "list" l JOIN detail d USING(list_row)
            WHERE NOT coalesce(l.hidden,false) AND list_contains(l.meeting_keys,cast(? AS VARCHAR))
              AND list_has_any(l.document_kind,['testimony','witness-statement','prepared-statement','witness-testimony'])
            ORDER BY l.list_row''',[query.event_id])
        if 'prepared_testimony' in result['sections']:
            self.document_rows(result['sections']['prepared_testimony'])
        for name,kind in [('official_transcripts','official'),('committee_transcripts','committee'),('captions','captions')]:
            if name in query.include:
                page=self._source_page(TranscriptQuery(event_id=query.event_id,kind=kind),offset=query.offsets.get(name,0),limit=query.limit)
                page['state']='present' if page['rows'] else ('unavailable' if kind=='captions' and 'recordings' not in self.schemas else 'unknown')
                if kind=='committee' and 'source' not in self.schemas['meetings'].get('transcripts',''):
                    page['state']='unavailable'
                if page['has_more']:
                    page['next']=dict(event_id=query.event_id,release_id=self.release_id,include=[name],limit=query.limit,offsets={name:page['next_offset']})
                result['sections'][name]=page
        if 'recordings' in query.include:
            if 'meeting_links' in self.schemas.get('recording_matches',{}):
                section('recordings','recording_matches', '''SELECT * REPLACE(list_filter(meeting_links,lambda l:l.event_id=?) AS meeting_links)
                    FROM recording_matches WHERE list_contains(list_transform(meeting_links,lambda l:l.event_id),?) ORDER BY match_id''',[query.event_id,query.event_id])
            else:
                result['sections']['recordings']=dict(state='unavailable',reason='Published meeting associations are unavailable; original observations remain in recording_matches',rows=[])
        section('coverage','meeting_coverage','SELECT * FROM meeting_coverage WHERE event_id=? ORDER BY aspect',[query.event_id])
        if 'meeting_coverage' in self.schemas:
            coverage=self.rows('SELECT * FROM meeting_coverage WHERE event_id=? ORDER BY aspect',[query.event_id],limit=10)['rows']
            by_aspect={row['aspect']:row for row in coverage}
            aspects=dict(witnesses='witnesses',prepared_testimony='documents',official_transcripts='transcript',
                         committee_transcripts='transcript',captions='captions',recordings='recording')
            for name,page in result['sections'].items():
                if name in aspects:
                    page['published_coverage']=by_aspect.get(aspects[name],dict(aspect=aspects[name],state='unavailable'))
        # Preserve individual rows and make every omitted row reachable through the same tool.
        for name, page in reversed(result['sections'].items()):
            while len(encoded(result))>MAX_BYTES-4096 and page['rows'] and name!='meeting':
                page['rows'].pop(); page['has_more']=True
                if not page['rows']:
                    page['state']='partial'
                    page['reason']='This section continues separately to fit the response byte limit'
                page['next']=dict(event_id=query.event_id,release_id=self.release_id,include=[name],limit=query.limit,
                                  offsets={name:query.offsets.get(name,0)+len(page['rows'])})
        if len(encoded(result))>MAX_BYTES:
            raise ExplorerError('Hearing section contains an oversized row; narrow include or use query_sql to slice its fields')
        result['notes']=['Sections without rows are unknown, never proof of absence. Coverage rows retain the publisher/model states.',
                         'Witnesses use the published current-appearance rule. Package context does not establish event-specific recording or caption coverage.']
        return result
