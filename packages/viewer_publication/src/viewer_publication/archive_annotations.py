"""Assemble per-source display evidence through the model's native SQL job."""
from pathlib import Path

from viewer_publication.archive_format import EMPTY_FACTS,EMPTY_STRINGS

ROOT=Path(__file__).parents[4]

# A date token that starts at an act's title year ("Bear Protection Act of 2019_6-23-20", "the Act of
# June 22, 1948") dates the act, not the document. Read over filename_readings f, own or linked name.
FILENAME_DATE=("CASE WHEN f.date_token IS NOT NULL AND strpos(regexp_replace(lower(f.filename),'[\\s_]+',' ','g'),"
    "'act of '||regexp_replace(lower(f.date_token),'[\\s_]+',' ','g'))>0 THEN NULL ELSE f.filename_date END")


def annotation_steps(catalog_version,*,root=ROOT):
    """Read the pinned filename pairs, page facts and attributed publisher links."""
    if not isinstance(catalog_version,str) or not catalog_version:
        raise ValueError('A pinned filename catalog version is required')
    replacements={'{{CATALOG_VERSION}}':"'"+catalog_version.replace("'","''")+"'",
                  '{{EMPTY_STRINGS}}':EMPTY_STRINGS,'{{EMPTY_FACTS}}':EMPTY_FACTS,'{{FILENAME_DATE}}':FILENAME_DATE}
    names=['linked_filenames','filename','addresses','publisher','codes','committees','unmapped_committees','facts','meetings','pages','final']
    steps=[]
    for name in names:
        filename='source-linked-filenames' if name=='linked_filenames' else 'source-annotations-'+name
        sql=(Path(root)/'model/sql'/(filename+'.sql')).read_text()
        for token,value in replacements.items():sql=sql.replace(token,value)
        steps.append(dict(name='source_linked_filename_readings' if name=='linked_filenames' else
            'source_filename_readings' if name=='filename' else
            'source_annotations' if name=='final' else 'source_annotation_'+name,sql=sql,materialize=True))
    return steps
