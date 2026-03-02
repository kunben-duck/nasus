"""
用户故事相关Celery任务
"""
import asyncio
from celery import shared_task
from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.models.user_story import UserStory, USStatus
from app.models.test_case import TestCase, TestCaseStatus, TestCasePriority, TestCaseType
from app.services.ai_service import ai_service
from app.core.security import get_password_hash
import uuid


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()


@shared_task(bind=True, max_retries=3)
def analyze_user_story_task(self, us_id: str):
    """
    分析用户故事任务
    
    Args:
        us_id: 用户故事ID
    """
    db = SessionLocal()
    
    try:
        # 获取用户故事
        us = db.query(UserStory).filter(UserStory.id == us_id).first()
        if not us:
            return {"status": "error", "message": f"US {us_id} 不存在"}
        
        # 更新状态为分析中
        us.status = USStatus.ANALYZING
        us.progress = 30
        db.commit()
        
        # 调用AI服务分析
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        result = loop.run_until_complete(ai_service.analyze_user_story(
            us_number=us.us_number,
            title=us.title,
            description=us.description,
            acceptance_criteria=us.acceptance_criteria
        ))
        
        loop.close()
        
        if result["status"] == "success":
            # 更新US数据
            us.validation_points = result["validation_points"]
            us.ai_analysis = {
                "analysis_summary": result["analysis_summary"],
                "estimated_test_cases": result["estimated_test_cases"]
            }
            us.status = USStatus.ANALYZED
            us.progress = 100
            us.analyzed_at = datetime.utcnow()
            db.commit()
            
            return {
                "status": "success",
                "us_id": us_id,
                "validation_points_count": len(result["validation_points"]),
                "estimated_test_cases": result["estimated_test_cases"]
            }
        else:
            us.status = USStatus.FAILED
            us.progress = 0
            db.commit()
            
            return {
                "status": "error",
                "us_id": us_id,
                "error": result.get("error", "未知错误")
            }
            
    except Exception as exc:
        db.rollback()
        # 更新状态为失败
        us = db.query(UserStory).filter(UserStory.id == us_id).first()
        if us:
            us.status = USStatus.FAILED
            db.commit()
        
        # 重试
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@shared_task(bind=True, max_retries=3)
def generate_test_cases_task(self, us_id: str, count: int = 5, created_by: str = None):
    """
    生成测试用例任务
    
    Args:
        us_id: 用户故事ID
        count: 生成数量
        created_by: 创建者ID
    """
    from datetime import datetime
    db = SessionLocal()
    
    try:
        # 获取用户故事
        us = db.query(UserStory).filter(UserStory.id == us_id).first()
        if not us:
            return {"status": "error", "message": f"US {us_id} 不存在"}
        
        # 更新状态
        us.status = USStatus.GENERATING
        us.progress = 50
        db.commit()
        
        # 调用AI服务生成测试用例
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        us_data = {
            "us_number": us.us_number,
            "title": us.title,
            "description": us.description,
            "acceptance_criteria": us.acceptance_criteria
        }
        
        test_cases_data = loop.run_until_complete(ai_service.generate_test_cases(
            us_data=us_data,
            validation_points=us.validation_points or [],
            count=count
        ))
        
        loop.close()
        
        # 创建测试用例
        created_case_ids = []
        for i, tc_data in enumerate(test_cases_data):
            case_number = f"TC-{us.us_number}-{str(i+1).zfill(3)}"
            
            test_case = TestCase(
                id=str(uuid.uuid4()),
                case_number=case_number,
                title=tc_data.get("title", "未命名测试用例"),
                description=tc_data.get("description", ""),
                preconditions=tc_data.get("preconditions", ""),
                steps=tc_data.get("steps", []),
                expected_result=tc_data.get("expected_result", ""),
                priority=TestCasePriority(tc_data.get("priority", "medium")),
                case_type=TestCaseType(tc_data.get("case_type", "functional")),
                tags=tc_data.get("tags", []),
                us_id=us_id,
                created_by=created_by,
                status=TestCaseStatus.DRAFT,
                ai_generated=True,
                generation_metadata={
                    "generated_at": datetime.utcnow().isoformat(),
                    "source_us": us.us_number
                }
            )
            
            db.add(test_case)
            created_case_ids.append(test_case.id)
        
        # 更新US状态
        us.status = USStatus.COMPLETED
        us.progress = 100
        db.commit()
        
        return {
            "status": "success",
            "us_id": us_id,
            "generated_count": len(created_case_ids),
            "test_case_ids": created_case_ids
        }
        
    except Exception as exc:
        db.rollback()
        # 更新状态为失败
        us = db.query(UserStory).filter(UserStory.id == us_id).first()
        if us:
            us.status = USStatus.FAILED
            db.commit()
        
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
