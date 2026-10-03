"""Small object-store implementation for the raw mirror; no acquisition policy."""

import base64
import hashlib
from contextlib import closing


class R2Store:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket
        self.index_etags = {}

    def read(self, key):
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                if key.startswith("indexes/"):
                    self.index_etags[key] = None
                return None
            raise
        if key.startswith("indexes/"):
            self.index_etags[key] = response["ETag"]
        with closing(response["Body"]) as stream:
            data = stream.read()
        if len(data) != response["ContentLength"]:
            raise ValueError(f"Incomplete stored object: {key}")
        return data

    def put(self, key, body, *, immutable=False):
        from botocore.exceptions import ClientError

        options = {}
        if immutable:
            options["IfNoneMatch"] = "*"
        elif key.startswith("indexes/"):
            if key not in self.index_etags:
                raise ValueError("Read an index before replacing it")
            etag = self.index_etags[key]
            options.update({"IfMatch": etag} if etag else {"IfNoneMatch": "*"})
        digest = hashlib.md5(body).digest()
        try:
            result = self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentMD5=base64.b64encode(digest).decode(),
                ContentType="application/gzip"
                if key.endswith(".gz")
                else "application/octet-stream",
                **options,
            )
        except ClientError as error:
            if error.response["Error"]["Code"] in {"PreconditionFailed", "412"}:
                if immutable and key.startswith("bodies/"):
                    return False
                if immutable and key.startswith("catalog-history/sha256/") and self.read(key) == body:
                    return False  # A retry may preserve the same prior table again.
                raise RuntimeError(
                    f"Concurrent update or reused receipt name: {key}; published receipts remain recoverable."
                ) from error
            raise
        if result["ETag"].strip('"') != digest.hex():
            raise ValueError(f"Upload checksum mismatch: {key}")
        if key.startswith("indexes/"):
            self.index_etags[key] = result["ETag"]
        return True

    def keys(self, prefix):
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            for item in page.get("Contents", []):
                yield item["Key"]
