"""/api/v1/business/update: name and membership validity of the token's business."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Business
from tests.conftest import login

URL = "/api/v1/business/update"
ME_URL = "/api/v1/auth/me"


@pytest.fixture
def admin(client: TestClient, two_businesses) -> TestClient:
    login(client, "admin.a@demo.mx")
    return client


def stored(session: Session, two_businesses) -> Business:
    business = session.get(Business, two_businesses["business_a"].id)
    session.refresh(business)
    return business


class TestUpdate:
    def test_returns_what_auth_me_shows(self, admin: TestClient, two_businesses) -> None:
        response = admin.patch(URL, json={"name": "Café Aurora", "validity_months": 6})
        assert response.status_code == 200
        assert response.json() == {
            "id": two_businesses["business_a"].id,
            "name": "Café Aurora",
            "logo_url": None,
            "status": "active",
            "validity_months": 6,
        }
        assert admin.get(ME_URL).json()["business"] == response.json()

    def test_only_the_fields_sent_change(
        self, admin: TestClient, session: Session, two_businesses
    ) -> None:
        admin.patch(URL, json={"validity_months": 24})
        business = stored(session, two_businesses)
        assert (business.name, business.validity_months) == ("Business A", 24)

        admin.patch(URL, json={"name": "Café Aurora"})
        business = stored(session, two_businesses)
        assert (business.name, business.validity_months) == ("Café Aurora", 24)

    def test_null_keeps_the_current_value(
        self, admin: TestClient, session: Session, two_businesses
    ) -> None:
        response = admin.patch(URL, json={"name": None, "validity_months": None})
        assert response.status_code == 200
        business = stored(session, two_businesses)
        assert (business.name, business.validity_months) == ("Business A", 12)

    def test_empty_body_changes_nothing(self, admin: TestClient) -> None:
        response = admin.patch(URL, json={})
        assert (response.status_code, response.json()["name"]) == (200, "Business A")

    def test_name_is_trimmed_and_spaces_collapsed(self, admin: TestClient) -> None:
        response = admin.patch(URL, json={"name": "  Café   Aurora 24 "})
        assert response.json()["name"] == "Café Aurora 24"

    @pytest.mark.parametrize("months", [1, 60])
    def test_validity_bounds_are_accepted(self, admin: TestClient, months: int) -> None:
        assert (
            admin.patch(URL, json={"validity_months": months}).json()["validity_months"] == months
        )

    @pytest.mark.parametrize(
        "body",
        [
            {"name": ""},
            {"name": "   "},
            {"name": "A"},
            {"name": "x" * 121},
            {"validity_months": 0},
            {"validity_months": 61},
            {"validity_months": -3},
            {"validity_months": 6.5},
            {"validity_months": "12"},
        ],
    )
    def test_invalid_values_are_422(
        self, admin: TestClient, session: Session, two_businesses, body: dict
    ) -> None:
        assert admin.patch(URL, json=body).status_code == 422
        business = stored(session, two_businesses)
        assert (business.name, business.validity_months) == ("Business A", 12)

    def test_status_and_logo_cannot_be_changed_here(
        self, admin: TestClient, session: Session, two_businesses
    ) -> None:
        admin.patch(URL, json={"status": "suspended", "logo_url": "https://x.mx/l.png"})
        business = stored(session, two_businesses)
        assert (business.status, business.logo_url) == ("active", None)

    def test_new_validity_applies_to_new_cards(self, admin: TestClient, session: Session) -> None:
        from services.customer_service import add_months
        from tests.api.test_customer import add_tier
        from tests.api.test_membership_payment import as_datetime, create

        business_id = admin.get(ME_URL).json()["business"]["id"]
        tier = add_tier(session, session.get(Business, business_id), "Oro", 0)
        admin.patch(URL, json={"validity_months": 3})
        response = create(admin, level_id=tier.id)
        assert response.status_code == 201, response.text
        body = response.json()
        assert as_datetime(body["valid_until"]) == add_months(as_datetime(body["issued_at"]), 3)


class TestPermissions:
    def test_employee_is_403(self, client: TestClient, two_businesses) -> None:
        login(client, "employee.a@demo.mx")
        assert client.patch(URL, json={"name": "Otro"}).status_code == 403

    def test_platform_is_403(self, client: TestClient, two_businesses) -> None:
        login(client, "owner@memberplus.mx")
        assert client.patch(URL, json={"name": "Otro"}).status_code == 403

    def test_without_session_is_401(self, client: TestClient) -> None:
        assert client.patch(URL, json={"name": "Otro"}).status_code == 401
