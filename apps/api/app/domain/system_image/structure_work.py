"""Worker ownership fences structural work, but never grants business authority."""
from dataclasses import dataclass

from .image_revision import require_digest


class StructureWorkBusy(RuntimeError):
    pass


class StructureWorkLost(RuntimeError):
    pass


class StructureWorkCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class StructureWorkLease:
    project_id: str
    invocation_id: str
    owner_id: str
    epoch: int
    command_hash: str

    def __post_init__(self):
        if (any(type(value) is not str or not value or len(value) > 128
                for value in (self.project_id, self.invocation_id, self.owner_id))
                or type(self.epoch) is not int or self.epoch < 1):
            raise ValueError("invalid structural worker ownership")
        require_digest(self.command_hash)
