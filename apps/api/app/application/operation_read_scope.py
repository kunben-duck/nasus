"""A read operation belongs to one task/thread and ends with its context manager."""
import asyncio
from dataclasses import dataclass, field
from threading import get_ident
from typing import Generic, TypeVar


Value = TypeVar("Value")


def _execution_identity():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return get_ident(), task


@dataclass
class OperationReadScope(Generic[Value]):
    value: Value
    execution_identity: tuple = field(default_factory=_execution_identity)
    is_open: bool = True

    @property
    def is_current(self):
        return self.is_open and self.execution_identity == _execution_identity()

    def close(self):
        self.is_open = False
