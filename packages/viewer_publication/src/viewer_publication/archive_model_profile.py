"""Pinned model definitions and native admission diagnostics for phase one."""
import json
from pathlib import Path
import re

from congress_api.lake.readings import bundle_version,worker_limits
from congress_api.lake.versions import version_digest
from congress_api.models.archive_profile import build_capture_profile
from congress_api.retention.provenance import file_pin

ROOT=Path(__file__).parents[4]
PARSERS=('sniff','html','xml','json')


def readings_bundle_version(versions):
    """Use the same current worker policy as the combined producer."""
    return bundle_version(versions,policy=worker_limits())


def _copy(value):
    return json.loads(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False))


def _definition_hashes(root):
    root=Path(root)
    # Source definitions are small metadata, read once each; table data is never opened.
    files=list((root/'model/sql').glob('*.sql'))
    files+=list((root/'model/registries').glob('*.json'))
    files+=list((root/'model/lake').glob('*.json'))
    package=root/'packages/viewer_publication/src/viewer_publication'
    files += [package/name for name in ('archive_model.py','archive_model_profile.py','archive_format.py','archive_model_lifetimes.py',
        'archive_annotations.py','archive_provenance.py','archive_reviews.py','archive_url_state.py')]
    files += [root/'packages/congress_api/src/congress_api/models/archive_profile.py',root/'uv.lock']
    files += [root/'packages/congress_api/src/congress_api'/name for name in ['lake/readings.py','retention/parser_worker.py','retention/process_resources.py']]
    return {path.relative_to(root).as_posix():file_pin(path)['sha256'] for path in sorted(set(files))}


def capture_profile_record(*,engine_revision,root=ROOT):
    """Use the maintained public capture profile, without a second URL definition."""
    root=Path(root)
    return build_capture_profile(engine_revision=engine_revision,
        url_normalized_sql=(root/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(root/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((root/'model/registries/url-rules.json').read_text()))


def profile_record(*,parser_versions,catalog_version,engine_revision,runtime_pins,
                   lake_versions,writer_settings,snapshots,file_hashes=None,root=ROOT):
    """Pin semantic definitions; retain exact physical selectors outside their digest."""
    if (not isinstance(parser_versions,dict) or not set(PARSERS)<=parser_versions.keys()
            or any(not isinstance(v,str) or not v for v in parser_versions.values())
            or not isinstance(catalog_version,str) or not catalog_version
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
    return dict(version=1,profile=profile,
        profile_sha256=version_digest(packages={},files={},values=profile),snapshots=_copy(snapshots))


def completeness_steps(*,root=ROOT):
    """Retain expected populations once before their independent coverage checks."""
    return [dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=name!='profile-bodies')
        for name in ['profile-bodies','profile-filename-pairs']]


def completeness_checks(*,catalog_version,readings_version,root=ROOT):
    """Return native counts; every positive value refuses accepted model output.

    Run completeness_steps first. Inputs are captures, readings, filename_readings, parser_versions,
    source_files, sniff_facts, body_admissions and active_unreadable.
    The latter is already reduced by supersession, with nullable body_sha256
    and record_sha string identities. Existing error/size_limit rows settle
    work; missing storage creates neither a row nor an unreadable decision.
    """
    if any(not isinstance(value,str) or not value for value in (catalog_version,readings_version)):
        raise ValueError('Completeness requires pinned filename and readings versions')
    sql=(Path(root)/'model/sql/profile-completeness.sql').read_text()
    for token,value in [('{{CATALOG_VERSION}}',catalog_version),('{{READINGS_VERSION}}',readings_version)]:
        sql=sql.replace(token,"'"+value.replace("'","''")+"'")
    return [dict(name='profile_completeness',sql=sql)]
