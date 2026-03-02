"""
测试执行相关Celery任务
"""
import asyncio
import subprocess
import tempfile
import os
from datetime import datetime
from celery import shared_task
from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.models.execution import Execution, ExecutionStatus, ExecutionResult
from app.models.script import Script
from app.services.ai_service import ai_service
from app.services.storage_service import storage_service


@shared_task(bind=True, max_retries=1)
def execute_test_task(self, execution_id: str):
    """
    执行测试任务
    
    Args:
        execution_id: 执行记录ID
    """
    db = SessionLocal()
    
    try:
        # 获取执行记录
        execution = db.query(Execution).filter(Execution.id == execution_id).first()
        if not execution:
            return {"status": "error", "message": f"执行记录 {execution_id} 不存在"}
        
        # 获取脚本
        script = db.query(Script).filter(Script.id == execution.script_id).first()
        if not script:
            execution.status = ExecutionStatus.FAILED
            execution.result = ExecutionResult.ERROR
            execution.error_message = "关联的脚本不存在"
            db.commit()
            return {"status": "error", "message": "脚本不存在"}
        
        # 更新状态为执行中
        execution.status = ExecutionStatus.RUNNING
        execution.started_at = datetime.utcnow()
        db.commit()
        
        # 创建临时文件保存脚本
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(script.code)
            script_path = f.name
        
        try:
            # 模拟执行（实际项目中应调用真实的测试框架）
            # 这里使用模拟数据演示流程
            
            # 模拟执行步骤
            total_steps = 5
            passed_steps = 4
            failed_steps = 1
            
            step_results = []
            for i in range(1, total_steps + 1):
                step_result = {
                    "step": i,
                    "action": f"执行步骤 {i}",
                    "status": "passed" if i <= passed_steps else "failed",
                    "duration": 2.5,
                    "screenshot": f"/screenshots/{execution_id}/step_{i}.png" if i == failed_steps else None,
                    "error": None if i <= passed_steps else "元素未找到"
                }
                step_results.append(step_result)
            
            # 模拟执行输出
            output = f"""
[Test Execution Started]
Execution ID: {execution.execution_number}
Script: {script.script_number}
Framework: {script.framework.value}

[Step 1] ✓ Navigate to login page - PASSED (2.3s)
[Step 2] ✓ Enter username - PASSED (1.8s)
[Step 3] ✓ Enter password - PASSED (1.5s)
[Step 4] ✗ Click login button - FAILED (5.0s)
  Error: Element not found: button[type="submit"]
[Step 5] - Verify dashboard - SKIPPED

[Test Execution Completed]
Total: {total_steps} steps
Passed: {passed_steps} steps
Failed: {failed_steps} steps
Duration: 12.5s
"""
            
            # 更新执行结果
            execution.status = ExecutionStatus.COMPLETED
            execution.result = ExecutionResult.PASSED if failed_steps == 0 else ExecutionResult.FAILED
            execution.completed_at = datetime.utcnow()
            execution.duration = 12.5
            execution.total_steps = total_steps
            execution.passed_steps = passed_steps
            execution.failed_steps = failed_steps
            execution.output = output
            execution.step_results = step_results
            execution.screenshot_urls = [f"/screenshots/{execution_id}/step_4.png"]
            execution.video_url = f"/videos/{execution_id}/recording.mp4"
            execution.log_url = f"/logs/{execution_id}/execution.log"
            
            db.commit()
            
            # AI分析执行结果
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            execution_data = {
                "execution_number": execution.execution_number,
                "script_name": script.name,
                "status": execution.status.value,
                "result": execution.result.value if execution.result else None,
                "total_steps": execution.total_steps,
                "passed_steps": execution.passed_steps,
                "failed_steps": execution.failed_steps,
                "duration": execution.duration,
                "step_results": execution.step_results,
                "error_message": execution.error_message
            }
            
            ai_analysis = loop.run_until_complete(ai_service.analyze_execution_result(execution_data))
            execution.ai_analysis = ai_analysis
            
            loop.close()
            
            db.commit()
            
            return {
                "status": "success",
                "execution_id": execution_id,
                "result": execution.result.value if execution.result else None,
                "duration": execution.duration
            }
            
        finally:
            # 清理临时文件
            if os.path.exists(script_path):
                os.remove(script_path)
        
    except Exception as exc:
        db.rollback()
        
        # 更新执行状态为失败
        execution = db.query(Execution).filter(Execution.id == execution_id).first()
        if execution:
            execution.status = ExecutionStatus.FAILED
            execution.result = ExecutionResult.ERROR
            execution.error_message = str(exc)
            execution.completed_at = datetime.utcnow()
            db.commit()
        
        return {
            "status": "error",
            "execution_id": execution_id,
            "error": str(exc)
        }
    finally:
        db.close()


@shared_task
def cleanup_old_executions(days: int = 30):
    """
    清理旧执行记录
    
    Args:
        days: 保留天数
    """
    from datetime import timedelta
    db = SessionLocal()
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # 查询旧记录
        old_executions = db.query(Execution).filter(
            Execution.created_at < cutoff_date,
            Execution.status.in_([ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED])
        ).all()
        
        count = 0
        for execution in old_executions:
            # 删除关联的文件
            if execution.screenshot_urls:
                for url in execution.screenshot_urls:
                    try:
                        # 从URL提取对象名称
                        object_name = url.lstrip("/")
                        asyncio.run(storage_service.delete_file(object_name))
                    except:
                        pass
            
            if execution.video_url:
                try:
                    object_name = execution.video_url.lstrip("/")
                    asyncio.run(storage_service.delete_file(object_name))
                except:
                    pass
            
            if execution.log_url:
                try:
                    object_name = execution.log_url.lstrip("/")
                    asyncio.run(storage_service.delete_file(object_name))
                except:
                    pass
            
            db.delete(execution)
            count += 1
        
        db.commit()
        
        return {
            "status": "success",
            "deleted_count": count,
            "cutoff_date": cutoff_date.isoformat()
        }
        
    except Exception as exc:
        db.rollback()
        return {
            "status": "error",
            "error": str(exc)
        }
    finally:
        db.close()
