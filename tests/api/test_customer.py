"""/api/v1/customer: customers and their card (API contract, section 3)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Business, Customer, Tier, TierFinish
from services.customer_service import VALIDITY_MONTHS, add_months
from tests.conftest import login

BASE = "/api/v1/customer"


def add_tier(session: Session, business: Business, name: str, price: int, **benefits) -> Tier:
    tier = Tier(
        business_id=business.id,
        name=name,
        finish=benefits.pop("finish", TierFinish.BRONZE),
        price_cents=price,
        discount_percent=Decimal(benefits.pop("discount", "0")),
        points_per_ten=benefits.pop("points", 1),
        cashback_percent=Decimal(benefits.pop("cashback", "0")),
    )
    session.add(tier)
    session.commit()
    session.refresh(tier)
    return tier


def add_customer(
    session: Session,
    business: Business,
    tier: Tier,
    name: str,
    *,
    code: str,
    issued_days_ago: int = 10,
    cancelled: bool = False,
) -> Customer:
    now = datetime.now(UTC)
    issued_at = now - timedelta(days=issued_days_ago)
    customer = Customer(
        business_id=business.id,
        tier_id=tier.id,
        code=code,
        full_name=name,
        email=f"{code.lower()}@correo.com",
        issued_at=issued_at,
        valid_until=add_months(issued_at, VALIDITY_MONTHS),
        cancelled_at=now if cancelled else None,
    )
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


@pytest.fixture
def tiers(session: Session, two_businesses) -> dict[str, Tier]:
    business = two_businesses["business_a"]
    return {
        "gold": add_tier(
            session, business, "Oro", 39_900, finish=TierFinish.GOLD, discount="15", cashback="3"
        ),
        "bronze": add_tier(session, business, "Bronce", 0, discount="5"),
    }


@pytest.fixture
def customers(session: Session, two_businesses, tiers) -> dict[str, Customer]:
    """Business A: one customer per status."""
    business = two_businesses["business_a"]
    return {
        "active": add_customer(session, business, tiers["gold"], "Laura Méndez", code="MP-4F7K2"),
        "expiring": add_customer(
            session,
            business,
            tiers["bronze"],
            "Carlos Ramírez",
            code="MP-7H3QX",
            issued_days_ago=350,
        ),
        "expired": add_customer(
            session,
            business,
            tiers["bronze"],
            "Ricardo Flores",
            code="MP-6QXZ9",
            issued_days_ago=400,
        ),
        "cancelled": add_customer(
            session, business, tiers["gold"], "Daniela Vega", code="MP-4YGK8", cancelled=True
        ),
    }


def new_customer(**overrides) -> dict:
    return {"full_name": "Sofía Hernández", "email": "sofia@correo.com", **overrides}


class TestCreate:
    def test_creates_with_the_contract_shape(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(
            f"{BASE}/create",
            json=new_customer(phone="664 123 4567", level_id=tiers["gold"].id),
        )
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {
            "id",
            "code",
            "full_name",
            "email",
            "phone",
            "level",
            "status",
            "expiring_soon",
            "issued_at",
            "valid_until",
            "points_balance",
            "cashback_balance_cents",
            "benefits",
            "last_purchase_at",
        }
        assert body["level"] == {"id": tiers["gold"].id, "name": "Oro", "finish": "gold"}
        assert body["benefits"] == {
            "discount_percent": 15,
            "points_per_ten": 1,
            "cashback_percent": 3,
        }
        assert (body["status"], body["expiring_soon"]) == ("active", False)
        assert (body["points_balance"], body["cashback_balance_cents"]) == (0, 0)
        assert body["last_purchase_at"] is None
        assert body["phone"] == "664 123 4567"

    def test_code_is_short_and_typeable(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        code = client.post(f"{BASE}/create", json=new_customer()).json()["code"]
        assert code.startswith("MP-") and len(code) == 8
        assert not set(code[3:]) & set("01OIL")

    def test_card_is_valid_for_twelve_months(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.post(f"{BASE}/create", json=new_customer()).json()
        issued = datetime.fromisoformat(body["issued_at"])
        assert datetime.fromisoformat(body["valid_until"]) == add_months(issued, 12)

    def test_dates_are_utc(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.post(f"{BASE}/create", json=new_customer()).json()
        assert datetime.fromisoformat(body["issued_at"]).utcoffset() == timedelta(0)

    def test_without_level_gets_the_cheapest_tier(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.post(f"{BASE}/create", json=new_customer()).json()
        assert body["level"]["name"] == "Bronce"

    def test_email_is_stored_lowercase(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.post(f"{BASE}/create", json=new_customer(email="Sofia@Correo.com")).json()
        assert body["email"] == "sofia@correo.com"

    def test_duplicate_email_is_email_taken(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        client.post(f"{BASE}/create", json=new_customer())
        response = client.post(f"{BASE}/create", json=new_customer(email="SOFIA@correo.com"))
        assert response.status_code == 409
        assert response.json() == {"detail": "Email already in use", "code": "email_taken"}

    def test_same_email_in_another_business_is_fine(
        self, client: TestClient, session: Session, two_businesses, tiers
    ) -> None:
        add_tier(session, two_businesses["business_b"], "Básico", 0)
        login(client, "admin.a@demo.mx")
        client.post(f"{BASE}/create", json=new_customer())
        client.cookies.clear()
        login(client, "admin.b@demo.mx")
        assert client.post(f"{BASE}/create", json=new_customer()).status_code == 201

    def test_unknown_level_is_tier_invalid(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json=new_customer(level_id=999999))
        assert response.status_code == 422
        assert response.json() == {"detail": "Tier not found", "code": "tier_invalid"}

    def test_business_without_tiers_cannot_create(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.b@demo.mx")
        response = client.post(f"{BASE}/create", json=new_customer())
        assert response.status_code == 422
        assert response.json()["code"] == "tier_invalid"

    @pytest.mark.parametrize(
        "changes",
        [{"full_name": "A"}, {"full_name": "Ana2"}, {"email": "no-email"}, {"phone": "abc"}],
    )
    def test_field_validation(self, client: TestClient, tiers, changes) -> None:
        login(client, "admin.a@demo.mx")
        assert client.post(f"{BASE}/create", json=new_customer(**changes)).status_code == 422

    def test_name_is_normalized(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.post(
            f"{BASE}/create", json=new_customer(full_name="  Sofía   Hernández ")
        ).json()
        assert body["full_name"] == "Sofía Hernández"


class TestStatus:
    @pytest.mark.parametrize(
        ("key", "status", "expiring"),
        [
            ("active", "active", False),
            ("expiring", "active", True),
            ("expired", "expired", False),
            ("cancelled", "cancelled", False),
        ],
    )
    def test_status_is_computed(self, client: TestClient, customers, key, status, expiring) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(f"{BASE}/{customers[key].id}").json()
        assert (body["status"], body["expiring_soon"]) == (status, expiring)

    def test_cancelled_wins_over_expired(
        self, client: TestClient, session: Session, two_businesses, tiers
    ) -> None:
        old = add_customer(
            session,
            two_businesses["business_a"],
            tiers["bronze"],
            "Viejo Cancelado",
            code="MP-22222",
            issued_days_ago=500,
            cancelled=True,
        )
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/{old.id}").json()["status"] == "cancelled"


class TestList:
    def test_ordered_by_name(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        names = [c["full_name"] for c in client.get(f"{BASE}/list").json()["items"]]
        assert names == ["Carlos Ramírez", "Daniela Vega", "Laura Méndez", "Ricardo Flores"]

    def test_paginated_shape(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(f"{BASE}/list", params={"page_size": 3}).json()
        assert (body["total"], body["page"], body["page_size"], len(body["items"])) == (4, 1, 3, 3)

    def test_default_page_size_is_eight(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/list").json()["page_size"] == 8

    def test_second_page(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(f"{BASE}/list", params={"page": 2, "page_size": 3}).json()
        assert [c["full_name"] for c in body["items"]] == ["Ricardo Flores"]

    def test_page_past_the_end_returns_the_last(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(f"{BASE}/list", params={"page": 99, "page_size": 3}).json()
        assert body["page"] == 2
        assert len(body["items"]) == 1

    def test_empty_business_is_page_one(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.b@demo.mx")
        body = client.get(f"{BASE}/list", params={"page": 5}).json()
        assert (body["items"], body["total"], body["page"]) == ([], 0, 1)

    @pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 501}])
    def test_bad_pagination_is_422(self, client: TestClient, customers, params) -> None:
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/list", params=params).status_code == 422

    def test_max_page_size_for_the_printable_sheet(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.get(f"{BASE}/list", params={"status": "active", "page_size": 500})
        assert response.status_code == 200

    @pytest.mark.parametrize(
        ("q", "expected"),
        [
            ("laura", ["Laura Méndez"]),
            ("MÉNDEZ", ["Laura Méndez"]),
            ("mp-7h3", ["Carlos Ramírez"]),
            ("6qxz9@correo", ["Ricardo Flores"]),
            ("  vega ", ["Daniela Vega"]),
            ("%", []),
            ("nadie", []),
        ],
    )
    def test_search(self, client: TestClient, customers, q, expected) -> None:
        login(client, "admin.a@demo.mx")
        items = client.get(f"{BASE}/list", params={"q": q}).json()["items"]
        assert [c["full_name"] for c in items] == expected

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("active", ["Carlos Ramírez", "Laura Méndez"]),
            ("expiring", ["Carlos Ramírez"]),
            ("expired", ["Ricardo Flores"]),
            ("cancelled", ["Daniela Vega"]),
        ],
    )
    def test_status_filter(self, client: TestClient, customers, status, expected) -> None:
        login(client, "admin.a@demo.mx")
        items = client.get(f"{BASE}/list", params={"status": status}).json()["items"]
        assert [c["full_name"] for c in items] == expected

    def test_unknown_status_is_422(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/list", params={"status": "vip"}).status_code == 422

    def test_level_filter(self, client: TestClient, customers, tiers) -> None:
        login(client, "admin.a@demo.mx")
        items = client.get(f"{BASE}/list", params={"level_id": tiers["gold"].id}).json()["items"]
        assert [c["full_name"] for c in items] == ["Daniela Vega", "Laura Méndez"]

    def test_filters_combine(self, client: TestClient, customers, tiers) -> None:
        login(client, "admin.a@demo.mx")
        params = {"level_id": tiers["gold"].id, "status": "active", "q": "laura"}
        body = client.get(f"{BASE}/list", params=params).json()
        assert (body["total"], body["items"][0]["full_name"]) == (1, "Laura Méndez")


class TestSummary:
    def test_counts_every_state(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/summary").json() == {
            "all": 4,
            "active": 2,
            "expiring": 1,
            "expired": 1,
            "cancelled": 1,
        }

    def test_summary_matches_the_list_filters(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        summary = client.get(f"{BASE}/summary").json()
        for status in ("active", "expiring", "expired", "cancelled"):
            total = client.get(f"{BASE}/list", params={"status": status}).json()["total"]
            assert total == summary[status]


class TestLookup:
    @pytest.mark.parametrize("code", ["MP-4F7K2", "mp-4f7k2", " MP-4F7K2 ", "MP- 4F7 K2"])
    def test_normalizes_the_code(self, client: TestClient, customers, code) -> None:
        login(client, "employee.a@demo.mx")
        response = client.get(f"{BASE}/lookup", params={"code": code})
        assert response.status_code == 200
        assert response.json()["full_name"] == "Laura Méndez"

    def test_unknown_code_is_customer_not_found(self, client: TestClient, customers) -> None:
        login(client, "employee.a@demo.mx")
        response = client.get(f"{BASE}/lookup", params={"code": "MP-ZZZZZ"})
        assert response.status_code == 404
        assert response.json() == {"detail": "Customer not found", "code": "customer_not_found"}

    @pytest.mark.parametrize(
        ("key", "status"), [("expired", "expired"), ("cancelled", "cancelled")]
    )
    def test_answers_for_expired_and_cancelled_cards(
        self, client: TestClient, customers, key, status
    ) -> None:
        # The counter warns and decides; the lookup does not hide the card.
        login(client, "employee.a@demo.mx")
        body = client.get(f"{BASE}/lookup", params={"code": customers[key].code}).json()
        assert body["status"] == status

    def test_requires_the_code(self, client: TestClient, customers) -> None:
        login(client, "employee.a@demo.mx")
        assert client.get(f"{BASE}/lookup").status_code == 422


class TestDetail:
    def test_returns_the_customer(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(f"{BASE}/{customers['active'].id}").json()
        assert (body["code"], body["full_name"]) == ("MP-4F7K2", "Laura Méndez")

    def test_unknown_is_customer_not_found(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.get(f"{BASE}/999999")
        assert response.status_code == 404
        assert response.json()["code"] == "customer_not_found"


class TestUpdate:
    def test_updates_personal_data(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            f"{BASE}/{customers['active'].id}/update",
            json={
                "full_name": "Laura Méndez López",
                "email": "LAURA@nuevo.com",
                "phone": "664 000 1111",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert (body["full_name"], body["email"], body["phone"]) == (
            "Laura Méndez López",
            "laura@nuevo.com",
            "664 000 1111",
        )

    def test_changes_the_tier_and_its_benefits(self, client: TestClient, customers, tiers) -> None:
        login(client, "admin.a@demo.mx")
        body = client.patch(
            f"{BASE}/{customers['active'].id}/update", json={"level_id": tiers["bronze"].id}
        ).json()
        assert body["level"]["name"] == "Bronce"
        assert body["benefits"]["discount_percent"] == 5

    def test_code_and_dates_do_not_change(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        before = client.get(f"{BASE}/{customers['active'].id}").json()
        after = client.patch(
            f"{BASE}/{customers['active'].id}/update", json={"full_name": "Otra Persona"}
        ).json()
        for field in ("code", "issued_at", "valid_until"):
            assert after[field] == before[field]

    def test_phone_can_be_cleared(self, client: TestClient, session: Session, customers) -> None:
        customer = customers["active"]
        customer.phone = "664 123 4567"
        session.add(customer)
        session.commit()
        login(client, "admin.a@demo.mx")
        body = client.patch(f"{BASE}/{customer.id}/update", json={"phone": None}).json()
        assert body["phone"] is None

    def test_null_required_fields_are_ignored(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            f"{BASE}/{customers['active'].id}/update",
            json={"full_name": None, "email": None, "level_id": None},
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "Laura Méndez"

    def test_taken_email_is_email_taken(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            f"{BASE}/{customers['active'].id}/update",
            json={"email": customers["expired"].email.upper()},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "email_taken"

    def test_keeping_its_own_email_is_fine(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        customer = customers["active"]
        response = client.patch(f"{BASE}/{customer.id}/update", json={"email": customer.email})
        assert response.status_code == 200

    def test_unknown_level_is_tier_invalid(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            f"{BASE}/{customers['active'].id}/update", json={"level_id": 999999}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "tier_invalid"

    def test_unknown_customer_is_404(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(f"{BASE}/999999/update", json={"full_name": "Nadie Aquí"})
        assert response.status_code == 404


class TestCancel:
    def test_cancels(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/{customers['active'].id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    def test_is_irreversible_and_idempotent(
        self, client: TestClient, session: Session, customers
    ) -> None:
        login(client, "admin.a@demo.mx")
        customer = customers["cancelled"]
        first = customer.cancelled_at
        assert client.post(f"{BASE}/{customer.id}/cancel").json()["status"] == "cancelled"
        session.expire_all()
        assert session.get(Customer, customer.id).cancelled_at == first

    def test_unknown_customer_is_404(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        assert client.post(f"{BASE}/999999/cancel").status_code == 404


class TestPermissions:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/list"),
            ("get", "/summary"),
            ("get", "/{id}"),
            ("post", "/create"),
            ("patch", "/{id}/update"),
            ("post", "/{id}/cancel"),
        ],
    )
    def test_employee_only_looks_up(self, client: TestClient, customers, method, path) -> None:
        login(client, "employee.a@demo.mx")
        url = BASE + path.format(id=customers["active"].id)
        response = getattr(client, method)(url, **({"json": {}} if method != "get" else {}))
        assert response.status_code == 403

    def test_platform_cannot_look_up(self, client: TestClient, customers) -> None:
        login(client, "owner@memberplus.mx")
        response = client.get(f"{BASE}/lookup", params={"code": "MP-4F7K2"})
        assert response.status_code == 403

    def test_platform_cannot_list(self, client: TestClient, customers) -> None:
        login(client, "owner@memberplus.mx")
        assert client.get(f"{BASE}/list").status_code == 403

    def test_requires_session(self, client: TestClient) -> None:
        response = client.get(f"{BASE}/lookup", params={"code": "MP-4F7K2"})
        assert response.status_code == 401


class TestTierCount:
    def test_tiers_count_non_cancelled_customers(self, client: TestClient, customers) -> None:
        login(client, "admin.a@demo.mx")
        counts = {t["name"]: t["customers_count"] for t in client.get("/api/v1/tier/list").json()}
        # Oro: Laura (active) counts, Daniela (cancelled) does not. Bronce: expiring + expired.
        assert counts == {"Bronce": 2, "Oro": 1}


class TestCodeAndRaces:
    def test_a_taken_code_is_regenerated(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, customers
    ) -> None:
        from services import customer_service

        codes = iter(["MP-4F7K2", "MP-NEW22"])  # the first one is Laura's
        monkeypatch.setattr(customer_service, "generate_code", lambda: next(codes))
        login(client, "admin.a@demo.mx")
        assert client.post(f"{BASE}/create", json=new_customer()).json()["code"] == "MP-NEW22"

    def test_gives_up_when_every_code_is_taken(
        self, session: Session, monkeypatch: pytest.MonkeyPatch, customers
    ) -> None:
        from services import customer_service

        monkeypatch.setattr(customer_service, "generate_code", lambda: "MP-4F7K2")
        with pytest.raises(RuntimeError, match="unique card code"):
            customer_service._new_code(session, customers["active"].business_id)

    def test_email_race_is_409_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, customers
    ) -> None:
        # Two requests pass the email check at the same time: the unique constraint stops one.
        from services import customer_service

        monkeypatch.setattr(customer_service, "_email_in_use", lambda *args, **kwargs: False)
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json=new_customer(email=customers["active"].email))
        assert response.status_code == 409
        assert response.json()["code"] == "email_taken"
        # The session was rolled back: the API keeps working.
        assert client.get(f"{BASE}/summary").status_code == 200
