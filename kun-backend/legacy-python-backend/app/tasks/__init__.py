"""
Celery任务模块
"""
from app.tasks.celery_app import celery_app
from app.tasks.us_tasks import analyze_user_story_task, generate_test_cases_task
from app.tasks.script_tasks import generate_script_task, validate_script_task
from app.tasks.execution_tasks import execute_test_task, cleanup_old_executions

__all__ = [
    "celery_app",
    "analyze_user_story_task",
    "generate_test_cases_task",
    "generate_script_task",
    "validate_script_task",
    "execute_test_task",
    "cleanup_old_executions",
]
