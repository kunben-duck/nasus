from __future__ import annotations

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictStr, conint

from .evidence_queries import EvidenceSummary


class EvidenceToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: StrictStr = Field(min_length=1, max_length=128)
    source_revision_id: StrictStr = Field(min_length=1, max_length=128)


class EvidenceListInput(EvidenceToolInput):
    object_id: StrictStr = Field(min_length=1, max_length=256)
    entity_revision_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)


class EvidenceReadInput(EvidenceToolInput):
    evidence_id: StrictStr = Field(min_length=1, max_length=128)
    start_line: Optional[conint(strict=True, ge=1)] = None
    max_lines: conint(strict=True, ge=1, le=200) = 100


class EvidenceListReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nasus.evidence-query.v1"] = "nasus.evidence-query.v1"
    operation: Literal["list"] = "list"
    project_id: str
    source_revision_id: str
    object_id: str
    entity_revision_id: Optional[str] = None
    items: List[EvidenceSummary] = Field(max_length=200)


class EvidenceReadReceipt(BaseModel):
    """Durable proof of a read, never a durable copy of the source text."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nasus.evidence-query.v1"] = "nasus.evidence-query.v1"
    operation: Literal["read"] = "read"
    project_id: str
    evidence: EvidenceSummary
    start_line: int
    end_line: int
    next_start_line: Optional[int]
    excerpt_hash: str
    integrity: Literal["verified"] = "verified"


EvidenceToolReceipt = Union[EvidenceListReceipt, EvidenceReadReceipt]
