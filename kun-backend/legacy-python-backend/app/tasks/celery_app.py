"""
Celery应用配置
"""
from celery import Celery
from app.core.config import settings

# 创建Celery应用
celery_app = Celery(
    "autotest_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.us_tasks",
        "app.tasks.script_tasks",
        "app.tasks.execution_tasks",
    ]
)

# Celery配置
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # 时区设置
    timezone="Asia/Shanghai",
    enable_utc=True,
    
    # 任务结果过期时间
    result_expires=3600 * 24 * 7,  # 7天
    
    # 任务跟踪
    task_track_started=True,
    task_time_limit=3600 * 2,  # 2小时超时
    
    # 工作进程配置
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    
    # 队列配置
    task_default_queue="default",
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "us_analysis": {"exchange": "us_analysis", "routing_key": "us_analysis"},
        "script_generation": {"exchange": "script_generation", "routing_key": "script_generation"},
        "test_execution": {"exchange": "test_execution", "routing_key": "test_execution"},
    },
    task_routes={
        "app.tasks.us_tasks.*": {"queue": "us_analysis"},
        "app.tasks.script_tasks.*": {"queue": "script_generation"},
        "app.tasks.execution_tasks.*": {"queue": "test_execution"},
    },
)
