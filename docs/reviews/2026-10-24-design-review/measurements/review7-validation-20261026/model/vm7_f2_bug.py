"""F2: the reviewer's file-shape exclusion (prof7_grouping2.py) used DuckDB SIMILAR TO with '%', which is a full regex match where '%' is
literal, so it never matched; and every HTML body at his [html,pdf] endpoints sits at a file-shaped locator."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__))
print(duckdb.sql(r"SELECT 'x/a.pdf' SIMILAR TO '%\.(pdf|zip|doc|docx|xml)' AS reviewer_pattern, regexp_matches('x/a.pdf', '\.(pdf|zip|doc|docx|xml)$') AS intended").fetchall())
print(duckdb.sql(f"""WITH e AS (SELECT ukey, any_value(fmts) fmts, bool_and(regexp_matches(lower(coalesce(original_path, regexp_replace(context_url,'[?#].*$',''))), '\\.(pdf|zip|doc|docx|xml)$')
     OR context_url LIKE '%/download/%' OR context_url LIKE '%download=1%' OR context_url LIKE '%file_id=%') FILTER (WHERE fmt='html') all_html_file_shaped FROM '{D}/vm7_prof_htmlpdf.parquet' GROUP BY 1)
  SELECT fmts, all_html_file_shaped, count(*) FROM e GROUP BY ALL ORDER BY 3 DESC""").fetchall())
