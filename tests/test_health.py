from fastapi.testclient import TestClient

from main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_user_list_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/user/list")
    assert response.status_code == 401
