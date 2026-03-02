"""
用户故事Schema
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ValidationPoint(BaseModel):
    """验证点Schema"""
    id: str
    description: str
    priority: str = "medium"
    test_type: str = "functional"


class UserStoryBase(BaseModel):
    """用户故事基础Schema"""
    us_number: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    description: str
    acceptance_criteria: Optional[str] = None


class UserStoryCreate(UserStoryBase):
    """用户故事创建Schema"""
    pass


class UserStoryUpdate(BaseModel):
    """用户故事更新Schema"""
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = Field(None, ge=0, le=100)


class UserStoryInDB(UserStoryBase):
    """数据库用户故事Schema"""
    id: str
    status: str
    progress: int
    validation_points: Optional[List[Dict[str, Any]]] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    analyzed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class UserStoryResponse(UserStoryInDB):
    """用户故事响应Schema"""
    pass


class UserStoryListResponse(BaseModel):
    """用户故事列表响应"""
    items: List[UserStoryResponse]
    total: int
    page: int
    page_size: int


class AIAnalysisRequest(BaseModel):
    """AI分析请求Schema"""
    us_id: str


class AIAnalysisResponse(BaseModel):
    """AI分析响应Schema"""
    us_id: str
    status: str
    validation_points: List[ValidationPoint]
    analysis_summary: str
    estimated_test_cases: int


class GenerateTestCasesRequest(BaseModel):
    """生成测试用例请求Schema"""
    us_id: str
    count: Optional[int] = Field(5, ge=1, le=20)


class GenerateTestCasesResponse(BaseModel):
    """生成测试用例响应Schema"""
    us_id: str
    status: str
    generated_count: int
    test_case_ids: List[str]
