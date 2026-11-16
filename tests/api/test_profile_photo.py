"""/api/v1/user/photo: each user changes only their own profile photo."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from core.config import settings
from models import User
from tests.conftest import bucket_keys, login, make_image

UPDATE = "/api/v1/user/photo/update"
DELETE = "/api/v1/user/photo/delete"
ME = "/api/v1/auth/me"


def upload(client: TestClient, data: bytes | None = None):
    return client.post(UPDATE, files={"file": ("yo.png", data or make_image(), "image/png")})


def test_unauthenticated(client: TestClient, storage) -> None:
    assert upload(client).status_code == 401
    assert client.post(DELETE).status_code == 401


@pytest.mark.parametrize("email", ["admin.a@demo.mx", "employee.a@demo.mx", "owner@memberplus.mx"])
def test_every_role_can_change_its_own_photo(
    client: TestClient, two_businesses, storage, email: str
) -> None:
    login(client, email)
    response = upload(client)
    assert response.status_code == 200
    assert response.json()["email"] == email
    assert "X-Amz-Signature" in response.json()["photo_url"]
    assert "X-Amz-Signature" in client.get(ME).json()["photo_url"]


def test_key_layout(client: TestClient, session: Session, two_businesses, storage) -> None:
    login(client, "employee.a@demo.mx")
    upload(client)
    client.cookies.clear()
    login(client, "owner@memberplus.mx")
    upload(client)

    employee = two_businesses["employee_a"]
    owner = two_businesses["platform"]
    keys = bucket_keys(storage)
    employee_prefix = f"businesses/{employee.business_id}/users/{employee.id}/photo/"
    assert any(k.startswith(employee_prefix) for k in keys)
    # The platform owner has no business: their photo goes under platform/.
    assert any(k.startswith(f"platform/users/{owner.id}/photo/") for k in keys)
    session.expire_all()
    assert session.get(User, employee.id).photo_url in keys


def test_user_list_shows_signed_urls_not_keys(client: TestClient, two_businesses, storage) -> None:
    login(client, "employee.a@demo.mx")
    upload(client)
    client.cookies.clear()
    login(client, "admin.a@demo.mx")
    photos = {u["email"]: u["photo_url"] for u in client.get("/api/v1/user/list").json()}
    assert "X-Amz-Signature" in photos["employee.a@demo.mx"]
    assert photos["admin.a@demo.mx"] is None


def test_replacing_deletes_the_previous_file(client: TestClient, two_businesses, storage) -> None:
    login(client, "admin.a@demo.mx")
    upload(client)
    [first] = bucket_keys(storage)
    upload(client, make_image("JPEG"))
    [second] = bucket_keys(storage)
    assert first != second


def test_delete(client: TestClient, two_businesses, storage) -> None:
    login(client, "admin.a@demo.mx")
    upload(client)
    response = client.post(DELETE)
    assert response.status_code == 200
    assert response.json()["photo_url"] is None
    assert bucket_keys(storage) == set()
    assert client.post(DELETE).status_code == 200  # Without a photo: still 200.


def test_validation(client: TestClient, two_businesses, storage) -> None:
    login(client, "admin.a@demo.mx")
    assert upload(client, b"not an image").json()["code"] == "image_invalid"
    assert upload(client, b"0" * (2 * 1024 * 1024 + 1)).status_code == 413
    assert bucket_keys(storage) == set()


def test_storage_disabled(
    client: TestClient, two_businesses, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "s3_endpoint_url", "")
    login(client, "admin.a@demo.mx")
    response = upload(client)
    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"


def test_one_user_never_touches_another(
    client: TestClient, session: Session, two_businesses, storage
) -> None:
    """There is no user id in the path: each request acts on the session user."""
    login(client, "admin.a@demo.mx")
    upload(client)
    [admin_key] = bucket_keys(storage)

    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    upload(client)
    client.post(DELETE)

    assert bucket_keys(storage) == {admin_key}
    session.expire_all()
    assert session.get(User, two_businesses["admin_a"].id).photo_url == admin_key
