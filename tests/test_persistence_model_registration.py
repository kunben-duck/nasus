"""Model registration must not depend on store/router import order or a live DB."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_independent_model_registry_resolves_all_foreign_keys_without_database_work():
    script = """
from sqlalchemy.engine import Engine
def refuse_connection(*args, **kwargs):
    raise AssertionError('Model registration must not connect to a database')
Engine.connect = refuse_connection
from apps.api.app.infrastructure.persistence import db_models
from apps.api.app.infrastructure.persistence.database import Base
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects.postgresql import dialect
expected = {'quality_run_plans', 'quality_run_plan_build_bindings',
    'quality_run_plan_build_members', 'quality_native_build_results',
    'quality_run_plan_environment_records', 'quality_run_plan_observation_records', 'quality_run_plan_health_records',
    'quality_run_plan_locator_records', 'quality_http_fixture_commands', 'quality_http_fixture_dispatch_commands',
    'quality_http_fixture_cancellations', 'quality_http_fixture_cancellation_deliveries',
    'quality_http_fixture_preparations', 'quality_http_fixture_preparation_bindings',
    'quality_http_fixture_preparation_cancellations', 'quality_http_fixture_preparation_cancel_deliveries',
    'quality_run_plan_case_work', 'quality_run_plan_case_leases', 'quality_run_plan_case_claims',
    'quality_run_plan_case_outcomes', 'quality_run_plan_case_cancellations',
    'quality_run_plan_case_preparations', 'quality_run_plan_case_preparation_bindings'}
assert expected <= set(Base.metadata.tables)
for table in Base.metadata.tables.values():
    for foreign_key in table.foreign_keys:
        assert foreign_key.column.table.key in Base.metadata.tables
    assert str(CreateTable(table).compile(dialect=dialect()))
environment = Base.metadata.tables['quality_run_plan_environment_records']
parents = {constraint.referred_table.name for constraint in environment.foreign_key_constraints}
assert parents == {'quality_run_plans', 'quality_run_plan_build_bindings', 'tool_invocations'}
health = Base.metadata.tables['quality_run_plan_health_records']
assert {constraint.referred_table.name for constraint in health.foreign_key_constraints} == parents
assert {'health_hash', 'dependency_health_verified', 'target_health_verified'} <= set(health.columns.keys())
locators = Base.metadata.tables['quality_run_plan_locator_records']
assert {constraint.referred_table.name for constraint in locators.foreign_key_constraints} == {'quality_run_plans', 'tool_invocations'}
assert {'report_hash', 'inventory_hash', 'image_artifact_hash', 'manifest_hash'} <= set(locators.columns.keys())
commands = Base.metadata.tables['quality_http_fixture_commands']
assert {constraint.referred_table.name for constraint in commands.foreign_key_constraints} == {'tool_invocations', 'quality_http_fixture_grants'}
dispatch_commands = Base.metadata.tables['quality_http_fixture_dispatch_commands']
assert {constraint.referred_table.name for constraint in dispatch_commands.foreign_key_constraints} == {'quality_http_fixture_commands', 'quality_http_fixture_dispatches'}
cancellations = Base.metadata.tables['quality_http_fixture_cancellations']
assert {constraint.referred_table.name for constraint in cancellations.foreign_key_constraints} == {'quality_http_fixture_commands', 'tool_invocations'}
deliveries = Base.metadata.tables['quality_http_fixture_cancellation_deliveries']
assert {constraint.referred_table.name for constraint in deliveries.foreign_key_constraints} == {'quality_http_fixture_cancellations'}
preparations = Base.metadata.tables['quality_http_fixture_preparations']
assert {constraint.referred_table.name for constraint in preparations.foreign_key_constraints} == {'tool_invocations'}
bindings = Base.metadata.tables['quality_http_fixture_preparation_bindings']
assert {constraint.referred_table.name for constraint in bindings.foreign_key_constraints} == {'quality_http_fixture_preparations', 'quality_http_fixture_commands'}
preparation_cancellations = Base.metadata.tables['quality_http_fixture_preparation_cancellations']
assert {constraint.referred_table.name for constraint in preparation_cancellations.foreign_key_constraints} == {'quality_http_fixture_preparations', 'tool_invocations'}
preparation_deliveries = Base.metadata.tables['quality_http_fixture_preparation_cancel_deliveries']
assert {constraint.referred_table.name for constraint in preparation_deliveries.foreign_key_constraints} == {'quality_http_fixture_preparation_cancellations'}
case_work = Base.metadata.tables['quality_run_plan_case_work']
assert {constraint.referred_table.name for constraint in case_work.foreign_key_constraints} == {'quality_run_plans', 'tool_invocations'}
case_claims = Base.metadata.tables['quality_run_plan_case_claims']
assert {constraint.referred_table.name for constraint in case_claims.foreign_key_constraints} == {'quality_run_plan_case_work'}
case_outcomes = Base.metadata.tables['quality_run_plan_case_outcomes']
assert {constraint.referred_table.name for constraint in case_outcomes.foreign_key_constraints} == {'quality_run_plan_case_claims'}
case_preparations = Base.metadata.tables['quality_run_plan_case_preparations']
assert {constraint.referred_table.name for constraint in case_preparations.foreign_key_constraints} == {'tool_invocations'}
case_bindings = Base.metadata.tables['quality_run_plan_case_preparation_bindings']
assert {constraint.referred_table.name for constraint in case_bindings.foreign_key_constraints} == {'quality_run_plan_case_preparations', 'quality_run_plan_case_work'}
print('All model foreign keys resolve; PostgreSQL DDL compiles without connection')
"""
    env = {**os.environ, "NASUS_DATABASE_URL": "postgresql+psycopg://metadata@127.0.0.1:1/nasus_metadata_probe",
           "NASUS_AUTO_CREATE_TABLES": "false"}
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "All model foreign keys resolve; PostgreSQL DDL compiles without connection"
