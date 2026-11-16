"""Isolation for /api/v1/customer/{customer_id}/photo: the most important case.

An admin must never upload, replace, delete or see the photo of a customer of
another business. The customer id is in the path, so this is where a leak
would happen: a foreign id must answer 404, like an id that does not exist.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Customer
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import bucket_keys, login, make_image

BASE = "/api/v1/customer"


def customers_of_both(session: Session, two_businesses) -> tuple[Customer, Customer]:
    tier_a = add_tier(session, two_businesses["business_a"], "Oro", 50000)
    tier_b = add_tier(session, two_businesses["business_b"], "Básico", 10000)
    a = add_customer(session, two_businesses["business_a"], tier_a, "Laura Díaz", code="MP-AAAA1")
    b = add_customer(session, two_businesses["business_b"], tier_b, "Mario Gil", code="MP-BBBB1")
    return a, b


def upload(client: TestClient, customer_id: int):
    return client.post(
        f"{BASE}/{customer_id}/photo/update",
        files={"file": ("foto.png", make_image(), "image/png")},
    )


def test_b_cannot_upload_a_photo_to_a_customer_of_a(
    client: TestClient, session: Session, two_businesses, storage
) -> None:
    a, _ = customers_of_both(session, two_businesses)
    login(client, "admin.b@demo.mx")
    response = upload(client, a.id)
    assert response.status_code == 404
    assert bucket_keys(storage) == set()
    session.expire_all()
    assert session.get(Customer, a.id).photo_url is None


def test_b_cannot_delete_the_photo_of_a_customer_of_a(
    client: TestClient, session: Session, two_businesses, storage
) -> None:
    a, _ = customers_of_both(session, two_businesses)
    login(client, "admin.a@demo.mx")
    upload(client, a.id)
    [a_key] = bucket_keys(storage)

    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    assert client.post(f"{BASE}/{a.id}/photo/delete").status_code == 404
    assert bucket_keys(storage) == {a_key}


def test_b_never_sees_the_photo_of_a(
    client: TestClient, session: Session, two_businesses, storage
) -> None:
    a, _ = customers_of_both(session, two_businesses)
    login(client, "admin.a@demo.mx")
    upload(client, a.id)

    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    # 0 rows of A in B's list, and A's customer is a 404 by id or by code.
    listing = client.get(f"{BASE}/list").json()
    assert [item["full_name"] for item in listing["items"]] == ["Mario Gil"]
    assert listing["items"][0]["photo_url"] is None
    assert client.get(f"{BASE}/{a.id}").status_code == 404
    assert client.get(f"{BASE}/lookup", params={"code": "MP-AAAA1"}).status_code == 404


def test_photos_are_separated_by_business_prefix(
    client: TestClient, session: Session, two_businesses, storage
) -> None:
    a, b = customers_of_both(session, two_businesses)
    for email, customer in (("admin.a@demo.mx", a), ("admin.b@demo.mx", b)):
        client.cookies.clear()
        login(client, email)
        assert upload(client, customer.id).status_code == 200
    prefixes = {key.split("/customers/")[0] for key in bucket_keys(storage)}
    assert prefixes == {
        f"businesses/{two_businesses['business_a'].id}",
        f"businesses/{two_businesses['business_b'].id}",
    }
