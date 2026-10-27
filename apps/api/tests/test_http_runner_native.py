"""Actual Node HTTP transport and private MinIO, not an exweb business oracle.

The HTTP execution receipt is not yet a canonical RunPlan execution fact.
"""
import base64
from dataclasses import replace
import hashlib
import json
from dataclasses import asdict
from uuid import uuid4

import pytest

from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
from apps.api.app.domain.quality_loop.http_runner_observations import verify_http_runner_observations
from apps.api.app.infrastructure.runner.http_observation_artifacts import verify_http_response_artifacts
from apps.api.app.infrastructure.runner.request_wire import runner_request_hash
from apps.api.tests.test_runner_observations_native import native_runner


def request(path='/http-proof', ident='original'):
    return dict(action='request', request_id=ident, method='GET', path=path, headers_json='{}', body_json='null')


def oracle(action, **values):
    return dict(action=action, request_id='original', **values)


@pytest.mark.parametrize('kind,status,states,observed,passed', [
    ('complete', 'passed', ['passed'] * 5, 4, 4),
    ('failure', 'failed', ['passed', 'failed', 'not_executed'], 1, 0),
    ('precise', 'failed', ['passed', 'failed'], 1, 0),
    ('duplicate', 'failed', ['passed', 'failed'], 1, 0),
    ('deadline', 'timed_out', ['interrupted', 'not_executed'], 0, 0),
    ('empty', 'passed', ['passed', 'passed'], 1, 1),
    ('post', 'passed', ['passed', 'passed'], 1, 1),
])
def test_actual_http_oracles_and_original_bytes_survive_private_archive(native_runner, kind, status, states, observed, passed):
    runner, base_url, storage = native_runner
    steps = [request()]
    if kind == 'complete':
        steps.extend([oracle('assert_status', value='200'), oracle('assert_header', name='X-Proof', value='observed'),
            oracle('assert_json', pointer='/nested/a~1b/~0key/0', value_json='1.0'),
            oracle('assert_body', value='native HTTP fixture')])
    if kind == 'failure':
        steps = [request('/http-failure'), oracle('assert_status', value='200'), request('/http-must-not-run', 'later')]
    if kind in {'precise', 'duplicate'}:
        steps = [request('/http-' + kind), oracle('assert_json', pointer='/value', value_json='0.1' if kind == 'precise' else '1')]
    if kind == 'deadline': steps = [request('/http-slow'), oracle('assert_status', value='200')]
    if kind == 'empty': steps = [request('/http-empty'), oracle('assert_status', value='204')]
    if kind == 'post':
        original = {**request(ident='request_\u6d4b\u8bd5'), 'method': 'POST', 'body_json': '{ "message": "\u4e2d\u6587", "first": 1 }'}
        steps = [original, {**oracle('assert_json', pointer='/body', value_json=json.dumps(original['body_json'], ensure_ascii=False)),
            'request_id': original['request_id']}]
    value = AutomationRunnerCommand(job_id='native-http-' + uuid4().hex, project_id='native-http-project',
        us_id='explicit-local-http-fixture', base_url=base_url, steps=tuple(steps), timeout_ms=1000 if kind == 'deadline' else 5000, kind='http')
    result = runner.execute(value)
    assert result.status == status, result.failure_summary
    assert result.runner_mode == 'http_native'
    receipt = result.execution_receipt
    assert [step['status'] for step in receipt['steps']] == states
    assert receipt['observed_assertion_count'] == observed and receipt['passed_assertion_count'] == passed
    assert receipt['target_build_verified'] is receipt['business_coverage_verified'] is False
    archived = []
    prefix = 'http-runner-native-tests/' + uuid4().hex
    for item in result.artifacts:
        body = base64.b64decode(item.content_base64, validate=True)
        stored = storage.put_bytes(prefix + '/' + item.name, body, content_type=item.media_type)
        assert stored.storage_ref.startswith('s3://')
        original = storage.get_bytes(stored.storage_ref)
        assert original == body and stored.content_hash == 'sha256:' + hashlib.sha256(original).hexdigest()
        archived.append(dict(artifact_type=item.artifact_type, name=item.name, media_type=item.media_type,
            content_base64=base64.b64encode(original).decode('ascii')))
    original_receipt = json.loads(base64.b64decode(next(item['content_base64'] for item in archived if item['name'] == 'http-execution.json')))
    assert verify_http_runner_observations(original_receipt, job_id=value.job_id, project_id=value.project_id,
        us_id=value.us_id, request_hash=runner_request_hash(value), steps=value.steps, status=status) == receipt
    verify_http_response_artifacts(original_receipt, archived, value.steps)
    if kind == 'empty': assert next(item['content_base64'] for item in archived if item['name'].endswith('.bin')) == ''


def test_actual_runner_requires_service_authentication_and_rejects_unbound_http_jobs(native_runner):
    runner, base_url, _storage = native_runner
    value = AutomationRunnerCommand(job_id='native-http-invalid', project_id='fixture-project', us_id='fixture-case',
        base_url=base_url, steps=(request(),), timeout_ms=2000, kind='http')
    wrong_token = type(runner)(runner.endpoint, 'wrong-protocol-only-service-token')
    denied = wrong_token.execute(value)
    assert denied.status == 'error' and denied.execution_receipt is None and not denied.artifacts
    invalid = runner.execute(replace(value, steps=(dict(request(), headers_json='{"Authorization":"not-an-authorized-fixture"}'),)))
    assert invalid.status == 'error' and invalid.execution_receipt is None and not invalid.artifacts


def test_original_plan_cases_and_failed_oracles_survive_native_runner_and_private_archive(native_runner):
    from apps.api.app.application.quality_loop.run_plan_observations import RunPlanObservationApplicationService
    from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
    from apps.api.app.domain.quality_loop.run_plan_observations import collect_run_plan_observations
    from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
    from apps.api.tests.test_run_plan_observations import http_plan

    runner, base_url, storage = native_runner
    plan = http_plan(base_url, request_path='/http-proof')
    service = RunPlanObservationApplicationService(HTTPRunnerObservationVerifier())
    commands = service.commands(plan, run_id='native-case-attempt-' + uuid4().hex, timeout_ms=5000)
    observations, raw_results = [], []
    for command in commands:
        result = runner.execute(command)
        assert result.status == 'failed', result.failure_summary
        observed = service.observe_http(plan, command, result)
        assert observed['case_id'] == command.us_id
        assert observed['oracles'][0]['status'] == 'failed'
        assert all(item['status'] == 'not_executed' for item in observed['oracles'][1:])
        observations.append(observed)
        raw_results.append(dict(case_id=command.us_id, receipt=result.execution_receipt, artifacts=[dict(
            artifact_type=item.artifact_type, name=item.name, media_type=item.media_type, content_base64=item.content_base64)
            for item in result.artifacts]))
    summary = collect_run_plan_observations(plan, observations)
    assert summary['observed_case_count'] == summary['failed_observation_count'] == len(commands)
    assert summary['passed_count'] == summary['executed_on_target_count'] == 0
    payload = dict(plan=plan, observations=observations, summary=summary, raw_results=raw_results)
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    stored = storage.put_bytes('http-runner-native-tests/' + uuid4().hex + '/original-case-observations.json', body, content_type='application/json')
    replay = json.loads(ObjectStorage().get_bytes(stored.storage_ref))
    assert replay == payload and acceptance_digest(replay['plan']) == acceptance_digest(plan)
    assert collect_run_plan_observations(replay['plan'], replay['observations']) == summary
    for command, raw in zip(commands, replay['raw_results']):
        verify_http_response_artifacts(raw['receipt'], raw['artifacts'], command.steps)


def test_private_application_archive_replays_native_http_case_observations_without_runner(native_runner):
    from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveApplicationService
    from apps.api.app.infrastructure.storage.run_plan_observation_artifacts import RunPlanObservationArtifacts
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
    from apps.api.tests.test_run_plan_observation_archives import OriginalPlanAccessSpecimen
    from apps.api.tests.test_run_plan_observations import http_plan, observation_service

    runner, base_url, storage = native_runner
    plan = http_plan(base_url, request_path='/http-proof')
    observations = observation_service()
    attempt = 'native-archive-attempt-' + uuid4().hex
    commands = observations.commands(plan, run_id=attempt, timeout_ms=5000)
    entries = [{'runner_job_id': command.job_id, 'result': asdict(runner.execute(command))} for command in commands]
    assert all(item['result']['status'] == 'failed' for item in entries)
    service = RunPlanObservationArchiveApplicationService(observations, RunPlanObservationArtifacts(storage), OriginalPlanAccessSpecimen(plan))
    saved = service.archive(plan, entries, run_id=attempt, timeout_ms=5000)
    assert saved['artifact_ref'].startswith('s3://')
    fresh = RunPlanObservationArchiveApplicationService(observation_service(), RunPlanObservationArtifacts(ObjectStorage()), OriginalPlanAccessSpecimen(plan))
    replay = fresh.read(plan['project_id'], saved['artifact_ref'], saved['artifact_hash'], plan_digest=plan['plan_digest'])
    assert replay['summary']['failed_observation_count'] == replay['summary']['observed_case_count'] == len(commands)
    assert replay['summary']['passed_count'] == replay['summary']['executed_on_target_count'] == 0
    assert replay['canonical_execution_committed'] is replay['execution_authorized'] is False


def test_lost_runner_reply_is_archived_as_unknown_without_repeating_the_request(native_runner):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import socket
    from threading import Thread
    from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveApplicationService
    from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
    from apps.api.app.infrastructure.runner.request_wire import runner_request_body
    from apps.api.app.infrastructure.storage.run_plan_observation_artifacts import RunPlanObservationArtifacts
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
    from apps.api.tests.test_run_plan_observation_archives import OriginalPlanAccessSpecimen
    from apps.api.tests.test_run_plan_observations import http_plan, observation_service

    runner, base_url, storage = native_runner
    received = []
    class LostReply(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers['Content-Length'])))
            # A real adapter request arrived, but no native target outcome is proven.
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
        def log_message(self, *args): pass

    endpoint = ThreadingHTTPServer(('127.0.0.1', 0), LostReply)
    thread = Thread(target=endpoint.serve_forever, daemon=True)
    thread.start()
    try:
        plan = http_plan(base_url, request_path='/http-proof')
        observations = observation_service()
        attempt = 'native-lost-reply-' + uuid4().hex
        commands = observations.commands(plan, run_id=attempt, timeout_ms=5000)
        dropped = HttpAutomationRunner(f'http://127.0.0.1:{endpoint.server_port}', 'explicit-transport-specimen-token',
            request_timeout_seconds=2).execute(commands[0])
        assert dropped.status == 'error' and dropped.execution_receipt is None and not dropped.artifacts
        assert received == [runner_request_body(commands[0])]
        entries = [{'runner_job_id': commands[0].job_id, 'result': asdict(dropped)}]
        entries.extend({'runner_job_id': command.job_id, 'result': asdict(runner.execute(command))} for command in commands[1:])
        service = RunPlanObservationArchiveApplicationService(observations, RunPlanObservationArtifacts(storage), OriginalPlanAccessSpecimen(plan))
        saved = service.archive(plan, entries, run_id=attempt, timeout_ms=5000)
        fresh = RunPlanObservationArchiveApplicationService(observation_service(), RunPlanObservationArtifacts(ObjectStorage()), OriginalPlanAccessSpecimen(plan))
        replay = fresh.read(plan['project_id'], saved['artifact_ref'], saved['artifact_hash'], plan_digest=plan['plan_digest'])
        assert replay['summary']['outcome_unknown_case_count'] == 1
        assert replay['summary']['failed_observation_count'] == len(commands) - 1
        assert replay['summary']['no_result_case_count'] == 0
        assert replay['unverified_attempts'][0]['native_dispatch_verified'] is False
        assert replay['summary']['passed_count'] == replay['summary']['executed_on_target_count'] == 0
        assert replay['raw_results'][0]['result'] == json.loads(json.dumps(asdict(dropped)))
        assert received == [runner_request_body(commands[0])]
    finally:
        endpoint.shutdown()
        endpoint.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_valid_native_timeout_receipt_is_preserved_without_unknown_downgrade(native_runner):
    from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveApplicationService
    from apps.api.app.infrastructure.storage.run_plan_observation_artifacts import RunPlanObservationArtifacts
    from apps.api.tests.test_run_plan_observation_archives import OriginalPlanAccessSpecimen
    from apps.api.tests.test_run_plan_observations import http_plan, observation_service

    runner, base_url, storage = native_runner
    plan = http_plan(base_url, request_path='/http-slow')
    observations = observation_service()
    attempt = 'native-original-deadline-' + uuid4().hex
    commands = observations.commands(plan, run_id=attempt, timeout_ms=1000)
    results = [runner.execute(command) for command in commands]
    assert all(result.status == 'timed_out' and result.execution_receipt is not None for result in results)
    entries = [{'runner_job_id': command.job_id, 'result': asdict(result)} for command, result in zip(commands, results)]
    service = RunPlanObservationArchiveApplicationService(observations, RunPlanObservationArtifacts(storage), OriginalPlanAccessSpecimen(plan))
    saved = service.archive(plan, entries, run_id=attempt, timeout_ms=1000)
    replay = service.read(plan['project_id'], saved['artifact_ref'], saved['artifact_hash'], plan_digest=plan['plan_digest'])
    assert replay['schema'] == 'nasus.run-plan-observation-archive.v1' and 'unverified_attempts' not in replay
    assert replay['summary']['observed_case_count'] == len(commands)
    assert all(item['status'] == 'timed_out' for item in replay['observations'])
    assert all(all(oracle['status'] == 'not_executed' for oracle in item['oracles']) for item in replay['observations'])
    assert replay['summary']['passed_count'] == replay['summary']['executed_on_target_count'] == 0
