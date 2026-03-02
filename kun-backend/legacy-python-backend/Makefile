.PHONY: help install run dev migrate test clean docker-build docker-up docker-down

help:
	@echo "AutoTest Platform Backend"
	@echo ""
	@echo "可用命令:"
	@echo "  make install      - 安装依赖"
	@echo "  make run          - 运行服务"
	@echo "  make dev          - 开发模式运行（带热重载）"
	@echo "  make migrate      - 运行数据库迁移"
	@echo "  make migrate-create - 创建新的迁移"
	@echo "  make test         - 运行测试"
	@echo "  make clean        - 清理缓存文件"
	@echo "  make docker-up    - 使用Docker Compose启动"
	@echo "  make docker-down  - 停止Docker Compose"
	@echo "  make worker       - 启动Celery Worker"
	@echo "  make flower       - 启动Flower监控"

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

dev:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

migrate:
	alembic upgrade head

migrate-create:
	@read -p "输入迁移描述: " desc; \
	alembic revision --autogenerate -m "$$desc"

test:
	pytest -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

worker:
	celery -A app.tasks.celery_app worker --loglevel=info -Q default,us_analysis,script_generation,test_execution

flower:
	celery -A app.tasks.celery_app flower --port=5555

beat:
	celery -A app.tasks.celery_app beat --loglevel=info
