"""/api/v1/movement: purchase history with totals and CSV export (API contract, section 6)."""

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Purchase, Tier, TierFinish
from services.customer_service import as_utc
from services.movement_service import pesos, safe_cell
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

BASE = "/api/v1/movement"
NOW = datetime.now(UTC)


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
def people(session: Session, two_businesses, gold) -> dict:
    business = two_businesses["business_a"]
    cashier = two_businesses["employee_a"]
    cashier.name = "Luis Pérez"
    session.add(cashier)
    session.commit()
    return {
        "laura": add_customer(session, business, gold, "Laura Méndez", code="MP-4F7K2"),
        "ricardo": add_customer(session, business, gold, "Ricardo Flores", code="MP-6QXZ9"),
    }


def charge(
    client: TestClient, session: Session, customer_id: int, amount: int, days_ago: int, **extra
) -> int:
    """Charge through the real checkout, then move the purchase back in time."""
    response = client.post(
        "/api/v1/checkout/create",
        json={"customer_id": customer_id, "amount_cents": amount, **extra},
    )
    assert response.status_code == 201, response.text
    purchase = session.get(Purchase, response.json()["id"])
    purchase.created_at = NOW - timedelta(days=days_ago)
    session.add(purchase)
    session.commit()
    return purchase.id


@pytest.fixture
def history(client: TestClient, session: Session, people) -> dict:
    """Three purchases charged by the cashier: Laura 30 and 2 days ago, Ricardo 10."""
    login(client, "employee.a@demo.mx")
    ids = {
        "laura_old": charge(client, session, people["laura"].id, 100_000, 30, concept="Café"),
        "ricardo": charge(client, session, people["ricardo"].id, 20_000, 10),
        "laura_new": charge(
            client, session, people["laura"].id, 25_000, 2, concept="Desayuno", use_cashback=True
        ),
    }
    login(client, "admin.a@demo.mx")
    return ids


def ids_of(response) -> list[int]:
    return [item["id"] for item in response.json()["items"]]


class TestList:
    def test_movement_has_the_contract_shape(self, client: TestClient, people, history) -> None:
        response = client.get(f"{BASE}/list", params={"customer_id": people["ricardo"].id})
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item.pop("created_at").endswith(("Z", "+00:00"))
        assert item == {
            "id": history["ricardo"],
            "customer": {
                "id": people["ricardo"].id,
                "full_name": "Ricardo Flores",
                "code": "MP-6QXZ9",
            },
            "cashier_name": "Luis Pérez",
            "card_status": "active",
            "concept": None,
            "amount_cents": 20_000,
            "discount_percent": 15.0,
            "discount_cents": 3_000,
            "cashback_used_cents": 0,
            "total_cents": 17_000,
            "points_delta": 17,
            "cashback_earned_cents": 510,
        }

    def test_movement_id_is_the_receipt_id(self, client: TestClient, history) -> None:
        receipt = client.get(f"/api/v1/checkout/{history['laura_new']}").json()
        movement = next(
            item
            for item in client.get(f"{BASE}/list").json()["items"]
            if item["id"] == history["laura_new"]
        )
        assert movement["total_cents"] == receipt["total_cents"]
        assert movement["points_delta"] == receipt["points_earned"]

    def test_newest_first(self, client: TestClient, history) -> None:
        response = client.get(f"{BASE}/list")
        assert ids_of(response) == [history["laura_new"], history["ricardo"], history["laura_old"]]

    def test_summary_covers_the_whole_filtered_set(self, client: TestClient, history) -> None:
        body = client.get(f"{BASE}/list", params={"page_size": 1}).json()
        assert (body["total"], len(body["items"])) == (3, 1)
        # Laura 85 000 + Ricardo 17 000 + Laura 21 250 base minus 2 550 cashback used.
        assert body["summary"] == {
            "count": 3,
            "collected_cents": 85_000 + 17_000 + 18_700,
            "discount_cents": 15_000 + 3_000 + 3_750,
            "cashback_used_cents": 2_550,
        }

    def test_without_purchases_summary_is_zero(self, client: TestClient, people) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(f"{BASE}/list").json()
        assert body == {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 8,
            "summary": {
                "count": 0,
                "collected_cents": 0,
                "discount_cents": 0,
                "cashback_used_cents": 0,
            },
        }

    def test_filter_by_customer(self, client: TestClient, people, history) -> None:
        response = client.get(f"{BASE}/list", params={"customer_id": people["laura"].id})
        assert ids_of(response) == [history["laura_new"], history["laura_old"]]
        assert response.json()["summary"]["count"] == 2

    @pytest.mark.parametrize("q", ["ricardo", "FLORES", "mp-6qx"])
    def test_q_searches_name_or_code(self, client: TestClient, history, q: str) -> None:
        assert ids_of(client.get(f"{BASE}/list", params={"q": q})) == [history["ricardo"]]

    def test_q_does_not_search_email(self, client: TestClient, history) -> None:
        assert ids_of(client.get(f"{BASE}/list", params={"q": "@correo.com"})) == []

    def test_date_range_is_inclusive(self, client: TestClient, session: Session, history) -> None:
        ricardo = session.get(Purchase, history["ricardo"])
        # Naive on purpose: a date without time zone is read as UTC.
        moment = as_utc(ricardo.created_at).replace(tzinfo=None).isoformat()
        response = client.get(f"{BASE}/list", params={"from": moment, "to": moment})
        assert ids_of(response) == [history["ricardo"]]

    def test_last_seven_days(self, client: TestClient, history) -> None:
        since = (NOW - timedelta(days=7)).isoformat()
        response = client.get(f"{BASE}/list", params={"from": since})
        assert ids_of(response) == [history["laura_new"]]
        assert response.json()["summary"]["collected_cents"] == 18_700

    def test_page_past_the_end_returns_the_last(self, client: TestClient, history) -> None:
        body = client.get(f"{BASE}/list", params={"page": 9, "page_size": 2}).json()
        assert body["page"] == 2
        assert [item["id"] for item in body["items"]] == [history["laura_old"]]

    def test_unknown_customer_is_an_empty_list(self, client: TestClient, history) -> None:
        body = client.get(f"{BASE}/list", params={"customer_id": 999_999}).json()
        assert (body["items"], body["summary"]["count"]) == ([], 0)

    @pytest.mark.parametrize(
        "params", [{"page": 0}, {"page_size": 501}, {"from": "ayer"}, {"q": "x" * 121}]
    )
    def test_invalid_params_are_422(self, client: TestClient, history, params: dict) -> None:
        assert client.get(f"{BASE}/list", params=params).status_code == 422


class TestExport:
    def rows(self, response) -> list[list[str]]:
        text = response.content.decode("utf-8")
        assert text.startswith("﻿")
        return list(csv.reader(io.StringIO(text.removeprefix("﻿"))))

    def test_csv_download(self, client: TestClient, history) -> None:
        response = client.get(f"{BASE}/export")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        disposition = response.headers["content-disposition"]
        assert disposition.startswith('attachment; filename="movimientos-')
        assert disposition.endswith('.csv"')

    def test_columns_and_amounts_in_pesos(self, client: TestClient, history) -> None:
        header, *rows = self.rows(client.get(f"{BASE}/export"))
        assert header == [
            "Fecha",
            "Cajero",
            "Cliente",
            "Código",
            "Concepto",
            "Monto",
            "Descuento",
            "Total",
            "Puntos",
            "Cashback ganado",
            "Cashback usado",
        ]
        assert len(rows) == 3
        oldest = rows[-1]
        assert oldest[0].endswith("Z")
        assert oldest[1:] == [
            "Luis Pérez",
            "Laura Méndez",
            "MP-4F7K2",
            "Café",
            "1000.00",
            "150.00",
            "850.00",
            "85",
            "25.50",
            "0.00",
        ]

    def test_same_filters_as_list_and_no_pagination(
        self, client: TestClient, people, history
    ) -> None:
        params = {"customer_id": people["laura"].id, "page_size": 1}
        _, *rows = self.rows(client.get(f"{BASE}/export", params=params))
        assert [row[4] for row in rows] == ["Desayuno", "Café"]

    def test_empty_export_has_only_the_header(self, client: TestClient, people) -> None:
        login(client, "admin.a@demo.mx")
        assert len(self.rows(client.get(f"{BASE}/export"))) == 1

    def test_formulas_are_neutralized(self, client: TestClient, session: Session, people) -> None:
        login(client, "admin.a@demo.mx")
        charge(client, session, people["laura"].id, 1_000, 1, concept='=HYPERLINK("x")')
        _, row = self.rows(client.get(f"{BASE}/export"))
        assert row[4] == '\'=HYPERLINK("x")'


class TestHelpers:
    @pytest.mark.parametrize(
        ("cents", "text"),
        [(0, "0.00"), (5, "0.05"), (2_550, "25.50"), (100_000, "1000.00"), (-150, "-1.50")],
    )
    def test_pesos(self, cents: int, text: str) -> None:
        assert pesos(cents) == text

    @pytest.mark.parametrize(
        ("value", "cell"),
        [
            (None, ""),
            ("", ""),
            ("Café", "Café"),
            ("=1+1", "'=1+1"),
            ("+52", "'+52"),
            ("-x", "'-x"),
            ("@a", "'@a"),
        ],
    )
    def test_safe_cell(self, value: str | None, cell: str) -> None:
        assert safe_cell(value) == cell


class TestPermissions:
    @pytest.mark.parametrize("email", ["employee.a@demo.mx", "owner@memberplus.mx"])
    @pytest.mark.parametrize("action", ["list", "export"])
    def test_only_admin(self, client: TestClient, two_businesses, email: str, action: str) -> None:
        login(client, email)
        assert client.get(f"{BASE}/{action}").status_code == 403

    @pytest.mark.parametrize("action", ["list", "export"])
    def test_without_session_is_401(self, client: TestClient, action: str) -> None:
        assert client.get(f"{BASE}/{action}").status_code == 401
