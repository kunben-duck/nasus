from __future__ import annotations

from uuid import uuid4

from apps.api.app.application.quality_loop.quality_models import USItem
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.quality_loop_repository import (
    QualityLoopRepository,
)


def _us_item(item_id: str, title: str) -> USItem:
    return USItem(
        id=item_id,
        title=title,
        owner="QA",
        status="draft",
        risk="medium",
        progress=0,
        next_action="Start quality loop",
    )


def test_replacing_us_items_preserves_other_version_history() -> None:
    init_database()
    repository = QualityLoopRepository()
    suffix = uuid4().hex
    project_id = f"project-version-isolation-{suffix}"
    first_version_id = f"version-a-{suffix}"
    second_version_id = f"version-b-{suffix}"
    first_item = _us_item(f"us-a-{suffix}", "First version requirement")
    second_item = _us_item(f"us-b-{suffix}", "Second version requirement")
    replacement = _us_item(f"us-b2-{suffix}", "Updated second version requirement")

    try:
        repository.replace_us_items(project_id, first_version_id, [first_item])
        repository.replace_us_items(project_id, second_version_id, [second_item])

        assert repository.list_us_items(project_id, first_version_id) == [first_item]
        assert repository.list_us_items(project_id, second_version_id) == [second_item]

        repository.replace_us_items(project_id, second_version_id, [replacement])

        assert repository.list_us_items(project_id, first_version_id) == [first_item]
        assert repository.list_us_items(project_id, second_version_id) == [replacement]
        assert repository.list_us_items(project_id) == [first_item, replacement]
    finally:
        repository.replace_us_items(project_id, None, [])
