"""
Alembic环境配置
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import context

# 导入应用配置和模型
from app.core.config import settings
from app.db.base import Base
from app.models import *  # 导入所有模型

# 这是Alembic配置对象
config = context.config

# 解释配置文件中的Python日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 添加模型元数据
target_metadata = Base.metadata

# 从环境变量获取数据库URL
def get_url():
    return settings.DATABASE_URL_SYNC


def run_migrations_offline():
    """以离线模式运行迁移"""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """执行迁移"""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """以在线模式运行迁移"""
    # 创建同步引擎
    from sqlalchemy import create_engine
    
    connectable = create_engine(
        get_url(),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
