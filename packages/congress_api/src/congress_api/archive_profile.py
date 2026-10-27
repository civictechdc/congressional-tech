"""Small public metadata shared by the model publisher and capture consumer."""
from hashlib import sha256
import re

RULE_FIELDS=('id','kind','host_pattern','pattern','replacement','decoder')


def build_capture_profile(*,engine_revision,url_normalized_sql,url_keys_sql,url_rules):
    """Copy the model's pinned capture instructions into content-only metadata."""
    value=dict(version=1,engine_revision=engine_revision,
        sql={name:dict(text=text,sha256=sha256(text.encode('utf-8')).hexdigest())
             for name,text in [('url_normalized',url_normalized_sql),('url_keys',url_keys_sql)]},
        url_rules=[{key:row.get(key) for key in RULE_FIELDS} for row in url_rules],
        url_variants_file='url_variants.parquet')
    return validate_capture_profile(value,engine_revision=engine_revision)


def validate_capture_profile(value,*,engine_revision):
    """Refuse changed instructions or an incompatible engine; perform no I/O."""
    if not isinstance(value,dict) or set(value)!={'version','engine_revision','sql','url_rules','url_variants_file'}:
        raise ValueError('Incomplete public capture profile')
    if (type(value['version']) is not int or value['version']!=1 or not isinstance(engine_revision,str)
            or re.fullmatch('[0-9a-f]{40}',engine_revision) is None
            or value['engine_revision']!=engine_revision):
        raise ValueError('Public capture profile version or engine revision is incompatible')
    if value['url_variants_file']!='url_variants.parquet':
        raise ValueError('Public variants must name the release-bound variant file')
    definitions=value['sql']
    if not isinstance(definitions,dict) or set(definitions)!={'url_normalized','url_keys'}:
        raise ValueError('Both shared URL steps are required')
    for definition in definitions.values():
        if (not isinstance(definition,dict) or set(definition)!={'text','sha256'}
                or not isinstance(definition['text'],str) or not definition['text'].strip()
                or sha256(definition['text'].encode('utf-8')).hexdigest()!=definition['sha256']):
            raise ValueError('Public capture SQL definition changed')
    rules=value['url_rules']
    if not isinstance(rules,list) or not rules:
        raise ValueError('Public URL rules are required')
    seen=set()
    for rule in rules:
        if (not isinstance(rule,dict) or set(rule)!=set(RULE_FIELDS)
                or not isinstance(rule['id'],str) or not rule['id'] or rule['id'] in seen
                or rule['kind'] not in ('wrapper','strip','repair')
                or not isinstance(rule['pattern'],str) or not rule['pattern']
                or rule['host_pattern'] is not None and not isinstance(rule['host_pattern'],str)
                or rule['replacement'] is not None and not isinstance(rule['replacement'],str)
                or rule['decoder'] not in (None,'none','percent','proofpoint')
                or rule['kind'] in ('wrapper','repair') and not isinstance(rule['replacement'],str)
                or rule['kind']=='strip' and (rule['replacement'] is not None or rule['decoder'] is not None)):
            raise ValueError('Invalid or duplicate public URL rule')
        seen.add(rule['id'])
    return value
