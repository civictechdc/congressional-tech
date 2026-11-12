"""Named research over published rows, with the same release-bound paging as SQL."""
from .models import BillActions, RollCalls, MemberBallots, ActivityQuery, ResearchQuery, ExplorerError
from .release import quote


class LegislativeReader:
    def research_coverage(self, tables, since=None, until=None):
        files = self.selection['manifest']['files']
        coverage = {table: [dict(f.get('coverage', {}),generations=f.get('generations'),producer=f.get('producer')) for f in files
                    if f['name'] == table+'.parquet' or f.get('table') == table] for table in tables}
        missing = [table for table in tables if table not in self.schemas]
        intervals = {}
        for table,parts in coverage.items():
            starts = [p['date_start'] for p in parts if p.get('date_start')]
            ends = [p['date_end'] for p in parts if p.get('date_end')]
            if table in missing: intervals[table] = 'unavailable'
            elif (since and ends and since>max(ends)) or (until and starts and until<=min(starts)):
                intervals[table] = 'outside_retained_dates'
            else: intervals[table] = 'retained_records_only'
        return dict(interval_coverage=intervals,status='unavailable' if len(missing) == len(tables) else ('partial' if missing else 'available'),
            missing_tables=missing, tables=coverage, window=dict(since=since, until=until, boundaries='since inclusive, until exclusive'),
            limits=['Only the selected release is read; an empty interval does not establish complete publisher coverage.',
                    'Source dates remain literal on detail rows. Events with unavailable or unparseable dates are excluded from dated queries.'])

    @staticmethod
    def dated_filters(query, column, args):
        terms = []
        if query.since:
            terms.append(f'{column}>=CAST(? AS DATE)'); args.append(query.since)
        if query.until:
            terms.append(f'{column}<CAST(? AS DATE)'); args.append(query.until)
        return terms

    @staticmethod
    def local_action_time(column):
        """Parse only a supplied local clock value; preserve literal precision and unknown zones."""
        return (f"CASE WHEN regexp_full_match({column},'[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{1,6}})?') "
                f'THEN try_cast({column} AS TIME) END')

    def roll_call_bill_match(self, vote, bill_id):
        """One association rule for bill lookups and activity filters; every match is existential."""
        matches = [f'lower({vote}.bill_id)=lower({bill_id})']
        if 'bill_references' in self.schemas.get('roll_call_votes', {}):
            matches.append(f'EXISTS (SELECT 1 FROM unnest({vote}.bill_references) refs(r) WHERE lower(r.bill_id)=lower({bill_id}))')
        elif 'bills' in self.schemas:
            matches.append(f'EXISTS (SELECT 1 FROM bills linked,unnest(linked.floor_votes) f(vote) WHERE linked.bill_id={bill_id} AND vote.vote_id={vote}.vote_id)')
        return '('+' OR '.join(matches)+')'

    def activity_bill_matches(self, ctes, name, field):
        # Build eligible IDs once. Correlating each event to bills and then
        # to vote references produces a cross product on archive-sized feeds.
        bills = name+'_bills'
        ctes.append(f'{bills} AS (SELECT bill_id FROM bills WHERE list_contains({field},?))')
        matches = [f'e.subject_id IN (SELECT bill_id FROM {bills})']
        if 'roll_call_votes' in self.schemas:
            votes = [f'SELECT v.vote_id FROM roll_call_votes v JOIN {bills} b ON lower(v.bill_id)=lower(b.bill_id)']
            if 'bill_references' in self.schemas['roll_call_votes']:
                votes.append(f'SELECT v.vote_id FROM roll_call_votes v CROSS JOIN unnest(v.bill_references) refs(r) '
                             f'JOIN {bills} b ON lower(r.bill_id)=lower(b.bill_id)')
            else:
                votes.append(f'SELECT vote.vote_id FROM bills linked CROSS JOIN unnest(linked.floor_votes) f(vote) '
                             f'JOIN {bills} b ON linked.bill_id=b.bill_id')
            matches.append("(e.source_table='roll_call_votes' AND e.event_key IN ("+' UNION ALL '.join(votes)+'))')
        return matches

    def _member_vote_date_buckets(self):
        shadowed = bool(self.db.execute(
            "SELECT 1 FROM duckdb_views() WHERE database_name='temp' AND view_name='member_votes' "
            "UNION ALL SELECT 1 FROM duckdb_tables() WHERE database_name='temp' AND table_name='member_votes' LIMIT 1"
        ).fetchall())
        if not shadowed and getattr(self, '_ballot_date_buckets', None) is not None:
            return self._ballot_date_buckets
        # Avoid a WHERE clause here: DuckDB otherwise pushes TRY_CAST below GROUP BY
        # onto all 10M+ ballot rows instead of evaluating it once per distinct string.
        grouped = self.db.execute(
            'SELECT vote_date,try_cast(vote_date AS DATE) IS NOT NULL,count(*) AS n '
            'FROM member_votes GROUP BY vote_date'
        ).fetchall()
        dated = [dict(v=literal, n=int(count)) for literal, parseable, count in grouped if parseable]
        rows = self.db.execute(
            'SELECT list(item.v ORDER BY item.v),sum(item.n)::BIGINT '
            'FROM unnest(?::STRUCT(v VARCHAR,n BIGINT)[]) u(item) '
            'GROUP BY try_cast(item.v AS DATE) ORDER BY try_cast(item.v AS DATE) ASC',
            [dated],
        ).fetchall() if dated else []
        buckets = [(list(literals), int(count)) for literals, count in rows]
        value = (buckets, sum(count for _, count in buckets))
        if not shadowed:
            self._ballot_date_buckets = value
        return value

    def legislative_page(self, query, table, date_field, identity):
        query.window()
        coverage = self.research_coverage([table], query.since, query.until)
        if table not in self.schemas:
            return dict(release_id=self.release_id, rows=[], has_more=False, coverage=coverage)
        args = []
        date_column = f'try_cast(t.{date_field} AS DATE)'
        # Ballot vote_date is a literal Senate/House display date. The vote table owns the ISO day.
        source = quote(table)+' t'
        if table == 'member_votes' and (query.since or query.until):
            if 'roll_call_votes' not in self.schemas:
                return dict(release_id=self.release_id, rows=[], has_more=False,
                    coverage=self.research_coverage(['roll_call_votes'], query.since, query.until))
            source += ' LEFT JOIN roll_call_votes v ON t.vote_id=v.vote_id'
            date_column = 'try_cast(v.vote_day AS DATE)'
        terms = self.dated_filters(query, date_column, args)
        for key in ('bill_id', 'vote_id', 'member_key', 'bioguide_id'):
            value = getattr(query, key, None)
            if value is not None:
                if key == 'bill_id': value = value.strip().lower()
                if key == 'bioguide_id': value = value.strip().upper()
                if key == 'bill_id' and table == 'roll_call_votes':
                    terms.append('EXISTS (SELECT 1 FROM (SELECT ? AS bill_id) subject WHERE '+self.roll_call_bill_match('t','subject.bill_id')+')')
                else:
                    terms.append(f't.{key}=?')
                args.append(value)
        if query.chamber:
            if table == 'bill_actions':
                terms.append("CASE WHEN lower(t.source_system_name) LIKE '%house%' THEN 'house' WHEN lower(t.source_system_name) LIKE '%senate%' THEN 'senate' END=?")
            else:
                terms.append("CASE lower(t.chamber) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' ELSE lower(t.chamber) END=?")
            args.append(query.chamber)
        order = date_column+' ASC NULLS LAST,'
        if table == 'bill_actions': order += self.local_action_time('t.action_time')+' ASC NULLS LAST,'
        order += ','.join('t.'+key for key in identity)
        sql = 'SELECT t.* FROM '+source+(' WHERE '+' AND '.join(terms) if terms else '')
        expand = None
        if table == 'member_votes' and not terms and self.entity_keys.get(table) == identity:
            buckets, dated_total = self._member_vote_date_buckets()
            if not buckets:
                # Every literal ballot date casts to NULL; primary-key Top-N order
                # preserves TRY_CAST(... ASC NULLS LAST) and prunes Parquet row groups.
                sql = 'SELECT t.vote_id,t.member_key FROM member_votes t'
                order = 't.vote_id,t.member_key'

                def expand(selected):
                    return ('WITH ballot_page AS MATERIALIZED ('+selected+') '
                            'SELECT t.* FROM ballot_page p JOIN member_votes t USING(vote_id,member_key) '
                            'ORDER BY t.vote_id,t.member_key')
            else:
                prefix_literals, covered = [], 0
                if not query.cursor and dated_total >= query.limit + 1:
                    for literals, count in buckets:
                        prefix_literals.extend(literals)
                        covered += count
                        if covered >= query.limit + 1:
                            break
                if prefix_literals and covered >= query.limit + 1 and len(prefix_literals) <= 500:
                    placeholders = ','.join('?' for _ in prefix_literals)
                    sql = f'''WITH ballot_dates AS MATERIALIZED (
                        SELECT vote_date,try_cast(vote_date AS DATE) AS parsed_date
                        FROM unnest([{placeholders}]::VARCHAR[]) u(vote_date))
                        SELECT t.vote_id,t.member_key,d.parsed_date FROM member_votes t
                        JOIN ballot_dates d ON t.vote_date=d.vote_date'''
                    args = list(prefix_literals)
                else:
                    # Cast each distinct literal once, retaining TRY_CAST's exact meaning.
                    # Select narrow page keys before fetching the published primary-key rows.
                    sql = '''WITH ballot_dates AS MATERIALIZED (
                        SELECT vote_date,try_cast(vote_date AS DATE) AS parsed_date
                        FROM (SELECT DISTINCT vote_date FROM member_votes))
                        SELECT t.vote_id,t.member_key,d.parsed_date FROM member_votes t
                        JOIN ballot_dates d ON t.vote_date IS NOT DISTINCT FROM d.vote_date'''
                order = 'd.parsed_date ASC NULLS LAST,t.vote_id,t.member_key'

                def expand(selected):
                    return 'WITH ballot_page AS MATERIALIZED ('+selected+''')
                        SELECT t.* FROM ballot_page p JOIN member_votes t USING(vote_id,member_key)
                        ORDER BY p.parsed_date ASC NULLS LAST,t.vote_id,t.member_key'''

        result = self.page(query, sql, args,order=order,expand=expand)
        if table == 'bill_actions':
            result['ordering'] = 'Calendar date, supplied local clock time ascending, then bill_id/action_index. Missing or unparseable clock values follow timed rows on the same date; their actual time remains unknown. No timezone is inferred.'
        result['coverage'] = coverage
        result['date_field'] = date_field
        return result

    def get_bill_actions(self, query):
        return self.legislative_page(BillActions.model_validate(query), 'bill_actions', 'action_date', ['bill_id','action_index'])

    def get_roll_calls(self, query):
        return self.legislative_page(RollCalls.model_validate(query), 'roll_call_votes', 'vote_day', ['vote_id'])

    def get_member_ballots(self, query):
        return self.legislative_page(MemberBallots.model_validate(query), 'member_votes', 'vote_date', ['vote_id','member_key'])

    def resolve_committee(self, value):
        if value is None: return None
        self.require('committees')
        key = value.strip().lower()
        rows = self.rows('SELECT system_code,name FROM committees WHERE lower(system_code)=? OR lower(name)=? ORDER BY system_code', [key,key])['rows']
        if not rows:
            rows = self.rows('SELECT system_code,name FROM committees WHERE contains(lower(name),?) ORDER BY system_code', [key])['rows']
        if len(rows) != 1:
            raise ExplorerError('Committee must identify one published code; candidates: '+str(rows[:12]))
        return rows[0]['system_code']

    def resolve_subject(self, value):
        if value is None: return None
        self.require('bills')
        if 'subjects' not in self.schemas['bills']:
            raise ExplorerError('This release does not publish bill subject associations')
        sql = 'SELECT DISTINCT unnest(subjects) AS subject FROM bills'
        key = value.strip().lower()
        rows = self.rows('SELECT subject FROM ('+sql+') WHERE lower(subject)=? ORDER BY subject', [key])['rows']
        if not rows:
            rows = self.rows('SELECT subject FROM ('+sql+') WHERE contains(lower(subject),?) ORDER BY subject', [key])['rows']
        if len(rows) != 1:
            raise ExplorerError('Subject must identify one published subject label; candidates: '+str(rows[:12]))
        return rows[0]['subject']

    def run_research_query(self, query):
        query = ResearchQuery.model_validate(query).window()
        table = {'recent_bills':'bills','pending_nominations':'nominations','hearings_by_committee':'meetings','legislation_by_subject':'bills'}[query.name]
        coverage = self.research_coverage([table], query.since, query.until)
        if table not in self.schemas:
            return dict(release_id=self.release_id, rows=[], has_more=False, coverage=coverage)
        if query.committee and 'committees' not in self.schemas:
            return dict(release_id=self.release_id,rows=[],has_more=False,coverage=self.research_coverage(['committees'],query.since,query.until))
        if query.subject and 'subjects' not in self.schemas.get('bills', {}):
            coverage.update(status='unavailable',missing_fields=['bills.subjects'])
            return dict(release_id=self.release_id,rows=[],has_more=False,coverage=coverage)
        committee = self.resolve_committee(query.committee)
        subject = self.resolve_subject(query.subject) if query.subject else None
        args, terms = [], []
        if query.name in ('recent_bills','legislation_by_subject'):
            key, field = 'bill_id', 'introduced'
            terms += self.dated_filters(query, 't.introduced', args)
            if committee: terms.append('list_contains(t.committees,?)'); args.append(committee)
            if subject: terms.append('list_contains(t.subjects,?)'); args.append(subject)
            if query.name == 'legislation_by_subject' and subject is None:
                raise ExplorerError('legislation_by_subject requires a published subject label')
            if query.chamber:
                terms.append("CASE split_part(t.bill_id,'-',2) WHEN 'hr' THEN 'house' WHEN 'hres' THEN 'house' WHEN 'hjres' THEN 'house' WHEN 'hconres' THEN 'house' WHEN 's' THEN 'senate' WHEN 'sres' THEN 'senate' WHEN 'sjres' THEN 'senate' WHEN 'sconres' THEN 'senate' END=?"); args.append(query.chamber)
            source_url = "'https://www.congress.gov/bill/'||split_part(t.bill_id,'-',1)||'th-congress/'||CASE split_part(t.bill_id,'-',2) WHEN 'hr' THEN 'house-bill' WHEN 's' THEN 'senate-bill' WHEN 'hres' THEN 'house-resolution' WHEN 'sres' THEN 'senate-resolution' WHEN 'hjres' THEN 'house-joint-resolution' WHEN 'sjres' THEN 'senate-joint-resolution' WHEN 'hconres' THEN 'house-concurrent-resolution' WHEN 'sconres' THEN 'senate-concurrent-resolution' END||'/'||split_part(t.bill_id,'-',3)"
        elif query.name == 'pending_nominations':
            key, field = 'nomination_id', 'received'
            terms += self.dated_filters(query, 't.received', args)
            if committee: terms.append('list_contains(t.committees,?)'); args.append(committee)
            # Source wording proves only "no terminal action recorded", never present-day pending status.
            terms.append("t.latest_action_text IS NOT NULL AND NOT regexp_matches(lower(t.latest_action_text),'^confirmed|withdrawal of nomination|withdrawn|^returned to the president|^rejected by the senate')")
            if query.chamber and query.chamber != 'senate': terms.append('false')
            if subject: raise ExplorerError('Nominations have no published bill-subject association')
            source_url = "'https://www.congress.gov/nomination/'||split_part(t.nomination_id,'-',1)||'th-congress/'||split_part(t.nomination_id,'-',3)"
            coverage['limits'].append('Pending means a known latest action without confirmed, withdrawn, returned or rejected wording in this snapshot. Missing latest actions remain unknown and are excluded.')
        else:
            key, field = 'event_id', 'meeting_date'
            if committee is None: raise ExplorerError('hearings_by_committee requires a committee code or unique name')
            terms += self.dated_filters(query, 't.meeting_date', args)
            terms.append("(lower(coalesce(t.meeting_type,'')) LIKE '%hearing%' OR upper(t.meeting_type)='HHRG')")
            terms.append('EXISTS (SELECT 1 FROM unnest(t.committees) c(item) WHERE item.system_code=?)'); args.append(committee)
            if query.chamber: terms.append('t.chamber=?'); args.append(query.chamber)
            if subject: raise ExplorerError('Use get_activity(topic=...) for meeting-to-bill subject associations')
            source_url = "'https://www.congress.gov/event/'||cast(t.event_id AS VARCHAR)"
        recipe = next((r for r in self.selection['controls']['schema'].get('recipes', []) if r['id']=='research_'+query.name), None)
        if recipe is None:
            raise ExplorerError('This release does not publish the named research recipe; use get_dataset_info for supported recipes')
        recipe_args = [query.since,query.since,query.until,query.until]
        if query.name == 'legislation_by_subject': recipe_args = [subject]
        captions = ','+self.meeting_captions('t') if table == 'meetings' else ''
        result = self.page(query, 'SELECT t.*,'+source_url+' AS publisher_url'+captions+' FROM ('+recipe['sql']+') t'+(' WHERE '+' AND '.join(terms) if terms else ''), [*recipe_args,*args],
            order=f't.{field} DESC NULLS LAST,t.{key}')
        result = self.entity_rows(result, table)
        for row in result['rows']:
            row['reference'] = dict(release_id=self.release_id,table=table,id=row[key])
            row['missing_fields'] = sorted(k for k,v in row.items() if v is None)
        result.update(coverage=coverage, query_name=query.name, date_field=field,
            resolved_filters=dict(committee=committee,subject=subject))
        return result

    def get_activity(self, query):
        query = ActivityQuery.model_validate(query).window()
        required = ['bill_actions','roll_call_votes','nominations','meetings']
        coverage = self.research_coverage(required, query.since, query.until)
        if 'nominations' in self.schemas:
            # Published nomination bounds cover received dates, not later actions.
            coverage['interval_coverage']['nominations'] = 'event_date_bounds_unavailable'
            coverage['limits'].append('Nomination date bounds describe received dates only; latest and committee actions can fall outside them. Activity date bounds are unavailable from this metadata.')
        if query.committee and 'committees' not in self.schemas:
            return dict(release_id=self.release_id,rows=[],has_more=False,coverage=self.research_coverage(['committees'],query.since,query.until))
        if query.topic and 'subjects' not in self.schemas.get('bills', {}):
            coverage.update(status='unavailable',missing_fields=['bills.subjects'])
            return dict(release_id=self.release_id,rows=[],has_more=False,coverage=coverage)
        committee = self.resolve_committee(query.committee)
        topic = self.resolve_subject(query.topic) if query.topic else None
        if (committee or topic) and 'bills' not in self.schemas:
            return dict(release_id=self.release_id,rows=[],has_more=False,coverage=self.research_coverage(['bills'],query.since,query.until))
        unions = []
        # Events preserve source occurrence keys, so equal dates/text never collapse distinct rows.
        if 'bill_actions' in self.schemas:
            chamber = "CASE WHEN lower(a.source_system_name) LIKE '%house%' THEN 'house' WHEN lower(a.source_system_name) LIKE '%senate%' THEN 'senate' END"
            unions.append("SELECT 'bill_action' AS event_type,a.bill_id||':'||cast(a.action_index AS VARCHAR) AS event_key,try_cast(a.action_date AS DATE) AS event_date,a.action_date AS source_date,a.action_time AS source_time,'day' AS date_precision,a.bill_id AS subject_id,a.action_text AS description,"+chamber+" AS chamber,'bill_actions' AS source_table,to_json(struct_pack(bill_id:=a.bill_id,action_index:=a.action_index)) AS source_key FROM bill_actions a")
        if 'roll_call_votes' in self.schemas:
            unions.append("SELECT 'roll_call',vote_id,try_cast(vote_day AS DATE),vote_date,NULL::VARCHAR,'day',bill_id,question,CASE lower(chamber) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' ELSE lower(chamber) END,'roll_call_votes',to_json(struct_pack(vote_id:=vote_id)) FROM roll_call_votes")
        if 'nominations' in self.schemas:
            unions.append("SELECT 'nomination_received',nomination_id,received,cast(received AS VARCHAR),NULL::VARCHAR,'day',nomination_id,description,'senate','nominations',to_json(struct_pack(nomination_id:=nomination_id)) FROM nominations")
            unions.append("SELECT 'nomination_latest_action',nomination_id,latest_action_date,cast(latest_action_date AS VARCHAR),NULL::VARCHAR,'day',nomination_id,latest_action_text,'senate','nominations',to_json(struct_pack(nomination_id:=nomination_id)) FROM nominations")
            if 'committee_activities' in self.schemas['nominations']:
                unions.append("SELECT 'nomination_committee_activity',n.nomination_id||':'||cast(gi AS VARCHAR)||':'||cast(ai AS VARCHAR),try_cast(substr(a.date,1,10) AS DATE),a.date,NULL::VARCHAR,'day',n.nomination_id,a.name,'senate','nominations',to_json(struct_pack(nomination_id:=n.nomination_id,committee_index:=gi,activity_index:=ai)) FROM nominations n,unnest(n.committee_activities) WITH ORDINALITY g(c,gi),unnest(c.activities) WITH ORDINALITY acts(a,ai)")
            coverage['limits'].append('Nomination latest actions are snapshot summaries, not a full Senate action history.')
        if 'meetings' in self.schemas:
            unions.append("SELECT 'meeting_scheduled',cast(event_id AS VARCHAR),meeting_date,cast(meeting_date AS VARCHAR),NULL::VARCHAR,'day',cast(event_id AS VARCHAR),title,chamber,'meetings',to_json(struct_pack(event_id:=event_id)) FROM meetings")
        if not unions:
            return dict(release_id=self.release_id,rows=[],has_more=False,coverage=coverage)
        ctes, filter_args, args = [], [], []
        terms = self.dated_filters(query, 'e.event_date', args)
        if query.chamber: terms.append('e.chamber=?'); args.append(query.chamber)
        if committee:
            matches = self.activity_bill_matches(ctes, 'committee', 'committees')
            filter_args.append(committee)
            if 'nominations' in self.schemas:
                matches.append('e.subject_id IN (SELECT nomination_id FROM nominations WHERE list_contains(committees,?))')
                args.append(committee)
            if 'meetings' in self.schemas:
                matches.append("(e.source_table='meetings' AND e.subject_id IN (SELECT cast(m.event_id AS VARCHAR) "
                               'FROM meetings m,unnest(m.committees) c(item) WHERE item.system_code=?))')
                args.append(committee)
            terms.append('('+' OR '.join(matches)+')')
        if topic:
            matches = self.activity_bill_matches(ctes, 'topic', 'subjects')
            filter_args.append(topic)
            if 'meetings' in self.schemas:
                matches.append("(e.source_table='meetings' AND e.subject_id IN (SELECT cast(m.event_id AS VARCHAR) "
                               'FROM meetings m CROSS JOIN unnest(m.subject_keys) s(bill_id) JOIN topic_bills b ON s.bill_id=b.bill_id))')
            terms.append('('+' OR '.join(matches)+')')
        prefix = 'WITH '+', '.join(ctes)+' ' if ctes else ''
        result = self.page(query, prefix+'SELECT e.* FROM ('+' UNION ALL '.join(unions)+') e(event_type,event_key,event_date,source_date,source_time,date_precision,subject_id,description,chamber,source_table,source_key) WHERE '+' AND '.join(terms), [*filter_args,*args],
            order='e.event_date ASC NULLS LAST,'+self.local_action_time('e.source_time')+
                " ASC NULLS LAST,e.event_type,e.subject_id ASC NULLS LAST,try_cast(json_extract_string(e.source_key,'$.action_index') AS BIGINT) ASC NULLS LAST,e.event_key")
        for row in result['rows']:
            row['reference'] = dict(release_id=self.release_id,table=row.pop('source_table'),key=row.pop('source_key'))
        coverage['limits'] += ['Meeting dates describe schedules, not proof of a sitting. Use the meeting outcome fields.',
            'Committee filters match exact published association codes, without automatically adding subcommittees.',
            'Topic filters use published bill subjects and meeting subject_keys, never title keywords. Roll calls follow their direct bill_id and supported bill references; one vote remains one event. Events outside local bill profiles have unavailable committee/topic associations.',
            'Same-day actions use supplied local clock time ascending; missing or unparseable times follow timed events. Their actual time remains unknown, and no timezone is inferred.']
        result.update(coverage=coverage,resolved_filters=dict(committee=committee,topic=topic))
        return result
