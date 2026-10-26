import duckdb, sys
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
c=duckdb.connect()
c.sql(f"create view cap as select * from '{A}captures.parquet'")
c.sql(f"create view d as select body_key, record_role, document_kind, source_page_type from '{A}documents.parquet'")
GOOD="http_status between 200 and 299 and sha256 is not null and bytes>0 and coalesce(pointer_json,'') not like '%archive_members%' and resolution in ('saved','html','digest_verified')"
def build(name, mediacond):
    c.sql(f"""create or replace temp table rows_{name} as select context_url, family, sha256, body_key, media_type, retrieved_at, bytes, fidelity, resolution
      from cap where {GOOD} and ({mediacond})""")
    c.sql(f"""create or replace temp table urls_{name} as select context_url, count(distinct sha256) nb, count(*) nrows,
       list(distinct family) fams, regexp_extract(context_url,'^https?://([^/]+)',1) host
       from rows_{name} group by 1 having count(distinct sha256)>=2""")
    c.sql(f"""create or replace temp table bodies_{name} as select distinct r.context_url, r.sha256, r.body_key, r.media_type, r.bytes, r.fidelity,
       min(r.retrieved_at) over (partition by r.context_url, r.sha256) first_seen
       from rows_{name} r join urls_{name} u using(context_url)""")
    c.sql(f"""create or replace temp table bodies_{name} as select b.*, d.record_role, d.document_kind, d.source_page_type from
       (select distinct * from bodies_{name}) b left join (select body_key, any_value(record_role) record_role, any_value(document_kind) document_kind, any_value(source_page_type) source_page_type from d group by 1) d using(body_key)""")
    c.sql(f"copy urls_{name} to '{O}urls_{name}.parquet'")
    c.sql(f"copy bodies_{name} to '{O}bodies_{name}.parquet'")
    print(name, c.sql(f"select count(*), sum(nb) from urls_{name}").fetchall())
build('html', "media_type ilike 'text/html%'")
build('bin', "media_type ilike 'application/pdf%' or media_type ilike 'application/zip%' or media_type ilike '%msword%' or media_type ilike '%wordprocessingml%' or media_type ilike 'application/x-octet-stream%'")
