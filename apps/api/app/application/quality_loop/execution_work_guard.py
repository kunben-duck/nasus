"""Separate live worker fencing from full verification at effect boundaries."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ExecutionWorkGuard:
    verify: Callable[[], None]
    poll: Callable[[], None]

    def __call__(self):
        self.verify()


def work_poll(guard):
    return guard.poll if isinstance(guard, ExecutionWorkGuard) else guard
