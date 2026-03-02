"""
极简版FastAPI应用 - 使用内置sqlite3
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

# 配置
settings = {
    "APP_NAME": "AutoTest Platform",
    "APP_VERSION": "1.0.0",
    "DEBUG": True,
    "ENVIRONMENT": "development"
}

# 初始化数据库
def init_db():
    conn = sqlite3.connect('autotest.db')
    cursor = conn.cursor()
    
    # 创建表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stories (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            acceptance_criteria TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_cases (
            id TEXT PRIMARY KEY,
            us_id TEXT,
            title TEXT NOT NULL,
            description TEXT,
            preconditions TEXT,
            steps TEXT,
            expected_results TEXT,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'active',
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scripts (
            id TEXT PRIMARY KEY,
            test_case_id TEXT,
            name TEXT,
            code TEXT,
            language TEXT DEFAULT 'python',
            framework TEXT DEFAULT 'midscene',
            status TEXT DEFAULT 'draft',
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            script_id TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            logs TEXT,
            screenshot_url TEXT,
            video_url TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# 创建FastAPI应用
app = FastAPI(
    title=settings["APP_NAME"],
    version=settings["APP_VERSION"],
    description="自动化测试平台后端API",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic模型
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
    created_at: str

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
    created_at: str

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
    created_at: str

class ExecutionCreate(BaseModel):
    script_id: str

class ExecutionResponse(BaseModel):
    id: str
    script_id: str
    status: str
    result: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str

# 数据库辅助函数
def get_db():
    conn = sqlite3.connect('autotest.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_uuid():
    return str(uuid.uuid4())

# 健康检查
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings["APP_VERSION"],
        "environment": settings["ENVIRONMENT"]
    }

# 根路径
@app.get("/")
async def root():
    return {
        "name": settings["APP_NAME"],
        "version": settings["APP_VERSION"],
        "docs": "/docs",
        "api": "/api/v1"
    }

# Dashboard API
@app.get("/api/v1/dashboard/stats")
async def get_dashboard_stats():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM user_stories")
    total_us = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM test_cases")
    total_test_cases = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM scripts")
    total_scripts = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM executions")
    total_executions = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM user_stories WHERE status = 'pending'")
    pending_us = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM executions WHERE status = 'running'")
    running_executions = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM executions WHERE status = 'failed'")
    failed_executions = cursor.fetchone()[0]
    
    conn.close()
    
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

@app.get("/api/v1/dashboard/recent-executions")
async def get_recent_executions(limit: int = 10):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, status, created_at FROM executions ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "status": r[1], "created_at": r[2]} for r in rows]

@app.get("/api/v1/dashboard/activity-trend")
async def get_activity_trend(days: int = 7):
    trend = []
    for i in range(days):
        trend.append({"date": f"2024-02-{10+i:02d}", "count": i * 2 + 5})
    return trend

# User Story API
@app.get("/api/v1/user-stories", response_model=List[UserStoryResponse])
async def list_user_stories(skip: int = 0, limit: int = 100):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM user_stories ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, skip)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/v1/user-stories", response_model=UserStoryResponse)
async def create_user_story(us: UserStoryCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    us_id = generate_uuid()
    cursor.execute(
        """INSERT INTO user_stories (id, title, description, acceptance_criteria, priority, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (us_id, us.title, us.description, us.acceptance_criteria, us.priority, 'pending', now, now)
    )
    conn.commit()
    conn.close()
    return {**us.model_dump(), "id": us_id, "status": "pending", "created_at": now}

@app.get("/api/v1/user-stories/{us_id}")
async def get_user_story(us_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_stories WHERE id = ?", (us_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User Story not found")
    return dict(row)

@app.put("/api/v1/user-stories/{us_id}")
async def update_user_story(us_id: str, us_update: UserStoryCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute(
        """UPDATE user_stories SET title = ?, description = ?, acceptance_criteria = ?, priority = ?, updated_at = ?
           WHERE id = ?""",
        (us_update.title, us_update.description, us_update.acceptance_criteria, us_update.priority, now, us_id)
    )
    conn.commit()
    cursor.execute("SELECT * FROM user_stories WHERE id = ?", (us_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/v1/user-stories/{us_id}")
async def delete_user_story(us_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_stories WHERE id = ?", (us_id,))
    conn.commit()
    conn.close()
    return {"message": "User Story deleted successfully"}

@app.post("/api/v1/user-stories/{us_id}/analyze")
async def analyze_user_story(us_id: str):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE user_stories SET status = ? WHERE id = ?", ("analyzing", us_id))
    conn.commit()
    
    now = datetime.utcnow().isoformat()
    # 生成测试用例
    test_cases = [
        (generate_uuid(), us_id, "测试用例 1: 验证基本功能", "验证核心功能正常工作", "系统正常运行", "1. 打开页面\n2. 执行操作", "功能正常工作", "high", now, now),
        (generate_uuid(), us_id, "测试用例 2: 边界测试", "验证边界条件处理", "系统正常运行", "1. 输入边界值\n2. 提交", "正确处理边界值", "medium", now, now),
    ]
    cursor.executemany(
        """INSERT INTO test_cases (id, us_id, title, description, preconditions, steps, expected_results, priority, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        test_cases
    )
    
    cursor.execute("UPDATE user_stories SET status = ? WHERE id = ?", ("completed", us_id))
    conn.commit()
    conn.close()
    
    return {"message": "Analysis completed", "test_cases_generated": len(test_cases)}

# Test Case API
@app.get("/api/v1/test-cases")
async def list_test_cases(us_id: Optional[str] = None, skip: int = 0, limit: int = 100):
    conn = get_db()
    cursor = conn.cursor()
    if us_id:
        cursor.execute(
            "SELECT * FROM test_cases WHERE us_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (us_id, limit, skip)
        )
    else:
        cursor.execute(
            "SELECT * FROM test_cases ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, skip)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/v1/test-cases")
async def create_test_case(tc: TestCaseCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    tc_id = generate_uuid()
    cursor.execute(
        """INSERT INTO test_cases (id, us_id, title, description, preconditions, steps, expected_results, priority, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tc_id, tc.us_id, tc.title, tc.description, tc.preconditions, tc.steps, tc.expected_results, tc.priority, 'active', now, now)
    )
    conn.commit()
    conn.close()
    return {**tc.model_dump(), "id": tc_id, "status": "active", "created_at": now}

@app.get("/api/v1/test-cases/{tc_id}")
async def get_test_case(tc_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM test_cases WHERE id = ?", (tc_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Test Case not found")
    return dict(row)

@app.put("/api/v1/test-cases/{tc_id}")
async def update_test_case(tc_id: str, tc_update: TestCaseCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute(
        """UPDATE test_cases SET us_id = ?, title = ?, description = ?, preconditions = ?, steps = ?, expected_results = ?, priority = ?, updated_at = ?
           WHERE id = ?""",
        (tc_update.us_id, tc_update.title, tc_update.description, tc_update.preconditions, tc_update.steps, tc_update.expected_results, tc_update.priority, now, tc_id)
    )
    conn.commit()
    cursor.execute("SELECT * FROM test_cases WHERE id = ?", (tc_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/v1/test-cases/{tc_id}")
async def delete_test_case(tc_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM test_cases WHERE id = ?", (tc_id,))
    conn.commit()
    conn.close()
    return {"message": "Test Case deleted successfully"}

# Script API
@app.get("/api/v1/scripts")
async def list_scripts(test_case_id: Optional[str] = None, skip: int = 0, limit: int = 100):
    conn = get_db()
    cursor = conn.cursor()
    if test_case_id:
        cursor.execute(
            "SELECT * FROM scripts WHERE test_case_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (test_case_id, limit, skip)
        )
    else:
        cursor.execute(
            "SELECT * FROM scripts ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, skip)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/v1/scripts")
async def create_script(script: ScriptCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    script_id = generate_uuid()
    cursor.execute(
        """INSERT INTO scripts (id, test_case_id, name, code, language, framework, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (script_id, script.test_case_id, script.name, script.code, script.language, script.framework, 'draft', now, now)
    )
    conn.commit()
    conn.close()
    return {**script.model_dump(), "id": script_id, "status": "draft", "created_at": now}

@app.get("/api/v1/scripts/{script_id}")
async def get_script(script_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scripts WHERE id = ?", (script_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Script not found")
    return dict(row)

@app.put("/api/v1/scripts/{script_id}")
async def update_script(script_id: str, script_update: ScriptCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute(
        """UPDATE scripts SET test_case_id = ?, name = ?, code = ?, language = ?, framework = ?, updated_at = ?
           WHERE id = ?""",
        (script_update.test_case_id, script_update.name, script_update.code, script_update.language, script_update.framework, now, script_id)
    )
    conn.commit()
    cursor.execute("SELECT * FROM scripts WHERE id = ?", (script_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/v1/scripts/{script_id}")
async def delete_script(script_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
    conn.commit()
    conn.close()
    return {"message": "Script deleted successfully"}

@app.post("/api/v1/scripts/{script_id}/generate")
async def generate_script(script_id: str):
    conn = get_db()
    cursor = conn.cursor()
    code = '''from midscene import agent

@agent()
def test_login():
    """测试登录功能"""
    agent.ai("在用户名输入框中输入 'test_user'")
    agent.ai("在密码输入框中输入 'password123'")
    agent.ai("点击登录按钮")
    agent.ai_assert("页面显示登录成功消息")
'''
    cursor.execute(
        "UPDATE scripts SET code = ?, status = ? WHERE id = ?",
        (code, "generated", script_id)
    )
    conn.commit()
    conn.close()
    return {"message": "Script generated successfully"}

# Execution API
@app.get("/api/v1/executions")
async def list_executions(script_id: Optional[str] = None, skip: int = 0, limit: int = 100):
    conn = get_db()
    cursor = conn.cursor()
    if script_id:
        cursor.execute(
            "SELECT * FROM executions WHERE script_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (script_id, limit, skip)
        )
    else:
        cursor.execute(
            "SELECT * FROM executions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, skip)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/v1/executions")
async def create_execution(execution: ExecutionCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    execution_id = generate_uuid()
    cursor.execute(
        """INSERT INTO executions (id, script_id, status, created_at)
           VALUES (?, ?, ?, ?)""",
        (execution_id, execution.script_id, 'pending', now)
    )
    conn.commit()
    conn.close()
    return {"id": execution_id, "script_id": execution.script_id, "status": "pending", "created_at": now}

@app.get("/api/v1/executions/{execution_id}")
async def get_execution(execution_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM executions WHERE id = ?", (execution_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Execution not found")
    return dict(row)

@app.post("/api/v1/executions/{execution_id}/run")
async def run_execution(execution_id: str):
    import time
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    cursor.execute(
        "UPDATE executions SET status = ?, started_at = ? WHERE id = ?",
        ("running", now, execution_id)
    )
    conn.commit()
    
    # 模拟执行
    time.sleep(1)
    
    completed_at = datetime.utcnow().isoformat()
    cursor.execute(
        "UPDATE executions SET status = ?, result = ?, logs = ?, completed_at = ? WHERE id = ?",
        ("completed", "PASS", "Test executed successfully\nAll assertions passed", completed_at, execution_id)
    )
    conn.commit()
    conn.close()
    
    return {"message": "Execution completed", "status": "completed", "result": "PASS"}

@app.post("/api/v1/executions/{execution_id}/stop")
async def stop_execution(execution_id: str):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute(
        "UPDATE executions SET status = ?, completed_at = ? WHERE id = ?",
        ("stopped", now, execution_id)
    )
    conn.commit()
    conn.close()
    return {"message": "Execution stopped"}

@app.get("/api/v1/executions/{execution_id}/logs")
async def get_execution_logs(execution_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT logs FROM executions WHERE id = ?", (execution_id,))
    row = cursor.fetchone()
    conn.close()
    return {"logs": row[0] if row and row[0] else "No logs available"}

@app.get("/api/v1/executions/{execution_id}/waterfall")
async def get_execution_waterfall(execution_id: str):
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
        "minimal_main:app",
        host="0.0.0.0",
        port=8080,
        reload=True
    )
