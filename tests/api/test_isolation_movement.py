"""Mandatory MVP test for movements: one business never sees another's history."""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import TierFinish
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

BASE = "/api/v1/movement"


@pytest.fixture
def data(client: TestClient, session: Session, two_businesses) -> dict:
    tier_a = add_tier(session, two_businesses["business_a"], "Oro A", 0, finish=TierFinish.GOLD)
    tier_b = add_tier(session, two_businesses["business_b"], "Oro B", 0, finish=TierFinish.GOLD)
    a = add_customer(session, two_businesses["business_a"], tier_a, "Cliente Alfa", code="MP-AAAAA")
    b = add_customer(session, two_businesses["business_b"], tier_b, "Cliente Beta", code="MP-BBBBB")
    login(client, "admin.b@demo.mx")
    client.post("/api/v1/checkout/create", json={"customer_id": b.id, "amount_cents": 50_000})
    login(client, "admin.a@demo.mx")
    client.post("/api/v1/checkout/create", json={"customer_id": a.id, "amount_cents": 10_000})
    return {"a": a, "b": b}


def test_list_shows_zero_rows_of_the_other_business(client: TestClient, data) -> None:
    body = client.get(f"{BASE}/list").json()
    assert [item["customer"]["code"] for item in body["items"]] == ["MP-AAAAA"]
    assert body["summary"]["count"] == 1
    assert body["summary"]["collected_cents"] == 10_000


def test_filtering_by_a_customer_of_the_other_business_finds_nothing(
    client: TestClient, data
) -> None:
    body = client.get(f"{BASE}/list", params={"customer_id": data["b"].id}).json()
    assert (body["items"], body["summary"]["count"]) == ([], 0)
    assert client.get(f"{BASE}/list", params={"q": "Beta"}).json()["items"] == []


def test_export_has_zero_rows_of_the_other_business(client: TestClient, data) -> None:
    text = client.get(f"{BASE}/export").content.decode("utf-8").removeprefix("﻿")
    _, *rows = list(csv.reader(io.StringIO(text)))
    assert [row[3] for row in rows] == ["MP-AAAAA"]
    params = {"customer_id": data["b"].id}
    text = client.get(f"{BASE}/export", params=params).content.decode("utf-8")
    assert len(list(csv.reader(io.StringIO(text.removeprefix("﻿"))))) == 1
