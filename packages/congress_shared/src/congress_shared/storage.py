"""Shared Cloudflare R2 / S3 client configuration and connection builder.

Boto3 and botocore are imported lazily inside :func:`connect_r2` and
:meth:`R2Config.botocore_config` so importing ``congress_shared.storage`` has
zero third-party import cost or side effects.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
import re
from typing import Any


def single_put_md5(etag):
    """Normalize the stored-byte checksum of a single-PUT object."""
    if isinstance(etag,str) and etag.startswith('"') and etag.endswith('"'):
        etag=etag[1:-1]
    if not isinstance(etag,str) or re.fullmatch('[a-fA-F0-9]{32}',etag) is None:
        raise ValueError('ETag must be a single-PUT MD5')
    return etag.lower()


@dataclass(frozen=True)
class R2Config:
    """Immutable Cloudflare R2 S3-compatible connection settings."""

    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket: str = "congressional-tech-raw"
    region_name: str = "auto"
    connect_timeout: int | float | None = 15
    read_timeout: int | float | None = 180
    retries: Mapping[str, Any] | None = None
    max_pool_connections: int | None = None
    checksum_when_required: bool = True

    @classmethod
    def from_env(
        cls,
        *,
        account_id: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket: str = "congressional-tech-raw",
        connect_timeout: int | float | None = 15,
        read_timeout: int | float | None = 180,
        retries: Mapping[str, Any] | None = None,
        max_pool_connections: int | None = None,
        checksum_when_required: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> R2Config:
        environ = os.environ if env is None else env
        resolved_account = account_id or environ.get("CLOUDFLARE_ACCOUNT_ID")
        resolved_endpoint = (
            endpoint_url
            or environ.get("R2_ENDPOINT_URL")
            or (
                f"https://{resolved_account}.r2.cloudflarestorage.com"
                if resolved_account
                else None
            )
        )
        resolved_key = access_key_id or environ.get("R2_ACCESS_KEY_ID")
        resolved_secret = secret_access_key or environ.get("R2_SECRET_ACCESS_KEY")
        if not all((resolved_endpoint, resolved_key, resolved_secret)):
            raise ValueError(
                "CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are required"
            )
        return cls(
            endpoint_url=str(resolved_endpoint),
            access_key_id=str(resolved_key),
            secret_access_key=str(resolved_secret),
            bucket=bucket,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries=retries,
            max_pool_connections=max_pool_connections,
            checksum_when_required=checksum_when_required,
        )

    @classmethod
    def from_ini_section(
        cls,
        section: Mapping[str, str],
        *,
        bucket: str = "congressional-tech-raw",
        connect_timeout: int | float | None = 15,
        read_timeout: int | float | None = 180,
        retries: Mapping[str, Any] | None = None,
        max_pool_connections: int | None = None,
        checksum_when_required: bool = False,
    ) -> R2Config:
        return cls(
            endpoint_url=section["endpoint"],
            access_key_id=section["access_key_id"],
            secret_access_key=section["secret_access_key"],
            bucket=bucket,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries=retries,
            max_pool_connections=max_pool_connections,
            checksum_when_required=checksum_when_required,
        )

    def client_kwargs(self) -> dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url,
            "aws_access_key_id": self.access_key_id,
            "aws_secret_access_key": self.secret_access_key,
            "region_name": self.region_name,
        }

    def botocore_config(self) -> Any:
        from botocore.config import Config

        options: dict[str, Any] = {}
        if self.connect_timeout is not None:
            options["connect_timeout"] = self.connect_timeout
        if self.read_timeout is not None:
            options["read_timeout"] = self.read_timeout
        if self.retries is not None:
            options["retries"] = dict(self.retries)
        else:
            options["retries"] = {"total_max_attempts": 1}
        if self.max_pool_connections is not None:
            options["max_pool_connections"] = self.max_pool_connections
        if self.checksum_when_required:
            options["request_checksum_calculation"] = "when_required"
            options["response_checksum_validation"] = "when_required"
        return Config(**options)


def connect_r2(
    config: R2Config | None = None,
    *,
    account_id: str | None = None,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    bucket: str = "congressional-tech-raw",
    connect_timeout: int | float | None = 15,
    read_timeout: int | float | None = 180,
    retries: Mapping[str, Any] | None = None,
    max_pool_connections: int | None = None,
    checksum_when_required: bool = True,
    use_botocore_config: bool = True,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Construct a configured ``boto3`` S3 client for Cloudflare R2."""
    import boto3

    resolved = config or R2Config.from_env(
        account_id=account_id,
        endpoint_url=endpoint_url,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        bucket=bucket,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries=retries,
        max_pool_connections=max_pool_connections,
        checksum_when_required=checksum_when_required,
        env=env,
    )
    kwargs = resolved.client_kwargs()
    if use_botocore_config:
        kwargs["config"] = resolved.botocore_config()
    return boto3.client("s3", **kwargs)
