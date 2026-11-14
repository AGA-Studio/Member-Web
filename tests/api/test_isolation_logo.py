"""Isolation for /api/v1/logo: a business never sees or touches another's logo.

The route takes no business id at all: the business comes from the token. These
tests prove that both the file and the reference stay inside that business.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Business
from tests.conftest import bucket_keys, login, make_image

UPDATE = "/api/v1/logo/update"
DELETE = "/api/v1/logo/delete"


def upload(client: TestClient) -> None:
    response = client.post(UPDATE, files={"file": ("logo.png", make_image(), "image/png")})
    assert response.status_code == 200, response.text


def test_logo_of_a_is_invisible_to_b(client: TestClient, two_businesses, storage) -> None:
    login(client, "admin.a@demo.mx")
    upload(client)
    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    # 0 rows of A: B's business shows no logo at all.
    assert client.get("/api/v1/auth/me").json()["business"]["logo_url"] is None


def test_upload_by_b_only_changes_b(
    client: TestClient, session: Session, two_businesses, storage
) -> None:
    login(client, "admin.a@demo.mx")
    upload(client)
    a_logo = session.get(Business, two_businesses["business_a"].id).logo_url

    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    upload(client)

    session.expire_all()
    assert session.get(Business, two_businesses["business_a"].id).logo_url == a_logo
    b_id = two_businesses["business_b"].id
    assert session.get(Business, b_id).logo_url.startswith(f"businesses/{b_id}/logo/")


def test_delete_by_b_does_not_touch_a(client: TestClient, two_businesses, storage) -> None:
    login(client, "admin.a@demo.mx")
    upload(client)
    [a_key] = bucket_keys(storage)

    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    assert client.post(DELETE).status_code == 200
    assert bucket_keys(storage) == {a_key}


def test_files_are_separated_by_business_prefix(
    client: TestClient, two_businesses, storage
) -> None:
    for email in ("admin.a@demo.mx", "admin.b@demo.mx"):
        client.cookies.clear()
        login(client, email)
        upload(client)
    prefixes = {key.split("/logo/")[0] for key in bucket_keys(storage)}
    assert prefixes == {
        f"businesses/{two_businesses['business_a'].id}",
        f"businesses/{two_businesses['business_b'].id}",
    }
