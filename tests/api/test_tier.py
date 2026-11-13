"""/api/v1/tier: list and edit the tiers of a business (API contract, section 4)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from models import Business, Tier, TierFinish
from tests.conftest import login

BASE = "/api/v1/tier"


def add_tier(
    session: Session,
    business: Business,
    name: str,
    min_points: int,
    finish: TierFinish = TierFinish.BRONZE,
    discount: str = "0",
    points: int = 1,
    cashback: str = "0",
) -> Tier:
    tier = Tier(
        business_id=business.id,
        name=name,
        finish=finish,
        min_points=min_points,
        discount_percent=Decimal(discount),
        points_per_ten=points,
        cashback_percent=Decimal(cashback),
    )
    session.add(tier)
    session.commit()
    session.refresh(tier)
    return tier


@pytest.fixture
def tiers(session: Session, two_businesses) -> dict[str, Tier]:
    """Business A: Bronce (0), Oro (1000), Plata (400), inserted out of order."""
    business = two_businesses["business_a"]
    return {
        "bronce": add_tier(session, business, "Bronce", 0, discount="5"),
        "oro": add_tier(session, business, "Oro", 1000, TierFinish.GOLD, "15", 1, "3"),
        "plata": add_tier(session, business, "Plata", 400, TierFinish.SILVER, "10", 1, "1"),
    }


def patch(client: TestClient, tier: Tier, **changes):
    return client.patch(f"{BASE}/{tier.id}/update", json=changes)


class TestList:
    def test_ordered_by_min_points(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.get(f"{BASE}/list")
        assert response.status_code == 200
        assert [t["name"] for t in response.json()] == ["Bronce", "Plata", "Oro"]

    def test_shape_matches_the_contract(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        gold = client.get(f"{BASE}/list").json()[2]
        assert gold == {
            "id": tiers["oro"].id,
            "name": "Oro",
            "finish": "gold",
            "min_points": 1000,
            "discount_percent": 15,
            "points_per_ten": 1,
            "cashback_percent": 3,
            "customers_count": 0,
        }

    def test_percents_are_json_numbers(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        tier = client.get(f"{BASE}/list").json()[0]
        assert isinstance(tier["discount_percent"], float)
        assert isinstance(tier["cashback_percent"], float)

    def test_employee_can_read_the_tiers(self, client: TestClient, tiers) -> None:
        # The checkout shows the benefits of the customer's tier.
        login(client, "employee.a@demo.mx")
        assert client.get(f"{BASE}/list").status_code == 200

    def test_business_without_tiers_gets_empty_list(self, client: TestClient, tiers) -> None:
        login(client, "admin.b@demo.mx")
        assert client.get(f"{BASE}/list").json() == []

    def test_platform_cannot_read_tiers(self, client: TestClient, tiers) -> None:
        login(client, "owner@memberplus.mx")
        assert client.get(f"{BASE}/list").status_code == 403

    def test_requires_session(self, client: TestClient) -> None:
        response = client.get(f"{BASE}/list")
        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"


class TestUpdate:
    def test_updates_every_field(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(
            client,
            tiers["oro"],
            name="Oro Plus",
            finish="onyx",
            min_points=1200,
            discount_percent=17.5,
            points_per_ten=2,
            cashback_percent=4.25,
        )
        assert response.status_code == 200
        assert response.json() == {
            "id": tiers["oro"].id,
            "name": "Oro Plus",
            "finish": "onyx",
            "min_points": 1200,
            "discount_percent": 17.5,
            "points_per_ten": 2,
            "cashback_percent": 4.25,
            "customers_count": 0,
        }

    def test_change_is_persisted(self, client: TestClient, session: Session, tiers) -> None:
        login(client, "admin.a@demo.mx")
        patch(client, tiers["plata"], discount_percent=12)
        session.expire_all()
        assert session.get(Tier, tiers["plata"].id).discount_percent == Decimal("12")

    def test_only_sent_fields_change(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        body = patch(client, tiers["plata"], cashback_percent=2).json()
        assert (body["name"], body["min_points"], body["discount_percent"]) == ("Plata", 400, 10)

    def test_null_means_not_sent(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(client, tiers["plata"], name=None, discount_percent=None)
        assert response.status_code == 200
        assert response.json()["name"] == "Plata"

    def test_name_is_trimmed(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        assert patch(client, tiers["oro"], name="  Oro   VIP ").json()["name"] == "Oro VIP"

    def test_zero_disables_a_benefit(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(
            client, tiers["oro"], discount_percent=0, points_per_ten=0, cashback_percent=0
        )
        assert response.status_code == 200

    def test_limits_are_accepted(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(client, tiers["oro"], discount_percent=100, cashback_percent=100)
        assert response.status_code == 200

    def test_employee_cannot_update(self, client: TestClient, tiers) -> None:
        login(client, "employee.a@demo.mx")
        assert patch(client, tiers["oro"], discount_percent=50).status_code == 403

    def test_platform_cannot_update(self, client: TestClient, tiers) -> None:
        login(client, "owner@memberplus.mx")
        assert patch(client, tiers["oro"], discount_percent=50).status_code == 403

    def test_unknown_tier_is_404(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(f"{BASE}/999999/update", json={"name": "X"})
        assert response.status_code == 404
        assert response.json() == {"detail": "Tier not found"}

    def test_unknown_finish_keeps_fastapi_shape(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(client, tiers["oro"], finish="platinum")
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


class TestUpdateValidation:
    """Out-of-range values answer 422 with `code: tier_invalid` and change nothing."""

    @pytest.mark.parametrize(
        "changes",
        [
            {"discount_percent": -1},
            {"discount_percent": 100.01},
            {"discount_percent": 12.345},
            {"cashback_percent": -0.5},
            {"cashback_percent": 101},
            {"cashback_percent": 1.001},
            {"points_per_ten": -1},
            {"points_per_ten": 1001},
            {"min_points": -10},
            {"min_points": 1_000_000_001},
            {"name": ""},
            {"name": "   "},
            {"name": "x" * 61},
        ],
    )
    def test_out_of_range_is_tier_invalid(
        self, client: TestClient, session: Session, tiers, changes
    ) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(client, tiers["oro"], **changes)
        assert response.status_code == 422
        assert response.json()["code"] == "tier_invalid"

        session.expire_all()
        unchanged = session.get(Tier, tiers["oro"].id)
        assert (unchanged.name, unchanged.min_points) == ("Oro", 1000)
        assert unchanged.discount_percent == Decimal("15")

    def test_lowest_tier_must_stay_at_zero(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(client, tiers["bronce"], min_points=100)
        assert response.status_code == 422
        assert response.json() == {
            "detail": "The lowest tier must keep min_points = 0",
            "code": "tier_invalid",
        }

    def test_entry_tier_stays_the_entry_tier(self, client: TestClient, tiers) -> None:
        # One PATCH changes one tier, so the tier at 0 cannot hand that role to another:
        # Plata cannot take 0 (Bronce has it) and Bronce cannot leave 0. Others move freely.
        login(client, "admin.a@demo.mx")
        assert patch(client, tiers["plata"], min_points=0).status_code == 422
        assert patch(client, tiers["bronce"], min_points=200).status_code == 422
        assert patch(client, tiers["oro"], min_points=500).status_code == 200

    def test_two_tiers_cannot_share_min_points(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = patch(client, tiers["oro"], min_points=400)
        assert response.status_code == 422
        assert response.json()["code"] == "tier_invalid"

    def test_keeping_its_own_min_points_is_fine(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        assert patch(client, tiers["oro"], min_points=1000).status_code == 200


class TestDatabaseConstraints:
    """Last line of defense if a bug or a script skips the service."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("min_points", -1),
            ("points_per_ten", -1),
            ("discount_percent", Decimal("101")),
            ("cashback_percent", Decimal("-1")),
        ],
    )
    def test_out_of_range_is_rejected(self, session: Session, two_businesses, field, value) -> None:
        tier = Tier(business_id=two_businesses["business_a"].id, name="Bad", finish="gold")
        setattr(tier, field, value)
        session.add(tier)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
