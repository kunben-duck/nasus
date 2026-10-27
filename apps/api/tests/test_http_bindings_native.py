"""Actual authenticated Node HTTP and private MinIO; local contract target, not business gold."""
import base64
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time
from uuid import uuid4

import pytest

from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand, AutomationRunnerResult, RunnerArtifact
from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.tests.test_http_bindings import command, digest, request, wire
from apps.api.tests.test_runner_observations_native import native_runner


@pytest.fixture
def binding_target():
    sessions, visits = {}, []
    class Target(BaseHTTPRequestHandler):
        def respond(self):
            visits.append((self.command, self.path))
            status = 200
            if self.command == 'POST' and self.path == '/sessions':
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                ident = 'session_' + uuid4().hex
                body = sessions[ident] = dict(sessionId=ident, status='ACTIVE', title=payload['title'])
            elif self.path.startswith('/sessions/'):
                ident = self.path.split('/')[2]
                body = sessions[ident].copy()
                if self.path.endswith('/close'):
                    body['status'] = sessions[ident]['status'] = 'CLOSED'
                elif self.path.endswith('/slow'):
                    time.sleep(1.25)
                elif body['status'] == 'CLOSED':
                    status, body = 500, dict(error='deliberate local negative contract fixture')
            else:
                status, body = 404, dict(error='fixture_not_found')
            raw = wire(body)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError): pass
        do_POST = do_GET = respond
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Target)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), sessions, visits
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.mark.parametrize('kind,status', [('complete', 'passed'), ('closed_error', 'failed'), ('deadline', 'timed_out')])
def test_actual_single_job_binds_dynamic_resource_and_replays_original_private_bytes(native_runner, binding_target, kind, status):
    runner, _unused_target, storage = native_runner
    base_url, sessions, visits = binding_target
    value = replace(command(), base_url=base_url, job_id='native-binding-' + uuid4().hex, timeout_ms=5000)
    if kind == 'closed_error':
        value = replace(value, steps=value.steps + (request('closed', '/sessions/{{session}}', 'GET'),
            dict(action='assert_status', request_id='closed', value='404')))
    if kind == 'deadline':
        value = replace(value, timeout_ms=1000, steps=value.steps[:3] + (request('slow', '/sessions/{{session}}/slow', 'GET'),))
    result = runner.execute(value)
    assert result.status == status, result.failure_summary
    receipt = HTTPRunnerObservationVerifier().verify(value, result)
    assert len(sessions) == 1 and visits[0] == ('POST', '/sessions')
    ident = next(iter(sessions))
    assert receipt['bindings'][0]['value'] == ident
    assert receipt['bindings'][0]['response_hash'] == receipt['requests'][0]['response_hash']
    assert visits[1][1] == '/sessions/' + ident + ('/slow' if kind == 'deadline' else '')
    assert receipt['steps'][2]['kind'] == 'action'
    assert receipt['passed_assertion_count'] == (1 if kind == 'deadline' else 3)
    assert receipt['failed_assertion_count'] == (1 if kind == 'closed_error' else 0)
    if kind == 'closed_error':
        assert receipt['requests'][-1]['response_status'] == 500
    if kind == 'deadline':
        assert receipt['steps'][-1]['status'] == 'interrupted' and len(receipt['requests']) == 1
    assert receipt['target_build_verified'] is receipt['business_coverage_verified'] is False

    payload = dict(command=asdict(value), result=asdict(result))
    raw = wire(payload)
    stored = storage.put_bytes('http-binding-native-tests/' + uuid4().hex + '/original.json', raw, content_type='application/json')
    assert stored.storage_ref.startswith('s3://')
    original = ObjectStorage().get_bytes(stored.storage_ref)
    assert original == raw and stored.content_hash == digest(original)
    replay = json.loads(original)
    recovered = AutomationRunnerCommand(**{**replay['command'], 'steps': tuple(replay['command']['steps'])})
    assert recovered == value
    archived = replay['result']
    rehydrated = AutomationRunnerResult(**{**archived, 'artifacts': tuple(RunnerArtifact(**item) for item in archived['artifacts']),
        'timeline': tuple(archived['timeline'])})
    assert HTTPRunnerObservationVerifier().verify(recovered, rehydrated) == receipt
    for item in rehydrated.artifacts:
        body = base64.b64decode(item.content_base64, validate=True)
        if item.name.endswith('.bin'):
            observed = next(row for row in receipt['requests'] if item.name == 'http-response-' + row['request_id'] + '.bin')
            assert observed['response_hash'] == digest(body) and observed['response_byte_count'] == len(body)


def test_binding_job_still_requires_authentication_and_explicit_version(native_runner, binding_target):
    runner, _unused_target, _storage = native_runner
    base_url, _sessions, visits = binding_target
    value = replace(command(), base_url=base_url)
    unauthorized = type(runner)(runner.endpoint, 'not-the-service-token').execute(value)
    assert unauthorized.status == 'error' and unauthorized.execution_receipt is None and visits == []
    old_protocol = runner.execute(replace(value, http_protocol='nasus.runner-http-execution.v1'))
    assert old_protocol.status == 'error' and old_protocol.execution_receipt is None and visits == []
