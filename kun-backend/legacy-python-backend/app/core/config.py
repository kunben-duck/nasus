"""
应用配置管理
"""
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import validator


class Settings(BaseSettings):
    """应用配置类"""
    
    # 应用信息
    APP_NAME: str = "AutoTest Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    
    # 数据库配置
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/autotest_platform"
    DATABASE_URL_SYNC: str = "postgresql://postgres:password@localhost:5432/autotest_platform"
    
    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # JWT配置
    SECRET_KEY: str = "your-super-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # OpenAI配置
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_TEMPERATURE: float = 0.7
    
    # MinIO配置
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "autotest-platform"
    MINIO_SECURE: bool = False
    
    # CORS配置
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:3000"
    
    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    
    # Midscene.js配置
    MIDSCENE_API_KEY: Optional[str] = None
    MIDSCENE_API_URL: str = "https://api.midscene.ai"
    
    @validator("CORS_ORIGINS")
    def parse_cors_origins(cls, v):
        """解析CORS来源列表"""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 全局配置实例
settings = Settings()
