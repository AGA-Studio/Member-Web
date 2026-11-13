"""/api/v1/checkout: charge at the counter and the receipt (API contract, section 5)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Purchase, Tier, TierFinish
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

BASE = "/api/v1/checkout"


@pytest.fixture
def gold(session: Session, two_businesses) -> Tier:
    return add_tier(
        session,
        two_businesses["business_a"],
        "Oro",
        39_900,
        finish=TierFinish.GOLD,
        discount="15",
        points=1,
        cashback="3",
    )


@pytest.fixture
def cards(session: Session, two_businesses, gold) -> dict:
    business = two_businesses["business_a"]
    return {
        "active": add_customer(session, business, gold, "Laura Méndez", code="MP-4F7K2"),
        "expired": add_customer(
            session, business, gold, "Ricardo Flores", code="MP-6QXZ9", issued_days_ago=400
        ),
        "cancelled": add_customer(
            session, business, gold, "Daniela Vega", code="MP-4YGK8", cancelled=True
        ),
    }


def charge(client: TestClient, customer_id: int, amount: int = 100_000, **extra):
    headers = extra.pop("headers", None)
    body = {"customer_id": customer_id, "amount_cents": amount, **extra}
    return client.post(f"{BASE}/create", json=body, headers=headers)


class TestCreate:
    def test_rubric_example_returns_the_contract_receipt(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        response = charge(client, cards["active"].id, concept="Café y pan dulce")
        assert response.status_code == 201
        body = response.json()
        assert body.pop("id") > 0
        assert body.pop("created_at").endswith(("Z", "+00:00"))
        assert body == {
            "customer": {"id": cards["active"].id, "full_name": "Laura Méndez", "code": "MP-4F7K2"},
            "level": {"id": cards["active"].tier_id, "name": "Oro", "finish": "gold"},
            "card_status": "active",
            "concept": "Café y pan dulce",
            "amount_cents": 100_000,
            "discount_percent": 15.0,
            "discount_cents": 15_000,
            "cashback_used_cents": 0,
            "total_cents": 85_000,
            "points_earned": 85,
            "cashback_earned_cents": 2_550,
            "points_balance_after": 85,
            "cashback_balance_after_cents": 2_550,
        }

    def test_customer_balances_come_from_the_purchases(self, client: TestClient, cards) -> None:
        login(client, "admin.a@demo.mx")
        charge(client, cards["active"].id)
        charge(client, cards["active"].id, 10_000)
        customer = client.get(f"/api/v1/customer/{cards['active'].id}").json()
        assert (customer["points_balance"], customer["cashback_balance_cents"]) == (93, 2_805)
        assert customer["last_purchase_at"] is not None
        listed = client.get("/api/v1/customer/list", params={"q": "Laura"}).json()["items"][0]
        assert (listed["points_balance"], listed["cashback_balance_cents"]) == (93, 2_805)
        looked = client.get("/api/v1/customer/lookup", params={"code": "MP-4F7K2"}).json()
        assert looked["points_balance"] == 93

    def test_customer_without_purchases_has_zero_balances(self, client: TestClient, cards) -> None:
        login(client, "admin.a@demo.mx")
        customer = client.get(f"/api/v1/customer/{cards['active'].id}").json()
        assert (customer["points_balance"], customer["cashback_balance_cents"]) == (0, 0)
        assert customer["last_purchase_at"] is None

    def test_use_cashback_spends_the_balance(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        charge(client, cards["active"].id)  # earns 2550
        body = charge(client, cards["active"].id, 10_000, use_cashback=True).json()
        assert (body["cashback_used_cents"], body["total_cents"]) == (2_550, 5_950)
        assert (body["points_earned"], body["cashback_earned_cents"]) == (8, 255)
        assert (body["points_balance_after"], body["cashback_balance_after_cents"]) == (93, 255)

    def test_cashback_used_is_capped_at_the_base(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        charge(client, cards["active"].id, 1_000_000)  # earns 25500
        body = charge(client, cards["active"].id, 1_000, use_cashback=True).json()
        assert (body["cashback_used_cents"], body["total_cents"]) == (850, 0)
        assert body["cashback_balance_after_cents"] == 25_500 - 850 + 26

    def test_use_cashback_without_balance_spends_nothing(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        body = charge(client, cards["active"].id, use_cashback=True).json()
        assert (body["cashback_used_cents"], body["total_cents"]) == (0, 85_000)

    @pytest.mark.parametrize("card", ["expired", "cancelled"])
    def test_expired_or_cancelled_card_pays_full_and_earns_nothing(
        self, client: TestClient, cards, card
    ) -> None:
        login(client, "employee.a@demo.mx")
        body = charge(client, cards[card].id, use_cashback=True).json()
        assert body["card_status"] == card
        assert (body["discount_percent"], body["discount_cents"], body["total_cents"]) == (
            0,
            0,
            100_000,
        )
        assert (body["points_earned"], body["cashback_earned_cents"]) == (0, 0)
        assert body["cashback_used_cents"] == 0

    def test_admin_can_charge_too(self, client: TestClient, cards) -> None:
        login(client, "admin.a@demo.mx")
        assert charge(client, cards["active"].id).status_code == 201

    def test_cashier_comes_from_the_token(
        self, client: TestClient, session: Session, cards, two_businesses
    ) -> None:
        login(client, "employee.a@demo.mx")
        receipt_id = charge(client, cards["active"].id).json()["id"]
        assert session.get(Purchase, receipt_id).cashier_id == two_businesses["employee_a"].id


class TestValidation:
    @pytest.mark.parametrize("amount", [0, -100, 100_000_001])
    def test_amount_out_of_range_is_amount_invalid(self, client: TestClient, cards, amount) -> None:
        login(client, "employee.a@demo.mx")
        response = charge(client, cards["active"].id, amount)
        assert response.status_code == 422
        assert response.json()["code"] == "amount_invalid"

    @pytest.mark.parametrize("amount", [100.5, "mil", None])
    def test_amount_must_be_an_integer(self, client: TestClient, cards, amount) -> None:
        login(client, "employee.a@demo.mx")
        response = charge(client, cards["active"].id, amount)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_concept_is_cleaned_and_blank_is_null(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        assert charge(client, cards["active"].id, concept="  Café   y pan ").json()["concept"] == (
            "Café y pan"
        )
        assert charge(client, cards["active"].id, concept="   ").json()["concept"] is None

    def test_concept_longer_than_120_is_rejected(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        assert charge(client, cards["active"].id, concept="x" * 121).status_code == 422

    def test_unknown_customer_is_customer_not_found(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        response = charge(client, 999_999)
        assert response.status_code == 404
        assert response.json()["code"] == "customer_not_found"

    def test_nothing_is_saved_when_it_fails(
        self, client: TestClient, session: Session, cards
    ) -> None:
        login(client, "employee.a@demo.mx")
        charge(client, cards["active"].id, 0)
        charge(client, 999_999)
        assert session.exec(select(Purchase)).all() == []


class TestReceipt:
    def test_get_returns_the_same_receipt(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        created = charge(client, cards["active"].id).json()
        assert client.get(f"{BASE}/{created['id']}").json() == created

    def test_admin_reads_every_receipt_of_the_business(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        receipt_id = charge(client, cards["active"].id).json()["id"]
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/{receipt_id}").status_code == 200

    def test_cashier_cannot_read_someone_elses_receipt(
        self, client: TestClient, cards, make_user, two_businesses
    ) -> None:
        login(client, "admin.a@demo.mx")
        receipt_id = charge(client, cards["active"].id).json()["id"]
        login(client, "employee.a@demo.mx")
        response = client.get(f"{BASE}/{receipt_id}")
        assert response.status_code == 404
        assert response.json()["code"] == "checkout_not_found"

    def test_unknown_receipt_is_checkout_not_found(self, client: TestClient, cards) -> None:
        login(client, "admin.a@demo.mx")
        response = client.get(f"{BASE}/999999")
        assert (response.status_code, response.json()["code"]) == (404, "checkout_not_found")

    def test_receipt_keeps_the_tier_applied_then(
        self, client: TestClient, session: Session, cards, gold
    ) -> None:
        login(client, "admin.a@demo.mx")
        receipt_id = charge(client, cards["active"].id).json()["id"]
        tier = session.get(Tier, gold.id)
        tier.name, tier.discount_percent = "Oro Plus", Decimal("40")
        session.add(tier)
        session.commit()
        receipt = client.get(f"{BASE}/{receipt_id}").json()
        assert (receipt["level"]["name"], receipt["discount_percent"]) == ("Oro", 15.0)
        # New purchases use the edited tier.
        assert charge(client, cards["active"].id).json()["discount_percent"] == 40.0


class TestPreview:
    def test_preview_matches_create_and_saves_nothing(
        self, client: TestClient, session: Session, cards
    ) -> None:
        login(client, "employee.a@demo.mx")
        body = {"customer_id": cards["active"].id, "amount_cents": 100_000}
        preview = client.post(f"{BASE}/preview", json=body)
        assert preview.status_code == 200
        assert session.exec(select(Purchase)).all() == []
        created = client.post(f"{BASE}/create", json=body).json()
        assert all(created[key] == value for key, value in preview.json().items())

    def test_preview_of_expired_card(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        body = {"customer_id": cards["expired"].id, "amount_cents": 5_000}
        preview = client.post(f"{BASE}/preview", json=body).json()
        assert (preview["card_status"], preview["total_cents"]) == ("expired", 5_000)

    def test_preview_validates_like_create(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        bad = client.post(
            f"{BASE}/preview", json={"customer_id": cards["active"].id, "amount_cents": 0}
        )
        assert bad.json()["code"] == "amount_invalid"
        missing = client.post(f"{BASE}/preview", json={"customer_id": 999_999, "amount_cents": 1})
        assert missing.json()["code"] == "customer_not_found"


class TestIdempotency:
    def test_same_key_does_not_charge_twice(
        self, client: TestClient, session: Session, cards
    ) -> None:
        login(client, "employee.a@demo.mx")
        headers = {"Idempotency-Key": "caja-1-0001"}
        first = charge(client, cards["active"].id, headers=headers)
        second = charge(client, cards["active"].id, headers=headers)
        assert second.status_code == 201
        assert second.headers["Idempotent-Replayed"] == "true"
        assert "Idempotent-Replayed" not in first.headers
        assert second.json() == first.json()
        assert len(session.exec(select(Purchase)).all()) == 1

    def test_same_key_with_another_amount_is_a_conflict(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        headers = {"Idempotency-Key": "caja-1-0002"}
        charge(client, cards["active"].id, headers=headers)
        response = charge(client, cards["active"].id, 5_000, headers=headers)
        assert (response.status_code, response.json()["code"]) == (409, "idempotency_conflict")

    def test_different_keys_are_different_purchases(
        self, client: TestClient, session: Session, cards
    ) -> None:
        login(client, "employee.a@demo.mx")
        charge(client, cards["active"].id, headers={"Idempotency-Key": "a"})
        charge(client, cards["active"].id, headers={"Idempotency-Key": "b"})
        charge(client, cards["active"].id)
        assert len(session.exec(select(Purchase)).all()) == 3

    def test_key_longer_than_64_is_rejected(self, client: TestClient, cards) -> None:
        login(client, "employee.a@demo.mx")
        response = charge(client, cards["active"].id, headers={"Idempotency-Key": "k" * 65})
        assert response.status_code == 422

    def test_race_with_the_same_key_returns_the_first_purchase(
        self, client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch, cards
    ) -> None:
        # Two retries pass the key lookup at the same time: the unique constraint stops one.
        from services import checkout_service

        login(client, "employee.a@demo.mx")
        headers = {"Idempotency-Key": "caja-1-0003"}
        first = charge(client, cards["active"].id, headers=headers).json()

        real_by_key = checkout_service._by_key
        lookups = []

        def first_lookup_misses(*args):
            lookups.append(args)
            return None if len(lookups) == 1 else real_by_key(*args)

        monkeypatch.setattr(checkout_service, "_by_key", first_lookup_misses)
        second = charge(client, cards["active"].id, headers=headers)
        assert second.status_code == 201
        assert second.headers["Idempotent-Replayed"] == "true"
        assert second.json()["id"] == first["id"]
        assert len(session.exec(select(Purchase)).all()) == 1


class TestPermissions:
    def test_platform_cannot_charge(self, client: TestClient, cards) -> None:
        login(client, "owner@memberplus.mx")
        assert charge(client, cards["active"].id).status_code == 403
        assert client.get(f"{BASE}/1").status_code == 403

    def test_anonymous_is_401(self, client: TestClient, cards) -> None:
        assert charge(client, cards["active"].id).status_code == 401
        response = client.post(f"{BASE}/preview", json={"customer_id": 1, "amount_cents": 1})
        assert response.status_code == 401
