"""Read-only chat for admins about their own business (issue #73).

Decision (wiki, "Agente de IA para admins: decisión"):
- Provider: any API compatible with OpenAI's `chat/completions` (Opencode Go
  today). Changing provider or model is configuration, not code.
- The model gets four tools, the queries that already exist: customer summary,
  card lookup by code, movements with totals and tiers. None takes a business:
  every tool runs with the session's `business_id`, so asking for another
  business's card answers "not found", like the rest of the API.
- Read only: no tool writes. Money is never computed here.
- At most `AI_MAX_ROUNDS` calls to the provider and `AI_TIMEOUT_SECONDS` in all.
  Off, unconfigured, offline, slow or a bad answer → 503 `ai_unavailable`, and
  nothing else in the panel depends on it.
- With `AI_TOOLS_ENABLED=false` (a model that cannot call tools) the backend
  sends the summary and the tiers itself, in the system prompt.
- No memory: nothing is stored. The API key is never logged.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import status
from sqlmodel import Session

from core.config import settings
from core.errors import ApiError, ErrorCode
from schemas.chat_schema import ChatReply, ChatSend
from services import customer_service, movement_service, tier_service

# uvicorn's logger is the one that reaches the console when the API runs.
logger = logging.getLogger("uvicorn.error")

USER_AGENT = "MemberPlus-Backend/1.0"
MAX_MOVEMENTS = 20

# HTTP transport for the provider. None = the real network. Tests replace it
# with an `httpx.MockTransport` that answers like the provider.
_transport: httpx.BaseTransport | None = None

SYSTEM_PROMPT = (
    "You are the assistant of Member+, a membership system, inside the admin panel "
    "of one business. Answer in Spanish (Mexico), briefly and politely. Use only the "
    "data the tools return; when a tool has no data, say so, and never invent "
    "customers, amounts or dates. You can only read: you cannot create customers, "
    "charge, or change tiers, prices or settings; if asked, explain that it is done "
    "from the panel. Amounts come in cents: show them in pesos (MXN). Today is {today}."
)

_unavailable = ApiError(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="The assistant is not available",
    code=ErrorCode.AI_UNAVAILABLE,
)


# --- Tools --------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "customer_summary",
            "description": "Count of the business's cards by status: active, expiring soon "
            "(within the month), expired and cancelled.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "customer_lookup",
            "description": "Find one card by its short code (for example MP-4F7K2): customer, "
            "tier, status, validity, points and cashback balance.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Card code"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "movement_list",
            "description": "Purchases charged at the counter, newest first (up to 20), with the "
            "totals of the whole filtered period. Dates are ISO 8601 (YYYY-MM-DD), inclusive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "From this date"},
                    "date_to": {"type": "string", "description": "Up to this date"},
                    "q": {"type": "string", "description": "Customer name or card code"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tier_list",
            "description": "The business's membership tiers: price, discount, points per $10, "
            "cashback and how many active cards each has.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _date(value: Any, end_of_day: bool = False) -> datetime | None:
    if value in (None, ""):
        return None
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if end_of_day and len(str(value)) == 10:
        moment = moment.replace(hour=23, minute=59, second=59)
    return moment


def _customer_summary(session: Session, business_id: int, _args: dict) -> Any:
    return customer_service.summary(session, business_id).model_dump(mode="json")


def _customer_lookup(session: Session, business_id: int, args: dict) -> Any:
    card = customer_service.lookup(session, business_id, str(args["code"])[:32])
    # A signed URL is of no use to the model.
    return card.model_dump(mode="json", exclude={"photo_url"})


def _movement_list(session: Session, business_id: int, args: dict) -> Any:
    page = movement_service.list_movements(
        session,
        business_id,
        q=(str(args["q"])[:120] if args.get("q") else None),
        date_from=_date(args.get("date_from")),
        date_to=_date(args.get("date_to"), end_of_day=True),
        page_size=MAX_MOVEMENTS,
    )
    return page.model_dump(mode="json", exclude={"page", "page_size"})


def _tier_list(session: Session, business_id: int, _args: dict) -> Any:
    return [tier.model_dump(mode="json") for tier in tier_service.list_tiers(session, business_id)]


_HANDLERS: dict[str, Callable[[Session, int, dict], Any]] = {
    "customer_summary": _customer_summary,
    "customer_lookup": _customer_lookup,
    "movement_list": _movement_list,
    "tier_list": _tier_list,
}


def run_tool(session: Session, business_id: int, name: str, raw_arguments: str | None) -> str:
    """Runs one tool for the session's business and returns its JSON for the model.

    Never raises: a missing card, bad arguments or an unknown tool become an
    `error` the model can explain.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": "unknown_tool"})
    try:
        args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError
        result = handler(session, business_id, args)
    except ApiError as exc:
        return json.dumps({"error": exc.code.value})
    except KeyError, ValueError, TypeError:
        return json.dumps({"error": "invalid_arguments"})
    return json.dumps(result, ensure_ascii=False)


# --- Provider -----------------------------------------------------------------


def _system_prompt(session: Session, business_id: int) -> str:
    prompt = SYSTEM_PROMPT.format(today=datetime.now(UTC).date().isoformat())
    if settings.ai_tools_enabled:
        return prompt
    # Fallback for a model without tools: the data travels in the prompt.
    context = {
        "customer_summary": _customer_summary(session, business_id, {}),
        "tiers": _tier_list(session, business_id, {}),
    }
    return f"{prompt}\nData of the business (JSON): {json.dumps(context, ensure_ascii=False)}"


def _headers(session_id: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "User-Agent": USER_AGENT,
    }
    if settings.ai_session_header:
        headers[settings.ai_session_header] = session_id
    return headers


def _complete(client: httpx.Client, payload: dict, session_id: str, deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    response = client.post(
        "/chat/completions", json=payload, headers=_headers(session_id), timeout=remaining
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    if not isinstance(message, dict):
        raise ValueError
    return message


def chat(session: Session, business_id: int, data: ChatSend) -> ChatReply:
    """One turn of the conversation: the reply already written for the admin."""
    if not settings.ai_configured:
        raise _unavailable
    session_id = data.session_id or str(uuid.uuid4())
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(session, business_id)},
        *(message.model_dump() for message in data.messages),
    ]
    deadline = time.monotonic() + settings.ai_timeout_seconds
    try:
        with httpx.Client(base_url=settings.ai_base_url, transport=_transport) as client:
            for round_number in range(settings.ai_max_rounds):
                payload: dict[str, Any] = {"model": settings.ai_model, "messages": messages}
                if settings.ai_tools_enabled:
                    payload["tools"] = TOOLS
                    # Last round: the model must answer with what it already has.
                    if round_number == settings.ai_max_rounds - 1:
                        payload["tool_choice"] = "none"
                message = _complete(client, payload, session_id, deadline)
                tool_calls = message.get("tool_calls") or []
                if tool_calls and settings.ai_tools_enabled:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": message.get("content") or "",
                            "tool_calls": tool_calls,
                        }
                    )
                    for call in tool_calls:
                        function = call["function"]
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": run_tool(
                                    session,
                                    business_id,
                                    function["name"],
                                    function.get("arguments"),
                                ),
                            }
                        )
                    continue
                reply = message.get("content")
                if isinstance(reply, str) and reply.strip():
                    return ChatReply(reply=reply.strip(), session_id=session_id)
                break
    except (httpx.HTTPError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("AI chat failed: %s", type(exc).__name__)
        raise _unavailable from None
    logger.warning("AI chat failed: no answer after %s rounds", settings.ai_max_rounds)
    raise _unavailable
