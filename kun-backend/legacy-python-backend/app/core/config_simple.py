"""
简化版配置 - 使用SQLite数据库
"""
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    # 应用信息
    APP_NAME: str = "AutoTest Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    
    # 数据库配置 - SQLite
    DATABASE_URL: str = "sqlite:///./autotest.db"
    DATABASE_URL_SYNC: str = "sqlite:///./autotest.db"
    
    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    
    # MinIO配置
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "autotest"
    
    # 安全配置
    SECRET_KEY: str = "your-super-secret-key-change-this-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"
    
    # CORS配置
    CORS_ORIGINS: List[str] = ["*"]
    
    # OpenAI配置
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_TEMPERATURE: float = 0.7
    
    # Midscene配置
    MIDSCENE_API_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
