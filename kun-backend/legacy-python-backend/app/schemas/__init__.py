"""
Schema模块
"""
from app.schemas.user import (
    UserBase, UserCreate, UserUpdate, UserInDB, UserResponse,
    UserLogin, Token, TokenPayload
)
from app.schemas.user_story import (
    UserStoryBase, UserStoryCreate, UserStoryUpdate, UserStoryInDB, UserStoryResponse,
    UserStoryListResponse, AIAnalysisRequest, AIAnalysisResponse,
    GenerateTestCasesRequest, GenerateTestCasesResponse, ValidationPoint
)
from app.schemas.test_case import (
    TestCaseBase, TestCaseCreate, TestCaseUpdate, TestCaseInDB, TestCaseResponse,
    TestCaseListResponse, GenerateScriptRequest, GenerateScriptResponse,
    TestStep
)
from app.schemas.script import (
    ScriptBase, ScriptCreate, ScriptUpdate, ScriptInDB, ScriptResponse,
    ScriptListResponse, ValidateScriptRequest, ValidateScriptResponse
)
from app.schemas.execution import (
    ExecutionBase, ExecutionCreate, ExecutionUpdate, ExecutionInDB, ExecutionResponse,
    ExecutionListResponse, ExecutionStartRequest, ExecutionStartResponse,
    ExecutionStopRequest, ExecutionConfig, ExecutionStepResult, ExecutionRealtimeData
)

__all__ = [
    # User
    "UserBase", "UserCreate", "UserUpdate", "UserInDB", "UserResponse",
    "UserLogin", "Token", "TokenPayload",
    # User Story
    "UserStoryBase", "UserStoryCreate", "UserStoryUpdate", "UserStoryInDB", "UserStoryResponse",
    "UserStoryListResponse", "AIAnalysisRequest", "AIAnalysisResponse",
    "GenerateTestCasesRequest", "GenerateTestCasesResponse", "ValidationPoint",
    # Test Case
    "TestCaseBase", "TestCaseCreate", "TestCaseUpdate", "TestCaseInDB", "TestCaseResponse",
    "TestCaseListResponse", "GenerateScriptRequest", "GenerateScriptResponse", "TestStep",
    # Script
    "ScriptBase", "ScriptCreate", "ScriptUpdate", "ScriptInDB", "ScriptResponse",
    "ScriptListResponse", "ValidateScriptRequest", "ValidateScriptResponse",
    # Execution
    "ExecutionBase", "ExecutionCreate", "ExecutionUpdate", "ExecutionInDB", "ExecutionResponse",
    "ExecutionListResponse", "ExecutionStartRequest", "ExecutionStartResponse",
    "ExecutionStopRequest", "ExecutionConfig", "ExecutionStepResult", "ExecutionRealtimeData",
]
