"""Pure checks for the real exweb fixture's bounded draft discovery."""
from copy import deepcopy

import pytest

from apps.api.tests.exweb_test_design_mapping_fixture import find_exweb_review_draft


class Pages:
    def __init__(self, values):
        self.values = values
        self.requests = []

    def list_for_review(self, request):
        self.requests.append(request)
        return {"request": request.model_dump(mode="json"), "can_review": True,
            "generation_authorized": False, "execution_authorized": False,
            **deepcopy(self.values[request.after_id])}


def item(ident, **values):
    return {"metadata": {"project_id": "exweb-page-fixture", "generation_id": ident, **values},
        "context_pin": {}, "scope_pin": {}}


def test_exweb_fixture_finds_recovered_draft_on_a_later_bounded_page():
    target = item("d")["metadata"]
    results = Pages({"": {"items": [item("a"), item("b"), item("c")], "next_after_id": "c"},
        "c": {"items": [item("d")], "next_after_id": None}})
    page, request, pages, count = find_exweb_review_draft(results, target)
    assert page["items"] == [item("d")] and request.after_id == "c"
    assert pages == 2 and count == 4
    assert [request.limit for request in results.requests] == [3, 3]


@pytest.mark.parametrize("invalid", ["duplicate", "backward", "cursor", "project", "missing", "overflow"])
def test_exweb_fixture_rejects_broken_or_missing_paginated_discovery(invalid):
    rows = [item("a"), item("b"), item("c")]
    cursor = "c"
    if invalid == "duplicate": rows[1] = item("a")
    if invalid == "backward": rows[1] = item("0")
    if invalid == "cursor": cursor = "a"
    if invalid == "project": rows[0] = item("a", project_id="other-project")
    if invalid == "missing": cursor = None
    if invalid == "overflow": rows.append(item("d"))
    results = Pages({"": {"items": rows, "next_after_id": cursor}})
    with pytest.raises(AssertionError):
        find_exweb_review_draft(results, item("z")["metadata"])
    assert len(results.requests) == 1


def test_exweb_fixture_stops_at_its_explicit_page_budget():
    values = {}
    cursor = ""
    for number in range(8):
        ident = f"generation-{number:02d}"
        values[cursor] = {"items": [item(ident)], "next_after_id": ident}
        cursor = ident
    results = Pages(values)
    with pytest.raises(AssertionError, match="eight bounded pages"):
        find_exweb_review_draft(results, item("z")["metadata"])
    assert len(results.requests) == 8
