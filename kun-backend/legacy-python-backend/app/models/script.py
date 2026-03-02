"""
自动化脚本模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum, JSON, Boolean
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base


class ScriptStatus(str, enum.Enum):
    """脚本状态"""
    DRAFT = "draft"               # 草稿
    GENERATING = "generating"     # AI生成中
    COMPLETED = "completed"       # 完成
    VALIDATING = "validating"     # 验证中
    VALIDATED = "validated"       # 验证通过
    FAILED = "failed"             # 失败


class ScriptLanguage(str, enum.Enum):
    """脚本语言"""
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    PYTHON = "python"


class ScriptFramework(str, enum.Enum):
    """测试框架"""
    MIDSCENE = "midscene"         # Midscene.js
    PLAYWRIGHT = "playwright"     # Playwright
    SELENIUM = "selenium"         # Selenium
    CYPRESS = "cypress"           # Cypress


class Script(Base):
    """自动化脚本表"""
    __tablename__ = "scripts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    script_number = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # 脚本内容
    code = Column(Text, nullable=False)
    language = Column(Enum(ScriptLanguage), default=ScriptLanguage.JAVASCRIPT)
    framework = Column(Enum(ScriptFramework), default=ScriptFramework.MIDSCENE)
    
    # 关联
    test_case_id = Column(String(36), ForeignKey("test_cases.id"), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    
    # 状态
    status = Column(Enum(ScriptStatus), default=ScriptStatus.DRAFT)
    
    # AI生成信息
    ai_generated = Column(Boolean, default=True)
    generation_metadata = Column(JSON, nullable=True)
    
    # 验证信息
    validated = Column(Boolean, default=False)
    validated_at = Column(DateTime, nullable=True)
    validation_result = Column(JSON, nullable=True)
    
    # 版本控制
    version = Column(String(20), default="1.0.0")
    parent_id = Column(String(36), ForeignKey("scripts.id"), nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    test_case = relationship("TestCase", back_populates="scripts")
    creator = relationship("User", back_populates="scripts")
    executions = relationship("Execution", back_populates="script", lazy="dynamic", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Script {self.script_number}: {self.name}>"
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "script_number": self.script_number,
            "name": self.name,
            "description": self.description,
            "code": self.code,
            "language": self.language.value if self.language else None,
            "framework": self.framework.value if self.framework else None,
            "status": self.status.value if self.status else None,
            "test_case_id": self.test_case_id,
            "case_number": self.test_case.case_number if self.test_case else None,
            "ai_generated": self.ai_generated,
            "validated": self.validated,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "validation_result": self.validation_result,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
