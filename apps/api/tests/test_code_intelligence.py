from __future__ import annotations

import hashlib

import pytest

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import (
    TreeSitterCodeIntelligenceAdapter,
)


def _unit(path: str, text: str) -> SourceTextUnit:
    return SourceTextUnit(
        relative_path=path,
        text=text,
        byte_count=len(text.encode("utf-8")),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


@pytest.mark.parametrize(
    ("path", "text", "expected_language", "expected_entities"),
    [
        (
            "payments/api.py",
            """
from fastapi import APIRouter
router = APIRouter()

class PaymentService:
    def authorize(self):
        return normalize()

def normalize():
    return True

@router.post("/payments")
def create_payment():
    return normalize()
""",
            "python",
            {
                ("class", "PaymentService"),
                ("method", "authorize"),
                ("function", "normalize"),
                ("api_route", "POST /payments"),
                ("dependency", "fastapi"),
            },
        ),
        (
            "checkout/service.ts",
            """
import { gateway } from "@nasus/payments";
interface Cart { id: string }
class CheckoutService { submit() { normalize(); } }
const normalize = () => true;
router.get("/checkout", normalize);
""",
            "typescript",
            {
                ("interface", "Cart"),
                ("class", "CheckoutService"),
                ("method", "submit"),
                ("function", "normalize"),
                ("api_route", "GET /checkout"),
                ("dependency", "@nasus/payments"),
            },
        ),
        (
            "orders/OrderController.java",
            """
import java.util.List;
class OrderController {
    void submit() { validate(); }
    void validate() {}
}
""",
            "java",
            {
                ("class", "OrderController"),
                ("method", "submit"),
                ("method", "validate"),
                ("dependency", "java.util.List"),
            },
        ),
        (
            "orders/handler.go",
            """
package orders
import "fmt"
func Submit() { Validate() }
func Validate() { fmt.Println("ok") }
""",
            "go",
            {
                ("function", "Submit"),
                ("function", "Validate"),
                ("dependency", "fmt"),
            },
        ),
    ],
)
def test_tree_sitter_extracts_cross_language_entities_and_relationships(
    path: str,
    text: str,
    expected_language: str,
    expected_entities: set[tuple[str, str]],
) -> None:
    result = TreeSitterCodeIntelligenceAdapter().analyze([_unit(path, text)])

    actual_entities = {(item.entity_kind, item.name) for item in result.entities}
    assert expected_entities <= actual_entities
    assert f"parser-language:{expected_language}" in result.evidence_refs
    assert any(ref.startswith("parser:tree-sitter:") for ref in result.evidence_refs)
    assert any(item.relationship_kind == "belongs_to" for item in result.relationships)
    assert any(item.relationship_kind == "depends_on" for item in result.relationships)
    if expected_language in {"python", "typescript", "java", "go"}:
        assert any(item.relationship_kind == "calls" for item in result.relationships)


def test_unsupported_language_is_explicitly_marked_as_lexical_fallback() -> None:
    result = TreeSitterCodeIntelligenceAdapter().analyze(
        [_unit("legacy/payment.rb", "class PaymentService\n  def authorize\n  end\nend\n")]
    )

    assert result.unsupported_paths == ("legacy/payment.rb",)
    assert "parser:lexical-fallback" in result.evidence_refs
    assert "parser-unsupported:.rb" in result.evidence_refs
    assert any(item.entity_kind == "class" and item.name == "PaymentService" for item in result.entities)
    assert all(
        "parser:lexical-fallback" in item.evidence_refs
        for item in result.entities
    )
