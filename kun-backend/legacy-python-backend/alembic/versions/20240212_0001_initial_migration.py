"""Initial migration

Revision ID: 0001_initial
Revises:
Create Date: 2024-02-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 创建用户表
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('email', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('is_superuser', sa.Boolean, default=False),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('last_login', sa.DateTime, nullable=True),
    )
    
    # 创建用户故事表
    op.create_table(
        'user_stories',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('us_number', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('acceptance_criteria', sa.Text, nullable=True),
        sa.Column('ai_analysis', postgresql.JSON, nullable=True),
        sa.Column('validation_points', postgresql.JSON, nullable=True),
        sa.Column('status', sa.Enum('pending', 'analyzing', 'analyzed', 'generating', 'completed', 'failed', name='usstatus'), nullable=False),
        sa.Column('progress', sa.Integer, default=0),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('analyzed_at', sa.DateTime, nullable=True),
    )
    
    # 创建测试用例表
    op.create_table(
        'test_cases',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('case_number', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('preconditions', sa.Text, nullable=True),
        sa.Column('steps', postgresql.JSON, nullable=False),
        sa.Column('expected_result', sa.Text, nullable=False),
        sa.Column('priority', sa.Enum('low', 'medium', 'high', 'critical', name='testcasepriority'), nullable=False),
        sa.Column('case_type', sa.Enum('functional', 'ui', 'api', 'e2e', 'regression', name='testcasetype'), nullable=False),
        sa.Column('tags', postgresql.JSON, nullable=True),
        sa.Column('us_id', sa.String(36), sa.ForeignKey('user_stories.id'), nullable=False),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.Enum('draft', 'pending', 'generating', 'completed', 'failed', name='testcasestatus'), nullable=False),
        sa.Column('ai_generated', sa.Boolean, default=True),
        sa.Column('generation_metadata', postgresql.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # 创建脚本表
    op.create_table(
        'scripts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('script_number', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('code', sa.Text, nullable=False),
        sa.Column('language', sa.Enum('javascript', 'typescript', 'python', name='scriptlanguage'), nullable=False),
        sa.Column('framework', sa.Enum('midscene', 'playwright', 'selenium', 'cypress', name='scriptframework'), nullable=False),
        sa.Column('test_case_id', sa.String(36), sa.ForeignKey('test_cases.id'), nullable=False),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.Enum('draft', 'generating', 'completed', 'validating', 'validated', 'failed', name='scriptstatus'), nullable=False),
        sa.Column('ai_generated', sa.Boolean, default=True),
        sa.Column('generation_metadata', postgresql.JSON, nullable=True),
        sa.Column('validated', sa.Boolean, default=False),
        sa.Column('validated_at', sa.DateTime, nullable=True),
        sa.Column('validation_result', postgresql.JSON, nullable=True),
        sa.Column('version', sa.String(20), default='1.0.0'),
        sa.Column('parent_id', sa.String(36), sa.ForeignKey('scripts.id'), nullable=True),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # 创建执行记录表
    op.create_table(
        'executions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('execution_number', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('script_id', sa.String(36), sa.ForeignKey('scripts.id'), nullable=False),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('config', postgresql.JSON, nullable=True),
        sa.Column('parameters', postgresql.JSON, nullable=True),
        sa.Column('status', sa.Enum('pending', 'queued', 'running', 'completed', 'failed', 'cancelled', 'timeout', name='executionstatus'), nullable=False),
        sa.Column('result', sa.Enum('passed', 'failed', 'skipped', 'error', 'unknown', name='executionresult'), nullable=True),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('duration', sa.Float, nullable=True),
        sa.Column('total_steps', sa.Integer, default=0),
        sa.Column('passed_steps', sa.Integer, default=0),
        sa.Column('failed_steps', sa.Integer, default=0),
        sa.Column('output', sa.Text, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('step_results', postgresql.JSON, nullable=True),
        sa.Column('screenshot_urls', postgresql.JSON, nullable=True),
        sa.Column('video_url', sa.String(500), nullable=True),
        sa.Column('log_url', sa.String(500), nullable=True),
        sa.Column('report_url', sa.String(500), nullable=True),
        sa.Column('ai_analysis', postgresql.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade():
    # 删除表（按依赖顺序）
    op.drop_table('executions')
    op.drop_table('scripts')
    op.drop_table('test_cases')
    op.drop_table('user_stories')
    op.drop_table('users')
    
    # 删除枚举类型
    op.execute('DROP TYPE IF EXISTS executionstatus')
    op.execute('DROP TYPE IF EXISTS executionresult')
    op.execute('DROP TYPE IF EXISTS scriptstatus')
    op.execute('DROP TYPE IF EXISTS scriptlanguage')
    op.execute('DROP TYPE IF EXISTS scriptframework')
    op.execute('DROP TYPE IF EXISTS testcasestatus')
    op.execute('DROP TYPE IF EXISTS testcasepriority')
    op.execute('DROP TYPE IF EXISTS testcasetype')
    op.execute('DROP TYPE IF EXISTS usstatus')
