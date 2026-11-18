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
            "primary_color": None,
            "primary_foreground": None,
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


class TestPrimaryColor:
    def test_sets_the_color_and_its_readable_foreground(self, admin: TestClient) -> None:
        body = admin.patch(URL, json={"primary_color": "#0062F2"}).json()
        # Stored in lowercase; white text stays readable on blue.
        assert (body["primary_color"], body["primary_foreground"]) == ("#0062f2", "#ffffff")
        me = admin.get(ME_URL).json()["business"]
        assert (me["primary_color"], me["primary_foreground"]) == ("#0062f2", "#ffffff")

    def test_a_light_color_gets_black_text(self, admin: TestClient) -> None:
        body = admin.patch(URL, json={"primary_color": "#facc15"}).json()
        assert body["primary_foreground"] == "#000000"

    def test_leaving_it_out_keeps_the_color(self, admin: TestClient) -> None:
        admin.patch(URL, json={"primary_color": "#b91c1c"})
        body = admin.patch(URL, json={"name": "Café Aurora"}).json()
        assert body["primary_color"] == "#b91c1c"

    def test_null_goes_back_to_member_plus_blue(
        self, admin: TestClient, session: Session, two_businesses
    ) -> None:
        admin.patch(URL, json={"primary_color": "#b91c1c"})
        body = admin.patch(URL, json={"primary_color": None}).json()
        assert (body["primary_color"], body["primary_foreground"]) == (None, None)
        assert stored(session, two_businesses).primary_color is None

    @pytest.mark.parametrize(
        "color", ["", "0062f2", "#fff", "#0062f2ff", "#gg0000", "red", " #0062f2", 255]
    )
    def test_invalid_color_is_422(
        self, admin: TestClient, session: Session, two_businesses, color: object
    ) -> None:
        assert admin.patch(URL, json={"primary_color": color}).status_code == 422
        assert stored(session, two_businesses).primary_color is None

    def test_employee_sees_the_color_but_cannot_change_it(
        self, admin: TestClient, client: TestClient
    ) -> None:
        admin.patch(URL, json={"primary_color": "#b91c1c"})
        client.cookies.clear()
        login(client, "employee.a@demo.mx")
        assert client.get(ME_URL).json()["business"]["primary_color"] == "#b91c1c"
        assert client.patch(URL, json={"primary_color": "#000000"}).status_code == 403


class TestPermissions:
    def test_employee_is_403(self, client: TestClient, two_businesses) -> None:
        login(client, "employee.a@demo.mx")
        assert client.patch(URL, json={"name": "Otro"}).status_code == 403

    def test_platform_is_403(self, client: TestClient, two_businesses) -> None:
        login(client, "owner@memberplus.mx")
        assert client.patch(URL, json={"name": "Otro"}).status_code == 403

    def test_without_session_is_401(self, client: TestClient) -> None:
        assert client.patch(URL, json={"name": "Otro"}).status_code == 401
