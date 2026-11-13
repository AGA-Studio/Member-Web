"""Object storage through the S3 API (RustFS locally, any S3 provider later).

The bucket is private. The database stores the object *key*
(`businesses/1/logo/<uuid>.webp`), never a URL; the API hands out signed URLs
that expire after `S3_URL_EXPIRE_SECONDS`. Keys start with the business id, so
objects are separated per business the same way rows are.

With no S3 settings, storage is disabled and every call raises
StorageUnavailable: the rest of the API keeps working.
"""

from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from core.config import settings

# Short timeouts: a missing storage server must not hang an API request.
_CLIENT_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    connect_timeout=3,
    read_timeout=10,
    retries={"max_attempts": 2},
)

_buckets_ready: set[str] = set()


class StorageUnavailable(RuntimeError):
    """Storage is not configured or did not answer."""


def is_storage_key(reference: str | None) -> bool:
    """A stored reference is a key unless it is already an absolute URL."""
    return bool(reference) and not reference.startswith(("http://", "https://"))


@lru_cache(maxsize=4)
def _client(endpoint_url: str, access_key: str, secret_key: str, region: str) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=_CLIENT_CONFIG,
    )


def _api_client() -> BaseClient:
    if not settings.storage_enabled:
        raise StorageUnavailable("Storage is not configured")
    return _client(
        settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key, settings.s3_region
    )


def _public_client() -> BaseClient:
    """Signs URLs for the host the browser reaches (signing makes no request)."""
    if not settings.storage_enabled:
        raise StorageUnavailable("Storage is not configured")
    return _client(
        settings.effective_s3_public_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_region,
    )


def _ensure_bucket(client: BaseClient) -> None:
    bucket = settings.s3_bucket
    if bucket in _buckets_ready:
        return
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
    _buckets_ready.add(bucket)


def put_object(key: str, data: bytes, content_type: str) -> None:
    client = _api_client()
    try:
        _ensure_bucket(client)
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    except (BotoCoreError, ClientError) as error:
        raise StorageUnavailable("Could not store the file") from error


def delete_object(key: str) -> None:
    """Best effort: an orphan file is harmless, a failed request is not."""
    try:
        _api_client().delete_object(Bucket=settings.s3_bucket, Key=key)
    except StorageUnavailable, BotoCoreError, ClientError:
        pass


def signed_url(key: str) -> str:
    return _public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.s3_url_expire_seconds,
    )


def public_url(reference: str | None) -> str | None:
    """What the API returns for a stored reference.

    External URLs pass through unchanged. Keys become signed URLs, or None if
    storage is off, so the frontend falls back to its placeholder.
    """
    if not reference:
        return None
    if not is_storage_key(reference):
        return reference
    try:
        return signed_url(reference)
    except StorageUnavailable:
        return None
