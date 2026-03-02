"""
API路由模块
"""
from fastapi import APIRouter
from app.api import auth, user_stories, test_cases, scripts, executions, dashboard

# 创建主API路由
api_router = APIRouter(prefix="/api/v1")

# 注册子路由
api_router.include_router(auth.router)
api_router.include_router(user_stories.router)
api_router.include_router(test_cases.router)
api_router.include_router(scripts.router)
api_router.include_router(executions.router)
api_router.include_router(dashboard.router)

__all__ = ["api_router"]
