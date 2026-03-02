# AutoTest Platform - Backend

自动化测试平台后端服务，基于Python FastAPI构建。

## 技术栈

- **框架**: FastAPI
- **数据库**: PostgreSQL + SQLAlchemy (异步)
- **ORM**: SQLAlchemy 2.0
- **迁移**: Alembic
- **AI服务**: LangChain + OpenAI
- **任务队列**: Celery + Redis
- **文件存储**: MinIO
- **认证**: JWT

## 项目结构

```
backend/
├── app/
│   ├── api/              # API路由
│   │   ├── auth.py       # 认证相关
│   │   ├── user_stories.py  # US管理
│   │   ├── test_cases.py    # 测试用例
│   │   ├── scripts.py       # 脚本管理
│   │   ├── executions.py    # 执行管理
│   │   └── dashboard.py     # 仪表盘
│   ├── core/             # 核心配置
│   │   ├── config.py     # 应用配置
│   │   └── security.py   # 安全相关
│   ├── db/               # 数据库
│   │   └── base.py       # 数据库基础配置
│   ├── models/           # 数据模型
│   │   ├── user.py
│   │   ├── user_story.py
│   │   ├── test_case.py
│   │   ├── script.py
│   │   └── execution.py
│   ├── schemas/          # Pydantic Schema
│   │   ├── user.py
│   │   ├── user_story.py
│   │   ├── test_case.py
│   │   ├── script.py
│   │   └── execution.py
│   ├── services/         # 业务服务
│   │   ├── ai_service.py     # AI服务
│   │   └── storage_service.py # 存储服务
│   ├── tasks/            # Celery任务
│   │   ├── celery_app.py
│   │   ├── us_tasks.py
│   │   ├── script_tasks.py
│   │   └── execution_tasks.py
│   ├── websocket/        # WebSocket
│   │   └── execution_ws.py
│   ├── __init__.py
│   └── main.py           # 应用入口
├── alembic/              # 数据库迁移
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── start.sh
└── README.md
```

## 快速开始

### 方式一：使用Docker Compose（推荐）

1. 克隆项目并进入backend目录

2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件，设置 OPENAI_API_KEY 等配置
```

3. 启动服务
```bash
docker-compose up -d
```

4. 访问服务
- API: http://localhost:8000
- API文档: http://localhost:8000/docs
- Flower监控: http://localhost:5555
- MinIO控制台: http://localhost:9001

### 方式二：本地开发

1. 创建虚拟环境
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件
```

4. 启动PostgreSQL和Redis
```bash
# 可以使用Docker启动依赖服务
docker-compose up -d postgres redis minio
```

5. 运行数据库迁移
```bash
alembic upgrade head
```

6. 启动服务
```bash
# 启动FastAPI服务
uvicorn app.main:app --reload

# 启动Celery Worker（另一个终端）
celery -A app.tasks.celery_app worker --loglevel=info

# 启动Celery Beat（可选，用于定时任务）
celery -A app.tasks.celery_app beat --loglevel=info
```

## API文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 核心功能

### 1. 用户故事(US)管理
- 创建/编辑/删除US
- AI智能分析，提取验证点
- 自动生成测试用例

### 2. 测试用例管理
- 测试用例CRUD
- 支持优先级、类型分类
- AI生成脚本

### 3. 脚本管理
- 自动化脚本CRUD
- 支持多种框架(Midscene.js, Playwright等)
- 脚本语法验证

### 4. 执行管理
- 创建执行记录
- 异步执行测试
- 实时WebSocket推送
- 录屏和截图存储

### 5. 仪表盘
- 统计数据汇总
- 执行趋势分析
- 活动动态

## Celery任务队列

### 队列配置
- `default`: 默认队列
- `us_analysis`: US分析队列
- `script_generation`: 脚本生成队列
- `test_execution`: 测试执行队列

### 常用命令
```bash
# 启动Worker
celery -A app.tasks.celery_app worker --loglevel=info

# 启动特定队列的Worker
celery -A app.tasks.celery_app worker -Q us_analysis --loglevel=info

# 启动Flower监控
celery -A app.tasks.celery_app flower --port=5555

# 查看任务状态
celery -A app.tasks.celery_app inspect active
```

## 数据库迁移

```bash
# 创建迁移
alembic revision --autogenerate -m "描述"

# 升级数据库
alembic upgrade head

# 降级数据库
alembic downgrade -1

# 查看历史
alembic history
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| DATABASE_URL | 异步数据库连接 | postgresql+asyncpg://... |
| DATABASE_URL_SYNC | 同步数据库连接 | postgresql://... |
| REDIS_URL | Redis连接 | redis://localhost:6379/0 |
| SECRET_KEY | JWT密钥 | - |
| OPENAI_API_KEY | OpenAI API密钥 | - |
| MINIO_ENDPOINT | MinIO地址 | localhost:9000 |
| CELERY_BROKER_URL | Celery Broker | redis://localhost:6379/0 |

## 开发指南

### 添加新API

1. 在 `app/schemas/` 创建Schema
2. 在 `app/api/` 创建路由
3. 在 `app/api/__init__.py` 注册路由

### 添加新模型

1. 在 `app/models/` 创建模型
2. 创建Alembic迁移
3. 更新 `app/models/__init__.py`

### 添加Celery任务

1. 在 `app/tasks/` 创建任务
2. 在 `app/tasks/celery_app.py` 导入

## 许可证

MIT
