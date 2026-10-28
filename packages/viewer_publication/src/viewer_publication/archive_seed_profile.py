"""Identify a display-only v5 seed independently of raw lake generations."""
import re

from congress_api.lake.versions import version_digest
from viewer_publication.archive_model_job import _pin
from viewer_publication.archive_model_profile import _copy

SOURCES=('documents','filenames','captures','accepted')
FIELDS={'version','kind','label','display_only','catalog_id','generation','document_rows',
        'input_files','engine_revision','definition_hashes'}


def _hex(value,length):
    if not isinstance(value,str) or re.fullmatch('[0-9a-f]{'+str(length)+'}',value) is None:
        raise ValueError('Seed identity requires an exact lowercase hexadecimal pin')


def _profile(*,catalog_id,generation,document_rows,input_files,engine_revision,definition_hashes):
    _hex(catalog_id,32);_hex(generation,32);_hex(engine_revision,40)
    if type(document_rows) is not int or document_rows<1:
        raise ValueError('Seed identity requires its positive source document count')
    if not isinstance(input_files,dict) or set(input_files)!=set(SOURCES):
        raise ValueError('Seed identity requires exactly the four approved source files')
    for value in input_files.values():_pin(value,{'sha256','size'})
    if not isinstance(definition_hashes,dict) or not definition_hashes:
        raise ValueError('Seed identity requires explicit definition hashes')
    for name,digest in definition_hashes.items():
        if (not isinstance(name,str) or not name or name.startswith('/') or '\\' in name
                or any(part in {'','.','..'} for part in name.split('/'))
                or any(ord(char)<32 for char in name)):
            raise ValueError('Seed definitions must use repository-relative paths')
        _hex(digest,64)
    return _copy(dict(version=1,kind='seed_v5',label='seed: v5 catalog '+generation[:8],display_only=True,
        catalog_id=catalog_id,generation=generation,document_rows=document_rows,input_files=input_files,
        engine_revision=engine_revision,definition_hashes=definition_hashes))


def seed_profile_record(**values):
    """Hash source contents and definitions; claim no raw receipts or lake pins."""
    profile=_profile(**values)
    return dict(version=1,profile=profile,
        profile_sha256=version_digest(packages={},files={},values=profile),snapshots={})


def validate_seed_profile(value):
    """Validate kept seed evidence using recorded definitions, without I/O."""
    if not isinstance(value,dict) or set(value)!=FIELDS:
        raise ValueError('Seed profile has missing or unknown fields')
    expected=_profile(**{name:value[name] for name in [
        'catalog_id','generation','document_rows','input_files','engine_revision','definition_hashes']})
    if value!=expected or type(value['version']) is not int or value['display_only'] is not True:
        raise ValueError('Seed profile must identify a display-only v5 catalog')
    return expected
