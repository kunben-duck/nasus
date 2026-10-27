from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Optional


AC_POLICY = "nasus.acceptance-authority.v1"
AC_SCHEMA = "nasus.acceptance-specification.v1"
AC_TOOL = "quality.acceptance_specification.review"


class StaleAcceptanceSpecification(ValueError):
    pass


class AcceptanceIntegrityError(ValueError):
    pass


def acceptance_digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def acceptance_identity(project_id, image_revision_id, object_id):
    # Approval applies to a frozen image, never to the mutable source or baseline head.
    return "ac_" + acceptance_digest([project_id, image_revision_id, object_id])[7:]


@dataclass(frozen=True)
class ObservableOracle:
    preconditions: str
    action: str
    observation: str
    expected_result: str

    def __post_init__(self):
        for value in asdict(self).values():
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError("an oracle requires bounded preconditions, action, observation and expected result")


def require_authority_decision(decision, oracle, authority_basis, previous_status, *, required_basis="user_confirmed_requirement"):
    if decision == "approve":
        if not isinstance(oracle, ObservableOracle) or authority_basis != required_basis:
            raise ValueError("approval requires an independently confirmed requirement and observable oracle")
    elif decision == "withdraw":
        if oracle is not None or authority_basis is not None or previous_status != "approved":
            raise ValueError("only an active approved specification can be withdrawn")
    else:
        raise ValueError("invalid acceptance authority decision")


@dataclass(frozen=True)
class AcceptanceRevision:
    revision_id: str
    ac_id: str
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    object_id: str
    binding_id: str
    source_revision_id: str
    document_revision_id: str
    basis_digest: str
    status: str
    previous_revision_id: Optional[str]
    sequence: int
    authority_actor: str
    invocation_id: str
    recorded_at: str
    artifact_hash: str
    policy_revision: str = AC_POLICY

    def __post_init__(self):
        if (self.ac_id != acceptance_identity(self.project_id, self.image_revision_id, self.object_id)
                or self.status not in {"approved", "withdrawn"} or self.policy_revision != AC_POLICY
                or type(self.sequence) is not int or not 1 <= self.sequence <= 1000
                or (self.sequence == 1) != (self.previous_revision_id is None)
                or (self.sequence == 1 and self.status == "withdrawn")):
            raise AcceptanceIntegrityError("invalid acceptance revision metadata")

    @property
    def digest(self):
        return acceptance_digest(asdict(self))
