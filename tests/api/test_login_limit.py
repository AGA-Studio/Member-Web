"""H4: at most 5 failed logins per email, then a 15-minute lock (429)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from tests.conftest import DEFAULT_PASSWORD, LOGIN_URL, login

EMAIL = "admin.a@demo.mx"


def fail(client: TestClient, email: str = EMAIL, times: int = 1) -> list[int]:
    return [
        client.post(LOGIN_URL, data={"username": email, "password": "wrong"}).status_code
        for _ in range(times)
    ]


def attempt(client: TestClient, email: str = EMAIL, password: str = DEFAULT_PASSWORD):
    return client.post(LOGIN_URL, data={"username": email, "password": password})


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    """Controllable clock for services.auth_service."""

    class Clock:
        now = datetime.now(UTC)

        def advance(self, **delta: int) -> None:
            self.now += timedelta(**delta)

    fake = Clock()
    monkeypatch.setattr("services.auth_service._now", lambda: fake.now)
    return fake


def test_five_failures_are_allowed_then_429(client: TestClient, two_businesses) -> None:
    assert fail(client, times=5) == [401] * 5
    response = attempt(client, password="wrong")
    assert response.status_code == 429
    assert response.json()["detail"] == "Too many failed login attempts. Try again later."


def test_locked_email_rejects_the_correct_password(client: TestClient, two_businesses) -> None:
    fail(client, times=5)
    response = attempt(client)
    assert response.status_code == 429
    assert "set-cookie" not in response.headers


def test_retry_after_header(client: TestClient, two_businesses) -> None:
    fail(client, times=5)
    retry_after = int(attempt(client).headers["retry-after"])
    assert 0 < retry_after <= settings.login_lockout_minutes * 60 + 1


def test_four_failures_do_not_lock(client: TestClient, two_businesses) -> None:
    fail(client, times=4)
    assert attempt(client).status_code == 200


def test_successful_login_resets_the_counter(client: TestClient, two_businesses) -> None:
    fail(client, times=4)
    login(client, EMAIL)
    client.cookies.clear()
    assert fail(client, times=4) == [401] * 4
    assert attempt(client).status_code == 200


def test_lock_expires_after_lockout_time(client: TestClient, two_businesses, clock) -> None:
    fail(client, times=5)
    clock.advance(minutes=settings.login_lockout_minutes - 1)
    assert attempt(client).status_code == 429
    clock.advance(minutes=2)
    assert attempt(client).status_code == 200


def test_after_the_lock_the_user_gets_five_new_attempts(
    client: TestClient, two_businesses, clock
) -> None:
    fail(client, times=5)
    clock.advance(minutes=settings.login_lockout_minutes + 1)
    assert fail(client, times=5) == [401] * 5
    assert attempt(client).status_code == 429


def test_old_failures_stop_counting(client: TestClient, two_businesses, clock) -> None:
    # Failures spread over time (outside the window) do not add up to a lock.
    fail(client, times=4)
    clock.advance(minutes=settings.login_lockout_minutes + 1)
    fail(client, times=4)
    assert attempt(client).status_code == 200


def test_lock_is_per_email(client: TestClient, two_businesses) -> None:
    fail(client, times=5)
    assert attempt(client, email="admin.b@demo.mx").status_code == 200


def test_email_case_does_not_bypass_the_lock(client: TestClient, two_businesses) -> None:
    fail(client, email="ADMIN.A@demo.mx", times=3)
    fail(client, email="Admin.A@Demo.MX", times=2)
    assert attempt(client).status_code == 429


def test_unknown_email_behaves_the_same(client: TestClient, two_businesses) -> None:
    # Same 401s and same 429: the limit does not reveal which emails exist.
    assert fail(client, email="nobody@demo.mx", times=5) == [401] * 5
    assert attempt(client, email="nobody@demo.mx").status_code == 429


def test_limit_is_configurable(
    client: TestClient, two_businesses, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 2)
    assert fail(client, times=2) == [401, 401]
    assert attempt(client).status_code == 429
