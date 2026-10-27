from typing import Literal, Optional, Tuple

from pydantic import Field, StrictInt

from .test_design_mapping_inputs import AssertionReview, MappingQueryInput
from .test_design_output import Digest, Id
from ...domain.quality_loop.mapping_partitions import MAX_PARTS, PART_SIZE


STAGED_PART_SCHEMA = "nasus.test-design-mapping-staged-part.v1"
STAGE_PART_TOOL = "quality.test_design_mapping.stage_part"


class MappingPartStageInput(MappingQueryInput):
    plan_digest: Digest
    expected_previous_revision_id: Optional[Id]
    sequence: StrictInt = Field(ge=0, lt=MAX_PARTS)
    part_digest: Digest
    expected_previous_part_revision_id: Optional[Id]
    decisions: Tuple[AssertionReview, ...] = Field(min_length=1, max_length=PART_SIZE)
    policy_revision: Literal["nasus.test-design-mapping-staging.v1"] = "nasus.test-design-mapping-staging.v1"
