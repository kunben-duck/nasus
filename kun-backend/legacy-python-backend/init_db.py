#!/usr/bin/env python3
"""
数据库初始化脚本
"""
import asyncio
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_engine, AsyncSessionLocal
from app.core.security import get_password_hash
from app.models import Base, User, UserStory, TestCase, Script, Execution


async def init_database():
    """初始化数据库"""
    print("正在初始化数据库...")
    
    # 创建所有表
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    print("数据库表创建完成")


async def create_test_data():
    """创建测试数据"""
    print("正在创建测试数据...")
    
    async with AsyncSessionLocal() as session:
        # 创建测试用户
        user = User(
            id=str(uuid.uuid4()),
            username="admin",
            email="admin@autotest.com",
            hashed_password=get_password_hash("admin123"),
            full_name="管理员",
            is_active=True,
            is_superuser=True
        )
        session.add(user)
        await session.flush()
        
        # 创建测试用户故事
        us1 = UserStory(
            id=str(uuid.uuid4()),
            us_number="US-001",
            title="用户登录功能",
            description="作为用户，我希望能够通过用户名和密码登录系统，以便访问我的账户。",
            acceptance_criteria="1. 输入正确的用户名和密码可以成功登录\n2. 输入错误的密码显示错误提示\n3. 支持记住密码功能",
            status="completed",
            progress=100,
            validation_points=[
                {"id": "vp1", "description": "验证正确的用户名和密码可以登录", "priority": "high", "test_type": "functional"},
                {"id": "vp2", "description": "验证错误的密码显示错误提示", "priority": "high", "test_type": "functional"},
                {"id": "vp3", "description": "验证记住密码功能", "priority": "medium", "test_type": "ui"}
            ],
            created_by=user.id,
            analyzed_at=datetime.utcnow()
        )
        session.add(us1)
        await session.flush()
        
        # 创建测试用例
        tc1 = TestCase(
            id=str(uuid.uuid4()),
            case_number="TC-US001-001",
            title="验证正确的用户名和密码可以成功登录",
            description="测试使用正确的用户名和密码登录系统",
            preconditions="1. 用户已注册\n2. 网络连接正常",
            steps=[
                {"step": 1, "action": "打开登录页面", "expected": "显示登录表单"},
                {"step": 2, "action": "输入正确的用户名", "expected": "用户名输入成功"},
                {"step": 3, "action": "输入正确的密码", "expected": "密码输入成功"},
                {"step": 4, "action": "点击登录按钮", "expected": "成功登录，跳转到首页"}
            ],
            expected_result="用户成功登录系统，显示首页",
            priority="high",
            case_type="functional",
            tags=["login", "positive"],
            us_id=us1.id,
            created_by=user.id,
            status="completed",
            ai_generated=True
        )
        session.add(tc1)
        await session.flush()
        
        # 创建脚本
        script1 = Script(
            id=str(uuid.uuid4()),
            script_number="SCRIPT-TC001-001",
            name="用户登录功能 - 自动化脚本",
            description="基于测试用例 TC-US001-001 生成的自动化脚本",
            code='''import { agent } from '@midscene/web';

test('用户登录功能测试', async () => {
  // 打开登录页面
  await page.goto('https://example.com/login');
  
  // 使用AI执行登录操作
  await agent.aiAction('在用户名输入框输入"testuser"');
  await agent.aiAction('在密码输入框输入"password123"');
  await agent.aiAction('点击登录按钮');
  
  // 验证登录成功
  await agent.aiAssert('页面显示用户已登录，显示欢迎信息');
});''',
            language="javascript",
            framework="midscene",
            test_case_id=tc1.id,
            created_by=user.id,
            status="validated",
            ai_generated=True,
            validated=True,
            validated_at=datetime.utcnow(),
            version="1.0.0"
        )
        session.add(script1)
        await session.flush()
        
        # 创建执行记录
        exec1 = Execution(
            id=str(uuid.uuid4()),
            execution_number="EXEC-20240212-A1B2C3D4",
            name="用户登录功能回归测试",
            script_id=script1.id,
            created_by=user.id,
            config={
                "browser": "chromium",
                "headless": True,
                "viewport_width": 1920,
                "viewport_height": 1080
            },
            status="completed",
            result="passed",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            duration=15.5,
            total_steps=4,
            passed_steps=4,
            failed_steps=0,
            output="[Test Execution Started]...",
            step_results=[
                {"step": 1, "action": "打开登录页面", "status": "passed", "duration": 2.1},
                {"step": 2, "action": "输入用户名", "status": "passed", "duration": 1.5},
                {"step": 3, "action": "输入密码", "status": "passed", "duration": 1.3},
                {"step": 4, "action": "点击登录", "status": "passed", "duration": 3.2}
            ]
        )
        session.add(exec1)
        
        await session.commit()
        
        print("测试数据创建完成")
        print(f"  - 用户: admin / admin123")
        print(f"  - US: {us1.us_number}")
        print(f"  - 测试用例: {tc1.case_number}")
        print(f"  - 脚本: {script1.script_number}")
        print(f"  - 执行: {exec1.execution_number}")


async def main():
    """主函数"""
    try:
        await init_database()
        await create_test_data()
        print("\n数据库初始化完成！")
    except Exception as e:
        print(f"初始化失败: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
