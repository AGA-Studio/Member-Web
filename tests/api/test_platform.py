"""/api/v1/platform: the platform owner's view of the businesses (API contract, section 7)."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import BusinessStatus, Role
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import DEFAULT_PASSWORD, LOGIN_URL, login

URL = "/api/v1/platform/business/list"
ME_URL = "/api/v1/auth/me"


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
            "logo_url": None,
            "status": "active",
            "customers_count": 1,
            "plan_key": "chain",
            "plan_name": "Cadena",
            "trial_ends_at": None,
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
        # The logo is the business's own image, not data of its customers.
        assert keys == {
            "id",
            "name",
            "logo_url",
            "status",
            "customers_count",
            "plan_key",
            "plan_name",
            "trial_ends_at",
            "created_at",
        }


class TestPermissions:
    @pytest.mark.parametrize("email", ["admin.a@demo.mx", "employee.a@demo.mx"])
    def test_business_users_are_403(self, client: TestClient, two_businesses, email: str) -> None:
        login(client, email)
        assert client.get(URL).status_code == 403

    def test_without_session_is_401(self, client: TestClient) -> None:
        assert client.get(URL).status_code == 401


def names_of(body: dict) -> list[str]:
    return [item["name"] for item in body["items"]]


class TestLogo:
    """The platform list shows each business's logo, with the /auth/me rule."""

    def test_logo_is_a_signed_url(
        self, client: TestClient, session: Session, platform, storage
    ) -> None:
        from tests.conftest import make_image

        login(client, "admin.a@demo.mx")
        client.post("/api/v1/logo/update", files={"file": ("l.png", make_image(), "image/png")})
        client.cookies.clear()
        login(client, "owner@memberplus.mx")
        items = {item["name"]: item for item in client.get(URL).json()["items"]}
        assert "X-Amz-Signature" in items["Business A"]["logo_url"]
        assert items["Business B"]["logo_url"] is None

    def test_external_url_passes_through(
        self, client: TestClient, session: Session, platform
    ) -> None:
        platform["a"].logo_url = "https://cdn.example.mx/a.png"
        session.add(platform["a"])
        session.commit()
        login(client, "owner@memberplus.mx")
        items = {item["name"]: item for item in client.get(URL).json()["items"]}
        assert items["Business A"]["logo_url"] == "https://cdn.example.mx/a.png"

    def test_stored_key_without_storage_is_null(
        self, client: TestClient, session: Session, platform, monkeypatch
    ) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "s3_endpoint_url", "")
        platform["a"].logo_url = "businesses/1/logo/x.webp"
        session.add(platform["a"])
        session.commit()
        login(client, "owner@memberplus.mx")
        items = {item["name"]: item for item in client.get(URL).json()["items"]}
        assert items["Business A"]["logo_url"] is None


def detail_url(business_id: int) -> str:
    return f"/api/v1/platform/business/{business_id}"


def update_url(business_id: int) -> str:
    return f"/api/v1/platform/business/{business_id}/update"


class TestDetail:
    def test_has_the_contract_shape(self, client: TestClient, platform) -> None:
        response = client.get(detail_url(platform["a"].id))
        assert response.status_code == 200
        body = response.json()
        assert body.pop("created_at").endswith(("Z", "+00:00"))
        plan = body.pop("plan")
        assert body == {
            "id": platform["a"].id,
            "name": "Business A",
            "logo_url": None,
            "status": "active",
            "customers_count": 1,
            "plan_key": "chain",
            "plan_name": "Cadena",
            "trial_ends_at": None,
            "validity_months": 12,
            "users_count": 2,
        }
        assert plan["plan"]["key"] == "chain"
        assert plan["usage"]["customers"]["used"] == 1
        assert plan["usage"]["users"]["used"] == 2

    def test_users_count_skips_inactive_users(
        self, client: TestClient, platform, make_user
    ) -> None:
        make_user("old.a@demo.mx", business=platform["a"], role=Role.EMPLOYEE, is_active=False)
        assert client.get(detail_url(platform["a"].id)).json()["users_count"] == 2

    def test_business_without_users_or_cards(self, client: TestClient, platform) -> None:
        body = client.get(detail_url(platform["trial"].id)).json()
        assert (body["status"], body["customers_count"], body["users_count"]) == ("trial", 0, 0)

    def test_unknown_business_is_404(self, client: TestClient, platform) -> None:
        response = client.get(detail_url(999_999))
        assert response.status_code == 404
        assert response.json() == {"detail": "Business not found", "code": "business_not_found"}

    def test_never_exposes_customer_or_user_data(self, client: TestClient, platform) -> None:
        text = client.get(detail_url(platform["a"].id)).text
        for secret in ("Laura", "MP-AAAA1", "@demo.mx", "@correo.com", "points", "cashback"):
            assert secret not in text


class TestUpdate:
    def test_suspend(self, client: TestClient, session: Session, platform) -> None:
        response = client.patch(update_url(platform["a"].id), json={"status": "suspended"})
        assert response.status_code == 200
        assert response.json()["status"] == "suspended"
        session.refresh(platform["a"])
        assert platform["a"].status == BusinessStatus.SUSPENDED

    def test_reactivate(self, client: TestClient, platform) -> None:
        response = client.patch(update_url(platform["suspended"].id), json={"status": "active"})
        assert (response.status_code, response.json()["status"]) == (200, "active")

    def test_trial_can_become_active(self, client: TestClient, platform) -> None:
        response = client.patch(update_url(platform["trial"].id), json={"status": "active"})
        assert response.json()["status"] == "active"

    def test_same_status_is_a_no_op(self, client: TestClient, platform) -> None:
        response = client.patch(update_url(platform["a"].id), json={"status": "active"})
        assert (response.status_code, response.json()["status"]) == (200, "active")

    def test_returns_the_detail(self, client: TestClient, platform) -> None:
        body = client.patch(update_url(platform["a"].id), json={"status": "suspended"}).json()
        assert (body["customers_count"], body["users_count"]) == (1, 2)

    @pytest.mark.parametrize("body", [{"status": "trial"}, {"status": "deleted"}, {}])
    def test_invalid_status_is_422(self, client: TestClient, platform, body: dict) -> None:
        assert client.patch(update_url(platform["a"].id), json=body).status_code == 422

    def test_only_the_status_changes(self, client: TestClient, session: Session, platform) -> None:
        client.patch(
            update_url(platform["a"].id),
            json={"status": "suspended", "name": "Hacked", "validity_months": 1},
        )
        session.refresh(platform["a"])
        assert (platform["a"].name, platform["a"].validity_months) == ("Business A", 12)

    def test_unknown_business_is_404(self, client: TestClient, platform) -> None:
        response = client.patch(update_url(999_999), json={"status": "suspended"})
        assert (response.status_code, response.json()["code"]) == (404, "business_not_found")


class TestSuspensionEffect:
    """H1: a suspended business can't log in and its open sessions stop working."""

    def test_suspending_cuts_open_sessions(self, client: TestClient, platform) -> None:
        admin = TestClient(client.app)
        login(admin, "admin.a@demo.mx")
        assert admin.get(ME_URL).status_code == 200

        client.patch(update_url(platform["a"].id), json={"status": "suspended"})

        response = admin.get(ME_URL)
        assert (response.status_code, response.json()["code"]) == (403, "business_suspended")
        response = TestClient(client.app).post(
            LOGIN_URL, data={"username": "employee.a@demo.mx", "password": DEFAULT_PASSWORD}
        )
        assert (response.status_code, response.json()["code"]) == (403, "business_suspended")

    def test_other_business_keeps_working(self, client: TestClient, platform) -> None:
        client.patch(update_url(platform["a"].id), json={"status": "suspended"})
        other = TestClient(client.app)
        login(other, "admin.b@demo.mx")
        assert other.get(ME_URL).status_code == 200

    def test_reactivating_lets_them_log_in(self, client: TestClient, platform) -> None:
        client.patch(update_url(platform["a"].id), json={"status": "suspended"})
        client.patch(update_url(platform["a"].id), json={"status": "active"})
        admin = TestClient(client.app)
        login(admin, "admin.a@demo.mx")
        assert admin.get(ME_URL).status_code == 200

    def test_platform_owner_is_not_affected(self, client: TestClient, platform) -> None:
        client.patch(update_url(platform["a"].id), json={"status": "suspended"})
        assert client.get(ME_URL).status_code == 200


class TestDetailAndUpdatePermissions:
    @pytest.mark.parametrize("email", ["admin.a@demo.mx", "employee.a@demo.mx"])
    def test_business_users_are_403(self, client: TestClient, two_businesses, email: str) -> None:
        login(client, email)
        business_id = two_businesses["business_a"].id
        assert client.get(detail_url(business_id)).status_code == 403
        response = client.patch(update_url(business_id), json={"status": "suspended"})
        assert response.status_code == 403

    def test_admin_cannot_touch_another_business(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        business_b = two_businesses["business_b"]
        assert client.get(detail_url(business_b.id)).status_code == 403
        response = client.patch(update_url(business_b.id), json={"status": "suspended"})
        assert response.status_code == 403

    def test_without_session_is_401(self, client: TestClient, two_businesses) -> None:
        business_id = two_businesses["business_a"].id
        assert client.get(detail_url(business_id)).status_code == 401
        assert client.patch(update_url(business_id), json={"status": "active"}).status_code == 401


SUMMARY_URL = "/api/v1/platform/business/summary"


class TestSummary:
    def test_has_the_contract_shape(self, client: TestClient, platform) -> None:
        """A and B active, one suspended, one trial; 2 live cards; 4 active business users."""
        response = client.get(SUMMARY_URL)
        assert response.status_code == 200
        assert response.json() == {
            "all": 4,
            "trial": 1,
            "active": 2,
            "suspended": 1,
            "customers_count": 2,
            "users_count": 4,
        }

    def test_skips_inactive_users(self, client: TestClient, platform, make_user) -> None:
        make_user("old.a@demo.mx", business=platform["a"], role=Role.EMPLOYEE, is_active=False)
        assert client.get(SUMMARY_URL).json()["users_count"] == 4

    def test_follows_status_changes(self, client: TestClient, platform) -> None:
        client.patch(update_url(platform["a"].id), json={"status": "suspended"})
        body = client.get(SUMMARY_URL).json()
        assert (body["active"], body["suspended"], body["all"]) == (1, 2, 4)

    def test_empty_platform_is_all_zeros(self, client: TestClient, make_user) -> None:
        make_user("owner@memberplus.mx", business=None, role=Role.PLATFORM)
        login(client, "owner@memberplus.mx")
        assert client.get(SUMMARY_URL).json() == {
            "all": 0,
            "trial": 0,
            "active": 0,
            "suspended": 0,
            "customers_count": 0,
            "users_count": 0,
        }

    def test_is_not_read_as_a_business_id(self, client: TestClient, platform) -> None:
        assert "customers_count" in client.get(SUMMARY_URL).json()
        assert "id" not in client.get(SUMMARY_URL).json()

    def test_never_exposes_customer_or_user_data(self, client: TestClient, platform) -> None:
        text = client.get(SUMMARY_URL).text
        for secret in ("Laura", "MP-AAAA1", "@demo.mx", "Business A", "points", "cashback"):
            assert secret not in text

    @pytest.mark.parametrize("email", ["admin.a@demo.mx", "employee.a@demo.mx"])
    def test_business_users_are_403(self, client: TestClient, two_businesses, email: str) -> None:
        login(client, email)
        assert client.get(SUMMARY_URL).status_code == 403

    def test_without_session_is_401(self, client: TestClient) -> None:
        assert client.get(SUMMARY_URL).status_code == 401
