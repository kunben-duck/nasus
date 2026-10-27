from pydantic import Field, StrictInt

from .test_design_mapping_inputs import MappingQueryInput
from .test_design_output import Digest
from ...domain.quality_loop.mapping_partitions import MAX_PARTS


class MappingPartitionPageInput(MappingQueryInput):
    plan_digest: Digest
    sequence: StrictInt = Field(ge=0, lt=MAX_PARTS)
