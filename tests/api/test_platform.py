"""/api/v1/platform: the platform owner's view of the businesses (API contract, section 7)."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import BusinessStatus
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

URL = "/api/v1/platform/business/list"


@pytest.fixture
def platform(client: TestClient, session: Session, two_businesses, make_business) -> dict:
    """A: 2 cards (1 cancelled). B: 1 card. Plus a suspended and a trial business."""
    a, b = two_businesses["business_a"], two_businesses["business_b"]
    tier_a, tier_b = add_tier(session, a, "Básico A", 0), add_tier(session, b, "Básico B", 0)
    add_customer(session, a, tier_a, "Laura Méndez", code="MP-AAAA1")
    add_customer(session, a, tier_a, "Daniela Vega", code="MP-AAAA2", cancelled=True)
    add_customer(session, b, tier_b, "Roberto Díaz", code="MP-BBBB1")
    businesses = {
        "a": a,
        "b": b,
        "suspended": make_business("Zapatería Sol", BusinessStatus.SUSPENDED),
        "trial": make_business("Café Nube", BusinessStatus.TRIAL),
    }
    login(client, "owner@memberplus.mx")
    return businesses


def names(response) -> list[str]:
    return [item["name"] for item in response.json()["items"]]


class TestList:
    def test_item_has_the_contract_shape(self, client: TestClient, platform) -> None:
        response = client.get(URL, params={"q": "business a"})
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item.pop("created_at").endswith(("Z", "+00:00"))
        assert item == {
            "id": platform["a"].id,
            "name": "Business A",
            "status": "active",
            "customers_count": 1,
        }

    def test_every_business_by_name(self, client: TestClient, platform) -> None:
        body = client.get(URL).json()
        assert names_of(body) == ["Business A", "Business B", "Café Nube", "Zapatería Sol"]
        assert (body["total"], body["page"], body["page_size"]) == (4, 1, 8)

    def test_customers_count_skips_cancelled_cards(self, client: TestClient, platform) -> None:
        counts = {item["name"]: item["customers_count"] for item in client.get(URL).json()["items"]}
        assert counts == {"Business A": 1, "Business B": 1, "Café Nube": 0, "Zapatería Sol": 0}

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("active", ["Business A", "Business B"]),
            ("trial", ["Café Nube"]),
            ("suspended", ["Zapatería Sol"]),
        ],
    )
    def test_filter_by_status(self, client: TestClient, platform, status: str, expected) -> None:
        assert names(client.get(URL, params={"status": status})) == expected

    @pytest.mark.parametrize("q", ["café", "CAFÉ", "nube"])
    def test_q_searches_the_name_ignoring_case(self, client: TestClient, platform, q: str) -> None:
        assert names(client.get(URL, params={"q": q})) == ["Café Nube"]

    def test_q_does_not_search_customers(self, client: TestClient, platform) -> None:
        assert names(client.get(URL, params={"q": "Laura"})) == []

    def test_page_past_the_end_returns_the_last(self, client: TestClient, platform) -> None:
        body = client.get(URL, params={"page": 9, "page_size": 3}).json()
        assert (body["page"], names_of(body)) == (2, ["Zapatería Sol"])

    @pytest.mark.parametrize(
        "params", [{"status": "deleted"}, {"page": 0}, {"page_size": 501}, {"q": "x" * 121}]
    )
    def test_invalid_params_are_422(self, client: TestClient, platform, params: dict) -> None:
        assert client.get(URL, params=params).status_code == 422


class TestPrivacy:
    def test_never_exposes_customer_data(self, client: TestClient, platform) -> None:
        text = client.get(URL).text
        for secret in ("Laura", "MP-AAAA1", "@correo.com", "points", "cashback", "email"):
            assert secret not in text
        keys = {key for item in client.get(URL).json()["items"] for key in item}
        assert keys == {"id", "name", "status", "customers_count", "created_at"}


class TestPermissions:
    @pytest.mark.parametrize("email", ["admin.a@demo.mx", "employee.a@demo.mx"])
    def test_business_users_are_403(self, client: TestClient, two_businesses, email: str) -> None:
        login(client, email)
        assert client.get(URL).status_code == 403

    def test_without_session_is_401(self, client: TestClient) -> None:
        assert client.get(URL).status_code == 401


def names_of(body: dict) -> list[str]:
    return [item["name"] for item in body["items"]]
