"""Assemble per-source display evidence through the model's native SQL job."""
from pathlib import Path

from viewer_publication.archive_format import EMPTY_FACTS,EMPTY_STRINGS

ROOT=Path(__file__).parents[4]


def annotation_steps(catalog_version,*,root=ROOT):
    """Read the pinned filename pairs, page facts and attributed publisher links."""
    if not isinstance(catalog_version,str) or not catalog_version:
        raise ValueError('A pinned filename catalog version is required')
    replacements={'{{CATALOG_VERSION}}':"'"+catalog_version.replace("'","''")+"'",
                  '{{EMPTY_STRINGS}}':EMPTY_STRINGS,'{{EMPTY_FACTS}}':EMPTY_FACTS}
    names=['filename','addresses','publisher','codes','committees','unmapped_committees','facts','meetings','final']
    steps=[]
    for name in names:
        sql=(Path(root)/'model/sql'/('source-annotations-'+name+'.sql')).read_text()
        for token,value in replacements.items():sql=sql.replace(token,value)
        steps.append(dict(name='source_filename_readings' if name=='filename' else
            'source_annotations' if name=='final' else 'source_annotation_'+name,sql=sql,materialize=True))
    return steps
