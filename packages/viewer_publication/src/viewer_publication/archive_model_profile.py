"""Pinned model definitions and native admission diagnostics for phase one."""
import json
from pathlib import Path
import re

from congress_api.lake._record_producer import (
    CURRENT_PAGE_READINGS_SQL,
    INLINE_CONGRESS_MEETINGS_SQL,
    expected_records_sql,
)
from congress_api.lake.readings import bundle_version,worker_limits
from congress_api.lake.versions import version_digest
from congress_api.models.archive_profile import build_capture_profile
from congress_api.retention.provenance import file_pin

ROOT=Path(__file__).parents[4]
PARSERS=('sniff','html','xml','json')
# Derived readings parsers a release may pin; html_metadata is required only to publish page metadata.
OPTIONAL_PARSERS=('html_metadata',)
MEETING_SOURCES=('congress_gov','house_xml')
APPEARANCE_SOURCES=('house_xml','congress_gov','senate_page','mods')
ENTITY_SOURCES={'meeting_records':MEETING_SOURCES,'appearance_records':APPEARANCE_SOURCES}
EXPLORER_SOURCES={'video_records':('youtube_cache','youtube_api'),'committee_records':('house_xml',)}
SELECTED_SOURCES={**ENTITY_SOURCES,**EXPLORER_SOURCES,'playlist_records':('hls',)}


def current_parser_versions(keys=()):
    """Current page-parser pins plus each named source-scoped table's, from one place.

    Job specs, the selective job and its model template all build their expected
    pins here, so a new source-scoped table cannot be added to one and not the others.
    """
    from congress_api.lake import readings,meeting_records,appearance_records,video_records,committee_records,playlist_records
    modules=dict(meeting_records=meeting_records,appearance_records=appearance_records,
                 video_records=video_records,committee_records=committee_records,playlist_records=playlist_records)
    result={p:readings.current_version(p) for p in (*PARSERS, *(p for p in OPTIONAL_PARSERS if p in keys))}
    result.update({name:modules[name].current_versions() for name in SELECTED_SOURCES if name in keys})
    return result


def readings_bundle_version(versions):
    """Use the same current worker policy as the combined producer."""
    page_versions={p:versions[p] for p in PARSERS if p in versions} if isinstance(versions,dict) else versions
    return bundle_version(page_versions,policy=worker_limits())


def validate_parser_versions(parser_versions,*,require_entities=False,require_explorer=False):
    """Validate page-parser and optional/required entity-parser version selections."""
    if (not isinstance(parser_versions,dict) or not set(PARSERS)<=parser_versions.keys()
            or not set(parser_versions)<=set(PARSERS)|set(OPTIONAL_PARSERS)|set(SELECTED_SOURCES)):
        raise ValueError('Model profile requires pinned parsers, catalog, engine, runtime, tables and writer')
    for name in (*PARSERS,*(p for p in OPTIONAL_PARSERS if p in parser_versions)):
        val=parser_versions.get(name)
        if not isinstance(val,str) or not val:
            raise ValueError('Model profile requires pinned parsers, catalog, engine, runtime, tables and writer')
    for entity_name,expected_sources in SELECTED_SOURCES.items():
        if entity_name not in parser_versions:
            if ((require_explorer and entity_name in EXPLORER_SOURCES)
                    or (require_entities and entity_name in ENTITY_SOURCES)):
                raise ValueError(f'Model profile with {entity_name} requires pinned {entity_name} parser_versions')
            continue
        val=parser_versions[entity_name]
        if (not isinstance(val,dict) or set(val)!=set(expected_sources)
                or any(not isinstance(v,str) or not v for v in val.values())):
            raise ValueError(f'Model profile requires exact source-scoped {entity_name} parser_versions')


def expand_parser_version_rows(parser_versions):
    """Flatten page and source-scoped entity parser versions into (parser, version) rows."""
    validate_parser_versions(parser_versions)
    rows=[dict(parser=name,version=parser_versions[name]) for name in sorted(PARSERS) + [p for p in OPTIONAL_PARSERS if p in parser_versions]]
    for entity_name,expected_sources in sorted(SELECTED_SOURCES.items()):
        if entity_name not in parser_versions:
            continue
        val=parser_versions[entity_name]
        for source in sorted(expected_sources):
            rows.append(dict(parser=f'{entity_name}.{source}',version=val[source]))
    return rows


def _copy(value):
    return json.loads(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False))


def _definition_hashes(root):
    root=Path(root)
    # Source definitions are small metadata, read once each; table data is never opened.
    files=list((root/'model/sql').glob('*.sql'))
    files+=list((root/'model/registries').glob('*.json'))
    files+=list((root/'model/lake').glob('*.json'))
    package=root/'packages/viewer_publication/src/viewer_publication'
    files += [package/name for name in ('archive_model.py','archive_model_profile.py','archive_format.py','archive_schema.py','archive_model_lifetimes.py','legislative_data.py',
        'archive_annotations.py','archive_provenance.py','archive_reviews.py','archive_url_state.py','archive_text_index.py',
        'lookup_aliases.py','meeting_detail_observations.py','historical_recording_matcher.py')]
    files += [root/'packages/congress_api/src/congress_api/models/archive_profile.py',root/'uv.lock']
    files += [root/'packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv']
    files += [root/'packages/congress_api/src/congress_api'/name for name in ['lake/readings.py','lake/reading_versions.py',
        'lake/compatible_versions.py','lake/versions.py','lake/_record_producer.py','lake/meeting_records.py','lake/appearance_records.py',
        'retention/parser_worker.py','retention/process_resources.py']]
    return {path.relative_to(root).as_posix():file_pin(path)['sha256'] for path in sorted(set(files))}


def capture_profile_record(*,engine_revision,root=ROOT):
    """Use the maintained public capture profile, without a second URL definition."""
    root=Path(root)
    return build_capture_profile(engine_revision=engine_revision,
        url_normalized_sql=(root/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(root/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((root/'model/registries/url-rules.json').read_text()))


def runtime_pins(engine):
    """Pin the native build that defines results, never its physical limits.

    C3 (ss-iwqu): exports are byte-identical across threads, batch sizes and a
    forced spill (test_model_determinism), so limits would only split one model
    into a Mac and a CI identity. The input record keeps them as `engine_limits`.
    """
    return dict(platform=engine.platform,build_features=list(engine.build_features),
                binary_sha256=engine.binary_sha256)


def profile_record(*,parser_versions,catalog_version,engine_revision,runtime_pins,
                   lake_versions,writer_settings,snapshots,file_hashes=None,root=ROOT,
                   relationship_metadata_update=None,recovery_policy=None,historical_recording_matcher=None):
    """Pin semantic definitions; retain exact physical selectors outside their digest."""
    require_entities=(isinstance(lake_versions,dict)
        and ('meeting_records' in lake_versions or 'appearance_records' in lake_versions))
    validate_parser_versions(parser_versions,require_entities=require_entities)
    if (not isinstance(catalog_version,str) or not catalog_version
            or not isinstance(engine_revision,str) or re.fullmatch('[0-9a-f]{40}',engine_revision) is None
            or any(not isinstance(v,dict) or not v for v in (runtime_pins,lake_versions,writer_settings,snapshots))):
        raise ValueError('Model profile requires pinned parsers, catalog, engine, runtime, tables and writer')
    hashes=_definition_hashes(root) if file_hashes is None else file_hashes
    if (not isinstance(hashes,dict) or not hashes or any(not isinstance(name,str) or not name
            or not isinstance(value,str) or re.fullmatch('[0-9a-f]{64}',value) is None for name,value in hashes.items())):
        raise ValueError('Model definitions require named SHA-256 values')
    profile=_copy(dict(parser_versions=parser_versions,catalog_version=catalog_version,
        engine_revision=engine_revision,runtime_pins=runtime_pins,lake_versions=lake_versions,
        writer_settings=writer_settings,file_hashes=hashes))
    if recovery_policy is not None:profile['recovery_policy']=_copy(recovery_policy)
    if historical_recording_matcher is not None:
        profile['historical_recording_matcher']={key:historical_recording_matcher[key] for key in ('sha256','size')}
    if relationship_metadata_update is not None:
        update=relationship_metadata_update
        digests={'base_release_id','registry_sha256','schema_sha256'}
        if (not isinstance(update,dict) or set(update)!=digests|{'relationships_version'}
                or type(update['relationships_version']) is not int or update['relationships_version']!=1
                or any(not isinstance(update[key],str) or re.fullmatch('[0-9a-f]{64}',update[key]) is None for key in digests)):
            raise ValueError('Relationship metadata update requires a base release, registry, schema and supported version')
        # Keep the original model pins: this versions metadata without claiming
        # that newer model code produced the unchanged Parquet data.
        profile['relationship_metadata_update']=_copy(update)
    return dict(version=1,profile=profile,
        profile_sha256=version_digest(packages={},files={},values=profile),snapshots=_copy(snapshots))


def completeness_steps(*,root=ROOT):
    """Retain expected populations once before their independent coverage checks."""
    return [dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=True)
        for name in ['profile-bodies','profile-filename-pairs','profile-capture-duplicates','profile-reading-duplicates',
            'profile-filename-duplicates']]


def _entity_version_cte(table_prefix,expected_sources,override_version):
    if override_version is not None:
        if (not isinstance(override_version,dict) or set(override_version)!=set(expected_sources)
                or any(not isinstance(v,str) or not v for v in override_version.values())):
            raise ValueError(f'Invalid {table_prefix} version override')
        mapping=dict(override_version)
        values_sql=','.join(
            f"('{s}','{mapping[s].replace(chr(39),chr(39)*2)}')"
            for s in sorted(expected_sources)
        )
        return f"""SELECT o.source,
            CASE
                WHEN pv_scoped.parser IS NULL AND pv_table.parser IS NULL THEN o.version
                WHEN coalesce(pv_scoped.version,pv_table.version)=o.version THEN o.version
                ELSE NULL
            END AS version
            FROM (SELECT column1 AS source,column2 AS version FROM (VALUES {values_sql})) o
            LEFT JOIN parser_versions pv_scoped ON pv_scoped.parser='{table_prefix}.'||o.source
            LEFT JOIN parser_versions pv_table ON pv_table.parser='{table_prefix}'"""
    sources_sql=','.join(f"('{s}')" for s in sorted(expected_sources))
    return f"""SELECT s.source,
        coalesce(pv_scoped.version,pv_table.version) AS version
        FROM (SELECT column1 AS source FROM (VALUES {sources_sql})) s
        LEFT JOIN parser_versions pv_scoped ON pv_scoped.parser='{table_prefix}.'||s.source
        LEFT JOIN parser_versions pv_table ON pv_table.parser='{table_prefix}'"""


def completeness_checks(*,catalog_version,include_entities=False,
                        meeting_records_version=None,appearance_records_version=None,root=ROOT):
    """Return native counts; every positive value refuses accepted model output.

    Run completeness_steps first. Inputs are captures, readings, filename_readings, parser_versions,
    accepted_versions, the selected_readings step, source_files, sniff_facts, body_admissions and
    active_unreadable.
    The latter is already reduced by supersession and withdrawal, with nullable body_sha256
    and record_sha string identities. Existing error/size_limit rows settle
    work; missing storage creates neither a row nor an unreadable decision.
    """
    if not isinstance(catalog_version,str) or not catalog_version:
        raise ValueError('Completeness requires a pinned filename version')
    sql=(Path(root)/'model/sql/profile-completeness.sql').read_text().replace('{{CATALOG_VERSION}}',"'"+catalog_version.replace("'","''")+"'")
    checks=[dict(name='profile_completeness',sql=sql)]
    if include_entities:
        mr_versions_sql=_entity_version_cte('meeting_records',MEETING_SOURCES,meeting_records_version)
        ar_versions_sql=_entity_version_cte('appearance_records',APPEARANCE_SOURCES,appearance_records_version)
        entity_sql=f"""WITH selected_mr_versions AS (
            {mr_versions_sql}
        ), selected_ar_versions AS (
            {ar_versions_sql}
        ), mr_dup AS (
            SELECT count(*) AS cnt FROM (
                SELECT record_sha_hex,source,parser_version FROM meeting_records_input
                GROUP BY record_sha_hex,source,parser_version HAVING count(*)>1
            )
        ), ar_dup AS (
            SELECT count(*) AS cnt FROM (
                SELECT record_sha_hex,source,parser_version FROM appearance_records_input
                GROUP BY record_sha_hex,source,parser_version HAVING count(*)>1
            )
        ), mr_invalid AS (
            SELECT (
                SELECT count(*) FROM meeting_records_input
                WHERE record_sha_hex IS NULL OR trim(record_sha_hex)=''
                   OR parser_version IS NULL OR trim(parser_version)=''
                   OR status IS NULL OR status NOT IN ('completed','error','size_limit')
                   OR source IS NULL OR source NOT IN ('congress_gov','house_xml')
            ) + (
                SELECT count(*) FROM selected_mr_versions WHERE version IS NULL OR trim(version)=''
            ) AS cnt
        ), ar_invalid AS (
            SELECT (
                SELECT count(*) FROM appearance_records_input
                WHERE record_sha_hex IS NULL OR trim(record_sha_hex)=''
                   OR parser_version IS NULL OR trim(parser_version)=''
                   OR status IS NULL OR status NOT IN ('completed','error','size_limit')
                   OR source IS NULL OR source NOT IN ('house_xml','congress_gov','senate_page','mods')
            ) + (
                SELECT count(*) FROM selected_ar_versions WHERE version IS NULL OR trim(version)=''
            ) AS cnt
        ), current_page_readings AS (
            {CURRENT_PAGE_READINGS_SQL}
        ), expected_mr AS (
            {expected_records_sql('meeting_records')}
        ), expected_ar AS (
            {expected_records_sql('appearance_records')}
        ), inline_cg_expected AS (
            SELECT DISTINCT CASE
                WHEN source_url<>'' THEN source_url
                ELSE receipt_key||':'||cast(receipt_line AS VARCHAR)
            END AS inline_key
            FROM ({INLINE_CONGRESS_MEETINGS_SQL})
        ), mr_settled AS (
            SELECT DISTINCT m.record_sha_hex,m.source
            FROM meeting_records_input m
            JOIN selected_mr_versions v ON m.source=v.source AND m.parser_version=v.version
            WHERE m.status IN ('completed','error','size_limit')
        ), mr_unreadable AS (
            SELECT DISTINCT lower(coalesce(u.record_sha,u.body_sha256)) AS record_sha_hex,v.source
            FROM active_unreadable u
            JOIN selected_mr_versions v ON u.parser_version=v.version
            WHERE u.parser IN ('meeting_records','meetings','meeting_records.'||v.source)
              AND coalesce(u.record_sha,u.body_sha256) IS NOT NULL
        ), mr_inline_unsettled AS (
            SELECT greatest(
                (SELECT count(*) FROM inline_cg_expected) - (
                    SELECT count(DISTINCT record_sha_hex) FROM (
                        SELECT record_sha_hex FROM mr_settled WHERE source='congress_gov'
                        UNION
                        SELECT record_sha_hex FROM mr_unreadable WHERE source='congress_gov'
                    ) s WHERE NOT EXISTS (
                        SELECT 1 FROM expected_mr e WHERE e.source='congress_gov' AND e.record_sha_hex=s.record_sha_hex
                    )
                ),
                0
            ) AS cnt
        ), mr_unsettled AS (
            SELECT (SELECT count(*) FROM (
                SELECT e.record_sha_hex,e.source
                FROM expected_mr e
                WHERE NOT EXISTS (
                    SELECT 1 FROM mr_settled s WHERE s.record_sha_hex=e.record_sha_hex AND s.source=e.source
                ) AND NOT EXISTS (
                    SELECT 1 FROM mr_unreadable u WHERE u.record_sha_hex=e.record_sha_hex AND u.source=e.source
                )
                UNION
                SELECT m.record_sha_hex,m.source
                FROM meeting_records_input m
                JOIN selected_mr_versions v ON m.source=v.source AND m.parser_version=v.version
                WHERE m.status NOT IN ('completed','error','size_limit')
                  AND NOT EXISTS (
                      SELECT 1 FROM mr_unreadable u WHERE u.record_sha_hex=m.record_sha_hex AND u.source=m.source
                  )
            )) + (SELECT cnt FROM mr_inline_unsettled) AS cnt
        ), ar_settled AS (
            SELECT DISTINCT a.record_sha_hex,a.source
            FROM appearance_records_input a
            JOIN selected_ar_versions v ON a.source=v.source AND a.parser_version=v.version
            WHERE a.status IN ('completed','error','size_limit')
        ), ar_unreadable AS (
            SELECT DISTINCT lower(coalesce(u.record_sha,u.body_sha256)) AS record_sha_hex,v.source
            FROM active_unreadable u
            JOIN selected_ar_versions v ON u.parser_version=v.version
            WHERE u.parser IN ('appearance_records','appearances','appearance_records.'||v.source)
              AND coalesce(u.record_sha,u.body_sha256) IS NOT NULL
        ), ar_inline_unsettled AS (
            SELECT greatest(
                (SELECT count(*) FROM inline_cg_expected) - (
                    SELECT count(DISTINCT record_sha_hex) FROM (
                        SELECT record_sha_hex FROM ar_settled WHERE source='congress_gov'
                        UNION
                        SELECT record_sha_hex FROM ar_unreadable WHERE source='congress_gov'
                    ) s WHERE NOT EXISTS (
                        SELECT 1 FROM expected_ar e WHERE e.source='congress_gov' AND e.record_sha_hex=s.record_sha_hex
                    )
                ),
                0
            ) AS cnt
        ), ar_unsettled AS (
            SELECT (SELECT count(*) FROM (
                SELECT e.record_sha_hex,e.source
                FROM expected_ar e
                WHERE NOT EXISTS (
                    SELECT 1 FROM ar_settled s WHERE s.record_sha_hex=e.record_sha_hex AND s.source=e.source
                ) AND NOT EXISTS (
                    SELECT 1 FROM ar_unreadable u WHERE u.record_sha_hex=e.record_sha_hex AND u.source=e.source
                )
                UNION
                SELECT a.record_sha_hex,a.source
                FROM appearance_records_input a
                JOIN selected_ar_versions v ON a.source=v.source AND a.parser_version=v.version
                WHERE a.status NOT IN ('completed','error','size_limit')
                  AND NOT EXISTS (
                      SELECT 1 FROM ar_unreadable u WHERE u.record_sha_hex=a.record_sha_hex AND u.source=a.source
                  )
            )) + (SELECT cnt FROM ar_inline_unsettled) AS cnt
        )
        SELECT
            (SELECT cnt FROM mr_dup) AS duplicate_meeting_records,
            (SELECT cnt FROM ar_dup) AS duplicate_appearance_records,
            (SELECT cnt FROM mr_invalid) AS invalid_meeting_records,
            (SELECT cnt FROM ar_invalid) AS invalid_appearance_records,
            (SELECT cnt FROM mr_unsettled) AS unsettled_meeting_records,
            (SELECT cnt FROM ar_unsettled) AS unsettled_appearance_records"""
        checks.append(dict(name='entity_profile_completeness',sql=entity_sql))
    return checks
