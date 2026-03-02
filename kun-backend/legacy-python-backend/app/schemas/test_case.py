"""
测试用例Schema
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TestStep(BaseModel):
    """测试步骤Schema"""
    step: int
    action: str
    expected: str
    data: Optional[str] = None


class TestCaseBase(BaseModel):
    """测试用例基础Schema"""
    title: str = Field(..., min_length=1, max_length=255)
    description: str
    preconditions: Optional[str] = None
    steps: List[TestStep]
    expected_result: str
    priority: str = "medium"
    case_type: str = "functional"
    tags: Optional[List[str]] = None


class TestCaseCreate(TestCaseBase):
    """测试用例创建Schema"""
    us_id: str


class TestCaseUpdate(BaseModel):
    """测试用例更新Schema"""
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    preconditions: Optional[str] = None
    steps: Optional[List[TestStep]] = None
    expected_result: Optional[str] = None
    priority: Optional[str] = None
    case_type: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None


class TestCaseInDB(TestCaseBase):
    """数据库测试用例Schema"""
    id: str
    case_number: str
    status: str
    us_id: str
    us_number: Optional[str] = None
    created_by: str
    ai_generated: bool
    generation_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class TestCaseResponse(TestCaseInDB):
    """测试用例响应Schema"""
    pass


class TestCaseListResponse(BaseModel):
    """测试用例列表响应"""
    items: List[TestCaseResponse]
    total: int
    page: int
    page_size: int


class GenerateScriptRequest(BaseModel):
    """生成脚本请求Schema"""
    case_id: str
    framework: Optional[str] = "midscene"
    language: Optional[str] = "javascript"


class GenerateScriptResponse(BaseModel):
    """生成脚本响应Schema"""
    case_id: str
    script_id: str
    status: str
    framework: str
    language: str
