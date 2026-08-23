from __future__ import annotations

from sqlalchemy import Engine, text


class DatabaseReadinessProbe:
    name = "database"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def check(self) -> dict[str, str]:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "backend": self._engine.url.get_backend_name(),
            "driver": self._engine.url.get_driver_name(),
        }


__all__ = ["DatabaseReadinessProbe"]
