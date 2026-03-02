"""
脚本管理API路由
"""
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.db.base import get_db
from app.models.user import User
from app.models.script import Script, ScriptStatus
from app.schemas.script import (
    ScriptCreate, ScriptUpdate, ScriptResponse, ScriptListResponse,
    ValidateScriptRequest, ValidateScriptResponse
)
from app.api.auth import get_current_active_user
from app.tasks.script_tasks import validate_script_task
import uuid

router = APIRouter(prefix="/scripts", tags=["脚本管理"])


@router.post("", response_model=ScriptResponse, status_code=status.HTTP_201_CREATED)
async def create_script(
    script_data: ScriptCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """创建脚本"""
    # 生成脚本编号
    result = await db.execute(
        select(func.count()).where(Script.test_case_id == script_data.test_case_id)
    )
    script_count = result.scalar()
    script_number = f"SCRIPT-{script_data.test_case_id[:8].upper()}-{str(script_count + 1).zfill(3)}"
    
    # 创建脚本
    script = Script(
        id=str(uuid.uuid4()),
        script_number=script_number,
        name=script_data.name,
        description=script_data.description,
        code=script_data.code,
        language=script_data.language,
        framework=script_data.framework,
        test_case_id=script_data.test_case_id,
        created_by=current_user.id,
        status=ScriptStatus.DRAFT,
        ai_generated=False,
        version="1.0.0"
    )
    
    db.add(script)
    await db.commit()
    await db.refresh(script)
    
    return script


@router.get("", response_model=ScriptListResponse)
async def list_scripts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    test_case_id: Optional[str] = None,
    status: Optional[str] = None,
    framework: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取脚本列表"""
    # 构建查询
    query = select(Script)
    
    if test_case_id:
        query = query.where(Script.test_case_id == test_case_id)
    
    if status:
        query = query.where(Script.status == ScriptStatus(status))
    
    if framework:
        query = query.where(Script.framework == framework)
    
    if search:
        query = query.where(
            (Script.script_number.contains(search)) |
            (Script.name.contains(search))
        )
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页
    query = query.order_by(desc(Script.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/{script_id}", response_model=ScriptResponse)
async def get_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取脚本详情"""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()
    
    if not script:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="脚本不存在"
        )
    
    return script


@router.put("/{script_id}", response_model=ScriptResponse)
async def update_script(
    script_id: str,
    script_data: ScriptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """更新脚本"""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()
    
    if not script:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="脚本不存在"
        )
    
    # 更新字段
    update_data = script_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(script, field, value)
    
    await db.commit()
    await db.refresh(script)
    
    return script


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> None:
    """删除脚本"""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()
    
    if not script:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="脚本不存在"
        )
    
    await db.delete(script)
    await db.commit()


@router.post("/{script_id}/validate", response_model=ValidateScriptResponse)
async def validate_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """验证脚本"""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()
    
    if not script:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="脚本不存在"
        )
    
    # 启动验证任务
    task = validate_script_task.delay(script_id)
    
    return {
        "script_id": script_id,
        "valid": False,
        "errors": [],
        "warnings": ["验证任务已启动，请稍后查看结果"]
    }


@router.get("/stats/summary")
async def get_script_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取脚本统计信息"""
    # 总数
    total_result = await db.execute(select(func.count()).select_from(Script))
    total = total_result.scalar()
    
    # 各状态数量
    status_counts = {}
    for status in ScriptStatus:
        count_result = await db.execute(
            select(func.count()).where(Script.status == status)
        )
        status_counts[status.value] = count_result.scalar()
    
    # AI生成数量
    ai_generated_result = await db.execute(
        select(func.count()).where(Script.ai_generated == True)
    )
    ai_generated = ai_generated_result.scalar()
    
    return {
        "total": total,
        "status_counts": status_counts,
        "ai_generated": ai_generated,
        "manual_created": total - ai_generated
    }
