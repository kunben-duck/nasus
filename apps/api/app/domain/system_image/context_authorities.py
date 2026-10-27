"""Exact historical authority dependencies; never infer pins from current heads."""
from dataclasses import dataclass
from typing import Optional

from .context_pack import ContextPackChanged, ContextPackIntegrityError
from .context_partition import MAX_CONSTRAINTS
from .image_revision import require_digest
from .source_snapshots import snapshot_digest


CONTEXT_AUTHORITY_POLICY = "nasus.context-authority-dependencies.v1"
REGISTER_CONTEXT_AUTHORITIES_TOOL = "system_image.context.register_authorities"


class ContextAuthorityRegistrationRequired(ContextPackChanged):
    pass


def require_context_authority(condition):
    if not condition:
        raise ContextPackIntegrityError("context authority dependencies failed verification")


def archived_authority_pins(payload):
    """Consume the original verified archive, including negative/unapproved pins."""
    raw = payload["provenance"]["authority_pins"]
    require_context_authority(type(raw) is list and len(raw) <= MAX_CONSTRAINTS)
    constraints = {item["object_id"]: item for item in payload["context"]["required_constraints"]}
    result, seen = [], set()
    for pin in raw:
        require_context_authority(type(pin) is dict and set(pin) == {
            "object_id", "basis_digest", "revision_id", "artifact_hash", "status"})
        obj = pin["object_id"]
        require_context_authority(obj not in seen and obj in constraints and constraints[obj]["authority"] == pin)
        seen.add(obj)
        fields = constraints[obj]["source_fields"]
        kinds = {field["name"] for field in fields}
        require_context_authority(kinds in ({"acceptance_criterion"}, {"business_rule"}))
        kind = "acceptance" if kinds == {"acceptance_criterion"} else "business_rule"
        require_digest(pin["basis_digest"])
        require_context_authority(pin["status"] in {"unapproved", "approved", "withdrawn"})
        if pin["status"] == "unapproved":
            require_context_authority(pin["revision_id"] is None and pin["artifact_hash"] is None)
        else:
            require_context_authority(type(pin["revision_id"]) is str and 0 < len(pin["revision_id"]) <= 128)
            require_digest(pin["artifact_hash"])
        result.append({**pin, "kind": kind})
    # v1/v2 deliberately have no rule authority; do not retrofit that meaning.
    required = {key for key, item in constraints.items() if "basis_digest" in item["authority"]}
    require_context_authority(seen == required)
    return tuple(sorted(result, key=lambda item: item["object_id"]))


@dataclass(frozen=True)
class ContextAuthorityDependency:
    project_id: str
    context_id: str
    object_id: str
    kind: str
    basis_digest: str
    status: str
    revision_id: Optional[str]
    artifact_hash: Optional[str]
    authority_registration_hash: Optional[str]
    image_revision_id: str
    member_provenance_hash: str

    def __post_init__(self):
        for value in (self.project_id, self.context_id, self.object_id, self.image_revision_id):
            require_context_authority(type(value) is str and 0 < len(value) <= 128)
        require_context_authority(self.kind in {"acceptance", "business_rule"}
            and self.status in {"unapproved", "approved", "withdrawn"})
        for value in (self.basis_digest, self.member_provenance_hash):
            require_digest(value)
        if self.status == "unapproved":
            require_context_authority(self.revision_id is None and self.artifact_hash is None
                and self.authority_registration_hash is None)
        else:
            require_context_authority(type(self.revision_id) is str and 0 < len(self.revision_id) <= 128)
            for value in (self.artifact_hash, self.authority_registration_hash):
                require_digest(value)

    @property
    def record_v1(self):
        fields = ("project_id", "context_id", "object_id", "kind", "basis_digest", "status", "revision_id",
            "artifact_hash", "authority_registration_hash", "image_revision_id", "member_provenance_hash")
        value = {key: getattr(self, key) for key in fields}
        value.update(member_node_key="member:" + self.image_revision_id + "/" + self.object_id,
            policy_revision=CONTEXT_AUTHORITY_POLICY)
        return {**value, "content_hash": snapshot_digest(value)}


def dependency_root(metadata, context_metadata_hash, dependencies, *, invocation_id, actor_id, recorded_at):
    require_context_authority(type(dependencies) is tuple and len(dependencies) <= MAX_CONSTRAINTS
        and tuple(item.object_id for item in dependencies) ==
        tuple(sorted({item.object_id for item in dependencies})))
    require_context_authority(all(type(value) is str and 0 < len(value) <= 128
        for value in (invocation_id, actor_id, recorded_at)))
    require_digest(context_metadata_hash)
    value = {key: metadata[key] for key in ("project_id", "context_id", "image_revision_id", "image_artifact_hash",
        "input_digest", "artifact_hash", "invocation_id")}
    value.update(context_metadata_hash=context_metadata_hash, registration_invocation_id=invocation_id,
        registered_by=actor_id, registered_at=recorded_at, policy_revision=CONTEXT_AUTHORITY_POLICY,
        authority_count=len(dependencies),
        authority_pins_hash=snapshot_digest([item.record_v1 for item in dependencies]))
    require_context_authority(all(item.project_id == value["project_id"] and item.context_id == value["context_id"]
        and item.image_revision_id == value["image_revision_id"] for item in dependencies))
    return {**value, "content_hash": snapshot_digest(value)}
