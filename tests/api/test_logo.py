"""/api/v1/logo: upload, replace and remove the business logo."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from core.config import settings
from models import Business
from services.image_service import MAX_UPLOAD_BYTES
from tests.conftest import bucket_keys, login, make_image

UPDATE = "/api/v1/logo/update"
DELETE = "/api/v1/logo/delete"
ME = "/api/v1/auth/me"


def upload(client: TestClient, data: bytes | None = None, name: str = "logo.png"):
    return client.post(UPDATE, files={"file": (name, data or make_image(), "image/png")})


class TestPermissions:
    def test_unauthenticated(self, client: TestClient, storage) -> None:
        assert upload(client).status_code == 401
        assert client.post(DELETE).status_code == 401

    @pytest.mark.parametrize("email", ["employee.a@demo.mx", "owner@memberplus.mx"])
    def test_only_admins(self, client: TestClient, two_businesses, storage, email) -> None:
        login(client, email)
        assert upload(client).status_code == 403
        assert client.post(DELETE).status_code == 403
        assert bucket_keys(storage) == set()


class TestUpload:
    def test_upload_returns_the_business_with_a_signed_url(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client)
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Business A"
        assert body["logo_url"].startswith("http://localhost:9000/")
        assert "X-Amz-Signature" in body["logo_url"]

    def test_stored_as_webp_under_the_business_prefix(
        self, client: TestClient, session: Session, two_businesses, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client)
        business_id = two_businesses["business_a"].id
        [key] = bucket_keys(storage)
        assert key.startswith(f"businesses/{business_id}/logo/")
        assert key.endswith(".webp")
        # The database keeps the key, never a URL.
        session.expire_all()
        assert session.get(Business, business_id).logo_url == key

    def test_me_shows_the_logo(self, client: TestClient, two_businesses, storage) -> None:
        login(client, "employee.a@demo.mx")
        assert client.get(ME).json()["business"]["logo_url"] is None
        client.cookies.clear()
        login(client, "admin.a@demo.mx")
        upload(client)
        client.cookies.clear()
        login(client, "employee.a@demo.mx")
        assert "X-Amz-Signature" in client.get(ME).json()["business"]["logo_url"]

    def test_replacing_deletes_the_previous_file(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client)
        [first] = bucket_keys(storage)
        upload(client, make_image("JPEG"))
        [second] = bucket_keys(storage)
        assert first != second

    def test_replacing_an_external_url_keeps_working(
        self, client: TestClient, session: Session, two_businesses, storage
    ) -> None:
        business = session.get(Business, two_businesses["business_a"].id)
        business.logo_url = "https://cdn.example.mx/old.png"
        session.add(business)
        session.commit()
        login(client, "admin.a@demo.mx")
        assert upload(client).status_code == 200
        assert len(bucket_keys(storage)) == 1


class TestValidation:
    def test_too_large(self, client: TestClient, two_businesses, storage) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client, b"0" * (MAX_UPLOAD_BYTES + 1))
        assert response.status_code == 413
        assert response.json()["code"] == "image_too_large"

    @pytest.mark.parametrize(
        ("data", "name"),
        [
            (b"not an image", "logo.png"),
            (make_image("GIF"), "logo.gif"),
            (b"%PDF-1.7\n" + b"0" * 100, "logo.png"),
        ],
        ids=["text", "gif", "pdf-renamed"],
    )
    def test_not_an_accepted_image(
        self, client: TestClient, two_businesses, storage, data, name
    ) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client, data, name)
        assert response.status_code == 422
        assert response.json()["code"] == "image_invalid"
        assert bucket_keys(storage) == set()

    def test_missing_file(self, client: TestClient, two_businesses, storage) -> None:
        login(client, "admin.a@demo.mx")
        assert client.post(UPDATE).status_code == 422

    def test_rejected_upload_keeps_the_current_logo(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        before = upload(client).json()["logo_url"].split("?")[0]
        upload(client, b"not an image")
        assert client.get(ME).json()["business"]["logo_url"].split("?")[0] == before


class TestDelete:
    def test_delete_removes_file_and_reference(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client)
        response = client.post(DELETE)
        assert response.status_code == 200
        assert response.json()["logo_url"] is None
        assert bucket_keys(storage) == set()
        assert client.get(ME).json()["business"]["logo_url"] is None

    def test_delete_without_logo_is_harmless(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        assert client.post(DELETE).status_code == 200
        assert client.post(DELETE).status_code == 200


class TestStorageDisabled:
    """Production today has no bucket: the rest of the API must not notice."""

    @pytest.fixture(autouse=True)
    def _no_storage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "s3_endpoint_url", "")

    def test_upload_is_503(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client)
        assert response.status_code == 503
        assert response.json()["code"] == "storage_unavailable"

    def test_invalid_image_is_still_422(self, client: TestClient, two_businesses) -> None:
        # Validation runs first: a bad file never needs the storage to be rejected.
        login(client, "admin.a@demo.mx")
        assert upload(client, b"not an image").status_code == 422

    def test_me_and_delete_keep_working(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = session.get(Business, two_businesses["business_a"].id)
        business.logo_url = "businesses/1/logo/stored-before.webp"
        session.add(business)
        session.commit()
        login(client, "admin.a@demo.mx")
        assert client.get(ME).json()["business"]["logo_url"] is None
        assert client.post(DELETE).status_code == 200
