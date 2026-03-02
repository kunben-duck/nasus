"""
测试用例管理API路由
"""
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.db.base import get_db
from app.models.user import User
from app.models.test_case import TestCase, TestCaseStatus, TestCasePriority, TestCaseType
from app.schemas.test_case import (
    TestCaseCreate, TestCaseUpdate, TestCaseResponse, TestCaseListResponse,
    GenerateScriptRequest, GenerateScriptResponse
)
from app.api.auth import get_current_active_user
from app.tasks.script_tasks import generate_script_task
import uuid

router = APIRouter(prefix="/test-cases", tags=["测试用例管理"])


@router.post("", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    case_data: TestCaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """创建测试用例"""
    # 生成用例编号
    result = await db.execute(
        select(func.count()).where(TestCase.us_id == case_data.us_id)
    )
    case_count = result.scalar()
    case_number = f"TC-{case_data.us_id[:8].upper()}-{str(case_count + 1).zfill(3)}"
    
    # 创建测试用例
    test_case = TestCase(
        id=str(uuid.uuid4()),
        case_number=case_number,
        title=case_data.title,
        description=case_data.description,
        preconditions=case_data.preconditions,
        steps=[step.model_dump() for step in case_data.steps],
        expected_result=case_data.expected_result,
        priority=TestCasePriority(case_data.priority),
        case_type=TestCaseType(case_data.case_type),
        tags=case_data.tags or [],
        us_id=case_data.us_id,
        created_by=current_user.id,
        status=TestCaseStatus.DRAFT,
        ai_generated=False
    )
    
    db.add(test_case)
    await db.commit()
    await db.refresh(test_case)
    
    return test_case


@router.get("", response_model=TestCaseListResponse)
async def list_test_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    us_id: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    case_type: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取测试用例列表"""
    # 构建查询
    query = select(TestCase)
    
    if us_id:
        query = query.where(TestCase.us_id == us_id)
    
    if status:
        query = query.where(TestCase.status == TestCaseStatus(status))
    
    if priority:
        query = query.where(TestCase.priority == TestCasePriority(priority))
    
    if case_type:
        query = query.where(TestCase.case_type == TestCaseType(case_type))
    
    if search:
        query = query.where(
            (TestCase.case_number.contains(search)) |
            (TestCase.title.contains(search)) |
            (TestCase.description.contains(search))
        )
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页
    query = query.order_by(desc(TestCase.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/{case_id}", response_model=TestCaseResponse)
async def get_test_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取测试用例详情"""
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    test_case = result.scalar_one_or_none()
    
    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在"
        )
    
    return test_case


@router.put("/{case_id}", response_model=TestCaseResponse)
async def update_test_case(
    case_id: str,
    case_data: TestCaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """更新测试用例"""
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    test_case = result.scalar_one_or_none()
    
    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在"
        )
    
    # 更新字段
    update_data = case_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "steps" and value:
            value = [step.model_dump() if hasattr(step, 'model_dump') else step for step in value]
        setattr(test_case, field, value)
    
    await db.commit()
    await db.refresh(test_case)
    
    return test_case


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> None:
    """删除测试用例"""
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    test_case = result.scalar_one_or_none()
    
    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在"
        )
    
    await db.delete(test_case)
    await db.commit()


@router.post("/{case_id}/generate-script", response_model=GenerateScriptResponse)
async def generate_script(
    case_id: str,
    request: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """生成自动化脚本"""
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    test_case = result.scalar_one_or_none()
    
    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在"
        )
    
    # 启动异步任务
    task = generate_script_task.delay(case_id, request.framework, request.language, current_user.id)
    
    return {
        "case_id": case_id,
        "script_id": "",
        "status": "generating",
        "framework": request.framework,
        "language": request.language
    }


@router.get("/stats/summary")
async def get_test_case_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取测试用例统计信息"""
    # 总数
    total_result = await db.execute(select(func.count()).select_from(TestCase))
    total = total_result.scalar()
    
    # 各状态数量
    status_counts = {}
    for status in TestCaseStatus:
        count_result = await db.execute(
            select(func.count()).where(TestCase.status == status)
        )
        status_counts[status.value] = count_result.scalar()
    
    # 优先级分布
    priority_counts = {}
    for priority in TestCasePriority:
        count_result = await db.execute(
            select(func.count()).where(TestCase.priority == priority)
        )
        priority_counts[priority.value] = count_result.scalar()
    
    return {
        "total": total,
        "status_counts": status_counts,
        "priority_counts": priority_counts
    }
