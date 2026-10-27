"""Versioned script ancestry, independent of v1 derivation and execution consent."""
from dataclasses import dataclass

from .evidence import valid_digest
from .source_snapshots import snapshot_digest


AUTOMATION_PROVENANCE_POLICY = "nasus.automation-provenance.v1"
MAX_SCRIPT_PARENTS = 517


@dataclass(frozen=True)
class AutomationProvenance:
    project_id: str
    context_id: str
    kind: str
    artifact_id: str
    artifact_hash: str
    invocation_id: str
    fact_hash: str
    origin_hash: str
    parents: tuple[tuple[str, str, str], ...]

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in {"script", "script_review"}:
            raise ValueError("unsupported automation provenance kind")
        for value in (self.project_id, self.context_id, self.artifact_id, self.invocation_id):
            if type(value) is not str or not 1 <= len(value) <= 128 or any(ord(c) < 32 for c in value):
                raise ValueError("invalid automation provenance identity")
        for value in (self.artifact_hash, self.fact_hash, self.origin_hash):
            if type(value) is not str or not valid_digest(value):
                raise ValueError("invalid automation provenance digest")
        if (type(self.parents) is not tuple or not self.parents or len(self.parents) > MAX_SCRIPT_PARENTS
                or any(type(pin) is not tuple or len(pin) != 3 or type(pin[0]) is not str
                    or not 1 <= len(pin[0]) <= 512 or not pin[0].partition(":")[2]
                    or any(ord(c) < 32 for c in pin[0])
                    or any(type(value) is not str or not valid_digest(value) for value in pin[1:])
                    for pin in self.parents)):
            raise ValueError("invalid automation provenance parents")
        keys = tuple(pin[0] for pin in self.parents)
        if keys != tuple(sorted(set(keys))) or self.key in keys:
            raise ValueError("automation provenance parents must be distinct and ordered")
        kinds = tuple(sorted(key.partition(":")[0] for key in keys))
        if self.kind == "script":
            required = ("context", "coverage", "generation", "mapping", "scope")
            if (tuple(kind for kind in kinds if kind != "case") != required or "case" not in kinds
                    or "context:" + self.context_id not in keys):
                raise ValueError("script requires exact context, scope, generation, coverage, mapping and cases")
        elif self.kind == "script_review":
            if kinds not in (("script",), ("script", "script_review")):
                raise ValueError("script review requires its original script and optional predecessor")
        else:
            raise ValueError("unsupported automation provenance kind")

    @property
    def key(self):
        return self.kind + ":" + self.artifact_id

    @property
    def payload_v1(self):
        return {"policy_revision": AUTOMATION_PROVENANCE_POLICY,
            **{key: getattr(self, key) for key in ("project_id", "context_id", "kind", "artifact_id",
                "artifact_hash", "invocation_id", "fact_hash", "origin_hash")},
            "parents": [list(pin) for pin in self.parents]}

    @property
    def content_hash(self):
        return snapshot_digest(self.payload_v1)
