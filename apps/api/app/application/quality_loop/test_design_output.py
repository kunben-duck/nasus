"""Strict model output DTOs. Models never provide coverage totals or authority."""
import json
from typing import Annotated, Tuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

from .acceptance_specifications import OracleInput
from ...domain.quality_loop.test_design_generation import TestDesignGenerationInvalid, planned_coverage


Id = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)]
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2000)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")]


class GenerationValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlannedAssertion(GenerationValue):
    row_id: Id
    oracle_digest: Digest
    oracle: OracleInput
    step_index: StrictInt = Field(ge=0, le=63)


class PlannedCase(GenerationValue):
    case_id: Id
    title: Text
    preconditions: Tuple[Text, ...] = Field(min_length=1, max_length=64)
    inputs: Tuple[Text, ...] = Field(min_length=1, max_length=64)
    steps: Tuple[Text, ...] = Field(min_length=1, max_length=64)
    assertions: Tuple[PlannedAssertion, ...] = Field(min_length=1, max_length=256)
    global_constraint_ids: Tuple[Id, ...] = Field(max_length=256)
    supporting_fact_ids: Tuple[Id, ...] = Field(max_length=256)
    reused_case_ids: Tuple[Id, ...] = Field(max_length=256)

    @model_validator(mode="after")
    def distinct_references(self):
        if any(len(items) != len(set(items)) for items in (self.supporting_fact_ids, self.reused_case_ids, self.global_constraint_ids)):
            raise ValueError("duplicate case source references")
        return self


class GenerationGap(GenerationValue):
    gap_id: Id
    row_ids: Tuple[Id, ...] = Field(min_length=1, max_length=2048)
    description: Text


class TestDesignModelOutput(GenerationValue):
    __test__ = False
    input_digest: Digest
    cases: Tuple[PlannedCase, ...] = Field(max_length=512)
    gaps: Tuple[GenerationGap, ...] = Field(max_length=512)


def parse_test_design_output(content, output_type=TestDesignModelOutput, *, max_bytes=1024 * 1024):
    if type(content) is not str or len(content.encode()) > max_bytes:
        raise TestDesignGenerationInvalid("generation output exceeds the content budget")

    def distinct_object(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TestDesignGenerationInvalid("duplicate JSON key in model output")
            result[key] = value
        return result

    def reject_constant(value):
        raise TestDesignGenerationInvalid("non-JSON numeric constant in model output")

    try:
        value = json.loads(content, object_pairs_hook=distinct_object, parse_constant=reject_constant)
        return output_type.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise TestDesignGenerationInvalid("model output must account for all pinned obligations without changing their oracles") from exc


def validate_test_design_output(prepared, content):
    output = parse_test_design_output(content)
    try:
        coverage = planned_coverage(prepared, output)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise TestDesignGenerationInvalid("model output must account for all pinned obligations without changing their oracles") from exc
    return {"cases": output["cases"], "gaps": output["gaps"], "coverage": coverage}
