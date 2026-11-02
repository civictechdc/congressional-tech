"""Native line-grain scheduling and scoped discovery for phase-one releases."""
from pathlib import Path

from viewer_publication.archive_format import TS

ROOT=Path(__file__).parents[4]


def url_state_steps(*,root=ROOT,recovery_policy=None):
    """Use shared good-fetch and URL keys, preserving explicit input diagnostics."""
    acquisition=(
        "mode='fetch' AND coalesce(fetch_outcome,outcome,'') NOT IN ('reference','saved-record') "
        "AND coalesce(outcome,'') NOT IN ('reference','saved-record') AND requested_url IS NOT NULL")
    fetch_status="CASE WHEN b.fetch_outcome IS NOT NULL THEN b.fetch_http_status ELSE b.http_status END"
    fetch_outcome="coalesce(b.fetch_outcome,b.outcome)"
    sqls=[('lines',f"""WITH base_captures AS (
        SELECT * FROM captures WHERE {acquisition}
    ), companion_keys AS (
        SELECT DISTINCT receipt_key,receipt_line,requested_url FROM base_captures WHERE family<>'external/provider-responses'
    ), stored_contexts AS (
        SELECT DISTINCT receipt_key,context_url FROM captures
        WHERE mode='fetch' AND complete AND outcome IN ('stored','unchanged')
          AND sha256 IS NOT NULL AND requested_url IS NULL AND context_url IS NOT NULL
    ), folded_captures AS (
        SELECT b.receipt_key,b.receipt_line,b.requested_url,b.family,b.retrieved_at,
            {fetch_status} AS http_status,
            {fetch_outcome} AS outcome,
            ({fetch_outcome}='failed' AND coalesce(b.attempt,0)=0 AND b.complete AND {fetch_status} BETWEEN 200 AND 299 AND {fetch_status}<>202 AND sc.context_url IS NOT NULL) AS context_good
        FROM base_captures b
        LEFT JOIN companion_keys c ON b.receipt_key=c.receipt_key AND b.receipt_line=c.receipt_line AND b.requested_url=c.requested_url
        LEFT JOIN stored_contexts sc ON b.receipt_key=sc.receipt_key AND b.requested_url=sc.context_url
        WHERE b.family<>'external/provider-responses' OR c.receipt_key IS NULL
    ) SELECT receipt_key,receipt_line,requested_url,max(family) AS family,
        max(arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS retrieved_at,
        max(http_status) AS http_status,
        CASE WHEN bool_or(context_good) THEN 'stored' ELSE max(outcome) END AS outcome,
        bool_or(context_good) AS context_good,
        count(DISTINCT json_array(family,http_status,outcome)) AS variants
        FROM folded_captures GROUP BY receipt_key,receipt_line,requested_url"""),
        ('good_lines',"""SELECT DISTINCT c.receipt_key,c.receipt_line,c.requested_url
            FROM good_fetch_contexts g JOIN captures c USING(receipt_key,receipt_line,capture_index)
            WHERE c.requested_url IS NOT NULL
            UNION
            SELECT DISTINCT receipt_key,receipt_line,requested_url FROM captures
            WHERE mode='fetch' AND complete AND outcome IN ('stored','unchanged') AND sha256 IS NOT NULL AND http_status IS NULL AND requested_url IS NOT NULL
            UNION
            SELECT DISTINCT receipt_key,receipt_line,requested_url FROM url_state_lines WHERE context_good"""),
        ('latest',"""SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY requested_url ORDER BY
            retrieved_at DESC NULLS LAST,receipt_key DESC,receipt_line DESC) AS preference FROM url_state_lines
            WHERE requested_url IS NOT NULL) WHERE preference=1"""),
        ('ages',"""WITH meetings AS (
            SELECT requested_url,min(cast(meeting_date AS DATE)) AS meeting_date FROM url_state_meeting_dates GROUP BY requested_url
            ), dated AS (SELECT l.*,coalesce(m.meeting_date,try_cast(regexp_replace(
            (regexp_match(l.requested_url,'(?i)^https?://docs[.]house[.]gov/meetings/[^/]+/[^/]+/([0-9]{8})/'))[1],
            '^([0-9]{4})([0-9]{2})([0-9]{2})$','$1-$2-$3') AS DATE)) AS meeting_date
            FROM meetings m RIGHT JOIN url_state_latest l ON l.requested_url=m.requested_url)
            SELECT *,cast((date_part('epoch',cast(retrieved_at AS DATE))-date_part('epoch',meeting_date))/86400 AS BIGINT) AS age_days FROM dated"""),
        ('interval_candidates',"""SELECT a.requested_url,i.id,i.interval_seconds
            FROM recheck_intervals i JOIN url_state_ages a ON a.family=i.family
            WHERE a.age_days IS NULL OR ((i.min_age_days IS NULL OR a.age_days>=i.min_age_days)
              AND (i.max_age_days IS NULL OR a.age_days<i.max_age_days))"""),
        ('intervals',"""WITH counts AS (
            SELECT requested_url,count(*) AS matches FROM url_state_interval_candidates GROUP BY requested_url
            ), ranked AS (SELECT *,row_number() OVER(PARTITION BY requested_url
            ORDER BY interval_seconds,id) AS preference FROM url_state_interval_candidates)
            SELECT r.requested_url,r.interval_seconds,c.matches,r.preference
            FROM counts c JOIN ranked r ON c.requested_url=r.requested_url WHERE r.preference=1"""),
        ('page_contexts',"""SELECT DISTINCT encode(g.sha256,'hex') AS page_body,g.context_url,g.member_path
            FROM good_fetch_contexts g JOIN record_roles r USING(receipt_key,receipt_line,capture_index)
            WHERE g.sha256 IS NOT NULL AND r.record_role IS DISTINCT FROM 'error_response'"""),
        ('fetched_keys',f"""WITH raw_urls AS (
            SELECT DISTINCT unnest(make_array(requested_url,url)) AS url FROM captures WHERE {acquisition}
            ) SELECT DISTINCT k.url_key FROM raw_urls f JOIN model_url_keys k ON f.url=k.url
            WHERE k.error IS NULL AND k.url_key IS NOT NULL"""),
        ('scope_patterns','SELECT family,unnest(patterns) AS pattern FROM capture_scope'),
        ('scope_exclusions','SELECT family,unnest(exclusions) AS pattern FROM capture_scope'),
        ('scoped_targets',"""SELECT DISTINCT l.target_url FROM
            url_state_scope_exclusions e RIGHT JOIN (
             url_state_scope_patterns s JOIN
             (SELECT DISTINCT target_url FROM resolved_link_targets WHERE target_member_path IS NULL) l
             ON regexp_like(l.target_url,s.pattern)
            ) ON e.family=s.family AND regexp_like(l.target_url,e.pattern)
            WHERE e.family IS NULL"""),
        ('queue_literals',"""SELECT k.url_key,min(l.target_url) AS url FROM resolved_link_targets l
            JOIN (SELECT * FROM url_state_page_contexts WHERE page_body IS NOT NULL AND context_url IS NOT NULL) p
              ON (l.page_body IS NOT DISTINCT FROM p.page_body) AND (l.context_url IS NOT DISTINCT FROM p.context_url)
              AND (l.member_path IS NOT DISTINCT FROM p.member_path)
            JOIN (SELECT * FROM model_url_keys WHERE url IS NOT NULL) k ON (l.target_url IS NOT DISTINCT FROM k.url)
            JOIN (SELECT * FROM url_state_scoped_targets WHERE target_url IS NOT NULL) s ON (l.target_url IS NOT DISTINCT FROM s.target_url)
            WHERE l.target_member_path IS NULL AND k.error IS NULL AND k.url_key IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM url_state_fetched_keys f WHERE f.url_key=k.url_key)
            GROUP BY k.url_key"""),
        ('public_urls',"""SELECT requested_url AS url FROM url_state_latest UNION SELECT url FROM url_state_queue_literals"""),
        ('query_parts',"""WITH queries AS (
            SELECT url,CASE WHEN strpos(split_part(url,'#',1),'?')>0
            THEN substr(split_part(url,'#',1),strpos(split_part(url,'#',1),'?')+1) END AS query
            FROM url_state_public_urls)
            SELECT url,unnest(string_to_array(query,'&')) AS part,
              unnest(range(0,cast(array_length(string_to_array(query,'&')) AS BIGINT))) AS position FROM queries"""),
        ('sanitized',"""WITH queries AS (
            SELECT p.url,string_agg(p.part,'&' ORDER BY p.position) AS query FROM credential_parameters c RIGHT ANTI JOIN url_state_query_parts p
            ON lower(percent_decode_utf8(replace(split_part(p.part,'=',1),'+',' ')))=lower(c.parameter)
            GROUP BY p.url)
            SELECT u.url,split_part(split_part(u.url,'#',1),'?',1)||
            CASE WHEN q.query IS NOT NULL THEN '?'||q.query ELSE '' END||
            CASE WHEN strpos(u.url,'#')>0 THEN substr(u.url,strpos(u.url,'#')) ELSE '' END AS public_url
            FROM queries q RIGHT JOIN url_state_public_urls u ON u.url=q.url"""),
        ('sanitized_inputs',"""SELECT DISTINCT encode(sha256(json_array(s.public_url)),'hex') AS input_id,s.public_url AS url
            FROM url_state_queue_literals q JOIN url_state_sanitized s ON q.url=s.url""")]
    steps=[dict(name='url_state_'+name,sql=sql,materialize=True) for name,sql in sqls]
    # Normalize only newly sanitized spellings with the same maintained policy.
    normalize=(Path(root)/'model/sql/url-normalized.sql').read_text().replace('url_inputs','url_state_sanitized_inputs')
    keys=(Path(root)/'model/sql/url-keys.sql').read_text().replace('url_inputs','url_state_sanitized_inputs').replace('url_normalized','url_state_sanitized_normalized')
    steps += [dict(name='url_state_sanitized_normalized',sql=normalize,materialize=True),
        dict(name='url_state_sanitized_keys',sql=keys,materialize=True),
        dict(name='url_state_queue',sql="""SELECT q.url_key AS original_key,s.public_url AS requested_url,k.url_key AS public_key,k.error
            FROM url_state_queue_literals q JOIN url_state_sanitized s ON q.url=s.url
            LEFT JOIN url_state_sanitized_keys k ON s.public_url=k.url""",materialize=True),
        dict(name='url_state',sql=(Path(root)/'model/sql/url-state.sql').read_text().replace('{{TS}}',TS),materialize=True),
        dict(name='url_state_invariants_step',sql="""SELECT
        (SELECT count(*) FROM url_state_latest l WHERE NOT EXISTS(SELECT 1 FROM url_state_intervals i WHERE i.requested_url=l.requested_url)) AS unknown_families,
        (SELECT count(*) FROM url_state_lines WHERE variants<>1) AS conflicting_lines,
        (SELECT count(*) FROM recheck_intervals WHERE interval_seconds IS NULL OR interval_seconds<=0) AS invalid_intervals,
        (SELECT count(*) FROM url_state_intervals i JOIN url_state_ages a ON i.requested_url=a.requested_url WHERE a.age_days IS NOT NULL AND i.matches<>1) AS overlapping_bands,
        ((SELECT count(*) FROM (SELECT public_key FROM url_state_queue GROUP BY public_key HAVING count(DISTINCT original_key)>1))
          +(SELECT count(*) FROM url_state_queue q JOIN url_state_fetched_keys f ON q.public_key=f.url_key)) AS sanitization_collisions,
        (SELECT count(*) FROM url_state_sanitized s JOIN url_state_latest l ON s.url=l.requested_url WHERE s.public_url<>s.url
          OR regexp_like(s.url,'(?i)^https?://[^/?#]*@')) AS private_history,
        (SELECT count(*) FROM url_state_queue WHERE public_key IS NULL OR error IS NOT NULL) AS unusable_queue_keys,
        (SELECT count(*) FROM (SELECT requested_url FROM url_state GROUP BY requested_url HAVING count(*)>1)) AS duplicate_urls""",materialize=True)]
    if recovery_policy is not None:
        # Keep ordinary HTTP facts untouched; recovery is a separate decision.
        state=next(step for step in steps if step['name']=='url_state')
        state['name']='url_state_history'
        policy=recovery_policy['acceptance_policy'].replace("'","''")
        eligibility=f"""WITH candidates AS (
          SELECT d.original_url,d.id,d.kind,d.target_requirement,d.acceptance_policy
          FROM recovery_decisions d JOIN recovery_requirements r ON d.original_url=r.original_url
          JOIN (SELECT DISTINCT original_url,encode(sha256,'hex') AS body_sha FROM captures
                WHERE mode='retained_import' AND complete) c
            ON c.original_url=d.original_url AND c.body_sha=lower(d.body_sha256)
          WHERE d.recovery_record_version=2 AND d.acceptance_status='accepted'
            AND d.acceptance_policy='{policy}' AND r.acceptance_policy='{policy}'
            AND d.target_requirement=r.target_requirement AND r.refresh_policy='historical_only'
            AND regexp_like(d.evidence_sha256,'^[0-9a-fA-F]{{64}}$')
            AND regexp_like(d.qualification_sha256,'^[0-9a-f]{{64}}$')
            AND d.id NOT IN (SELECT supersedes FROM recovery_decisions WHERE supersedes IS NOT NULL)
        ), active_counts AS (
          SELECT original_url,count(*) AS n FROM recovery_decisions d
          WHERE d.id NOT IN (SELECT supersedes FROM recovery_decisions WHERE supersedes IS NOT NULL)
          GROUP BY original_url
        ), unambiguous AS (
          SELECT c.original_url,min(c.id) AS id FROM candidates c JOIN active_counts a ON c.original_url=a.original_url AND a.n=1
          WHERE c.kind='recovered_document'
            OR (c.target_requirement IN ('requested_content','current_official_counterpart') AND c.kind IN
                ('requested_content_in_official_hearing','requested_content_in_official_report',
                 'requested_content_in_official_amendment_packet','official_complete_statement_text_available',
                 'same_article_publisher_text_available'))
            OR (c.target_requirement='current_official_counterpart' AND c.kind IN
                ('official_updated_revision_available','official_introduced_bill_counterpart',
                 'official_recorded_votes_available','official_alternate_amendment_available',
                 'official_public_statement_counterpart','official_report_counterpart_available','related_final_report_available'))
          GROUP BY c.original_url HAVING count(*)=1
        ), excluded AS (SELECT DISTINCT l.requested_url FROM url_state_latest l JOIN url_state_scope_exclusions e
            ON e.family=l.family AND regexp_like(l.requested_url,e.pattern))
        SELECT h.*,
          CASE WHEN x.requested_url IS NOT NULL THEN 'excluded'
               WHEN u.id IS NOT NULL THEN 'satisfied' ELSE 'eligible' END AS capture_disposition,
          CASE WHEN x.requested_url IS NOT NULL THEN 'scope_exclusion'
               WHEN u.id IS NOT NULL THEN 'qualified_recovery' ELSE 'no_satisfying_recovery' END AS capture_reason,
          CASE WHEN x.requested_url IS NOT NULL THEN cast(NULL AS VARCHAR)
               ELSE u.id END AS capture_decision_id
        FROM url_state_history h LEFT JOIN unambiguous u ON h.requested_url=u.original_url
          LEFT JOIN excluded x ON h.requested_url=x.requested_url"""
        index=next(i for i,step in enumerate(steps) if step['name']=='url_state_invariants_step')
        steps.insert(index,dict(name='url_state',sql=eligibility,materialize=True))
        steps[index+1]['sql']+=f""",(SELECT count(*) FROM recovery_requirements WHERE original_url IS NULL OR trim(original_url)=''
            OR target_requirement IS NULL OR target_requirement NOT IN ('historical_exact','requested_content','current_official_counterpart')
            OR (acceptance_policy IS DISTINCT FROM '{policy}')
            OR refresh_policy IS NULL OR refresh_policy NOT IN ('historical_only','refresh_live')) +
            (SELECT count(*) FROM (SELECT original_url FROM recovery_requirements GROUP BY original_url HAVING count(*)<>1)) AS invalid_recovery_requirements"""
    return steps


def url_state_diagnostics():
    """Return build-blocking counts; callers must check them before publication."""
    return [dict(name='url_state_invariants',sql="SELECT * FROM url_state_invariants_step")]
