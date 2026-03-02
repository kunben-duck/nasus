"""
仪表盘API路由
"""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta
from app.db.base import get_db
from app.models.user import User
from app.models.user_story import UserStory, USStatus
from app.models.test_case import TestCase, TestCaseStatus
from app.models.script import Script, ScriptStatus
from app.models.execution import Execution, ExecutionStatus, ExecutionResult
from app.api.auth import get_current_active_user

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取仪表盘统计数据"""
    
    # US统计
    us_total_result = await db.execute(select(func.count()).select_from(UserStory))
    us_total = us_total_result.scalar()
    
    us_analyzed_result = await db.execute(
        select(func.count()).where(UserStory.status.in_([USStatus.ANALYZED, USStatus.COMPLETED]))
    )
    us_analyzed = us_analyzed_result.scalar()
    
    # 测试用例统计
    tc_total_result = await db.execute(select(func.count()).select_from(TestCase))
    tc_total = tc_total_result.scalar()
    
    tc_completed_result = await db.execute(
        select(func.count()).where(TestCase.status == TestCaseStatus.COMPLETED)
    )
    tc_completed = tc_completed_result.scalar()
    
    # 脚本统计
    script_total_result = await db.execute(select(func.count()).select_from(Script))
    script_total = script_total_result.scalar()
    
    script_validated_result = await db.execute(
        select(func.count()).where(Script.validated == True)
    )
    script_validated = script_validated_result.scalar()
    
    # 执行统计
    exec_total_result = await db.execute(select(func.count()).select_from(Execution))
    exec_total = exec_total_result.scalar()
    
    exec_passed_result = await db.execute(
        select(func.count()).where(Execution.result == ExecutionResult.PASSED)
    )
    exec_passed = exec_passed_result.scalar()
    
    exec_failed_result = await db.execute(
        select(func.count()).where(Execution.result == ExecutionResult.FAILED)
    )
    exec_failed = exec_failed_result.scalar()
    
    # 计算通过率
    exec_completed = exec_passed + exec_failed
    pass_rate = (exec_passed / exec_completed * 100) if exec_completed > 0 else 0
    
    return {
        "user_stories": {
            "total": us_total,
            "analyzed": us_analyzed,
            "pending": us_total - us_analyzed
        },
        "test_cases": {
            "total": tc_total,
            "completed": tc_completed,
            "draft": tc_total - tc_completed
        },
        "scripts": {
            "total": script_total,
            "validated": script_validated,
            "pending": script_total - script_validated
        },
        "executions": {
            "total": exec_total,
            "passed": exec_passed,
            "failed": exec_failed,
            "pass_rate": round(pass_rate, 2)
        }
    }


@router.get("/recent-executions")
async def get_recent_executions(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取最近执行记录"""
    result = await db.execute(
        select(Execution)
        .order_by(desc(Execution.created_at))
        .limit(limit)
    )
    executions = result.scalars().all()
    
    return [
        {
            "id": exec.id,
            "execution_number": exec.execution_number,
            "name": exec.name,
            "status": exec.status.value if exec.status else None,
            "result": exec.result.value if exec.result else None,
            "duration": exec.duration,
            "created_at": exec.created_at.isoformat() if exec.created_at else None
        }
        for exec in executions
    ]


@router.get("/execution-trend")
async def get_execution_trend(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取执行趋势"""
    from sqlalchemy import cast, Date
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # 按日期分组统计
    result = await db.execute(
        select(
            cast(Execution.created_at, Date).label("date"),
            func.count().label("total"),
            func.sum(func.case([(Execution.result == ExecutionResult.PASSED, 1)], else_=0)).label("passed"),
            func.sum(func.case([(Execution.result == ExecutionResult.FAILED, 1)], else_=0)).label("failed")
        )
        .where(Execution.created_at >= start_date)
        .group_by(cast(Execution.created_at, Date))
        .order_by("date")
    )
    
    trend_data = []
    for row in result:
        trend_data.append({
            "date": row.date.isoformat() if row.date else None,
            "total": row.total,
            "passed": row.passed or 0,
            "failed": row.failed or 0
        })
    
    return trend_data


@router.get("/activity-feed")
async def get_activity_feed(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取活动动态"""
    activities = []
    
    # 最近的US
    us_result = await db.execute(
        select(UserStory)
        .order_by(desc(UserStory.created_at))
        .limit(5)
    )
    for us in us_result.scalars():
        activities.append({
            "type": "us_created",
            "title": f"创建用户故事: {us.us_number}",
            "description": us.title,
            "timestamp": us.created_at.isoformat() if us.created_at else None,
            "status": us.status.value if us.status else None
        })
    
    # 最近的测试用例
    tc_result = await db.execute(
        select(TestCase)
        .order_by(desc(TestCase.created_at))
        .limit(5)
    )
    for tc in tc_result.scalars():
        activities.append({
            "type": "test_case_created",
            "title": f"创建测试用例: {tc.case_number}",
            "description": tc.title,
            "timestamp": tc.created_at.isoformat() if tc.created_at else None,
            "status": tc.status.value if tc.status else None
        })
    
    # 最近的执行
    exec_result = await db.execute(
        select(Execution)
        .order_by(desc(Execution.created_at))
        .limit(5)
    )
    for exec in exec_result.scalars():
        activities.append({
            "type": "execution_completed",
            "title": f"执行完成: {exec.execution_number}",
            "description": exec.name,
            "timestamp": exec.created_at.isoformat() if exec.created_at else None,
            "status": exec.result.value if exec.result else exec.status.value if exec.status else None
        })
    
    # 按时间排序
    activities.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    
    return activities[:limit]
