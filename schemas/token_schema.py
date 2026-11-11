"""JWT token DTOs."""

from pydantic import BaseModel

from models.user_model import Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Already-validated JWT contents."""

    user_id: int
    role: Role
    business_id: int | None
