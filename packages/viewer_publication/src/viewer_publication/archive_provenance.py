"""Native selections and attachment for application-owned provenance records."""
from pathlib import Path

from congress_api.retention.provenance import field,json_input

ROOT=Path(__file__).parents[4]
RECOVERY_FIELDS={name:'Utf8' for name in ('id','body_sha256','original_url','recovered_filename',
    'recovered_url','kind','identity_note','decided_at','supersedes','target_requirement',
    'acceptance_status','acceptance_policy','qualification_sha256','evidence_sha256')}
RECOVERY_FIELDS['recovery_record_version']='Int32'
REVIEW_FIELDS={name:'Utf8' for name in ('id','target','verdict','note','reviewer','decided_at','supersedes')}


# ct-u9y4: every recovery row of a dead link belongs to that link's document, so one document can
# hold recovered files that are not the same document and shows only the first. This counts, per
# build, the documents holding several different recovered files by what their text says:
# same_text (equal fingerprints), text_differs, or text_unread (a file with no fingerprint, as every
# PDF today). 215 such documents were published in 619db5f9e08e. Since 2026-11-11 the reviewed roles
# decide them and archive_model.RECOVERED_FILE_INVARIANTS refuses one whose files are not all reviewed.
RECOVERY_FILE_AGREEMENT=dict(name='recovery_documents_with_several_files',sql="""SELECT agreement,count(*) AS documents FROM (
 SELECT r.component,CASE WHEN count(f.fingerprint)<count(*) THEN 'text_unread'
  WHEN min(f.fingerprint)<>max(f.fingerprint) THEN 'text_differs' ELSE 'same_text' END AS agreement
 FROM (SELECT DISTINCT component,body_sha FROM saved_recoveries) r LEFT JOIN fingerprints f ON f.body_sha=r.body_sha
 GROUP BY r.component HAVING count(*)>1) GROUP BY 1 ORDER BY 1""")


def provenance_inputs(work,*,recovery_files=(),review_files=()):
    """Register raw decisions without converting heterogeneous review values."""
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    inputs=[]
    for name,files,fields in [('recovery_decisions',recovery_files,RECOVERY_FIELDS),
                              ('review_provenance_rows',review_files,REVIEW_FIELDS)]:
        if files:
            inputs.append(dict(name=name,kind='json_lines',files=list(files),
                schema=dict(fields=[field(key,kind) for key,kind in fields.items()],metadata={})))
        else:inputs.append(json_input(work,name,[],**fields))
    steps=[dict(name='review_records',sql="SELECT *,json_get_json(__raw_line,'value') AS value_json FROM review_provenance_rows",materialize=True)]
    return inputs,steps


# Single owner of DM 7.5 recovery display order and container-ZIP exclusion, shared by
# model/sql/provenance-recovered-copy-links.sql and model/sql/saved-recoveries.sql (ct-jcnd).
NON_ARCHIVE_RECOVERY_FILTER_SQL=(
    "r.body_sha NOT IN (SELECT lower(encode(sha256,'hex')) FROM archive_bodies)\n"
    "  AND NOT EXISTS (SELECT 1 FROM good_archive_containers z"
    " WHERE z.receipt_key=r.receipt_key AND z.receipt_line=r.receipt_line)"
)
RECOVERY_ORDER_SQL=(
    "CASE r.kind WHEN 'recovered_document' THEN 0 WHEN 'full_recording_recovered' THEN 0\n"
    "  WHEN 'requested_content_in_official_hearing' THEN 2 ELSE 1 END,\n"
    "  cast(r.imported_at AS TIMESTAMP WITH TIME ZONE) DESC NULLS LAST,"
    "r.body_sha,r.receipt_key,r.receipt_line,r.capture_index"
)


def _render_recovery_sql(sql):
    return (sql
        .replace('{{NON_ARCHIVE_RECOVERY_FILTER}}',NON_ARCHIVE_RECOVERY_FILTER_SQL)
        .replace('{{RECOVERY_ORDER}}',RECOVERY_ORDER_SQL))


def _steps(names,root):
    return [dict(name=name.replace('-','_'),sql=_render_recovery_sql((Path(root)/'model/sql'/('provenance-'+name+'.sql')).read_text()),materialize=True)
            for name in names]


def saved_recoveries_step(*,root=ROOT):
    """Rank attached non-container recoveries in DM 7.5 display order (ct-jcnd)."""
    return dict(name='saved_recoveries',
        sql=_render_recovery_sql((Path(root)/'model/sql/saved-recoveries.sql').read_text()),
        materialize=True)


def current_steps(*,root=ROOT):
    """Select actual recovery rows and remaining decisions before source grouping.

    Inputs: captures, recovery_decisions, review_records(value_json), recovery_kinds.
    model_recovery_rows retains capture PKs and a unique recovery_id; current_recoveries
    supplies the shared filename/source producer. The caller must refuse fatal
    recovery_diagnostics before accepting a release; unmatched decisions are reports.
    """
    return _steps(['remaining-recovery-decisions','current-reviews','recovery-candidates','model-recovery-rows',
                   'current-recoveries','recovery-diagnostics'],root)


def attachment_steps(*,root=ROOT):
    """Attach through normalized keys, using an original's own source as fallback.

    Inputs: model_recovery_rows, source_files, source_labels, effective_filenames,
    copy_url_keys(source_id,url_key), recovery_original_keys(recovery_id,url_key).
    The caller must refuse recovery_attachment_diagnostics before release acceptance.
    """
    return _steps(['recovery-copy-components','recovery-original-components','recovery-attachments',
                   'recovery-attachment-diagnostics'],root)


def recovered_copy_steps(*,root=ROOT):
    """Name each original link a recovered copy makes another address of a published body.

    Inputs: model_recovery_rows, effective_filenames, source_files, body_evidence, body_fingerprints,
    recovered_file_roles.
    A link names only the published body its own row would show (its first recovered copy in the
    recovery order) or another of its copies with that copy's text (ct-u9y4) or a reviewed
    byte equivalence for that pair at that original URL (ct-m3h3).
    grouping_steps(recovered_copies=True) moves each such link into the body's one document.
    """
    return _steps(['recovered-copy-links'],root)


def body_review_steps(*,root=ROOT):
    """Provide body-node duplicate edges before the first component calculation."""
    return _steps(['body-review-key-conflicts','body-review-edges'],root)
