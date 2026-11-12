"""Known issues found while testing (see docs/TESTING.md, section "Hallazgos").

Each test describes the DESIRED behavior and is marked xfail(strict=True):
- today it fails, which is expected and keeps the suite green;
- once the issue is fixed it will pass, and strict mode turns that into a
  failure so whoever fixes it removes the marker.
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import LOGIN_URL, login


@pytest.mark.xfail(strict=True, reason="H2: logout only deletes the cookie; JWT stays valid")
def test_h2_token_is_invalid_after_logout(client: TestClient, two_businesses) -> None:
    token = login(client, "admin.a@demo.mx")
    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.xfail(strict=True, reason="H4: no rate limit on failed logins")
def test_h4_repeated_failed_logins_are_throttled(client: TestClient, two_businesses) -> None:
    for _ in range(10):
        client.post(LOGIN_URL, data={"username": "admin.a@demo.mx", "password": "wrong"})
    response = client.post(LOGIN_URL, data={"username": "admin.a@demo.mx", "password": "wrong"})
    assert response.status_code == 429


@pytest.mark.xfail(strict=True, reason="H5: names made only of spaces pass validation")
def test_h5_blank_name_is_rejected(client: TestClient, two_businesses) -> None:
    login(client, "admin.a@demo.mx")
    response = client.post(
        "/api/v1/user/create",
        json={"name": "   ", "email": "blank@demo.mx", "password": "password123"},
    )
    assert response.status_code == 422
