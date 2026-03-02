"""
服务模块
"""
from app.services.ai_service import ai_service, AIService
from app.services.storage_service import storage_service, StorageService

__all__ = [
    "ai_service",
    "AIService",
    "storage_service",
    "StorageService",
]
