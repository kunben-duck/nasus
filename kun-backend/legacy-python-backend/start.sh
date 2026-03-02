#!/bin/bash

# AutoTest Platform 启动脚本

echo "======================================"
echo "  AutoTest Platform - Backend"
echo "======================================"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python3，请先安装Python 3.11+"
    exit 1
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -r requirements.txt

# 检查环境变量
if [ ! -f ".env" ]; then
    echo "创建环境变量文件..."
    cp .env.example .env
    echo "请编辑 .env 文件配置您的环境变量"
fi

# 运行数据库迁移
echo "运行数据库迁移..."
alembic upgrade head

# 启动服务
echo "启动FastAPI服务..."
echo "API文档: http://localhost:8000/docs"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
