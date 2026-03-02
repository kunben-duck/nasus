"""
简化版FastAPI应用 - 使用SQLite数据库
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 配置
class Settings:
    APP_NAME: str = "AutoTest Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite:///./autotest.db"
    SECRET_KEY: str = "your-super-secret-key-change-this-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    CORS_ORIGINS: list = ["*"]

settings = Settings()

# 数据库配置
engine = create_engine(settings.DATABASE_URL, echo=settings.DEBUG)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 创建数据库表
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="自动化测试平台后端API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据模型
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ForeignKey
from datetime import datetime
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    full_name = Column(String)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class UserStory(Base):
    __tablename__ = "user_stories"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    title = Column(String, index=True)
    description = Column(Text)
    acceptance_criteria = Column(Text)
    status = Column(String, default="pending")  # pending, analyzing, completed, failed
    priority = Column(String, default="medium")
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TestCase(Base):
    __tablename__ = "test_cases"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    us_id = Column(String, ForeignKey("user_stories.id"))
    title = Column(String)
    description = Column(Text)
    preconditions = Column(Text)
    steps = Column(Text)
    expected_results = Column(Text)
    priority = Column(String, default="medium")
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Script(Base):
    __tablename__ = "scripts"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    test_case_id = Column(String, ForeignKey("test_cases.id"))
    name = Column(String)
    code = Column(Text)
    language = Column(String, default="python")
    framework = Column(String, default="midscene")
    status = Column(String, default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Execution(Base):
    __tablename__ = "executions"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    script_id = Column(String, ForeignKey("scripts.id"))
    status = Column(String, default="pending")  # pending, running, completed, failed
    result = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)
    screenshot_url = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Pydantic模型
from pydantic import BaseModel
from typing import Optional, List

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class UserStoryCreate(BaseModel):
    title: str
    description: str
    acceptance_criteria: str
    priority: str = "medium"

class UserStoryResponse(BaseModel):
    id: str
    title: str
    description: str
    acceptance_criteria: str
    status: str
    priority: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class TestCaseCreate(BaseModel):
    us_id: str
    title: str
    description: str
    preconditions: str
    steps: str
    expected_results: str
    priority: str = "medium"

class TestCaseResponse(BaseModel):
    id: str
    us_id: str
    title: str
    description: str
    priority: str
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class ScriptCreate(BaseModel):
    test_case_id: str
    name: str
    code: str
    language: str = "python"
    framework: str = "midscene"

class ScriptResponse(BaseModel):
    id: str
    test_case_id: str
    name: str
    language: str
    framework: str
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class ExecutionCreate(BaseModel):
    script_id: str

class ExecutionResponse(BaseModel):
    id: str
    script_id: str
    status: str
    result: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True

# 依赖注入
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# API路由
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

# 健康检查
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT
    }

# 根路径
@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "api": "/api/v1"
    }

# Dashboard API
@api_router.get("/dashboard/stats")
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """获取仪表盘统计数据"""
    total_us = db.query(UserStory).count()
    total_test_cases = db.query(TestCase).count()
    total_scripts = db.query(Script).count()
    total_executions = db.query(Execution).count()
    
    pending_us = db.query(UserStory).filter(UserStory.status == "pending").count()
    running_executions = db.query(Execution).filter(Execution.status == "running").count()
    failed_executions = db.query(Execution).filter(Execution.status == "failed").count()
    
    return {
        "total_us": total_us,
        "total_test_cases": total_test_cases,
        "total_scripts": total_scripts,
        "total_executions": total_executions,
        "pending_us": pending_us,
        "running_executions": running_executions,
        "failed_executions": failed_executions,
        "success_rate": 0.95 if total_executions > 0 else 0
    }

@api_router.get("/dashboard/recent-executions")
async def get_recent_executions(limit: int = 10, db: Session = Depends(get_db)):
    """获取最近执行记录"""
    executions = db.query(Execution).order_by(Execution.created_at.desc()).limit(limit).all()
    return [{"id": e.id, "status": e.status, "created_at": e.created_at} for e in executions]

@api_router.get("/dashboard/activity-trend")
async def get_activity_trend(days: int = 7, db: Session = Depends(get_db)):
    """获取活动趋势"""
    from datetime import timedelta
    
    trend = []
    for i in range(days):
        date = datetime.utcnow() - timedelta(days=i)
        count = db.query(Execution).filter(
            Execution.created_at >= date.replace(hour=0, minute=0, second=0),
            Execution.created_at < date.replace(hour=23, minute=59, second=59)
        ).count()
        trend.append({"date": date.strftime("%Y-%m-%d"), "count": count})
    return list(reversed(trend))

# User Story API
@api_router.get("/user-stories", response_model=List[UserStoryResponse])
async def list_user_stories(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取US列表"""
    return db.query(UserStory).offset(skip).limit(limit).all()

@api_router.post("/user-stories", response_model=UserStoryResponse)
async def create_user_story(us: UserStoryCreate, db: Session = Depends(get_db)):
    """创建US"""
    db_us = UserStory(**us.model_dump())
    db.add(db_us)
    db.commit()
    db.refresh(db_us)
    return db_us

@api_router.get("/user-stories/{us_id}", response_model=UserStoryResponse)
async def get_user_story(us_id: str, db: Session = Depends(get_db)):
    """获取US详情"""
    us = db.query(UserStory).filter(UserStory.id == us_id).first()
    if not us:
        raise HTTPException(status_code=404, detail="User Story not found")
    return us

@api_router.put("/user-stories/{us_id}", response_model=UserStoryResponse)
async def update_user_story(us_id: str, us_update: UserStoryCreate, db: Session = Depends(get_db)):
    """更新US"""
    us = db.query(UserStory).filter(UserStory.id == us_id).first()
    if not us:
        raise HTTPException(status_code=404, detail="User Story not found")
    for key, value in us_update.model_dump().items():
        setattr(us, key, value)
    db.commit()
    db.refresh(us)
    return us

@api_router.delete("/user-stories/{us_id}")
async def delete_user_story(us_id: str, db: Session = Depends(get_db)):
    """删除US"""
    us = db.query(UserStory).filter(UserStory.id == us_id).first()
    if not us:
        raise HTTPException(status_code=404, detail="User Story not found")
    db.delete(us)
    db.commit()
    return {"message": "User Story deleted successfully"}

@api_router.post("/user-stories/{us_id}/analyze")
async def analyze_user_story(us_id: str, db: Session = Depends(get_db)):
    """分析US并生成测试用例"""
    us = db.query(UserStory).filter(UserStory.id == us_id).first()
    if not us:
        raise HTTPException(status_code=404, detail="User Story not found")
    
    us.status = "analyzing"
    db.commit()
    
    # 模拟生成测试用例
    test_cases = [
        TestCase(
            us_id=us_id,
            title=f"测试用例 1: {us.title}",
            description="验证基本功能",
            preconditions="系统正常运行",
            steps="1. 打开页面\n2. 执行操作",
            expected_results="功能正常工作",
            priority="high"
        ),
        TestCase(
            us_id=us_id,
            title=f"测试用例 2: {us.title} - 边界测试",
            description="验证边界条件",
            preconditions="系统正常运行",
            steps="1. 输入边界值\n2. 提交",
            expected_results="正确处理边界值",
            priority="medium"
        )
    ]
    for tc in test_cases:
        db.add(tc)
    
    us.status = "completed"
    db.commit()
    
    return {"message": "Analysis completed", "test_cases_generated": len(test_cases)}

# Test Case API
@api_router.get("/test-cases", response_model=List[TestCaseResponse])
async def list_test_cases(us_id: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取测试用例列表"""
    query = db.query(TestCase)
    if us_id:
        query = query.filter(TestCase.us_id == us_id)
    return query.offset(skip).limit(limit).all()

@api_router.post("/test-cases", response_model=TestCaseResponse)
async def create_test_case(tc: TestCaseCreate, db: Session = Depends(get_db)):
    """创建测试用例"""
    db_tc = TestCase(**tc.model_dump())
    db.add(db_tc)
    db.commit()
    db.refresh(db_tc)
    return db_tc

@api_router.get("/test-cases/{tc_id}", response_model=TestCaseResponse)
async def get_test_case(tc_id: str, db: Session = Depends(get_db)):
    """获取测试用例详情"""
    tc = db.query(TestCase).filter(TestCase.id == tc_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Test Case not found")
    return tc

@api_router.put("/test-cases/{tc_id}", response_model=TestCaseResponse)
async def update_test_case(tc_id: str, tc_update: TestCaseCreate, db: Session = Depends(get_db)):
    """更新测试用例"""
    tc = db.query(TestCase).filter(TestCase.id == tc_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Test Case not found")
    for key, value in tc_update.model_dump().items():
        setattr(tc, key, value)
    db.commit()
    db.refresh(tc)
    return tc

@api_router.delete("/test-cases/{tc_id}")
async def delete_test_case(tc_id: str, db: Session = Depends(get_db)):
    """删除测试用例"""
    tc = db.query(TestCase).filter(TestCase.id == tc_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Test Case not found")
    db.delete(tc)
    db.commit()
    return {"message": "Test Case deleted successfully"}

# Script API
@api_router.get("/scripts", response_model=List[ScriptResponse])
async def list_scripts(test_case_id: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取脚本列表"""
    query = db.query(Script)
    if test_case_id:
        query = query.filter(Script.test_case_id == test_case_id)
    return query.offset(skip).limit(limit).all()

@api_router.post("/scripts", response_model=ScriptResponse)
async def create_script(script: ScriptCreate, db: Session = Depends(get_db)):
    """创建脚本"""
    db_script = Script(**script.model_dump())
    db.add(db_script)
    db.commit()
    db.refresh(db_script)
    return db_script

@api_router.get("/scripts/{script_id}", response_model=ScriptResponse)
async def get_script(script_id: str, db: Session = Depends(get_db)):
    """获取脚本详情"""
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script

@api_router.put("/scripts/{script_id}", response_model=ScriptResponse)
async def update_script(script_id: str, script_update: ScriptCreate, db: Session = Depends(get_db)):
    """更新脚本"""
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    for key, value in script_update.model_dump().items():
        setattr(script, key, value)
    db.commit()
    db.refresh(script)
    return script

@api_router.delete("/scripts/{script_id}")
async def delete_script(script_id: str, db: Session = Depends(get_db)):
    """删除脚本"""
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    db.delete(script)
    db.commit()
    return {"message": "Script deleted successfully"}

@api_router.post("/scripts/{script_id}/generate")
async def generate_script(script_id: str, db: Session = Depends(get_db)):
    """生成脚本代码"""
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    
    # 模拟生成代码
    script.code = '''from midscene import agent

@agent()
def test_login():
    """测试登录功能"""
    agent.ai("在用户名输入框中输入 'test_user'")
    agent.ai("在密码输入框中输入 'password123'")
    agent.ai("点击登录按钮")
    agent.ai_assert("页面显示登录成功消息")
'''
    script.status = "generated"
    db.commit()
    
    return {"message": "Script generated successfully"}

# Execution API
@api_router.get("/executions", response_model=List[ExecutionResponse])
async def list_executions(script_id: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取执行记录列表"""
    query = db.query(Execution)
    if script_id:
        query = query.filter(Execution.script_id == script_id)
    return query.offset(skip).limit(limit).all()

@api_router.post("/executions", response_model=ExecutionResponse)
async def create_execution(execution: ExecutionCreate, db: Session = Depends(get_db)):
    """创建执行记录"""
    db_execution = Execution(**execution.model_dump())
    db.add(db_execution)
    db.commit()
    db.refresh(db_execution)
    return db_execution

@api_router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(execution_id: str, db: Session = Depends(get_db)):
    """获取执行记录详情"""
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution

@api_router.post("/executions/{execution_id}/run")
async def run_execution(execution_id: str, db: Session = Depends(get_db)):
    """执行测试脚本"""
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    execution.status = "running"
    execution.started_at = datetime.utcnow()
    db.commit()
    
    # 模拟执行
    import time
    time.sleep(2)
    
    execution.status = "completed"
    execution.result = "PASS"
    execution.logs = "Test executed successfully\\nAll assertions passed"
    execution.completed_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Execution completed", "status": "completed", "result": "PASS"}

@api_router.post("/executions/{execution_id}/stop")
async def stop_execution(execution_id: str, db: Session = Depends(get_db)):
    """停止执行"""
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    execution.status = "stopped"
    execution.completed_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Execution stopped"}

@api_router.get("/executions/{execution_id}/logs")
async def get_execution_logs(execution_id: str, db: Session = Depends(get_db)):
    """获取执行日志"""
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return {"logs": execution.logs or "No logs available"}

@api_router.get("/executions/{execution_id}/waterfall")
async def get_execution_waterfall(execution_id: str, db: Session = Depends(get_db)):
    """获取执行瀑布图数据"""
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    return {
        "execution_id": execution_id,
        "steps": [
            {"name": "初始化", "start": 0, "duration": 500, "status": "completed"},
            {"name": "打开页面", "start": 500, "duration": 1200, "status": "completed"},
            {"name": "输入数据", "start": 1700, "duration": 800, "status": "completed"},
            {"name": "点击提交", "start": 2500, "duration": 600, "status": "completed"},
            {"name": "验证结果", "start": 3100, "duration": 400, "status": "completed"},
            {"name": "清理", "start": 3500, "duration": 300, "status": "completed"},
        ],
        "total_duration": 3800
    }

# 注册路由
app.include_router(api_router)

# WebSocket
@app.websocket("/ws/executions/{execution_id}")
async def execution_websocket(websocket: WebSocket, execution_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({
                "execution_id": execution_id,
                "status": "running",
                "progress": 50,
                "message": "Processing..."
            })
    except:
        await websocket.close()

@app.websocket("/ws/global")
async def global_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({
                "type": "notification",
                "message": "Connected to global websocket"
            })
    except:
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "simple_main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
