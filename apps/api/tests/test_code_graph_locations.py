from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.infrastructure.system_image.codebase_memory_locations import load_exact_locations


@pytest.mark.parametrize("rows,expected", [
    ([["payments.authorize", "pay.py", "2", "3"]], (2, 3)),
    ([["payments.authorize", "pay.py", "0", "3"]], None),
    ([["payments.authorize", "pay.py", "1", "300"]], None),
    ([["payments.authorize", "pay.py", "3", "2"]], None),
    ([["payments.authorize", "other.py", "1", "2"]], None),
    ([["payments.authorize", "pay.py", None, None]], None),
    ([["payments.authorize", "pay.py", "2", "3"], ["payments.authorize", "pay.py", "2", "3"]], None),
])
def test_exact_locations_require_unambiguous_valid_snapshot_ranges(tmp_path: Path, rows, expected) -> None:
    (tmp_path / "pay.py").write_text("# payment\ndef authorize():\n    return True\n")
    def call(tool, payload):
        assert tool == "query_graph"
        assert payload["project"] == "provider-private-project"
        return {"columns": ["n.qualified_name", "n.file_path", "n.start_line", "n.end_line"], "rows": rows}
    result = load_exact_locations(call, project="provider-private-project", root=tmp_path, identities=[("payments.authorize", "pay.py")])
    assert result.get(("payments.authorize", "pay.py")) == expected


def test_exact_location_schema_drift_fails_explicitly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="schema is incompatible"):
        load_exact_locations(lambda *args: {"rows": []}, project="p", root=tmp_path, identities=[("pay", "pay.py")])


def test_unicode_separators_do_not_inflate_provider_line_bounds(tmp_path: Path) -> None:
    (tmp_path / "pay.py").write_text('value = "a\u2028b\u2028c\u2028d"\n')
    result = load_exact_locations(lambda *args: {
        "columns": ["n.qualified_name", "n.file_path", "n.start_line", "n.end_line"],
        "rows": [["pay", "pay.py", 3, 4]],
    }, project="p", root=tmp_path, identities=[("pay", "pay.py")])
    assert result == {}
