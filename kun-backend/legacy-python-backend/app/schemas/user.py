"""
用户Schema
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """用户基础Schema"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=100)


class UserCreate(UserBase):
    """用户创建Schema"""
    password: str = Field(..., min_length=6, max_length=100)


class UserUpdate(BaseModel):
    """用户更新Schema"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class UserInDB(UserBase):
    """数据库用户Schema"""
    id: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class UserResponse(UserInDB):
    """用户响应Schema"""
    pass


class UserLogin(BaseModel):
    """用户登录Schema"""
    username: str
    password: str


class Token(BaseModel):
    """令牌Schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """令牌载荷Schema"""
    sub: Optional[str] = None
    exp: Optional[datetime] = None
    type: Optional[str] = None
