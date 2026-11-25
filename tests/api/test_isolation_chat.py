"""Isolation for /api/v1/chat: the assistant never reads another business.

The model cannot name a business: every tool runs with the token's. Even when
the model asks for another business's card, the answer is "not found".
"""

from fastapi.testclient import TestClient

from tests.api.test_chat import answer, cards, provider, question, tool_call  # noqa: F401
from tests.conftest import login

URL = "/api/v1/chat/send"


def test_card_of_a_is_invisible_to_b(
    client: TestClient,
    cards,  # noqa: F811
    provider,  # noqa: F811
) -> None:
    provider.script = [
        tool_call("customer_lookup", {"code": "MP-4F7K2", "business_id": 1}),
        answer("No encontré esa tarjeta."),
    ]
    login(client, "admin.b@demo.mx")
    assert client.post(URL, json=question("Busca MP-4F7K2")).status_code == 200
    # 0 rows of A: the tool answers not found, and A's customer never travels.
    assert provider.tool_results() == [{"error": "customer_not_found"}]
    assert "Laura" not in provider.requests[-1].content.decode()


def test_summary_and_tiers_are_only_the_sessions(
    client: TestClient,
    cards,  # noqa: F811
    provider,  # noqa: F811
) -> None:
    provider.script = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "customer_summary", "arguments": "{}"},
                            },
                            {
                                "id": "c2",
                                "type": "function",
                                "function": {"name": "tier_list", "arguments": "{}"},
                            },
                            {
                                "id": "c3",
                                "type": "function",
                                "function": {"name": "movement_list", "arguments": "{}"},
                            },
                        ],
                    }
                }
            ]
        },
        answer("Listo."),
    ]
    login(client, "admin.b@demo.mx")
    client.post(URL, json=question())
    summary, tiers, movements = provider.tool_results()
    assert summary["active"] == 1
    assert [tier["name"] for tier in tiers] == ["Plata"]
    assert movements["summary"]["count"] == 0
    assert "Oro" not in provider.requests[-1].content.decode()
