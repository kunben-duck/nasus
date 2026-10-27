import copy

import pytest

from apps.api.app.domain.system_image.context_pack import budget_context, canonical_bytes, MandatoryContextTooLarge
from apps.api.app.application.system_image.context_pack_inputs import ContextPreviewInput


def test_mandatory_constraints_are_never_squeezed_out_by_retrieval_or_budget():
    base = {"required_constraints": [{"id": "mandatory", "oracle": "批准的原文预期"}], "readiness": {"status": "partial"}}
    original = copy.deepcopy(base)
    facts = [{"title": "x" * 700}, {"title": "small optional observation"}]
    value = budget_context(base, facts, 512)
    assert value["required_constraints"] == original["required_constraints"] and base == original
    assert value["facts"] == [facts[1]] and value["budget"]["omitted_optional_facts"] == 1
    assert value["budget"]["used_upper_bound"] == len(canonical_bytes(value)) <= 512
    with pytest.raises(MandatoryContextTooLarge):
        budget_context({"required_constraints": [{"oracle": "预期" * 500}]}, [], 512)


@pytest.mark.parametrize("budget", [True, 511, 32769, "12000"])
def test_context_budget_is_strict_and_other_purposes_are_not_silently_test_design(budget):
    with pytest.raises(ValueError):
        budget_context({"required_constraints": []}, [], budget)
    with pytest.raises(ValueError):
        ContextPreviewInput(project_id="p", image_revision_id="i", image_artifact_hash="sha256:" + "a" * 64, purpose="release")
