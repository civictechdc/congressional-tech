"""Application-owned policy inputs and native SQL for raw-derived releases."""
import json
from pathlib import Path

from congress_api.retention.provenance import json_input,list_of

ROOT=Path(__file__).parents[4]
REGISTRIES={
    'file_shapes':dict(id='Utf8',pattern='Utf8'),
    'page_signals':dict(id='Utf8',kind='Utf8',pattern='Utf8',number='Int64'),
    'formats':dict(id='Utf8',kind='Utf8',value='Utf8',rank='Int32'),
    'publisher_kinds':dict(id='Utf8',basis='Utf8',pattern='Utf8',document_kind='Utf8'),
    'display_facts':dict(id='Utf8',field='Utf8',label='Utf8'),
    'committee_codes':dict(id='Utf8',code='Utf8',system_code='Utf8',chamber='Utf8'),
    'recheck_intervals':dict(id='Utf8',family='Utf8',min_age_days='Int64',max_age_days='Int64',interval_seconds='Int64'),
    'url_rules':dict(id='Utf8',kind='Utf8',host_pattern='Utf8',pattern='Utf8',replacement='Utf8',decoder='Utf8'),
    'filename_parameters':dict(priority='Int64',parameter='Utf8'),
    'import_runs':dict(run_id='Utf8',date='Utf8'),
    'credential_parameters':dict(parameter='Utf8'),
    'recovery_kinds':dict(category='Utf8',match_basis='Utf8',kind='Utf8',import_category='Utf8'),
    'capture_scope':dict(family='Utf8',patterns=list_of('Utf8'),exclusions=list_of('Utf8')),
}


def registry_inputs(directory,*,root=ROOT):
    """Serialize policy records only; native SQL performs every policy join."""
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    inputs=[]
    for name,fields in REGISTRIES.items():
        path=Path(root)/'model/registries'/(name.replace('_','-')+'.json')
        value=json.loads(path.read_text())
        if name=='capture_scope':
            if not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=1:
                raise ValueError('Unsupported capture scope registry')
            value=value.get('entries')
        if not isinstance(value,list) or any(not isinstance(row,dict) for row in value):
            raise ValueError('Registry must contain records: '+name)
        inputs.append(json_input(directory,name,value,**fields))
    return inputs
