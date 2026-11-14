"""services/storage_service.py against S3 simulated by moto."""

from urllib.parse import parse_qs, urlparse

import pytest

from core.config import settings
from services import storage_service
from services.storage_service import StorageUnavailable
from tests.conftest import TEST_S3_BUCKET, TEST_S3_PUBLIC_ENDPOINT, bucket_keys


class TestEnabled:
    def test_put_creates_the_bucket_and_stores_the_object(self, storage) -> None:
        storage_service.put_object("businesses/1/logo/a.webp", b"img", "image/webp")
        stored = storage.get_object(Bucket=TEST_S3_BUCKET, Key="businesses/1/logo/a.webp")
        assert stored["Body"].read() == b"img"
        assert stored["ContentType"] == "image/webp"

    def test_delete_removes_the_object(self, storage) -> None:
        storage_service.put_object("k.webp", b"img", "image/webp")
        storage_service.delete_object("k.webp")
        assert bucket_keys(storage) == set()

    def test_delete_of_a_missing_object_is_harmless(self, storage) -> None:
        storage_service.delete_object("never-existed.webp")

    def test_signed_url_points_to_the_public_host_and_expires(self, storage) -> None:
        url = urlparse(storage_service.signed_url("businesses/1/logo/a.webp"))
        query = parse_qs(url.query)
        assert f"{url.scheme}://{url.netloc}" == TEST_S3_PUBLIC_ENDPOINT
        assert url.path == f"/{TEST_S3_BUCKET}/businesses/1/logo/a.webp"
        assert query["X-Amz-Expires"] == [str(settings.s3_url_expire_seconds)]
        assert "X-Amz-Signature" in query

    def test_public_url_signs_keys(self, storage) -> None:
        assert "X-Amz-Signature" in storage_service.public_url("businesses/1/logo/a.webp")


class TestReferences:
    @pytest.mark.parametrize(
        ("reference", "is_key"),
        [
            ("businesses/1/logo/a.webp", True),
            ("https://cdn.example.mx/logo.png", False),
            ("http://cdn.example.mx/logo.png", False),
            ("", False),
            (None, False),
        ],
    )
    def test_is_storage_key(self, reference, is_key) -> None:
        assert storage_service.is_storage_key(reference) is is_key

    def test_external_urls_pass_through(self) -> None:
        url = "https://cdn.example.mx/logo.png"
        assert storage_service.public_url(url) == url

    @pytest.mark.parametrize("reference", [None, ""])
    def test_no_reference_is_none(self, reference) -> None:
        assert storage_service.public_url(reference) is None


class TestDisabled:
    """No S3 settings (production today): the API keeps working."""

    @pytest.fixture(autouse=True)
    def _no_storage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "s3_endpoint_url", "")

    def test_is_disabled(self) -> None:
        assert settings.storage_enabled is False

    def test_put_raises(self) -> None:
        with pytest.raises(StorageUnavailable):
            storage_service.put_object("k", b"x", "image/webp")

    def test_signed_url_raises(self) -> None:
        with pytest.raises(StorageUnavailable):
            storage_service.signed_url("k")

    def test_delete_is_silent(self) -> None:
        storage_service.delete_object("k")

    def test_stored_keys_are_reported_as_none(self) -> None:
        assert storage_service.public_url("businesses/1/logo/a.webp") is None

    def test_external_urls_still_pass_through(self) -> None:
        assert storage_service.public_url("https://cdn.example.mx/l.png").startswith("https")


def test_unreachable_server_is_storage_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "s3_endpoint_url": "http://127.0.0.1:1",
        "s3_access_key": "a",
        "s3_secret_key": "b",
    }.items():
        monkeypatch.setattr(settings, name, value)
    storage_service._client.cache_clear()
    storage_service._buckets_ready.clear()
    try:
        with pytest.raises(StorageUnavailable):
            storage_service.put_object("k", b"x", "image/webp")
    finally:
        storage_service._client.cache_clear()
