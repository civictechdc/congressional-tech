"""Measure an originally prepared document-model slice through its native owner.

    documents_slice.py --prepared-request REQUEST --request-sha256 SHA256
        --engine-config RUNTIME --live LIVE_RELEASE --packages PACKAGES --work DIR

The maintained model command resumes the original admitted request. This tool
does not rebuild inputs, choose new producer versions or publish a release.
The separate select_slice helper prepares the original frozen v21 measurement
population for authoring a model job through the ordinary adoption path.
Keys: every GovInfo package whose direct HTML and ZIP member HTML share no body
(PROBES/nosh_pkgs.csv), 300 that share one, CHRG-119hhrg64404, the six HTTP 206
ZIP packages, 100 direct-only packages, every Files.Serve URL, and the URLs of
live rows with a blank filename, a link-word title or a NULL source URL.
The slice is every capture row naming a key, every row of a page body linking
one, and then every capture row and reading of each body so taken, so a
placeholder or same-body edge seen on full captures stays seen.

It cannot see: recovery attachment, review merges and copy verification (no
provenance inputs), links from pages outside the slice, corpus scale or memory.
The select_slice helper can replace v21 HTML rows with supplied readings for
the bodies they cover. That changes the inputs and requires its own adopted job.
"""
import argparse
import json
from pathlib import Path

import duckdb

PKG = r"(?i)/content/pkg/([A-Z]+-[0-9A-Za-z]+)"
EXTRA_PACKAGES = ['CHRG-119hhrg64404', 'CHRG-118hhrg56269', 'CHRG-118shrg51949', 'CHRG-117shrg45446',
                  'CHRG-118hhrg56213', 'CHRG-118shrg53230', 'CHRG-118shrg62354']
LINK_WORDS = ('zip', 'pdf', 'xml', 'html', 'htm', 'txt', 'text', 'json', 'here', 'click here', 'email',
              'download', 'download pdf', 'view pdf', 'link', 'file', 'document', 'view', 'read more', 'more')


def select_slice(db, inputs, live, probes, work, readings=None):
    db.execute(f"CREATE VIEW c AS SELECT * FROM read_parquet('{inputs}/captures.parquet')")
    db.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{inputs}/readings.parquet')")
    db.execute(f"""CREATE TABLE cpkg AS SELECT sha256, member_path,
        coalesce(regexp_extract(coalesce(url, requested_url, context_url), '{PKG}', 1), '') AS pkg FROM c""")
    db.execute(f"""CREATE TABLE direct AS SELECT DISTINCT pkg FROM cpkg WHERE member_path IS NULL AND pkg LIKE 'CHRG-%'""")
    db.execute(f"""CREATE TABLE member AS SELECT DISTINCT pkg FROM cpkg WHERE member_path IS NOT NULL AND pkg LIKE 'CHRG-%'""")
    db.execute(f"""CREATE TABLE pkgs AS
        SELECT pkg FROM read_csv('{probes}/nosh_pkgs.csv', header=true)
        UNION SELECT pkg FROM (SELECT pkg FROM read_parquet('{probes}/pkg_html_cls.parquet') WHERE same_body
            ORDER BY hash(pkg || 'slice') LIMIT 300)
        UNION SELECT unnest({EXTRA_PACKAGES!r})
        UNION SELECT pkg FROM (SELECT pkg FROM (SELECT pkg FROM direct EXCEPT SELECT pkg FROM member) ORDER BY hash(pkg || 'slice') LIMIT 100)""")
    db.execute(f"CREATE VIEW l AS SELECT row_number() OVER () - 1 AS list_row, * FROM read_parquet('{live}/list.parquet')")
    db.execute(f"CREATE VIEW s AS SELECT * FROM read_parquet('{live}/sources.parquet')")
    words = ','.join(f"'{w}'" for w in LINK_WORDS)
    db.execute(f"""CREATE TABLE urls AS
        SELECT DISTINCT s.url FROM s JOIN l USING (list_row)
        WHERE s.url IS NOT NULL AND (l.filename = '' OR lower(trim(l.title)) IN ({words})
            OR list_row IN (SELECT list_row FROM s WHERE url IS NULL))
        UNION SELECT DISTINCT url FROM c WHERE url LIKE '%Files.Serve%'""")
    db.execute("""CREATE TABLE seed AS SELECT DISTINCT sha256 FROM c
        WHERE sha256 IS NOT NULL AND (regexp_extract(coalesce(url, requested_url, context_url, ''), '""" + PKG + """', 1) IN (SELECT pkg FROM pkgs)
            OR url IN (SELECT url FROM urls) OR requested_url IN (SELECT url FROM urls) OR context_url IN (SELECT url FROM urls))""")
    db.execute(f"""CREATE TABLE pages AS SELECT DISTINCT body_sha AS sha256 FROM (
            SELECT body_sha, unnest(links) AS link FROM r WHERE parser IN ('html', 'xml') AND status = 'completed')
        WHERE regexp_extract(link.href, '{PKG}', 1) IN (SELECT pkg FROM pkgs) OR link.href IN (SELECT url FROM urls)""")
    db.execute("CREATE TABLE bodies AS SELECT sha256 FROM seed UNION SELECT sha256 FROM pages")
    captures, slice_readings = work / 'captures.parquet', work / 'readings.parquet'
    db.execute(f"""COPY (SELECT * FROM c WHERE sha256 IN (SELECT sha256 FROM bodies)
        OR (sha256 IS NULL AND (url IN (SELECT url FROM urls)
            OR regexp_extract(coalesce(url, requested_url, context_url, ''), '{PKG}', 1) IN (SELECT pkg FROM pkgs))))
        TO '{captures}' (FORMAT PARQUET)""")
    if readings is None:
        db.execute(f"COPY (SELECT * FROM r WHERE body_sha IN (SELECT sha256 FROM bodies)) TO '{slice_readings}' (FORMAT PARQUET)")
    else:
        db.execute(f"""COPY (SELECT * FROM r WHERE body_sha IN (SELECT sha256 FROM bodies)
                AND NOT (parser = 'html' AND body_sha IN (SELECT body_sha FROM read_parquet('{readings}')))
            UNION ALL BY NAME SELECT * FROM read_parquet('{readings}') WHERE body_sha IN (SELECT sha256 FROM bodies))
            TO '{slice_readings}' (FORMAT PARQUET)""")
    counts = dict(packages=db.sql('SELECT count(*) FROM pkgs').fetchone()[0], urls=db.sql('SELECT count(*) FROM urls').fetchone()[0],
                  bodies=db.sql('SELECT count(*) FROM bodies').fetchone()[0],
                  capture_rows=db.sql(f"SELECT count(*) FROM read_parquet('{captures}')").fetchone()[0],
                  reading_rows=db.sql(f"SELECT count(*) FROM read_parquet('{slice_readings}')").fetchone()[0])
    db.execute(f"COPY pkgs TO '{work / 'packages.parquet'}' (FORMAT PARQUET)")
    return captures, slice_readings, counts


def measure(db, release, live, packages):
    db.from_parquet(str(release['list.parquet'])).create_view('nl_rows')
    db.from_parquet(str(release['detail.parquet'])).create_view('nd_rows')
    db.from_parquet(str(release['sources.parquet'])).create_view('ns')
    db.from_parquet(str(packages)).create_view('selected_packages')
    db.from_parquet(str(Path(live)/'meetings.parquet')).create_view('live_meetings')
    db.execute('CREATE OR REPLACE VIEW nl AS SELECT row_number() OVER () - 1 AS list_row, * FROM nl_rows')
    db.execute('CREATE OR REPLACE VIEW nd AS SELECT row_number() OVER () - 1 AS list_row, * FROM nd_rows')
    db.execute("""CREATE OR REPLACE TABLE pairs AS SELECT DISTINCT event_id, t.package_id
        FROM live_meetings, unnest(transcripts) u(t) WHERE t.package_id IS NOT NULL""")
    words = ','.join(f"'{w}'" for w in LINK_WORDS)
    q = lambda sql: db.sql(sql).fetchall()
    per_pkg = q("""SELECT n, count(*) FROM (SELECT package_id, count(*) n FROM nd
        WHERE package_id IN (SELECT pkg FROM selected_packages) GROUP BY 1) GROUP BY 1 ORDER BY 1""")
    dup = q("""SELECT count(DISTINCT event_id), count(DISTINCT package_id), count(*) FROM pairs p
        JOIN (SELECT package_id, count(*) n FROM nd WHERE package_id IS NOT NULL GROUP BY 1) d USING (package_id) WHERE d.n > 1""")
    return dict(
        list_rows=q('SELECT count(*) FROM nl')[0][0],
        rows_per_package=per_pkg,
        transcript_duplicates=dict(zip(['events', 'packages', 'pairs'], dup[0])),
        format_by_package_rows=q("""SELECT format, count(*) FROM nd WHERE package_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"""),
        link_word_titles=q(f"""SELECT lower(trim(title)) t, format, count(*) FROM nl WHERE lower(trim(title)) IN ({words})
            GROUP BY ALL ORDER BY 3 DESC"""),
        blank_filename=q("""SELECT format, title IS NULL AS no_title, count(*) FROM nl WHERE filename = '' GROUP BY ALL ORDER BY 3 DESC"""),
        null_sources_url=q('SELECT count(*) FROM ns WHERE url IS NULL')[0][0],
        version_key_rows=q('SELECT count(*) FROM nl WHERE len(version_keys) > 0')[0][0])


def main(argv=None):
    from viewer_publication.archive_model_job import resume_prepared
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('prepared-request', 'engine-config', 'live', 'packages', 'work'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--request-sha256', required=True)
    args = parser.parse_args(argv)
    work = args.work.resolve()
    packages = args.packages.resolve(strict=True)
    work.mkdir(parents=True, exist_ok=False)
    request = dict(path=str(args.prepared_request.resolve(strict=True)), sha256=args.request_sha256)
    built = resume_prepared(request, engine_config=args.engine_config)
    with duckdb.connect(config=dict(memory_limit='2GB', threads=4)) as db:
        result = dict(release_id=built['release_id'], prepared_request=request,
                      **measure(db, built['files'], args.live, packages))
    (work / 'measure.json').write_text(json.dumps(result, indent=1, default=str) + '\n')
    print(json.dumps(result, indent=1, default=str))


if __name__ == '__main__':
    main()
