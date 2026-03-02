"""
测试用例模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum, JSON, Integer
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base


class TestCaseStatus(str, enum.Enum):
    """测试用例状态"""
    DRAFT = "draft"               # 草稿
    PENDING = "pending"           # 待生成脚本
    GENERATING = "generating"     # 生成中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败


class TestCasePriority(str, enum.Enum):
    """测试用例优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TestCaseType(str, enum.Enum):
    """测试用例类型"""
    FUNCTIONAL = "functional"     # 功能测试
    UI = "ui"                     # UI测试
    API = "api"                   # API测试
    E2E = "e2e"                   # 端到端测试
    REGRESSION = "regression"     # 回归测试


class TestCase(Base):
    """测试用例表"""
    __tablename__ = "test_cases"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_number = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    
    # 测试步骤
    preconditions = Column(Text, nullable=True)
    steps = Column(JSON, nullable=False)  # 步骤列表 [{"step": 1, "action": "...", "expected": "..."}]
    expected_result = Column(Text, nullable=False)
    
    # 分类
    priority = Column(Enum(TestCasePriority), default=TestCasePriority.MEDIUM)
    case_type = Column(Enum(TestCaseType), default=TestCaseType.FUNCTIONAL)
    tags = Column(JSON, nullable=True)  # 标签列表
    
    # 关联
    us_id = Column(String(36), ForeignKey("user_stories.id"), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    
    # 状态
    status = Column(Enum(TestCaseStatus), default=TestCaseStatus.DRAFT)
    
    # AI生成信息
    ai_generated = Column(Boolean, default=True)
    generation_metadata = Column(JSON, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user_story = relationship("UserStory", back_populates="test_cases")
    creator = relationship("User", back_populates="test_cases")
    scripts = relationship("Script", back_populates="test_case", lazy="dynamic", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<TestCase {self.case_number}: {self.title}>"
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "case_number": self.case_number,
            "title": self.title,
            "description": self.description,
            "preconditions": self.preconditions,
            "steps": self.steps,
            "expected_result": self.expected_result,
            "priority": self.priority.value if self.priority else None,
            "case_type": self.case_type.value if self.case_type else None,
            "tags": self.tags,
            "status": self.status.value if self.status else None,
            "us_id": self.us_id,
            "us_number": self.user_story.us_number if self.user_story else None,
            "ai_generated": self.ai_generated,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
