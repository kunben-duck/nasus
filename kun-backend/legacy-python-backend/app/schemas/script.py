"""
脚本Schema
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ScriptBase(BaseModel):
    """脚本基础Schema"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    code: str
    language: str = "javascript"
    framework: str = "midscene"


class ScriptCreate(ScriptBase):
    """脚本创建Schema"""
    test_case_id: str


class ScriptUpdate(BaseModel):
    """脚本更新Schema"""
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    code: Optional[str] = None
    status: Optional[str] = None


class ScriptInDB(ScriptBase):
    """数据库脚本Schema"""
    id: str
    script_number: str
    status: str
    test_case_id: str
    case_number: Optional[str] = None
    created_by: str
    ai_generated: bool
    validated: bool
    validated_at: Optional[datetime] = None
    validation_result: Optional[Dict[str, Any]] = None
    version: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ScriptResponse(ScriptInDB):
    """脚本响应Schema"""
    pass


class ScriptListResponse(BaseModel):
    """脚本列表响应"""
    items: List[ScriptResponse]
    total: int
    page: int
    page_size: int


class ValidateScriptRequest(BaseModel):
    """验证脚本请求Schema"""
    script_id: str


class ValidateScriptResponse(BaseModel):
    """验证脚本响应Schema"""
    script_id: str
    valid: bool
    errors: List[str]
    warnings: List[str]
