"""
执行记录Schema
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ExecutionConfig(BaseModel):
    """执行配置Schema"""
    browser: str = "chromium"
    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080
    timeout: int = 30000
    slow_mo: int = 0
    env_vars: Optional[Dict[str, str]] = None


class ExecutionStepResult(BaseModel):
    """执行步骤结果Schema"""
    step: int
    action: str
    status: str  # passed, failed, skipped
    duration: float
    screenshot: Optional[str] = None
    error: Optional[str] = None


class ExecutionBase(BaseModel):
    """执行记录基础Schema"""
    name: str = Field(..., min_length=1, max_length=255)
    config: Optional[ExecutionConfig] = None
    parameters: Optional[Dict[str, Any]] = None


class ExecutionCreate(ExecutionBase):
    """执行记录创建Schema"""
    script_id: str


class ExecutionUpdate(BaseModel):
    """执行记录更新Schema"""
    status: Optional[str] = None
    result: Optional[str] = None
    output: Optional[str] = None
    error_message: Optional[str] = None


class ExecutionInDB(ExecutionBase):
    """数据库执行记录Schema"""
    id: str
    execution_number: str
    script_id: str
    script_number: Optional[str] = None
    created_by: str
    status: str
    result: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration: Optional[float] = None
    total_steps: int
    passed_steps: int
    failed_steps: int
    output: Optional[str] = None
    error_message: Optional[str] = None
    step_results: Optional[List[Dict[str, Any]]] = None
    screenshot_urls: Optional[List[str]] = None
    video_url: Optional[str] = None
    log_url: Optional[str] = None
    report_url: Optional[str] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ExecutionResponse(ExecutionInDB):
    """执行记录响应Schema"""
    pass


class ExecutionListResponse(BaseModel):
    """执行记录列表响应"""
    items: List[ExecutionResponse]
    total: int
    page: int
    page_size: int


class ExecutionStartRequest(BaseModel):
    """开始执行请求Schema"""
    execution_id: str


class ExecutionStartResponse(BaseModel):
    """开始执行响应Schema"""
    execution_id: str
    task_id: str
    status: str
    message: str


class ExecutionStopRequest(BaseModel):
    """停止执行请求Schema"""
    execution_id: str


class ExecutionRealtimeData(BaseModel):
    """执行实时数据Schema（WebSocket）"""
    execution_id: str
    status: str
    current_step: int
    total_steps: int
    step_result: Optional[ExecutionStepResult] = None
    output: Optional[str] = None
    progress: int
    timestamp: datetime
