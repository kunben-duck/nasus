"""Explicit delivery intake only; drafts are not business facts or permissions."""
import re
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictStr


DELIVERY_STATE_KEY = "delivery_intake"
IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"


class DialogueImageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    publication_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_head_id: StrictStr = Field(min_length=1, max_length=128)


class DeliveryIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["nasus.delivery-dialogue.v1"] = "nasus.delivery-dialogue.v1"
    project_id: StrictStr = Field(min_length=1, max_length=128)
    proposal_id: StrictStr = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=128)
    name: StrictStr = Field(default="", max_length=120)
    publication_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    image_binding: Optional[DialogueImageBinding] = None
    stage: Literal["selection", "confirmation", "created"] = "selection"
    version_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    locale: Literal["zh", "en"] = "zh"


def read_delivery_intake(conversation):
    for message in reversed(conversation.messages):
        if message.role == "assistant" and DELIVERY_STATE_KEY in message.metadata:
            state = DeliveryIntake.model_validate(message.metadata[DELIVERY_STATE_KEY])
            if state.project_id != conversation.project_id:
                raise ValueError("Delivery proposal belongs to another project")
            return state
    return None


def delivery_turn(text):
    """Return a bounded command, never infer writes from quoted or compound prose."""
    value = text.strip().rstrip("。.!！")
    if not value or len(value) > 512 or re.search(r"[\n\r`\"“”<>]", value):
        return None
    if re.fullmatch(r"(?:确认创建迭代|确认创建版本|confirm (?:iteration|version) creation)", value, re.I):
        return {"kind": "confirm"}
    if re.fullmatch(r"(?:取消创建迭代|cancel iteration creation)", value, re.I):
        return {"kind": "cancel"}
    if re.fullmatch(r"(?:(?:查看|查询|看看)?(?:当前)?迭代(?:进度|状态)(?:如何|怎么样)?[？?]?|iteration (?:status|progress)[?]?)", value, re.I):
        return {"kind": "status"}
    selected = re.fullmatch(rf"(?:查看迭代|select iteration|view iteration)\s+({IDENTIFIER})", value, re.I)
    if selected:
        return {"kind": "status", "version_id": selected[1]}
    if re.fullmatch(r"(?:(?:请|帮我|请帮我)?发布(?:系统)?画像(?:基线)?|publish (?:the )?(?:system )?image(?: baseline)?)", value, re.I):
        return {"kind": "publication"}
    selected = re.fullmatch(rf"(?:使用画像发布|选择画像发布|use publication|select publication)\s+({IDENTIFIER})", value, re.I)
    if selected:
        return {"kind": "select", "publication_id": selected[1]}
    named = re.fullmatch(r"(?:迭代名称[：:\s]+|iteration name(?: is|:)?\s+)([^？?；;\n]{1,120})", value, re.I)
    if named:
        return {"kind": "name", "name": named[1].strip()}
    matched = re.fullmatch(
        r"(?:(?:请|帮我|请帮我)?(?:创建|新建)(?:一个|新的|新)?(?:迭代|版本)|"
        r"(?:please )?create (?:a |an |new )?(?:iteration|version))"
        r"(?:[：:，,\s]+(?:(?:名称|名字)?(?:叫|为|是)|named |called )?\s*(.*))?", value, re.I)
    if matched is None:
        return None
    rest = (matched[1] or "").strip()
    parts = re.fullmatch(rf"(.*?)(?:[，,]\s*|\s+)(?:使用画像发布|using publication)\s+({IDENTIFIER})", rest, re.I)
    name, publication_id = (parts[1].strip(), parts[2]) if parts else (rest, None)
    if len(name) > 120 or re.search(r"[？?；;]|然后|并且|同时|不要|不需要|\b(?:then|and|without)\b", name, re.I):
        return None
    return {"kind": "create", "name": name, **({"publication_id": publication_id} if publication_id else {})}
