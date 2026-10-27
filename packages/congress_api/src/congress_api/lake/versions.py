"""Content versions for parser packages, their inputs and locked dependencies."""
from hashlib import sha256
import json
from pathlib import Path


def version_digest(*, packages, files, values=None):
    """Hash package source/data recursively, explicit input files and vocabularies.

    Names and lengths delimit bytes, so moving a rule or changing a vocabulary
    changes the version. Runtime caches and build outputs never enter it.
    """
    digest = sha256()
    def add(name, data):
        label = name.encode('utf-8')
        digest.update(len(label).to_bytes(8, 'big')); digest.update(label)
        digest.update(len(data).to_bytes(8, 'big')); digest.update(data)
    for name, directory in sorted(packages.items()):
        directory = Path(directory)
        paths = sorted(path for path in directory.rglob('*')
                       if path.is_file() and path.suffix in {'.py', '.json', '.sql'}
                       and '__pycache__' not in path.parts)
        if not paths:
            raise ValueError('Version package has no source or data: ' + name)
        for path in paths:
            add('package/' + name + '/' + path.relative_to(directory).as_posix(), path.read_bytes())
    for name, path in sorted(files.items()):
        add('file/' + name, Path(path).read_bytes())
    add('values', json.dumps(values or {}, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode('utf-8'))
    return digest.hexdigest()
