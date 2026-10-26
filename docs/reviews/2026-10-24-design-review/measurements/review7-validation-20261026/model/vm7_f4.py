"""F4: GovInfo ZIP shape. ZIP bodies at govinfo.gov /content/pkg/*.zip that are real (vm7 proxy), their members from the same line."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:25]: print('  ',r)
q("all govinfo ZIP rows (top-level): good?, format, recovery", """SELECT fmt, good, recovery, count(*), count(DISTINCT sha), count(DISTINCT ctx) FROM c WHERE ctx ILIKE '%govinfo.gov%' AND regexp_matches(lower(regexp_replace(ctx,'[?#].*$','')),'\\.zip$') AND mem IS NULL AND sha IS NOT NULL GROUP BY ALL ORDER BY 4 DESC""")
con.execute("""CREATE TEMP TABLE gz AS SELECT DISTINCT rk, rl, ctx, sha FROM real WHERE fmt='zip' AND mem IS NULL AND ctx ILIKE '%govinfo.gov%'""")
q("real GovInfo ZIP bodies / lines / URLs", "SELECT count(DISTINCT sha), count(*), count(DISTINCT ctx) FROM gz")
con.execute("""CREATE TEMP TABLE gm AS SELECT gz.sha zip, m.mem, m.sha msha, m.fmt mfmt, m.role mrole,
   CASE WHEN regexp_matches(m.mem,'(^|/)dip\\.xml$') THEN 'dip.xml' WHEN regexp_matches(m.mem,'(^|/)mods\\.xml$') THEN 'mods.xml' WHEN regexp_matches(m.mem,'(^|/)premis\\.xml$') THEN 'premis.xml'
        WHEN regexp_matches(m.mem,'/html/[^/]+\\.htm$') THEN 'html/*.htm' WHEN regexp_matches(m.mem,'/pdf/[^/]+\\.pdf$') THEN 'pdf/*.pdf' ELSE 'other:'||regexp_extract(m.mem,'([^/]*)$',1) END kind
   FROM gz JOIN c m ON m.rk=gz.rk AND m.rl=gz.rl AND m.mem IS NOT NULL""")
con.execute("""CREATE TEMP TABLE gshape AS SELECT zip, list_sort(list(DISTINCT kind || '#' || mem)) mems,
   list_sort(list(kind)) kinds FROM (SELECT DISTINCT zip, mem, kind FROM gm) GROUP BY 1""")
q("ZIPs by member-kind multiset (distinct member paths per ZIP body)", "SELECT kinds::VARCHAR, count(*) FROM gshape GROUP BY 1 ORDER BY 2 DESC LIMIT 12")
q("summary: ZIPs with members; exactly the five; lacking pdf; >1 html or >1 pdf", """SELECT count(*),
   count(*) FILTER (WHERE kinds=['dip.xml','html/*.htm','mods.xml','pdf/*.pdf','premis.xml']),
   count(*) FILTER (WHERE NOT list_contains(kinds,'pdf/*.pdf')),
   count(*) FILTER (WHERE len(list_filter(kinds, x -> x='html/*.htm'))>1 OR len(list_filter(kinds, x -> x='pdf/*.pdf'))>1),
   count(*) FILTER (WHERE NOT list_contains(kinds,'html/*.htm')) FROM gshape""")
q("real ZIPs with no captured members", "SELECT count(*) FROM (SELECT DISTINCT sha FROM gz) WHERE sha NOT IN (SELECT zip FROM gshape)")
q("member roles in this proxy (xml members are source_record only by basename here)", "SELECT kind, mfmt, mrole, count(*) FROM gm WHERE kind IN ('dip.xml','mods.xml','premis.xml','html/*.htm','pdf/*.pdf') GROUP BY ALL ORDER BY 4 DESC")
q("one-body-per-format among real members + the ZIP (xml manifests excluded as source records): ZIPs drawing edges; refused", """
  WITH r AS (SELECT zip, count(DISTINCT msha) FILTER (WHERE mfmt='html' AND mrole='document') nh, count(DISTINCT msha) FILTER (WHERE mfmt='pdf' AND mrole='document') np,
                    count(DISTINCT msha) FILTER (WHERE mfmt='xml' AND mrole='document') nx FROM gm GROUP BY 1)
  SELECT count(*) FILTER (WHERE nh<=1 AND np<=1 AND nx=0 AND nh+np>=1) draws, count(*) FILTER (WHERE nh>1 OR np>1) refused_same_format,
         count(*) FILTER (WHERE nx>0) has_real_xml, count(*) FILTER (WHERE nh=1 AND np=1 AND nx=0) html_and_pdf FROM r""")
q("same, if METS (dip.xml) were NOT a source record: dip.xml becomes a real xml document in every ZIP", """
  WITH r AS (SELECT zip, count(DISTINCT msha) FILTER (WHERE mfmt='html') nh, count(DISTINCT msha) FILTER (WHERE mfmt='pdf') np,
                    count(DISTINCT msha) FILTER (WHERE kind='dip.xml') nd FROM gm GROUP BY 1)
  SELECT count(*) FILTER (WHERE nh<=1 AND np<=1 AND nd<=1) still_one_per_format FROM r""")
q("sample ZIP URLs for a public check", "SELECT ctx, sha FROM gz ORDER BY sha LIMIT 2")
