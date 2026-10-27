from pydantic import ValidationError

from ..quality_loop.environment_observation_records import EnvironmentRecordQuery
from ..quality_loop.http_fixture_recipes import HttpFixtureRecipeRequest
from ...domain.quality_loop.http_fixture_recipe import RECIPE_TOOL, RECIPE_TOOLS
from .environment_record_receipts import EnvironmentRecordReceiptAccess
from .errors import PlatformApplicationError
from .tool_handlers.query_input import query_payload


class HttpFixtureRecipeReceiptAccess(EnvironmentRecordReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id in RECIPE_TOOLS

    @staticmethod
    def _scope(invocation):
        model = HttpFixtureRecipeRequest if invocation.tool_id == RECIPE_TOOL else EnvironmentRecordQuery
        try:
            return model.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except ValidationError as exc:
            raise PlatformApplicationError("fixture_recipe_invalid", "Original fixture recipe scope cannot be verified.", 409) from exc

    @staticmethod
    def _receipt(invocation):
        result = invocation.result
        receipt = result.http_fixture_recipe if result else None
        if invocation.status != "completed":
            if receipt is not None:
                raise PlatformApplicationError("fixture_recipe_invalid", "Incomplete command cannot contain a fixture recipe receipt.", 502)
            return None
        if (result is None or result.invocation_id != invocation.id or result.status != "completed" or type(receipt) is not dict
                or invocation.tool_id == RECIPE_TOOL and (type(receipt.get("metadata")) is not dict
                    or receipt["metadata"].get("invocation_id") != invocation.id)):
            raise PlatformApplicationError("fixture_recipe_invalid", "Original fixture recipe receipt cannot be verified.", 502)
        return receipt

    def broadcast_view(self, invocation):
        value = super().broadcast_view(invocation)
        if self.applies(invocation):
            return value.model_copy(update={"summary": f"Fixture definition command status: {invocation.status}."})
        return value
