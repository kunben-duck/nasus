"""
用户模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer
from sqlalchemy.orm import relationship
from app.db.base import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    
    # 用户状态
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # 关系
    user_stories = relationship("UserStory", back_populates="creator", lazy="dynamic")
    test_cases = relationship("TestCase", back_populates="creator", lazy="dynamic")
    scripts = relationship("Script", back_populates="creator", lazy="dynamic")
    executions = relationship("Execution", back_populates="creator", lazy="dynamic")
    
    def __repr__(self):
        return f"<User {self.username}>"
