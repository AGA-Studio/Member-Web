"""GET /api/v1/plan/list: the public plan catalog (issue #70)."""

from fastapi.testclient import TestClient

from tests.conftest import login

URL = "/api/v1/plan/list"


def test_answers_without_a_session(client: TestClient) -> None:
    response = client.get(URL)
    assert response.status_code == 200
    assert [p["key"] for p in response.json()] == ["free", "counter", "business"]


def test_shape(client: TestClient) -> None:
    free = client.get(URL).json()[0]
    assert set(free) == {
        "id",
        "key",
        "name",
        "price_cents",
        "max_customers",
        "max_users",
        "max_devices",
        "history_days",
        "images_enabled",
        "exports_enabled",
        "ai_enabled",
        "ai_messages_month",
        "trial_days",
        "is_default",
    }
    assert free["is_default"] is True
    assert free["price_cents"] == 0


def test_unlimited_is_null(client: TestClient) -> None:
    business = next(p for p in client.get(URL).json() if p["key"] == "business")
    assert business["history_days"] is None
    assert business["trial_days"] == 30


def test_same_list_for_any_business(client: TestClient, two_businesses) -> None:
    """A global catalog: nothing in it depends on who asks."""
    anonymous = client.get(URL).json()
    login(client, "admin.a@demo.mx")
    assert client.get(URL).json() == anonymous
    login(client, "admin.b@demo.mx")
    assert client.get(URL).json() == anonymous
