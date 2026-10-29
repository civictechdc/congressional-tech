"""Native selections and attachment for application-owned provenance records."""
from pathlib import Path

from congress_api.retention.provenance import field,json_input

ROOT=Path(__file__).parents[4]
RECOVERY_FIELDS={name:'Utf8' for name in ('id','body_sha256','original_url','recovered_filename',
    'recovered_url','kind','identity_note','decided_at','supersedes')}
REVIEW_FIELDS={name:'Utf8' for name in ('id','target','verdict','note','reviewer','decided_at','supersedes')}


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


def _steps(names,root):
    lazy={'recovery-diagnostics','recovery-attachment-diagnostics','body-review-key-conflicts'}
    return [dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/('provenance-'+name+'.sql')).read_text(),materialize=name not in lazy)
            for name in names]


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


def body_review_steps(*,root=ROOT):
    """Provide body-node duplicate edges before the first component calculation."""
    return _steps(['body-review-key-conflicts','body-review-edges'],root)
