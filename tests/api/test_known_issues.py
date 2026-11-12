"""Known issues found while testing (see docs/TESTING.md, section "Hallazgos").

Each test describes the DESIRED behavior and is marked xfail(strict=True):
- today it fails, which is expected and keeps the suite green;
- once the issue is fixed it will pass, and strict mode turns that into a
  failure so whoever fixes it removes the marker.
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import LOGIN_URL


@pytest.mark.xfail(strict=True, reason="H4: no rate limit on failed logins")
def test_h4_repeated_failed_logins_are_throttled(client: TestClient, two_businesses) -> None:
    for _ in range(10):
        client.post(LOGIN_URL, data={"username": "admin.a@demo.mx", "password": "wrong"})
    response = client.post(LOGIN_URL, data={"username": "admin.a@demo.mx", "password": "wrong"})
    assert response.status_code == 429
