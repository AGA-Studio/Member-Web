"""DTOs of the admin chat (issue #73).

The server keeps no conversation: the browser sends the history of its tab on
every turn. No `business_id` here: it comes from the token.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_MESSAGES = 20
MAX_MESSAGE_LENGTH = 2000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


class ChatSend(BaseModel):
    """The tab's history, oldest first, ending with the admin's new question.

    `session_id` is the one the previous reply returned; without it a new
    conversation starts.
    """

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{8,64}$")

    @model_validator(mode="after")
    def _ends_with_a_question(self) -> ChatSend:
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be the user's")
        return self


class ChatReply(BaseModel):
    reply: str
    # Send it back on the next turn of the same conversation.
    session_id: str
