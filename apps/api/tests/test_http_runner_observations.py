"""HTTP observations bind physical bytes, exact oracles and original steps.

Protocol specimens here are not native exweb execution or business approval.
"""
import base64
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json

import httpx
import pytest

from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
from apps.api.app.domain.quality_loop.http_runner_observations import (
    HTTP_ASSERTIONS, HTTP_RUNNER_RECEIPT_SCHEMA, http_step_input_hash, verify_http_runner_observations,
)
from apps.api.app.domain.quality_loop.http_runner_oracles import strict_http_json
from apps.api.app.domain.quality_loop.runner_observations import RunnerObservationInvalid
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_observation_artifacts import verify_http_response_artifacts
from apps.api.app.infrastructure.runner.request_wire import runner_request_body, runner_request_hash


def _wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _hash(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def request(ident='original'):
    return dict(action='request', request_id=ident, method='GET', path='/', headers_json='{}', body_json='null')


def oracle(action, **fields):
    return dict(action=action, request_id='original', **fields)


def command():
    return AutomationRunnerCommand(job_id='http-job', project_id='http-project', us_id='http-case',
        base_url='http://127.0.0.1:32123', timeout_ms=2000, kind='http', steps=(request(),
            oracle('assert_status', value='200'), oracle('assert_json', pointer='/nested/a~1b/~0name/0', value_json='1.0'),
            oracle('assert_header', name='X-Proof', value='observed'), oracle('assert_body', value='HTTP fixture')))


def artifact(name, body, media_type='application/json'):
    return dict(artifact_type='report', name=name, media_type=media_type, content_base64=base64.b64encode(body).decode('ascii'))


def payload(value=None, *, body=None, states=None, status='passed', response_status=200, headers=None):
    value = value or command()
    states = states or ['passed'] * len(value.steps)
    body = body if body is not None else b'{"message":"HTTP fixture","nested":{"a/b":{"~name":[1,true]}}}'
    steps = [dict(step_index=index, action=step['action'], kind='assertion' if step['action'] in HTTP_ASSERTIONS else 'action',
        status=states[index]) for index, step in enumerate(value.steps)]
    assertions = [step for step in steps if step['kind'] == 'assertion']
    receipt = dict(schema=HTTP_RUNNER_RECEIPT_SCHEMA, runner_job_id=value.job_id, project_id=value.project_id,
        us_id=value.us_id, request_hash=runner_request_hash(value), execution_status=status, step_count=len(steps), steps=steps,
        assertion_count=len(assertions), observed_assertion_count=sum(s['status'] in {'passed', 'failed'} for s in assertions),
        passed_assertion_count=sum(s['status'] == 'passed' for s in assertions),
        failed_assertion_count=sum(s['status'] == 'failed' for s in assertions), target_build_verified=False,
        business_coverage_verified=False, requests=[])
    artifacts = []
    for index, original in enumerate(value.steps):
        if original['action'] != 'request' or states[index] != 'passed':
            continue
        observed = dict(request_id=original['request_id'], step_index=index, method=original['method'],
            input_hash=http_step_input_hash(original), response_status=response_status, response_byte_count=len(body), response_hash=_hash(body))
        metadata = _wire(dict(schema='nasus.http-response.v1', **observed, headers=headers if headers is not None else {'x-proof': 'observed'}))
        receipt['requests'].append(dict(**observed, response_metadata_hash=_hash(metadata)))
        artifacts.extend([artifact('http-response-' + original['request_id'] + '.bin', body, 'application/octet-stream'),
            artifact('http-response-' + original['request_id'] + '.json', metadata)])
    artifacts.append(artifact('http-execution.json', _wire(receipt)))
    return dict(runner_job_id=value.job_id, status=status, failure_summary='', summary='HTTP fixture result',
        started_at='2026-10-10T00:00:00Z', completed_at='2026-10-10T00:00:01Z', timeline=[],
        execution_receipt=receipt, artifacts=artifacts)


def verify(result, value=None):
    value = value or command()
    return verify_http_runner_observations(result['execution_receipt'], job_id=value.job_id,
        project_id=value.project_id, us_id=value.us_id, request_hash=runner_request_hash(value),
        steps=value.steps, status=result['status'])


def execute(monkeypatch, result, value=None):
    value = value or command()
    class Response:
        def raise_for_status(self): pass
        def json(self): return deepcopy(result)
    def send(*args, **kwargs):
        assert kwargs['content'] == runner_request_body(value)
        return Response()
    monkeypatch.setattr(httpx, 'post', send)
    return HttpAutomationRunner('http://private-runner.test', 'protocol-only-service-token').execute(value)


def test_http_wire_is_explicit_and_browser_wire_stays_unchanged():
    value = command()
    actual = json.loads(runner_request_body(value))
    assert actual['execution_kind'] == 'http' and actual['receipt_protocol'] == HTTP_RUNNER_RECEIPT_SCHEMA
    browser = replace(value, kind='browser', steps=({'action': 'goto', 'path': '/'},))
    expected = dict(job_id=browser.job_id, project_id=browser.project_id, us_id=browser.us_id,
        base_url=browser.base_url, steps=list(browser.steps), timeout_ms=browser.timeout_ms,
        metadata=browser.metadata, receipt_protocol='nasus.runner-execution.v1')
    assert runner_request_body(browser) == json.dumps(expected, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(',', ':')).encode('utf-8')
    with pytest.raises(ValueError): runner_request_body(replace(value, kind='unsupported'))


def test_complete_bound_http_receipt_and_physical_oracles_are_rechecked(monkeypatch):
    result = payload()
    receipt = verify(result)
    receipt['requests'][0]['response_status'] = 500
    assert result['execution_receipt']['requests'][0]['response_status'] == 200
    verify_http_response_artifacts(result['execution_receipt'], result['artifacts'], command().steps)
    accepted = execute(monkeypatch, result)
    assert accepted.status == 'passed' and accepted.runner_mode == 'http_native'
    assert accepted.execution_receipt['passed_assertion_count'] == 4
    assert accepted.execution_receipt['target_build_verified'] is accepted.execution_receipt['business_coverage_verified'] is False


@pytest.mark.parametrize('field,replacement', [
    ('schema', 'nasus.runner-execution.v1'), ('request_hash', 'sha256:' + '0' * 64), ('project_id', 'other'),
    ('us_id', 'other'), ('step_count', True), ('passed_assertion_count', 100), ('business_coverage_verified', True),
    ('target_build_verified', True), ('requests', []), ('steps', []),
])
def test_http_envelope_cannot_change_scope_or_authority(monkeypatch, field, replacement):
    result = payload(); result['execution_receipt'][field] = replacement
    with pytest.raises(RunnerObservationInvalid): verify(result)
    assert execute(monkeypatch, result).status == 'error'


@pytest.mark.parametrize('field,replacement', [
    ('request_id', 'different'), ('request_id', []), ('step_index', True), ('step_index', 1),
    ('method', 'POST'), ('method', []), ('input_hash', 'sha256:' + '0' * 64), ('response_status', True),
    ('response_status', 600), ('response_byte_count', True), ('response_byte_count', -1),
    ('response_byte_count', 1024 * 1024 + 1), ('response_hash', 'arbitrary'), ('response_metadata_hash', 'arbitrary'),
])
def test_each_observed_request_requires_the_exact_original_and_bounded_response(monkeypatch, field, replacement):
    result = payload(); result['execution_receipt']['requests'][0][field] = replacement
    with pytest.raises(RunnerObservationInvalid): verify(result)
    assert execute(monkeypatch, result).status == 'error'


@pytest.mark.parametrize('change', ['missing_body', 'missing_metadata', 'missing_manifest', 'extra', 'duplicate',
    'wrong_bytes', 'wrong_base64', 'wrong_media', 'wrong_metadata', 'wrong_manifest', 'boolean_manifest'])
def test_http_artifacts_cannot_be_substituted_or_incomplete(monkeypatch, change):
    result = payload()
    artifacts = result['artifacts']
    if change == 'missing_body': del artifacts[0]
    if change == 'missing_metadata': del artifacts[1]
    if change == 'missing_manifest': artifacts.pop()
    if change == 'extra': artifacts.append(artifact('unrelated.json', b'{}'))
    if change == 'duplicate': artifacts.append(deepcopy(artifacts[0]))
    if change == 'wrong_bytes': artifacts[0]['content_base64'] = base64.b64encode(b'altered').decode()
    if change == 'wrong_base64': artifacts[0]['content_base64'] = '!!'
    if change == 'wrong_media': artifacts[0]['media_type'] = 'text/plain'
    if change == 'wrong_metadata': artifacts[1]['content_base64'] = base64.b64encode(b'{}').decode()
    if change == 'wrong_manifest': artifacts[-1] = artifact('http-execution.json', b'{}')
    if change == 'boolean_manifest':
        manifest = deepcopy(result['execution_receipt']); manifest['requests'][0]['step_index'] = False
        artifacts[-1] = artifact('http-execution.json', _wire(manifest))
    with pytest.raises(RunnerObservationInvalid): verify_http_response_artifacts(result['execution_receipt'], artifacts, command().steps)
    accepted = execute(monkeypatch, result)
    assert accepted.status == 'error' and not accepted.artifacts


@pytest.mark.parametrize('original,body,response_status,headers', [
    (oracle('assert_status', value='200'), b'{}', 500, {}),
    (oracle('assert_header', name='X-Proof', value='observed'), b'{}', 200, {'x-proof': 'different'}),
    (oracle('assert_body', value='expected'), b'actual', 200, {}),
    (oracle('assert_body', value='\ufffd'), b'\xff', 200, {}),
    (oracle('assert_json', pointer='/value', value_json='0.1'), b'{"value":0.10000000000000000001}', 200, {}),
    (oracle('assert_json', pointer='/value', value_json='1'), b'{"value":true}', 200, {}),
    (oracle('assert_json', pointer='/value', value_json='1'), b'{"value":1,"value":1}', 200, {}),
    (oracle('assert_json', pointer='/absent', value_json='null'), b'{}', 200, {}),
    (oracle('assert_json', pointer='/decimal', value_json='"1e0"'), b'1', 200, {}),
    (oracle('assert_json', pointer='/00', value_json='1'), b'[1]', 200, {}),
    (oracle('assert_json', pointer='/~2', value_json='1'), b'{"~2":1}', 200, {}),
])
def test_reported_pass_must_match_the_bound_response_not_just_a_valid_hash(monkeypatch, original, body, response_status, headers):
    value = replace(command(), steps=(request(), original))
    result = payload(value, body=body, response_status=response_status, headers=headers)
    assert verify(result, value)
    with pytest.raises(RunnerObservationInvalid): verify_http_response_artifacts(result['execution_receipt'], result['artifacts'], value.steps)
    assert execute(monkeypatch, result, value).status == 'error'
    # An actual mismatch is valid failure evidence, not a fabricated success.
    failed = payload(value, body=body, response_status=response_status, headers=headers, states=['passed', 'failed'], status='failed')
    assert execute(monkeypatch, failed, value).status == 'failed'


def test_reported_failure_cannot_disagree_with_a_matching_oracle(monkeypatch):
    value = replace(command(), steps=(request(), oracle('assert_status', value='200')))
    result = payload(value, states=['passed', 'failed'], status='failed')
    assert execute(monkeypatch, result, value).status == 'error'


@pytest.mark.parametrize('status,states', [('timed_out', ['interrupted', 'not_executed']),
    ('error', ['interrupted', 'not_executed']), ('error', ['not_executed', 'not_executed'])])
def test_interruption_does_not_invent_a_response_or_later_oracle(monkeypatch, status, states):
    value = replace(command(), steps=(request(), oracle('assert_status', value='200')))
    result = payload(value, status=status, states=states)
    accepted = execute(monkeypatch, result, value)
    assert accepted.status == status and accepted.execution_receipt['requests'] == []
    assert accepted.execution_receipt['observed_assertion_count'] == 0


@pytest.mark.parametrize('status', ['error', 'timed_out', 'failed'])
def test_terminal_error_cannot_claim_every_step_passed(status):
    result = payload(status=status)
    with pytest.raises(RunnerObservationInvalid): verify(result)


def test_empty_body_and_unicode_request_id_keep_exact_artifacts(monkeypatch):
    value = replace(command(), steps=(request('request_\u6d4b\u8bd5'),))
    result = payload(value, body=b'', response_status=204)
    accepted = execute(monkeypatch, result, value)
    assert accepted.status == 'passed' and len(accepted.artifacts) == 3
    assert accepted.artifacts[0].content_base64 == ''
    assert accepted.execution_receipt['observed_assertion_count'] == 0


def test_requests_are_exactly_ordered_and_the_aggregate_budget_is_checked():
    value = replace(command(), steps=tuple(request('request_' + str(index)) for index in range(17)))
    result = payload(value)
    result['execution_receipt']['requests'].reverse()
    with pytest.raises(RunnerObservationInvalid): verify(result, value)
    result = payload(value)
    for item in result['execution_receipt']['requests']: item['response_byte_count'] = 1024 * 1024
    with pytest.raises(RunnerObservationInvalid): verify(result, value)


@pytest.mark.parametrize('raw', ['{"a":1,"\\u0061":2}', 'NaN', 'Infinity', '9007199254740992', '9007199254740992.1', '1e999',
    '[' * 65 + ']' * 65, '0.' + '0' * 256 + '1'])
def test_python_oracle_parser_rejects_the_same_ambiguous_or_unbounded_json(raw):
    with pytest.raises(RunnerObservationInvalid): strict_http_json(raw)


@pytest.mark.parametrize('raw,expected', [('null', None), ('true', True), ('1.0', Decimal('1')),
    ('0.10000000000000000001', Decimal('0.10000000000000000001')), ('1e-400', Decimal('1e-400'))])
def test_exact_json_oracles_keep_types_and_decimal_precision(raw, expected):
    actual = strict_http_json(raw)
    assert type(actual) is type(expected) and actual == expected


def test_maximum_json_nesting_keeps_the_complete_original_shape():
    actual = strict_http_json('[' * 64 + ']' * 64)
    for _index in range(63):
        assert type(actual) is list and len(actual) == 1
        actual = actual[0]
    assert actual == []
