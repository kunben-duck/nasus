from typing import Literal, Optional

from .test_design_mapping_inputs import MappingQueryInput
from .test_design_output import Id, Digest, Text
from ...domain.quality_loop.mapping_part_sets import FINALIZE_POLICY


class MappingFinalizationPreviewInput(MappingQueryInput):
    plan_digest: Digest


class MappingFinalizeInput(MappingFinalizationPreviewInput):
    expected_previous_revision_id: Optional[Id]
    part_set_digest: Digest
    decision: Literal["review"] = "review"
    reason: Text
    policy_revision: Literal["nasus.test-design-mapping.v2"] = FINALIZE_POLICY
