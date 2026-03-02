"""
脚本生成相关Celery任务
"""
import asyncio
from celery import shared_task
from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.models.script import Script, ScriptStatus, ScriptLanguage, ScriptFramework
from app.models.test_case import TestCase, TestCaseStatus
from app.services.ai_service import ai_service
import uuid


@shared_task(bind=True, max_retries=3)
def generate_script_task(self, case_id: str, framework: str = "midscene", 
                         language: str = "javascript", created_by: str = None):
    """
    生成自动化脚本任务
    
    Args:
        case_id: 测试用例ID
        framework: 测试框架
        language: 编程语言
        created_by: 创建者ID
    """
    db = SessionLocal()
    
    try:
        # 获取测试用例
        test_case = db.query(TestCase).filter(TestCase.id == case_id).first()
        if not test_case:
            return {"status": "error", "message": f"测试用例 {case_id} 不存在"}
        
        # 更新状态
        test_case.status = TestCaseStatus.GENERATING
        db.commit()
        
        # 调用AI服务生成脚本
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        tc_data = {
            "case_number": test_case.case_number,
            "title": test_case.title,
            "description": test_case.description,
            "preconditions": test_case.preconditions,
            "steps": test_case.steps,
            "expected_result": test_case.expected_result
        }
        
        result = loop.run_until_complete(ai_service.generate_script(
            test_case=tc_data,
            framework=framework,
            language=language
        ))
        
        loop.close()
        
        # 创建脚本
        script_number = f"SCRIPT-{test_case.case_number}"
        
        script = Script(
            id=str(uuid.uuid4()),
            script_number=script_number,
            name=f"{test_case.title} - 自动化脚本",
            description=result.get("description", f"基于测试用例 {test_case.case_number} 生成的脚本"),
            code=result.get("code", ""),
            language=ScriptLanguage(language),
            framework=ScriptFramework(framework),
            test_case_id=case_id,
            created_by=created_by,
            status=ScriptStatus.COMPLETED,
            ai_generated=True,
            generation_metadata={
                "generated_at": datetime.utcnow().isoformat() if hasattr(datetime, 'utcnow') else __import__('datetime').datetime.utcnow().isoformat(),
                "source_case": test_case.case_number,
                "framework": framework,
                "language": language,
                "dependencies": result.get("dependencies", [])
            },
            version="1.0.0"
        )
        
        db.add(script)
        
        # 更新测试用例状态
        test_case.status = TestCaseStatus.COMPLETED
        db.commit()
        
        return {
            "status": "success",
            "case_id": case_id,
            "script_id": script.id,
            "script_number": script_number,
            "framework": framework,
            "language": language
        }
        
    except Exception as exc:
        db.rollback()
        # 更新状态为失败
        test_case = db.query(TestCase).filter(TestCase.id == case_id).first()
        if test_case:
            test_case.status = TestCaseStatus.FAILED
            db.commit()
        
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@shared_task(bind=True, max_retries=2)
def validate_script_task(self, script_id: str):
    """
    验证脚本任务
    
    Args:
        script_id: 脚本ID
    """
    from datetime import datetime
    db = SessionLocal()
    
    try:
        # 获取脚本
        script = db.query(Script).filter(Script.id == script_id).first()
        if not script:
            return {"status": "error", "message": f"脚本 {script_id} 不存在"}
        
        # 更新状态
        script.status = ScriptStatus.VALIDATING
        db.commit()
        
        # 简单的语法验证（实际项目中可以使用更复杂的验证）
        code = script.code
        errors = []
        warnings = []
        
        # 基本检查
        if not code or len(code.strip()) == 0:
            errors.append("脚本代码为空")
        else:
            # 检查必要的导入
            if script.framework == ScriptFramework.MIDSCENE:
                if "@midscene" not in code and "midscene" not in code.lower():
                    warnings.append("可能缺少Midscene.js导入")
            elif script.framework == ScriptFramework.PLAYWRIGHT:
                if "@playwright" not in code and "playwright" not in code.lower():
                    warnings.append("可能缺少Playwright导入")
            
            # 检查基本结构
            if "test(" not in code and "it(" not in code and "describe(" not in code:
                warnings.append("脚本可能缺少测试结构")
            
            # 检查断言
            if "assert" not in code.lower() and "expect" not in code.lower():
                warnings.append("脚本可能缺少断言")
        
        # 更新验证结果
        script.validated = len(errors) == 0
        script.validated_at = datetime.utcnow()
        script.validation_result = {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "validated_at": datetime.utcnow().isoformat()
        }
        script.status = ScriptStatus.VALIDATED if len(errors) == 0 else ScriptStatus.FAILED
        
        db.commit()
        
        return {
            "status": "success",
            "script_id": script_id,
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
        
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()
