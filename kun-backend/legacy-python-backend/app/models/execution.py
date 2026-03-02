"""
执行记录模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum, JSON, Integer, Float
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base


class ExecutionStatus(str, enum.Enum):
    """执行状态"""
    PENDING = "pending"           # 待执行
    QUEUED = "queued"             # 已入队
    RUNNING = "running"           # 执行中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 已取消
    TIMEOUT = "timeout"           # 超时


class ExecutionResult(str, enum.Enum):
    """执行结果"""
    PASSED = "passed"             # 通过
    FAILED = "failed"             # 失败
    SKIPPED = "skipped"           # 跳过
    ERROR = "error"               # 错误
    UNKNOWN = "unknown"           # 未知


class Execution(Base):
    """执行记录表"""
    __tablename__ = "executions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_number = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    
    # 关联
    script_id = Column(String(36), ForeignKey("scripts.id"), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    
    # 执行配置
    config = Column(JSON, nullable=True)  # 执行配置：浏览器、环境变量等
    parameters = Column(JSON, nullable=True)  # 执行参数
    
    # 状态
    status = Column(Enum(ExecutionStatus), default=ExecutionStatus.PENDING)
    result = Column(Enum(ExecutionResult), nullable=True)
    
    # 执行时间
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration = Column(Float, nullable=True)  # 执行时长（秒）
    
    # 执行统计
    total_steps = Column(Integer, default=0)
    passed_steps = Column(Integer, default=0)
    failed_steps = Column(Integer, default=0)
    
    # 结果详情
    output = Column(Text, nullable=True)  # 控制台输出
    error_message = Column(Text, nullable=True)
    step_results = Column(JSON, nullable=True)  # 步骤执行结果
    
    # 资源文件
    screenshot_urls = Column(JSON, nullable=True)  # 截图URL列表
    video_url = Column(String(500), nullable=True)  # 录屏URL
    log_url = Column(String(500), nullable=True)  # 日志文件URL
    report_url = Column(String(500), nullable=True)  # 报告URL
    
    # AI分析
    ai_analysis = Column(JSON, nullable=True)  # AI分析结果
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    script = relationship("Script", back_populates="executions")
    creator = relationship("User", back_populates="executions")
    
    def __repr__(self):
        return f"<Execution {self.execution_number}: {self.name}>"
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "execution_number": self.execution_number,
            "name": self.name,
            "script_id": self.script_id,
            "script_number": self.script.script_number if self.script else None,
            "status": self.status.value if self.status else None,
            "result": self.result.value if self.result else None,
            "config": self.config,
            "parameters": self.parameters,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration": self.duration,
            "total_steps": self.total_steps,
            "passed_steps": self.passed_steps,
            "failed_steps": self.failed_steps,
            "output": self.output,
            "error_message": self.error_message,
            "step_results": self.step_results,
            "screenshot_urls": self.screenshot_urls,
            "video_url": self.video_url,
            "log_url": self.log_url,
            "report_url": self.report_url,
            "ai_analysis": self.ai_analysis,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
