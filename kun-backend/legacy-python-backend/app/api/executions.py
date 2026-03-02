"""
执行管理API路由
"""
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.db.base import get_db
from app.models.user import User
from app.models.execution import Execution, ExecutionStatus, ExecutionResult
from app.schemas.execution import (
    ExecutionCreate, ExecutionUpdate, ExecutionResponse, ExecutionListResponse,
    ExecutionStartRequest, ExecutionStartResponse, ExecutionStopRequest
)
from app.api.auth import get_current_active_user
from app.tasks.execution_tasks import execute_test_task
import uuid

router = APIRouter(prefix="/executions", tags=["执行管理"])


@router.post("", response_model=ExecutionResponse, status_code=status.HTTP_201_CREATED)
async def create_execution(
    execution_data: ExecutionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """创建执行记录"""
    # 生成执行编号
    from datetime import datetime
    execution_number = f"EXEC-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    
    # 创建执行记录
    execution = Execution(
        id=str(uuid.uuid4()),
        execution_number=execution_number,
        name=execution_data.name,
        script_id=execution_data.script_id,
        created_by=current_user.id,
        config=execution_data.config.model_dump() if execution_data.config else {},
        parameters=execution_data.parameters or {},
        status=ExecutionStatus.PENDING,
        total_steps=0,
        passed_steps=0,
        failed_steps=0
    )
    
    db.add(execution)
    await db.commit()
    await db.refresh(execution)
    
    return execution


@router.get("", response_model=ExecutionListResponse)
async def list_executions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    script_id: Optional[str] = None,
    status: Optional[str] = None,
    result: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取执行记录列表"""
    # 构建查询
    query = select(Execution)
    
    if script_id:
        query = query.where(Execution.script_id == script_id)
    
    if status:
        query = query.where(Execution.status == ExecutionStatus(status))
    
    if result:
        query = query.where(Execution.result == ExecutionResult(result))
    
    if search:
        query = query.where(
            (Execution.execution_number.contains(search)) |
            (Execution.name.contains(search))
        )
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页
    query = query.order_by(desc(Execution.created_at)).offset((page - 1) * page_size).limit(page_size)
    result_query = await db.execute(query)
    items = result_query.scalars().all()
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取执行记录详情"""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="执行记录不存在"
        )
    
    return execution


@router.post("/{execution_id}/start", response_model=ExecutionStartResponse)
async def start_execution(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """开始执行测试"""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="执行记录不存在"
        )
    
    if execution.status not in [ExecutionStatus.PENDING, ExecutionStatus.FAILED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前状态 {execution.status.value} 不允许启动执行"
        )
    
    # 启动执行任务
    task = execute_test_task.delay(execution_id)
    
    # 更新状态
    execution.status = ExecutionStatus.QUEUED
    await db.commit()
    
    return {
        "execution_id": execution_id,
        "task_id": task.id,
        "status": "queued",
        "message": "测试执行任务已加入队列"
    }


@router.post("/{execution_id}/stop", status_code=status.HTTP_200_OK)
async def stop_execution(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """停止执行"""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="执行记录不存在"
        )
    
    if execution.status not in [ExecutionStatus.QUEUED, ExecutionStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前状态 {execution.status.value} 不允许停止"
        )
    
    # 更新状态为取消
    execution.status = ExecutionStatus.CANCELLED
    await db.commit()
    
    return {
        "execution_id": execution_id,
        "status": "cancelled",
        "message": "执行已取消"
    }


@router.delete("/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> None:
    """删除执行记录"""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="执行记录不存在"
        )
    
    await db.delete(execution)
    await db.commit()


@router.get("/{execution_id}/logs")
async def get_execution_logs(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取执行日志"""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="执行记录不存在"
        )
    
    return {
        "execution_id": execution_id,
        "output": execution.output or "",
        "step_results": execution.step_results or []
    }


@router.get("/stats/summary")
async def get_execution_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取执行统计信息"""
    # 总数
    total_result = await db.execute(select(func.count()).select_from(Execution))
    total = total_result.scalar()
    
    # 各状态数量
    status_counts = {}
    for status in ExecutionStatus:
        count_result = await db.execute(
            select(func.count()).where(Execution.status == status)
        )
        status_counts[status.value] = count_result.scalar()
    
    # 各结果数量
    result_counts = {}
    for result in ExecutionResult:
        count_result = await db.execute(
            select(func.count()).where(Execution.result == result)
        )
        result_counts[result.value] = count_result.scalar()
    
    # 总执行时长
    from sqlalchemy import func
    duration_result = await db.execute(
        select(func.sum(Execution.duration)).where(Execution.duration != None)
    )
    total_duration = duration_result.scalar() or 0
    
    return {
        "total": total,
        "status_counts": status_counts,
        "result_counts": result_counts,
        "total_duration": total_duration
    }
