"""Pure protocol specimens; actual Node/MinIO and exweb are validated separately."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from apps.api.app.domain.quality_loop.http_bindings import (
    HTTP_BINDING_RECEIPT_SCHEMA, http_binding_value_hash, http_path_bindings, resolve_http_path,
    validate_http_binding_steps,
)
from apps.api.app.domain.quality_loop.http_runner_observations import HTTP_ASSERTIONS, http_step_input_hash, verify_http_runner_observations
from apps.api.app.domain.quality_loop.runner_observations import RunnerObservationInvalid
from apps.api.app.infrastructure.runner.http_observation_artifacts import verify_http_response_artifacts
from apps.api.app.infrastructure.runner.request_wire import runner_request_body, runner_request_hash
from apps.api.tests.test_http_runner_observations import artifact, command as v1_command, execute


def request(ident='create', path='/sessions', method='POST'):
    return dict(action='request', request_id=ident, method=method, path=path, headers_json='{}',
        body_json='{"title":"Independent fixture"}' if method == 'POST' else 'null')


def capture(pointer='/sessionId', name='session'):
    return dict(action='capture_json', request_id='create', pointer=pointer, binding_id=name)


def oracle(ident, status):
    return dict(action='assert_json', request_id=ident, pointer='/status', value_json=json.dumps(status))


def command():
    return replace(v1_command(), http_protocol=HTTP_BINDING_RECEIPT_SCHEMA, steps=(request(), oracle('create', 'ACTIVE'), capture(),
        request('read', '/sessions/{{session}}', 'GET'), oracle('read', 'ACTIVE'),
        request('close', '/sessions/{{session}}/close'), oracle('close', 'CLOSED')))


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def digest(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def specimen(value=None, *, binding_value='session_original', body_value='session_original', states=None, status='passed'):
    value = value or command()
    states = states or ['passed'] * len(value.steps)
    observed_steps = [dict(step_index=i, action=step['action'], kind='assertion' if step['action'] in HTTP_ASSERTIONS else 'action',
        status=states[i]) for i, step in enumerate(value.steps)]
    assertions = [step for step in observed_steps if step['kind'] == 'assertion']
    receipt = dict(schema=HTTP_BINDING_RECEIPT_SCHEMA, runner_job_id=value.job_id, project_id=value.project_id, us_id=value.us_id,
        request_hash=runner_request_hash(value), execution_status=status, step_count=len(value.steps), steps=observed_steps,
        assertion_count=len(assertions), observed_assertion_count=sum(s['status'] in {'passed', 'failed'} for s in assertions),
        passed_assertion_count=sum(s['status'] == 'passed' for s in assertions), failed_assertion_count=sum(s['status'] == 'failed' for s in assertions),
        target_build_verified=False, business_coverage_verified=False, requests=[], bindings=[])
    artifacts, values, responses = [], {}, {}
    for index, step in enumerate(value.steps):
        if states[index] != 'passed':
            continue
        if step['action'] == 'capture_json':
            item = dict(binding_id=step['binding_id'], request_id=step['request_id'], step_index=index, pointer=step['pointer'],
                response_hash=responses[step['request_id']], value=binding_value, value_hash=http_binding_value_hash(binding_value))
            receipt['bindings'].append(item); values[step['binding_id']] = binding_value
        elif step['action'] == 'request':
            body = wire(dict(sessionId=body_value, status='CLOSED' if step['request_id'] == 'close' else 'ACTIVE'))
            path = resolve_http_path(step['path'], values)
            observed = dict(request_id=step['request_id'], step_index=index, method=step['method'],
                input_hash=http_step_input_hash(dict(step, path=path)), declared_input_hash=http_step_input_hash(step),
                path=path, binding_ids=http_path_bindings(step['path']), response_status=200, response_byte_count=len(body), response_hash=digest(body))
            metadata = wire(dict(schema='nasus.http-response.v2', **observed, headers={}))
            receipt['requests'].append(dict(observed, response_metadata_hash=digest(metadata)))
            responses[step['request_id']] = digest(body)
            artifacts.extend([artifact('http-response-' + step['request_id'] + '.bin', body, 'application/octet-stream'),
                artifact('http-response-' + step['request_id'] + '.json', metadata)])
    artifacts.append(artifact('http-execution.json', wire(receipt)))
    return dict(runner_job_id=value.job_id, status=status, failure_summary='', summary='Explicit binding protocol specimen',
        started_at='2026-10-11T00:00:00Z', completed_at='2026-10-11T00:00:01Z', timeline=[], execution_receipt=receipt, artifacts=artifacts)


def verify(result, value=None):
    value = value or command()
    return verify_http_runner_observations(result['execution_receipt'], job_id=value.job_id, project_id=value.project_id,
        us_id=value.us_id, request_hash=runner_request_hash(value), steps=value.steps, status=result['status'], protocol=value.http_protocol)


def test_explicit_v2_tracks_resource_location_not_coverage_and_preserves_original_wire(monkeypatch):
    value, result = command(), specimen()
    assert json.loads(runner_request_body(value))['receipt_protocol'] == HTTP_BINDING_RECEIPT_SCHEMA
    receipt = verify(result)
    assert receipt['bindings'][0]['value'] == 'session_original'
    assert receipt['steps'][2]['kind'] == 'action' and receipt['passed_assertion_count'] == 3
    assert receipt['requests'][1]['path'] == '/sessions/session_original'
    assert receipt['requests'][1]['input_hash'] != receipt['requests'][1]['declared_input_hash']
    assert receipt['business_coverage_verified'] is receipt['target_build_verified'] is False
    verify_http_response_artifacts(receipt, result['artifacts'], value.steps)
    assert execute(monkeypatch, result, value).status == 'passed'
    receipt['bindings'][0]['value'] = 'mutated_copy'
    assert result['execution_receipt']['bindings'][0]['value'] == 'session_original'


def test_protocol_is_selected_by_the_original_command_not_an_untrusted_receipt(monkeypatch):
    value = replace(command(), http_protocol='nasus.runner-http-execution.v1')
    result = specimen()
    with pytest.raises(ValueError): runner_request_body(value)
    with pytest.raises(RunnerObservationInvalid):
        verify_http_runner_observations(result['execution_receipt'], job_id=value.job_id, project_id=value.project_id,
            us_id=value.us_id, request_hash=result['execution_receipt']['request_hash'], steps=value.steps,
            status=result['status'], protocol=value.http_protocol)
    assert execute(monkeypatch, result, value).status == 'error'
    with pytest.raises(ValueError): runner_request_body(replace(command(), kind='browser'))
    for protocol in ('future', [], None, True):
        with pytest.raises(ValueError): runner_request_body(replace(command(), http_protocol=protocol))


@pytest.mark.parametrize('field,replacement', [
    ('binding_id', 'another'), ('binding_id', []), ('step_index', True), ('step_index', 3), ('request_id', 'read'),
    ('pointer', '/different'), ('response_hash', 'sha256:' + '0' * 64), ('value_hash', 'sha256:' + '0' * 64),
    ('value', '../escape'), ('value', True), ('value', []), ('value', 'x' * 129), ('value', '\u4e2d\u6587'),
])
def test_binding_metadata_cannot_change_source_value_or_hash(monkeypatch, field, replacement):
    result = specimen(); result['execution_receipt']['bindings'][0][field] = replacement
    with pytest.raises(RunnerObservationInvalid): verify(result)
    assert execute(monkeypatch, result, command()).status == 'error'


@pytest.mark.parametrize('field,replacement', [
    ('path', '//external/path'), ('path', '/sessions/another'), ('path', []), ('binding_ids', []), ('binding_ids', ['another']),
    ('binding_ids', ['session', 'session']), ('binding_ids', 'session'), ('declared_input_hash', 'sha256:' + '0' * 64),
    ('input_hash', 'sha256:' + '0' * 64),
])
def test_resolved_request_must_preserve_declared_operands_and_exact_binding(monkeypatch, field, replacement):
    result = specimen(); result['execution_receipt']['requests'][1][field] = replacement
    with pytest.raises(RunnerObservationInvalid): verify(result)
    assert execute(monkeypatch, result, command()).status == 'error'


@pytest.mark.parametrize('change', ['missing', 'extra', 'duplicate', 'wrong_kind', 'failed_source', 'authority', 'unknown_field'])
def test_capture_count_order_kind_and_authority_are_checked(change):
    result = specimen(); receipt = result['execution_receipt']
    if change == 'missing': receipt['bindings'] = []
    if change in {'extra', 'duplicate'}: receipt['bindings'].append(deepcopy(receipt['bindings'][0]))
    if change == 'wrong_kind': receipt['steps'][2]['kind'] = 'assertion'
    if change == 'failed_source': receipt['requests'][0]['response_status'] = 500
    if change == 'authority': receipt['business_coverage_verified'] = True
    if change == 'unknown_field': receipt['bindings'][0]['oracle'] = True
    with pytest.raises(RunnerObservationInvalid): verify(result)


def test_a_forged_binding_cannot_pass_even_when_all_derived_paths_hashes_and_metadata_agree(monkeypatch):
    result = specimen(binding_value='forged_resource', body_value='session_original')
    assert verify(result)
    with pytest.raises(RunnerObservationInvalid):
        verify_http_response_artifacts(result['execution_receipt'], result['artifacts'], command().steps)
    rejected = execute(monkeypatch, result, command())
    assert rejected.status == 'error' and not rejected.artifacts


@pytest.mark.parametrize('body', [b'{}', b'{"sessionId":null}', b'{"sessionId":1}', b'{"sessionId":true}',
    b'{"sessionId":"../escape"}', b'{"sessionId":"same","sessionId":"same"}', b'\xff'])
def test_full_response_recheck_rejects_unusable_json_even_with_fresh_matching_hashes(body):
    result = specimen(); receipt = result['execution_receipt']
    observed = receipt['requests'][0]
    observed.update(response_byte_count=len(body), response_hash=digest(body))
    receipt['bindings'][0]['response_hash'] = digest(body)
    metadata = wire(dict(schema='nasus.http-response.v2', headers={}, **{key: value for key, value in observed.items() if key != 'response_metadata_hash'}))
    observed['response_metadata_hash'] = digest(metadata)
    result['artifacts'][0] = artifact('http-response-create.bin', body, 'application/octet-stream')
    result['artifacts'][1] = artifact('http-response-create.json', metadata)
    result['artifacts'][-1] = artifact('http-execution.json', wire(receipt))
    assert verify(result)
    with pytest.raises(RunnerObservationInvalid): verify_http_response_artifacts(receipt, result['artifacts'], command().steps)


def test_failed_oracle_and_interrupted_capture_preserve_only_original_observations():
    failed = specimen(states=['passed', 'passed', 'passed', 'passed', 'failed', 'not_executed', 'not_executed'], status='failed')
    assert verify(failed)['failed_assertion_count'] == 1
    value = replace(command(), steps=(request(), capture(), request('read', '/sessions/{{session}}', 'GET')))
    interrupted = specimen(value, states=['passed', 'interrupted', 'not_executed'], status='error')
    assert verify(interrupted, value)['bindings'] == []
    verify_http_response_artifacts(interrupted['execution_receipt'], interrupted['artifacts'], value.steps)


@pytest.mark.parametrize('steps', [
    (capture(),), (request('create', '/sessions/{{session}}'), capture()), (request(), capture(), capture()),
    (request(), capture('/~2')), (request(), dict(capture(), oracle=True)), (request(), dict(capture(), source_step_indices=None)),
    (request(), dict(capture(), source_step_indices=[True])), (request(), dict(capture(), binding_id='../escape')),
    (request(), capture(), request('read', '/sessions/prefix{{session}}')), (request(), capture(), request('read', '/sessions?x={{session}}')),
    (request(), capture(), request('read', '/sessions/{{missing}}')), (request('create', '//elsewhere/path'),),
    (dict(request(), action=['request']),), (dict(request(), headers_json='{"Authorization":"denied"}'),),
    (dict(request(), body_json='{"x":1,"x":1}'),), (request(), *tuple(capture(name='binding_' + str(i)) for i in range(33))),
])
def test_invalid_binding_grammar_is_rejected_before_any_transport(steps):
    with pytest.raises(RunnerObservationInvalid): validate_http_binding_steps(steps)
    with pytest.raises(ValueError): runner_request_body(replace(command(), steps=steps))


def test_repeated_binding_segments_remain_one_declared_dependency_and_cannot_be_reassigned():
    path = '/sessions/{{session}}/{{session}}?constant=1'
    assert http_path_bindings(path) == ['session']
    assert resolve_http_path(path, {'session': 'resource_1'}) == '/sessions/resource_1/resource_1?constant=1'
    assert http_binding_value_hash('resource_1') == digest(b'"resource_1"')


def test_original_script_proposal_does_not_silently_gain_a_new_execution_grammar():
    from apps.api.app.domain.quality_loop.automation_input import compile_automation_input
    from apps.api.app.domain.quality_loop.automation_scripts import validate_script_proposal
    from apps.api.tests.test_automation_input import automation_inputs
    from apps.api.tests.test_automation_scripts import script_output
    prepared = compile_automation_input(*automation_inputs())
    output = script_output(prepared, kind='http')
    script = output['scripts'][0]
    script['actions'].append(dict(capture(), request_id=script['actions'][0]['request_id'], source_step_indices=[0]))
    with pytest.raises(ValueError): validate_script_proposal(prepared, output)
