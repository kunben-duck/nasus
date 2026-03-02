"""
FastAPI应用主入口
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api import api_router
from app.db.base import async_engine, Base
from app.websocket import execution_websocket_endpoint, global_websocket_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    # 创建数据库表（开发环境使用，生产环境应使用Alembic）
    # async with async_engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # 关闭时执行
    await async_engine.dispose()


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="自动化测试平台后端API",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由
app.include_router(api_router)

# WebSocket路由
@app.websocket("/ws/executions/{execution_id}")
async def execution_websocket(websocket: WebSocket, execution_id: str):
    """执行实时数据WebSocket"""
    await execution_websocket_endpoint(websocket, execution_id)


@app.websocket("/ws/global")
async def global_websocket(websocket: WebSocket):
    """全局实时数据WebSocket"""
    await global_websocket_endpoint(websocket)


# 健康检查
@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT
    }


# 根路径
@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "api": "/api/v1"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
