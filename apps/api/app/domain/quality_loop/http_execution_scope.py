"""Identity of a private HTTP batch; possession of this value grants no authority."""
from dataclasses import asdict, dataclass
from datetime import datetime
import re


class HttpExecutionScopeInvalid(ValueError):
    pass


@dataclass(frozen=True)
class HttpExecutionScope:
    project_id: str
    version_id: str
    batch_id: str
    case_id: str
    environment_id: str
    environment_epoch: int
    inventory_hash: str
    expires_at: str

    def payload(self):
        for field in (self.project_id, self.version_id, self.batch_id, self.case_id, self.environment_id):
            if type(field) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", field):
                raise HttpExecutionScopeInvalid("Private HTTP scope requires bounded identities")
        if type(self.environment_epoch) is not int or not 1 <= self.environment_epoch <= 9007199254740991:
            raise HttpExecutionScopeInvalid("Private HTTP scope requires an explicit environment epoch")
        if type(self.inventory_hash) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.inventory_hash):
            raise HttpExecutionScopeInvalid("Private HTTP scope requires its pinned inventory")
        self.deadline()
        return asdict(self)

    def deadline(self):
        try:
            value = datetime.fromisoformat(self.expires_at)
            if value.tzinfo is None:
                raise ValueError()
            return value
        except (TypeError, ValueError):
            raise HttpExecutionScopeInvalid("Private HTTP scope requires an aware expiration") from None
