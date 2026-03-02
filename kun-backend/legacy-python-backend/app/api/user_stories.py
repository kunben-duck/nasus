"""
用户故事(US)管理API路由
"""
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.db.base import get_db
from app.models.user import User
from app.models.user_story import UserStory, USStatus
from app.schemas.user_story import (
    UserStoryCreate, UserStoryUpdate, UserStoryResponse, UserStoryListResponse,
    AIAnalysisRequest, AIAnalysisResponse, GenerateTestCasesRequest, GenerateTestCasesResponse
)
from app.api.auth import get_current_active_user
from app.tasks.us_tasks import analyze_user_story_task, generate_test_cases_task
import uuid

router = APIRouter(prefix="/us", tags=["用户故事管理"])


@router.post("", response_model=UserStoryResponse, status_code=status.HTTP_201_CREATED)
async def create_user_story(
    us_data: UserStoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """创建用户故事"""
    # 检查US编号是否已存在
    result = await db.execute(select(UserStory).where(UserStory.us_number == us_data.us_number))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="US编号已存在"
        )
    
    # 创建US
    us = UserStory(
        id=str(uuid.uuid4()),
        us_number=us_data.us_number,
        title=us_data.title,
        description=us_data.description,
        acceptance_criteria=us_data.acceptance_criteria,
        status=USStatus.PENDING,
        progress=0,
        created_by=current_user.id
    )
    
    db.add(us)
    await db.commit()
    await db.refresh(us)
    
    return us


@router.get("", response_model=UserStoryListResponse)
async def list_user_stories(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取用户故事列表"""
    # 构建查询
    query = select(UserStory)
    
    if status:
        query = query.where(UserStory.status == USStatus(status))
    
    if search:
        query = query.where(
            (UserStory.us_number.contains(search)) |
            (UserStory.title.contains(search)) |
            (UserStory.description.contains(search))
        )
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页
    query = query.order_by(desc(UserStory.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/{us_id}", response_model=UserStoryResponse)
async def get_user_story(
    us_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取用户故事详情"""
    result = await db.execute(select(UserStory).where(UserStory.id == us_id))
    us = result.scalar_one_or_none()
    
    if not us:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户故事不存在"
        )
    
    return us


@router.put("/{us_id}", response_model=UserStoryResponse)
async def update_user_story(
    us_id: str,
    us_data: UserStoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """更新用户故事"""
    result = await db.execute(select(UserStory).where(UserStory.id == us_id))
    us = result.scalar_one_or_none()
    
    if not us:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户故事不存在"
        )
    
    # 更新字段
    update_data = us_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(us, field, value)
    
    await db.commit()
    await db.refresh(us)
    
    return us


@router.delete("/{us_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_story(
    us_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> None:
    """删除用户故事"""
    result = await db.execute(select(UserStory).where(UserStory.id == us_id))
    us = result.scalar_one_or_none()
    
    if not us:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户故事不存在"
        )
    
    await db.delete(us)
    await db.commit()


@router.post("/{us_id}/analyze", response_model=AIAnalysisResponse)
async def analyze_user_story(
    us_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """触发AI分析用户故事"""
    result = await db.execute(select(UserStory).where(UserStory.id == us_id))
    us = result.scalar_one_or_none()
    
    if not us:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户故事不存在"
        )
    
    # 启动异步任务
    task = analyze_user_story_task.delay(us_id)
    
    return {
        "us_id": us_id,
        "status": "analyzing",
        "validation_points": [],
        "analysis_summary": "AI分析任务已启动",
        "estimated_test_cases": 0
    }


@router.post("/{us_id}/generate-test-cases", response_model=GenerateTestCasesResponse)
async def generate_test_cases(
    us_id: str,
    request: GenerateTestCasesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """生成测试用例"""
    result = await db.execute(select(UserStory).where(UserStory.id == us_id))
    us = result.scalar_one_or_none()
    
    if not us:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户故事不存在"
        )
    
    # 启动异步任务
    task = generate_test_cases_task.delay(us_id, request.count, current_user.id)
    
    return {
        "us_id": us_id,
        "status": "generating",
        "generated_count": 0,
        "test_case_ids": []
    }


@router.get("/stats/summary")
async def get_us_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """获取US统计信息"""
    # 总数
    total_result = await db.execute(select(func.count()).select_from(UserStory))
    total = total_result.scalar()
    
    # 各状态数量
    status_counts = {}
    for status in USStatus:
        count_result = await db.execute(
            select(func.count()).where(UserStory.status == status)
        )
        status_counts[status.value] = count_result.scalar()
    
    return {
        "total": total,
        "status_counts": status_counts
    }
