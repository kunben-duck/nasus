"""
AI服务 - 使用LangChain + OpenAI
"""
import json
import uuid
from typing import List, Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from app.core.config import settings


class ValidationPointOutput(BaseModel):
    """验证点输出"""
    id: str = Field(description="验证点唯一标识")
    description: str = Field(description="验证点描述")
    priority: str = Field(description="优先级: low, medium, high, critical")
    test_type: str = Field(description="测试类型: functional, ui, api, e2e")


class TestCaseOutput(BaseModel):
    """测试用例输出"""
    title: str = Field(description="测试用例标题")
    description: str = Field(description="测试用例描述")
    preconditions: str = Field(description="前置条件")
    steps: List[Dict[str, str]] = Field(description="测试步骤列表")
    expected_result: str = Field(description="预期结果")
    priority: str = Field(description="优先级")
    case_type: str = Field(description="测试类型")
    tags: List[str] = Field(description="标签列表")


class AIService:
    """AI服务类"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=settings.OPENAI_TEMPERATURE,
            api_key=settings.OPENAI_API_KEY
        )
    
    async def analyze_user_story(self, us_number: str, title: str, description: str, 
                                  acceptance_criteria: Optional[str] = None) -> Dict[str, Any]:
        """
        分析用户故事，提取验证点
        
        Args:
            us_number: US编号
            title: US标题
            description: US描述
            acceptance_criteria: 验收标准
            
        Returns:
            分析结果，包含验证点列表
        """
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", """你是一位资深测试专家，擅长分析用户故事并提取测试验证点。
请根据提供的用户故事信息，分析出所有需要验证的功能点。

输出格式要求：
1. 每个验证点包含：id, description, priority, test_type
2. priority可选值：low, medium, high, critical
3. test_type可选值：functional, ui, api, e2e
4. 验证点应该覆盖所有功能路径，包括正常流程和异常流程

请以JSON格式输出。"""),
            ("human", """请分析以下用户故事：

US编号: {us_number}
标题: {title}
描述: {description}
验收标准: {acceptance_criteria}

请提取所有测试验证点，并以JSON数组格式返回。""")
        ])
        
        chain = prompt_template | self.llm
        
        response = await chain.ainvoke({
            "us_number": us_number,
            "title": title,
            "description": description,
            "acceptance_criteria": acceptance_criteria or "未提供"
        })
        
        # 解析响应
        try:
            content = response.content
            # 提取JSON部分
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            
            validation_points = json.loads(json_str)
            
            # 确保每个验证点有id
            for vp in validation_points:
                if "id" not in vp:
                    vp["id"] = str(uuid.uuid4())[:8]
            
            return {
                "status": "success",
                "validation_points": validation_points,
                "analysis_summary": f"成功提取 {len(validation_points)} 个验证点",
                "estimated_test_cases": len(validation_points)
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "validation_points": [],
                "analysis_summary": "分析失败",
                "estimated_test_cases": 0
            }
    
    async def generate_test_cases(self, us_data: Dict[str, Any], 
                                   validation_points: List[Dict[str, Any]],
                                   count: int = 5) -> List[Dict[str, Any]]:
        """
        根据用户故事和验证点生成测试用例
        
        Args:
            us_data: 用户故事数据
            validation_points: 验证点列表
            count: 期望生成的用例数量
            
        Returns:
            测试用例列表
        """
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", """你是一位资深测试工程师，擅长编写高质量的测试用例。
请根据用户故事和验证点，生成详细的测试用例。

每个测试用例必须包含：
1. title: 测试用例标题（简洁明了）
2. description: 测试用例描述
3. preconditions: 前置条件
4. steps: 测试步骤数组，每个步骤包含 step(序号), action(操作), expected(预期结果), data(测试数据，可选)
5. expected_result: 总体预期结果
6. priority: 优先级 (low, medium, high, critical)
7. case_type: 测试类型 (functional, ui, api, e2e, regression)
8. tags: 标签数组

请以JSON数组格式输出。"""),
            ("human", """请为以下用户故事生成 {count} 个测试用例：

US编号: {us_number}
标题: {title}
描述: {description}
验收标准: {acceptance_criteria}

验证点：
{validation_points}

请生成详细的测试用例，以JSON数组格式返回。""")
        ])
        
        chain = prompt_template | self.llm
        
        response = await chain.ainvoke({
            "count": count,
            "us_number": us_data.get("us_number"),
            "title": us_data.get("title"),
            "description": us_data.get("description"),
            "acceptance_criteria": us_data.get("acceptance_criteria", "未提供"),
            "validation_points": json.dumps(validation_points, ensure_ascii=False, indent=2)
        })
        
        # 解析响应
        try:
            content = response.content
            # 提取JSON部分
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            
            test_cases = json.loads(json_str)
            
            # 确保数据格式正确
            for tc in test_cases:
                if "steps" in tc and isinstance(tc["steps"], list):
                    for i, step in enumerate(tc["steps"]):
                        if isinstance(step, str):
                            tc["steps"][i] = {
                                "step": i + 1,
                                "action": step,
                                "expected": ""
                            }
            
            return test_cases
        except Exception as e:
            print(f"生成测试用例失败: {e}")
            return []
    
    async def generate_script(self, test_case: Dict[str, Any], 
                              framework: str = "midscene",
                              language: str = "javascript") -> Dict[str, Any]:
        """
        根据测试用例生成自动化脚本
        
        Args:
            test_case: 测试用例数据
            framework: 测试框架
            language: 编程语言
            
        Returns:
            脚本信息
        """
        framework_guide = {
            "midscene": """使用Midscene.js框架，基于AI驱动的UI自动化测试。
参考文档: https://midscenejs.com/
关键API:
- aiAction('描述要执行的操作') - 执行UI操作
- aiQuery('查询内容') - 查询UI元素信息
- aiAssert('断言内容') - 执行断言
示例:
```javascript
import { agent } from '@midscene/web';

await agent.aiAction('在搜索框输入"test"并点击搜索按钮');
const result = await agent.aiQuery('搜索结果列表');
await agent.aiAssert('页面显示搜索结果');
```""",
            "playwright": """使用Playwright框架。
示例:
```javascript
import { test, expect } from '@playwright/test';

test('test', async ({ page }) => {
  await page.goto('https://example.com');
  await page.fill('[name="search"]', 'test');
  await page.click('button[type="submit"]');
  await expect(page.locator('.results')).toBeVisible();
});
```"""
        }
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", f"""你是一位资深自动化测试工程师，擅长编写UI自动化测试脚本。
请根据测试用例生成可执行的自动化脚本。

框架指南：
{framework_guide.get(framework, framework_guide["midscene"])}

要求：
1. 脚本必须完整可执行
2. 包含必要的导入语句
3. 包含详细的注释
4. 使用描述性的选择器
5. 添加适当的等待和断言
6. 处理可能的异常情况

请以JSON格式输出，包含：code(完整代码), description(脚本描述), dependencies(依赖列表)"""),
            ("human", """请为以下测试用例生成 {framework} 框架的自动化脚本：

测试用例编号: {case_number}
标题: {title}
描述: {description}
前置条件: {preconditions}
测试步骤: {steps}
预期结果: {expected_result}

请生成完整的自动化脚本，以JSON格式返回。""")
        ])
        
        chain = prompt_template | self.llm
        
        response = await chain.ainvoke({
            "framework": framework,
            "case_number": test_case.get("case_number"),
            "title": test_case.get("title"),
            "description": test_case.get("description"),
            "preconditions": test_case.get("preconditions", "无"),
            "steps": json.dumps(test_case.get("steps", []), ensure_ascii=False, indent=2),
            "expected_result": test_case.get("expected_result")
        })
        
        # 解析响应
        try:
            content = response.content
            # 提取JSON部分
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            
            result = json.loads(json_str)
            return result
        except Exception as e:
            # 如果解析失败，直接返回代码
            return {
                "code": response.content,
                "description": f"基于测试用例 {test_case.get('case_number')} 生成的脚本",
                "dependencies": ["@midscene/web"] if framework == "midscene" else ["@playwright/test"]
            }
    
    async def analyze_execution_result(self, execution_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析执行结果，提供AI洞察
        
        Args:
            execution_data: 执行数据
            
        Returns:
            AI分析结果
        """
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", """你是一位测试分析专家，擅长分析自动化测试执行结果。
请根据执行数据提供详细的分析和建议。

分析内容应包括：
1. 执行概况总结
2. 失败原因分析（如有）
3. 改进建议
4. 风险评估

请以JSON格式输出。"""),
            ("human", """请分析以下测试执行结果：

执行编号: {execution_number}
测试脚本: {script_name}
执行状态: {status}
执行结果: {result}
总步骤: {total_steps}
通过步骤: {passed_steps}
失败步骤: {failed_steps}
执行时长: {duration}秒

步骤结果: {step_results}
错误信息: {error_message}

请提供详细的AI分析，以JSON格式返回。""")
        ])
        
        chain = prompt_template | self.llm
        
        response = await chain.ainvoke({
            "execution_number": execution_data.get("execution_number"),
            "script_name": execution_data.get("script_name"),
            "status": execution_data.get("status"),
            "result": execution_data.get("result"),
            "total_steps": execution_data.get("total_steps", 0),
            "passed_steps": execution_data.get("passed_steps", 0),
            "failed_steps": execution_data.get("failed_steps", 0),
            "duration": execution_data.get("duration", 0),
            "step_results": json.dumps(execution_data.get("step_results", []), ensure_ascii=False),
            "error_message": execution_data.get("error_message", "无")
        })
        
        try:
            content = response.content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            
            return json.loads(json_str)
        except Exception as e:
            return {
                "summary": "执行分析",
                "analysis": response.content,
                "recommendations": [],
                "risk_level": "unknown"
            }


# 全局AI服务实例
ai_service = AIService()
