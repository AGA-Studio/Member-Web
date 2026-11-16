"""/api/v1/customer/{customer_id}/photo: the customer's photo (decision of 16 nov 2026).

Only to show the customer in the panel and at the counter. Deleted when the
membership is cancelled.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from core.config import settings
from models import Customer
from services.image_service import MAX_UPLOAD_BYTES
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import bucket_keys, login, make_image

BASE = "/api/v1/customer"


@pytest.fixture
def customer(session: Session, two_businesses) -> Customer:
    tier = add_tier(session, two_businesses["business_a"], "Oro", 50000)
    return add_customer(session, two_businesses["business_a"], tier, "Laura Díaz", code="MP-AAAA1")


def upload(client: TestClient, customer_id: int, data: bytes | None = None):
    return client.post(
        f"{BASE}/{customer_id}/photo/update",
        files={"file": ("foto.jpg", data or make_image("JPEG"), "image/jpeg")},
    )


class TestPermissions:
    def test_unauthenticated(self, client: TestClient, customer, storage) -> None:
        assert upload(client, customer.id).status_code == 401
        assert client.post(f"{BASE}/{customer.id}/photo/delete").status_code == 401

    @pytest.mark.parametrize("email", ["employee.a@demo.mx", "owner@memberplus.mx"])
    def test_only_admins(self, client: TestClient, customer, storage, email: str) -> None:
        login(client, email)
        assert upload(client, customer.id).status_code == 403
        assert client.post(f"{BASE}/{customer.id}/photo/delete").status_code == 403
        assert bucket_keys(storage) == set()


class TestUpload:
    def test_returns_the_customer_with_a_signed_url(
        self, client: TestClient, customer, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client, customer.id)
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == customer.id
        assert body["photo_url"].startswith("http://localhost:9000/")
        assert "X-Amz-Signature" in body["photo_url"]

    def test_stored_under_the_customer_prefix(
        self, client: TestClient, session: Session, customer, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client, customer.id)
        [key] = bucket_keys(storage)
        assert key.startswith(f"businesses/{customer.business_id}/customers/{customer.id}/photo/")
        assert key.endswith(".webp")
        session.expire_all()
        # The database keeps the key, never a URL.
        assert session.get(Customer, customer.id).photo_url == key

    @pytest.mark.parametrize("path", ["list", "lookup?code=MP-AAAA1", "{id}"])
    def test_every_customer_response_carries_the_photo(
        self, client: TestClient, customer, storage, path: str
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client, customer.id)
        body = client.get(f"{BASE}/{path.format(id=customer.id)}").json()
        item = body["items"][0] if "items" in body else body
        assert "X-Amz-Signature" in item["photo_url"]

    def test_cashier_sees_it_at_the_counter(self, client: TestClient, customer, storage) -> None:
        login(client, "admin.a@demo.mx")
        upload(client, customer.id)
        client.cookies.clear()
        login(client, "employee.a@demo.mx")
        body = client.get(f"{BASE}/lookup", params={"code": "MP-AAAA1"}).json()
        assert "X-Amz-Signature" in body["photo_url"]

    def test_without_photo_it_is_null(self, client: TestClient, customer, storage) -> None:
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/{customer.id}").json()["photo_url"] is None

    def test_replacing_deletes_the_previous_file(
        self, client: TestClient, customer, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client, customer.id)
        [first] = bucket_keys(storage)
        upload(client, customer.id, make_image("PNG"))
        [second] = bucket_keys(storage)
        assert first != second

    def test_unknown_customer_is_404(self, client: TestClient, two_businesses, storage) -> None:
        login(client, "admin.a@demo.mx")
        assert upload(client, 999999).status_code == 404
        assert client.post(f"{BASE}/999999/photo/delete").status_code == 404


class TestValidation:
    def test_too_large(self, client: TestClient, customer, storage) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client, customer.id, b"0" * (MAX_UPLOAD_BYTES + 1))
        assert response.status_code == 413
        assert response.json()["code"] == "image_too_large"

    @pytest.mark.parametrize("data", [b"not an image", make_image("GIF")], ids=["text", "gif"])
    def test_not_an_accepted_image(self, client: TestClient, customer, storage, data) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client, customer.id, data)
        assert response.status_code == 422
        assert response.json()["code"] == "image_invalid"
        assert bucket_keys(storage) == set()

    def test_rejected_upload_keeps_the_current_photo(
        self, client: TestClient, customer, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client, customer.id)
        before = bucket_keys(storage)
        upload(client, customer.id, b"not an image")
        assert bucket_keys(storage) == before


class TestDelete:
    def test_delete_removes_file_and_reference(self, client: TestClient, customer, storage) -> None:
        login(client, "admin.a@demo.mx")
        upload(client, customer.id)
        response = client.post(f"{BASE}/{customer.id}/photo/delete")
        assert response.status_code == 200
        assert response.json()["photo_url"] is None
        assert bucket_keys(storage) == set()

    def test_delete_without_photo_is_200(self, client: TestClient, customer, storage) -> None:
        login(client, "admin.a@demo.mx")
        assert client.post(f"{BASE}/{customer.id}/photo/delete").status_code == 200


class TestCancel:
    """Decision of 16 nov 2026: the photo is deleted when the membership is cancelled."""

    def test_cancelling_deletes_the_photo(
        self, client: TestClient, session: Session, customer, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        upload(client, customer.id)
        response = client.post(f"{BASE}/{customer.id}/cancel")
        assert response.status_code == 200
        assert response.json()["photo_url"] is None
        assert bucket_keys(storage) == set()
        session.expire_all()
        assert session.get(Customer, customer.id).photo_url is None

    def test_cancelled_card_cannot_get_a_photo(self, client: TestClient, customer, storage) -> None:
        login(client, "admin.a@demo.mx")
        client.post(f"{BASE}/{customer.id}/cancel")
        response = upload(client, customer.id)
        assert response.status_code == 409
        assert response.json()["code"] == "customer_cancelled"
        assert bucket_keys(storage) == set()

    def test_cancelling_without_photo_still_works(
        self, client: TestClient, customer, storage
    ) -> None:
        login(client, "admin.a@demo.mx")
        assert client.post(f"{BASE}/{customer.id}/cancel").status_code == 200


class TestStorageDisabled:
    @pytest.fixture(autouse=True)
    def _no_storage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "s3_endpoint_url", "")

    def test_upload_is_503(self, client: TestClient, customer) -> None:
        login(client, "admin.a@demo.mx")
        response = upload(client, customer.id)
        assert response.status_code == 503
        assert response.json()["code"] == "storage_unavailable"

    def test_stored_photo_reads_as_null(
        self, client: TestClient, session: Session, customer
    ) -> None:
        customer.photo_url = "businesses/1/customers/1/photo/old.webp"
        session.add(customer)
        session.commit()
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/{customer.id}").json()["photo_url"] is None
