from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    role: str
    avatar_url: Optional[str] = None
    avatar_preset: Optional[str] = None
    avatar_image: bool = False
    avatar_updated_at: Optional[str] = None


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: str
    user: UserProfile


class UserAvatarUpdateRequest(BaseModel):
    avatar_url: Optional[str] = None
    avatar_preset: Optional[str] = None


__all__ = [
    "AuthLoginRequest",
    "AuthRegisterRequest",
    "AuthSessionResponse",
    "UserAvatarUpdateRequest",
    "UserProfile",
]
