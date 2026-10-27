"""Recheck HTTP oracles from bound response bytes, without granting coverage."""
from decimal import Decimal
import json
import math
import re

from .runner_observations import RunnerObservationInvalid


def strict_http_json(text):
    def distinct(items):
        result = {}
        for key, item in items:
            if key in result:
                raise RunnerObservationInvalid("HTTP JSON keys are ambiguous")
            result[key] = item
        return result

    def number(raw):
        if len(raw) > 256:
            raise RunnerObservationInvalid("HTTP JSON number exceeds its operand bound")
        item = Decimal(raw)
        # Match Node's representability gate without using rounded values for comparison.
        native = float(raw)
        if not math.isfinite(native) or native.is_integer() and abs(native) > 9007199254740991:
            raise RunnerObservationInvalid("HTTP JSON number exceeds the exact comparison bound")
        return item

    def invalid(_raw):
        raise RunnerObservationInvalid("HTTP JSON is not strict")

    try:
        result = json.loads(text, object_pairs_hook=distinct, parse_int=number,
            parse_float=number, parse_constant=invalid)
        pending = [(result, 0)]
        while pending:
            item, depth = pending.pop()
            if type(item) in {dict, list} and depth >= 64:
                raise RunnerObservationInvalid("HTTP JSON nesting exceeds its bound")
            if type(item) is dict:
                pending.extend((child, depth + 1) for child in item.values())
            elif type(item) is list:
                pending.extend((child, depth + 1) for child in item)
        return result
    except (ValueError, TypeError, RecursionError, ArithmeticError):
        raise RunnerObservationInvalid("HTTP JSON cannot be verified") from None


def _pointer(value, pointer):
    if type(pointer) is not str or pointer and (not pointer.startswith('/') or re.search(r'~(?![01])', pointer)):
        raise RunnerObservationInvalid("HTTP JSON pointer is invalid")
    if pointer == '':
        return value
    for raw in pointer[1:].split('/'):
        key = raw.replace('~1', '/').replace('~0', '~')
        if type(value) is dict and key in value:
            value = value[key]
        elif type(value) is list and re.fullmatch(r'0|[1-9][0-9]*', key) and len(key) <= 7 and int(key) < len(value):
            value = value[int(key)]
        else:
            raise RunnerObservationInvalid("HTTP JSON pointer is absent")
    return value


def same_http_json(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(same_http_json(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(same_http_json(a, b) for a, b in zip(left, right))
    return left == right


def verify_http_assertion_results(receipt, steps, responses):
    for original, observed in zip(steps, receipt['steps']):
        if observed['kind'] != 'assertion' or observed['status'] not in {'passed', 'failed'}:
            continue
        response = responses.get(original.get('request_id'))
        if response is None:
            raise RunnerObservationInvalid("HTTP oracle lacks the original response")
        matches = False
        try:
            action = original['action']
            if action == 'assert_status':
                matches = response['status'] == int(original['value'])
            elif action == 'assert_header':
                matches = response['headers'].get(original['name'].lower()) == original['value']
            elif action == 'assert_body':
                matches = original['value'] in response['body'].decode('utf-8', errors='strict')
            elif action == 'assert_json':
                matches = same_http_json(_pointer(strict_http_json(response['body'].decode('utf-8', errors='strict')),
                    original['pointer']), strict_http_json(original['value_json']))
        except (ValueError, TypeError, KeyError, UnicodeError):
            matches = False
        if matches is not (observed['status'] == 'passed'):
            raise RunnerObservationInvalid("HTTP oracle observation differs from its bound actual response")
