"""Composite read-only research recipes over published Parquet tables."""
from .models import ExplorerError, MAX_BYTES, exact_scalar
from .release import encoded


def run_organization_dossier(reader, query):
    """Resolve an organization (including 1-hop organization_redirects) with witness and document breakdown."""
    if not query.org_id or not query.org_id.strip():
        raise ExplorerError('organization_dossier requires org_id (current or retired org_id)')
    tables = ['organizations', 'organization_ids', 'organization_redirects', 'witness_organizations', 'witnesses', 'meetings', 'documents']
    coverage = reader.research_coverage(tables)
    if 'organizations' not in reader.schemas:
        coverage['status'] = 'unavailable'
        return dict(
            release_id=reader.release_id,
            query_name='organization_dossier',
            rows=[],
            has_more=False,
            coverage=coverage,
        )
    raw_id = exact_scalar(query.org_id, reader.schemas['organizations']['org_id'], 'organizations.org_id')
    resolved_id, redirected_from = reader._resolve_org_id(raw_id)
    org_rows = reader.rows(
        f'SELECT {reader.entity_columns("organizations")} FROM organizations WHERE org_id=?',
        [resolved_id],
        limit=1,
    )['rows']
    if not org_rows:
        raise ExplorerError(f'Organization {resolved_id!r} is absent from this release')
    org = org_rows[0]

    parent_org = None
    if org.get('parent_org_id'):
        parents = reader.rows(
            'SELECT org_id,display_name,kind,taxonomy_parent,taxonomy_category FROM organizations WHERE org_id=?',
            [org['parent_org_id']],
            limit=1,
        )['rows']
        parent_org = parents[0] if parents else None
    child_orgs = reader.rows(
        'SELECT org_id,display_name,kind,taxonomy_parent,taxonomy_category,appearance_count '
        'FROM organizations WHERE parent_org_id=? ORDER BY appearance_count DESC NULLS LAST,org_id',
        [resolved_id],
        limit=50,
    )['rows']

    external_ids = []
    if 'organization_ids' in reader.schemas:
        external_ids = reader.rows(
            'SELECT scheme,value FROM organization_ids WHERE org_id=? ORDER BY scheme,value',
            [resolved_id],
            limit=100,
        )['rows']

    appearances = []
    appearances_truncated = False
    by_field = []
    by_committee = []
    distinct_witnesses = 0
    distinct_hearings = 0
    if 'witness_organizations' in reader.schemas:
        if 'witnesses' in reader.schemas:
            sup_filter = ' AND w.superseded_by IS NULL' if 'superseded_by' in reader.schemas['witnesses'] else ''
            has_meetings = 'meetings' in reader.schemas
            m_cols = reader.schemas.get('meetings', {})
            meeting_join = ' LEFT JOIN meetings m ON w.event_id=m.event_id' if has_meetings else ''
            selected_m = [
                f'm.{col} AS meeting_title' if col == 'title' else f'm.{col}'
                for col in ('title', 'meeting_date', 'congress', 'chamber') if col in m_cols
            ]
            meeting_cols = (',' + ','.join(selected_m)) if selected_m else ''
            order_date = 'm.meeting_date DESC NULLS LAST,' if 'meeting_date' in m_cols else ''
            app_sql = (
                f'SELECT wo.witness_key,wo.field,wo.raw_text,w.name,w.rank,w.credentials,w.position,'
                f'w.organization,w.on_behalf_of,w.occasion,w.event_id,w.package_id,w.witness_type{meeting_cols} '
                f'FROM witness_organizations wo JOIN witnesses w USING(witness_key){meeting_join} '
                f'WHERE wo.org_id=?{sup_filter} '
                f'ORDER BY {order_date}w.event_id NULLS LAST,wo.witness_key,wo.field'
            )
            app_res = reader.rows(app_sql, [resolved_id], limit=min(query.limit, 100))
            appearances = app_res['rows']
            appearances_truncated = bool(app_res['has_more'])
            counts_row = reader.db.execute(
                f'SELECT count(DISTINCT wo.witness_key),count(DISTINCT w.event_id) '
                f'FROM witness_organizations wo JOIN witnesses w USING(witness_key) WHERE wo.org_id=?{sup_filter}',
                [resolved_id],
            ).fetchall()[0]
            distinct_witnesses, distinct_hearings = int(counts_row[0] or 0), int(counts_row[1] or 0)
            by_field = reader.rows(
                f'SELECT wo.field,count(*) AS count FROM witness_organizations wo '
                f'JOIN witnesses w USING(witness_key) WHERE wo.org_id=?{sup_filter} '
                f'GROUP BY wo.field ORDER BY count DESC,wo.field',
                [resolved_id],
                limit=20,
            )['rows']
            if has_meetings:
                comm_join = ' LEFT JOIN committees c ON cm.system_code=c.system_code' if 'committees' in reader.schemas else ''
                comm_name = 'any_value(c.name)' if 'committees' in reader.schemas else 'NULL::VARCHAR'
                by_committee = reader.rows(
                    f'SELECT cm.system_code,{comm_name} AS name,count(DISTINCT wo.witness_key) AS witness_count '
                    f'FROM witness_organizations wo JOIN witnesses w USING(witness_key) '
                    f'JOIN meetings m ON w.event_id=m.event_id,unnest(m.committees) u(cm){comm_join} '
                    f'WHERE wo.org_id=?{sup_filter} GROUP BY cm.system_code ORDER BY witness_count DESC,cm.system_code',
                    [resolved_id],
                    limit=25,
                )['rows']
        else:
            app_res = reader.rows(
                'SELECT witness_key,field,raw_text FROM witness_organizations WHERE org_id=? ORDER BY witness_key,field',
                [resolved_id],
                limit=min(query.limit, 100),
            )
            appearances = app_res['rows']
            appearances_truncated = bool(app_res['has_more'])

    docs_res = dict(rows=[], has_more=False)
    if 'witness_organizations' in reader.schemas and 'documents' in reader.schemas:
        docs_res = reader.document_rows(reader.rows(
            f'SELECT {reader.document_summary} FROM "list" l JOIN detail d USING(list_row) '
            'WHERE NOT coalesce(l.hidden,false) AND EXISTS ('
            'SELECT 1 FROM witness_organizations wo WHERE wo.org_id=? AND list_contains(l.witness_keys,wo.witness_key)'
            ') ORDER BY l.document_date DESC NULLS LAST,l.list_row',
            [resolved_id],
            limit=min(query.limit, 25),
        ))

    dossier = dict(
        organization=org,
        parent_org=parent_org,
        child_orgs=child_orgs,
        organization_ids=external_ids,
        witness_breakdown=dict(
            distinct_witnesses=distinct_witnesses,
            distinct_hearings=distinct_hearings,
            by_field=by_field,
            by_committee=by_committee,
            appearances=appearances,
            appearances_truncated=appearances_truncated,
        ),
        documents=docs_res['rows'],
        documents_truncated=bool(docs_res['has_more']),
        reference=dict(release_id=reader.release_id, table='organizations', id=resolved_id),
    )
    if redirected_from:
        dossier['redirected_from'] = redirected_from

    response = dict(
        release_id=reader.release_id,
        query_name='organization_dossier',
        rows=[dossier],
        has_more=False,
        coverage=coverage,
    )
    if redirected_from:
        response['redirected_from'] = redirected_from

    # Enforce MAX_BYTES cleanly by trimming nested lists from largest to smallest.
    while len(encoded(response)) > MAX_BYTES and dossier['documents']:
        dossier['documents'].pop()
        dossier['documents_truncated'] = True
    while len(encoded(response)) > MAX_BYTES and dossier['witness_breakdown']['appearances']:
        dossier['witness_breakdown']['appearances'].pop()
        dossier['witness_breakdown']['appearances_truncated'] = True
    return response


def run_accountability_documents(reader, query):
    """Query quietly removed, retired/redirected, recovered-only, and multi-edition documents."""
    kind = query.churn_kind or 'all'
    committee = reader.resolve_committee(query.committee) if query.committee else None
    tables = ['list', 'detail', 'links', 'recoveries', 'retired_links']
    coverage = reader.research_coverage(tables, query.since, query.until)
    has_removed_on = 'removed_on' in reader.schemas.get('detail', {})
    has_retired = 'retired_links' in reader.schemas
    has_recoveries = 'recoveries' in reader.schemas
    coverage['removed_on_published'] = has_removed_on

    if 'list' not in reader.schemas or 'detail' not in reader.schemas:
        return dict(release_id=reader.release_id, query_name='accountability_documents', rows=[], has_more=False, coverage=coverage)

    unions = []
    args = []
    doc_filters = []
    doc_args = []
    if committee:
        doc_filters.append('list_contains(l.committee_keys,?)')
        doc_args.append(committee)
    if query.chamber:
        doc_filters.append('list_contains(l.chambers,?)')
        doc_args.append(query.chamber)
    if query.since:
        doc_filters.append('l.document_date>=CAST(? AS DATE)')
        doc_args.append(query.since)
    if query.until:
        doc_filters.append('l.document_date<CAST(? AS DATE)')
        doc_args.append(query.until)
    doc_where = (' AND ' + ' AND '.join(doc_filters)) if doc_filters else ''

    removed_cond = '(d.removed_on IS NOT NULL OR coalesce(l.hidden,false))' if has_removed_on else 'coalesce(l.hidden,false)'
    removed_expr = 'd.removed_on' if has_removed_on else 'NULL::DATE'
    removed_kind = "CASE WHEN d.removed_on IS NOT NULL THEN 'removed_on' ELSE 'review_removed' END" if has_removed_on else "'review_removed'"
    review_note_expr = 'd.review_note' if 'review_note' in reader.schemas['detail'] else 'NULL::VARCHAR'
    review_decided_expr = 'd.review_decided_at' if 'review_decided_at' in reader.schemas['detail'] else 'NULL::DATE'

    rec_select = (
        "(SELECT list(struct_pack(kind:=r.kind,identity_note:=r.identity_note,recovered_url:=r.recovered_url,imported_at:=cast(r.imported_at AS VARCHAR)) ORDER BY r.ordinal) "
        "FROM recoveries r WHERE r.list_row=l.list_row)"
        if has_recoveries else "[]::STRUCT(kind VARCHAR,identity_note VARCHAR,recovered_url VARCHAR,imported_at VARCHAR)[]"
    )

    if kind in ('all', 'removed'):
        unions.append(
            f"SELECT {removed_kind} AS churn_kind,l.list_row,lower(hex(d.link_key)) AS link_key,"
            f"NULL::VARCHAR AS successor_key,NULL::VARCHAR AS last_release_id,NULL::VARCHAR AS last_filename,"
            f"[]::VARCHAR[] AS address_versions,l.filename,l.title,l.congress,l.format,l.document_date,"
            f"l.first_captured,l.saved_kind,l.hidden,{removed_expr} AS removed_on,"
            f"{review_note_expr} AS review_note,{review_decided_expr} AS review_decided_at,"
            f"len(coalesce(l.version_keys,[]::VARCHAR[])) AS edition_count,"
            f"lower(hex(d.saved_body)) AS saved_body,d.saved_suffix,{rec_select} AS recoveries "
            f'FROM "list" l JOIN detail d USING(list_row) WHERE {removed_cond}{doc_where}'
        )
        args.extend(doc_args)

    if kind in ('all', 'recovered'):
        unions.append(
            f"SELECT 'recovered_only' AS churn_kind,l.list_row,lower(hex(d.link_key)) AS link_key,"
            f"NULL::VARCHAR AS successor_key,NULL::VARCHAR AS last_release_id,NULL::VARCHAR AS last_filename,"
            f"[]::VARCHAR[] AS address_versions,l.filename,l.title,l.congress,l.format,l.document_date,"
            f"l.first_captured,l.saved_kind,l.hidden,{removed_expr} AS removed_on,"
            f"{review_note_expr} AS review_note,{review_decided_expr} AS review_decided_at,"
            f"len(coalesce(l.version_keys,[]::VARCHAR[])) AS edition_count,"
            f"lower(hex(d.saved_body)) AS saved_body,d.saved_suffix,{rec_select} AS recoveries "
            f"FROM \"list\" l JOIN detail d USING(list_row) WHERE l.saved_kind='recovery' AND NOT coalesce(l.hidden,false){doc_where}"
        )
        args.extend(doc_args)

    if kind in ('all', 'multi_edition'):
        unions.append(
            f"SELECT 'multi_edition' AS churn_kind,l.list_row,lower(hex(d.link_key)) AS link_key,"
            f"NULL::VARCHAR AS successor_key,NULL::VARCHAR AS last_release_id,NULL::VARCHAR AS last_filename,"
            f"[]::VARCHAR[] AS address_versions,l.filename,l.title,l.congress,l.format,l.document_date,"
            f"l.first_captured,l.saved_kind,l.hidden,{removed_expr} AS removed_on,"
            f"{review_note_expr} AS review_note,{review_decided_expr} AS review_decided_at,"
            f"len(coalesce(l.version_keys,[]::VARCHAR[])) AS edition_count,"
            f"lower(hex(d.saved_body)) AS saved_body,d.saved_suffix,{rec_select} AS recoveries "
            f"FROM \"list\" l JOIN detail d USING(list_row) WHERE len(coalesce(l.version_keys,[]::VARCHAR[]))>0 AND NOT coalesce(l.hidden,false){doc_where}"
        )
        args.extend(doc_args)

    if kind in ('all', 'retired') and has_retired and not (committee or query.chamber or query.since or query.until):
        addr_expr = (
            "list_transform(coalesce(address_versions,[]::BLOB[]),lambda v:lower(hex(v)))"
            if 'address_versions' in reader.schemas['retired_links'] else "[]::VARCHAR[]"
        )
        unions.append(
            f"SELECT CASE WHEN successor_key IS NOT NULL THEN 'retired_redirected' ELSE 'retired_removed' END AS churn_kind,"
            f"NULL::BIGINT AS list_row,lower(hex(link_key)) AS link_key,"
            f"lower(hex(successor_key)) AS successor_key,last_release_id,last_filename,"
            f"{addr_expr} AS address_versions,last_filename AS filename,NULL::VARCHAR AS title,"
            f"NULL::SMALLINT AS congress,NULL::VARCHAR AS format,NULL::DATE AS document_date,"
            f"NULL::DATE AS first_captured,NULL::VARCHAR AS saved_kind,NULL::BOOLEAN AS hidden,"
            f"NULL::DATE AS removed_on,NULL::VARCHAR AS review_note,NULL::DATE AS review_decided_at,"
            f"len({addr_expr}) AS edition_count,NULL::VARCHAR AS saved_body,NULL::VARCHAR AS saved_suffix,"
            f"[]::STRUCT(kind VARCHAR,identity_note VARCHAR,recovered_url VARCHAR,imported_at VARCHAR)[] AS recoveries "
            f"FROM retired_links"
        )
    elif kind in ('all', 'retired') and has_retired and (committee or query.chamber or query.since or query.until):
        coverage['limits'].append('retired_links records do not carry committee, chamber, or document_date metadata; omit those filters to list retired links.')

    if not unions:
        return dict(release_id=reader.release_id, query_name='accountability_documents', churn_kind=kind, rows=[], has_more=False, coverage=coverage)

    sql = 'SELECT * FROM (' + ' UNION ALL '.join(unions) + ') t'
    result = reader.page(query, sql, args, order='t.churn_kind,t.list_row NULLS LAST,t.link_key')
    for row in result['rows']:
        body = row.pop('saved_body', None)
        suffix = row.pop('saved_suffix', None)
        if row.get('list_row') is not None and row.get('link_key'):
            row['reference'] = dict(release_id=reader.release_id, link_key=row['link_key'])
        row['saved_url'] = reader.file_url(body, suffix) if body else None
    result.update(
        query_name='accountability_documents',
        churn_kind=kind,
        coverage=coverage,
        resolved_filters=dict(committee=committee),
    )
    return result
