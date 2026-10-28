"""Issue fixture creation evidence from the buffer used to write each source."""
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def write_qualified_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    authority = path.with_name(path.name+'.qualification.json')
    authority.write_text(json.dumps(dict(path=str(path.resolve()),
        sha256=sha256(data).hexdigest(), size=len(data), producer='synthetic fixture creation')))
    return str(authority.resolve())


def write_qualified_parquet(table, path, **kwargs):
    output = pa.BufferOutputStream()
    pq.write_table(table, output, **kwargs)
    return write_qualified_bytes(path, output.getvalue().to_pybytes())


def created_qualifications(path):
    """Bind the explicit qualification issued by these fixture writers."""
    path = Path(path).resolve()
    return {str(path): str(path.with_name(path.name+'.qualification.json'))}
