"""Router for /api/v1/chat: the admin's read-only assistant (issue #73).

Only the admin, of a business whose plan includes the AI. The business comes
from the token; the logic lives in `services/ai_service.py`.
"""

from fastapi import APIRouter, Depends

from api.v1.dependencies import BusinessId, SessionDep, require_permission, require_plan_feature
from core.permissions import Permission
from schemas.chat_schema import ChatReply, ChatSend
from services import ai_service
from services.plan_service import Feature

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    # The permission first: an employee sees 403 for the permission, not a plan to upgrade.
    dependencies=[
        Depends(require_permission(Permission.AI_CHAT)),
        Depends(require_plan_feature(Feature.AI)),
    ],
)


@router.post("/send", response_model=ChatReply)
def send(data: ChatSend, session: SessionDep, business_id: BusinessId) -> ChatReply:
    """One turn: the tab's history in, the reply already written out.

    503 `ai_unavailable` when the assistant is off or the provider fails or is slow.
    """
    return ai_service.chat(session, business_id, data)
