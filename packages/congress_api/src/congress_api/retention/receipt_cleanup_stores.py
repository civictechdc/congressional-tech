"""File transfer adapters for the exceptional B0 rewrite, never for ordinary writers."""
import base64
from contextlib import closing
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from congress_api.retention.receipt_cleanup import digest


class DirectoryFiles:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or not key.startswith('receipts/'):
            raise ValueError('Expected a receipt key inside the selected directory')
        return path

    def get_file(self, key, destination):
        source = self.path(key)
        try:
            shutil.copyfile(source, destination)
        except FileNotFoundError:
            return None
        return dict(etag=digest(destination), size=destination.stat().st_size)

    def put_file(self, key, source, *, if_match=None, create_only=False):
        if bool(if_match) == bool(create_only):
            raise ValueError('Choose one conditional write')
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / '.cx_receipt_cleanup.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if if_match and (not path.exists() or digest(path) != if_match):
                raise ValueError('Conditional receipt rewrite lost a race')
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.cx_', delete=False) as out:
                temporary = Path(out.name)
                try:
                    with Path(source).open('rb') as before:
                        shutil.copyfileobj(before, out)
                    out.flush()
                    os.fsync(out.fileno())
                    if create_only:
                        os.link(temporary, path)
                    else:
                        os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)


class R2ReceiptFiles:
    """The only non-create-only raw adapter: receipt keys and If-Match required."""
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def get_file(self, key, destination):
        from botocore.exceptions import ClientError
        if not key.startswith('receipts/'):
            raise ValueError('Expected a receipt key')
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response['Error']['Code'] in {'NoSuchKey', '404'}:
                return None
            raise
        with closing(response['Body']) as before, Path(destination).open('wb') as after:
            shutil.copyfileobj(before, after)
        return dict(etag=response['ETag'].strip('"'), size=response['ContentLength'])

    def put_file(self, key, source, *, if_match=None, create_only=False):
        if not key.startswith('receipts/') or create_only or not if_match:
            raise ValueError('B0 only replaces receipts with an original ETag')
        checksum = digest(source)
        with Path(source).open('rb') as body:
            result = self.client.put_object(
                Bucket=self.bucket, Key=key, Body=body,
                ContentLength=Path(source).stat().st_size,
                ContentMD5=base64.b64encode(bytes.fromhex(checksum)).decode(),
                IfMatch=if_match, ContentType='application/gzip')
        if result['ETag'].strip('"') != checksum:
            raise ValueError('Receipt rewrite returned the wrong MD5')
