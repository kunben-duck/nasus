"""
用户故事(US)模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum, Integer, JSON
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base


class USStatus(str, enum.Enum):
    """US状态"""
    PENDING = "pending"           # 待处理
    ANALYZING = "analyzing"       # AI分析中
    ANALYZED = "analyzed"         # 分析完成
    GENERATING = "generating"     # 生成用例中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败


class UserStory(Base):
    """用户故事表"""
    __tablename__ = "user_stories"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    us_number = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    acceptance_criteria = Column(Text, nullable=True)
    
    # AI分析结果
    ai_analysis = Column(JSON, nullable=True)
    validation_points = Column(JSON, nullable=True)  # 验证点列表
    
    # 状态
    status = Column(Enum(USStatus), default=USStatus.PENDING, nullable=False)
    progress = Column(Integer, default=0)  # 进度百分比
    
    # 关联用户
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    analyzed_at = Column(DateTime, nullable=True)
    
    # 关系
    creator = relationship("User", back_populates="user_stories")
    test_cases = relationship("TestCase", back_populates="user_story", lazy="dynamic", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<UserStory {self.us_number}: {self.title}>"
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "us_number": self.us_number,
            "title": self.title,
            "description": self.description,
            "acceptance_criteria": self.acceptance_criteria,
            "status": self.status.value if self.status else None,
            "progress": self.progress,
            "validation_points": self.validation_points,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
        }
