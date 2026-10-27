"""Exact-source native build, canonical reservation and original-output replay."""
import asyncio
from typing import Protocol

from .native_build_execution import execute_native_build
from .native_build_inputs import NativeBuildSelection, NativeBuildCommand, NativeBuildTarget, NativeBuildOutcomeUnknown
from .native_build_ports import NativeBuildPort, NativeBuildArtifactPort
from ...domain.quality_loop.native_build import NativeBuildRequest, build_receipt
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.source_access import SourceAccessDenied


class NativeBuildSourcePort(Protocol):
    def read(self, *, project_id, image_revision_id, image_artifact_hash, binding_id, source_revision_id): ...


class NativeBuildRepositoryPort(Protocol):
    def inspect(self, project_id, invocation_id): ...
    def reserve(self, request, source_pin, operator_policy, *, actor_id, invocation_id, lease, require_current): ...
    def commit(self, request, saved, receipt, *, invocation_id, lease, require_current): ...


class NativeBuildApplicationService:
    def __init__(self, sources: NativeBuildSourcePort, authorization, builder: NativeBuildPort,
                 repository: NativeBuildRepositoryPort, artifacts: NativeBuildArtifactPort):
        self.sources, self.authorization, self.builder = sources, authorization, builder
        self.repository, self.artifacts = repository, artifacts

    def _access(self, project_id, *, execute=False):
        access = self.authorization.scope(project_id)
        if execute and access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("native source execution requires a current project administrator")
        return access

    def _request(self, selection):
        source = self.sources.read(**{key: getattr(selection, key) for key in
            ("project_id", "image_revision_id", "image_artifact_hash", "binding_id", "source_revision_id")})
        return NativeBuildRequest(source, selection.artifact_path, selection.expected_artifact_hash)

    def preview(self, selection: NativeBuildSelection):
        selection = NativeBuildSelection.model_validate(selection.model_dump(mode="json"))
        access = self._access(selection.project_id, execute=True)
        access.require_binding(selection.binding_id)
        request, policy = self._request(selection), self.builder.policy()
        self.authorization.require_current(access)
        command = NativeBuildCommand(**selection.model_dump(mode="json"), request_digest=request.digest,
            operator_policy_digest=snapshot_digest(policy), source_scope_digest=access.fingerprint)
        return {"request": command.model_dump(mode="json"), "source": {"pin": request.source.metadata()["pin"],
            "file_count": len(request.source.files), "byte_count": sum(len(item.body) for item in request.source.files)},
            "operator_policy": policy, "status": "preview", "source_execution_started": False,
            "execution_authorized": False, "remaining_gates": ["independent_build_confirmation", "native_target_execution"]}

    def require_receipt_inputs_access(self, scope):
        self.require_receipt_inputs_access_many((scope,))

    def require_receipt_inputs_access_many(self, scopes):
        if not 1 <= len(scopes) <= 128:
            raise ValueError("native build receipt scopes exceed the read bound")
        access = {scope.project_id: self._access(scope.project_id) for scope in scopes}
        for scope in scopes:
            if isinstance(scope, NativeBuildTarget):
                self.read(scope.project_id, scope.invocation_id)
            elif isinstance(scope, NativeBuildSelection):
                access[scope.project_id].require_binding(scope.binding_id)
                request = self._request(scope)
                if isinstance(scope, NativeBuildCommand) and request.digest != scope.request_digest:
                    raise ValueError("native build original command source differs")
            else:
                raise ValueError("unsupported native build receipt scope")
        # Recheck the initial cohort after every original archive has been read.
        for original in access.values():
            self.authorization.require_current(original)

    async def execute(self, command: NativeBuildCommand, *, invocation_id, lease, require_work):
        command = NativeBuildCommand.model_validate(command.model_dump(mode="json"))
        access = await asyncio.to_thread(self._access, command.project_id, execute=True)
        await asyncio.to_thread(access.require_binding, command.binding_id)
        prior = await asyncio.to_thread(self.repository.inspect, command.project_id, invocation_id)
        if prior["result"] is not None:
            view = await asyncio.to_thread(self.read, command.project_id, invocation_id)
            if prior["request"] != command.model_dump(mode="json"):
                raise ValueError("native build recovery cannot rebind its command")
            await asyncio.to_thread(require_work)
            return view["metadata"]
        if prior["reservation"] is not None:
            raise NativeBuildOutcomeUnknown("native build was reserved without a committed result; never automatically rebuild")
        request = await asyncio.to_thread(self._request, command.selection())
        policy = await asyncio.to_thread(self.builder.policy)
        request_digest = await asyncio.to_thread(lambda: request.digest)
        if (request_digest != command.request_digest or snapshot_digest(policy) != command.operator_policy_digest
                or access.fingerprint != command.source_scope_digest):
            raise ValueError("native build preview or authority changed; preview and confirm again")

        def current():
            require_work()
            self.authorization.require_current(access)
            if snapshot_digest(self.builder.policy()) != command.operator_policy_digest:
                raise ValueError("native build operator policy changed")

        source_pin = await asyncio.to_thread(request.source.metadata)
        reserved = await asyncio.to_thread(self.repository.reserve, command, source_pin, policy,
            actor_id=access.actor_id, invocation_id=invocation_id, lease=lease, require_current=current)
        # Source, policy and lease ports perform synchronous I/O. Keep their
        # guards off the event loop so renewal and cancellation remain runnable.
        await asyncio.to_thread(current)
        output = await execute_native_build(self.builder, request, require_work=current)
        if output.toolchain["image_id"] != policy["image_id"]:
            raise ValueError("native builder differs from the confirmed toolchain")
        receipt = await asyncio.to_thread(build_receipt, request, output)
        await asyncio.to_thread(current)
        saved = await asyncio.to_thread(self.artifacts.put, reserved["build_id"], request, output)
        await asyncio.to_thread(current)
        value = await asyncio.to_thread(self.repository.commit, command, saved, receipt,
            invocation_id=invocation_id, lease=lease, require_current=current)
        await asyncio.to_thread(self.authorization.require_current, access)
        return value

    def read(self, project_id, invocation_id):
        access = self._access(project_id)
        stored = self.repository.inspect(project_id, invocation_id)
        command = NativeBuildCommand.model_validate(stored["request"])
        access.require_binding(command.binding_id)
        request = self._request(command.selection())
        if request.digest != command.request_digest:
            raise ValueError("native build original source digest differs")
        metadata = stored["result"]
        if metadata is None:
            self.authorization.require_current(access)
            return {"project_id": project_id, "invocation_id": invocation_id, "status": stored["status"],
                "call_reserved": stored["reservation"] is not None,
                "outcome_unknown": stored["reservation"] is not None and stored["worker"] != "active",
                "worker": stored["worker"],
                "metadata": None, "cleanup_confirmed": False, "execution_authorized": False}
        archived = self.artifacts.read(metadata["build_id"], request, artifact_ref=metadata["artifact_ref"],
                                       artifact_hash=metadata["artifact_hash"])
        receipt = archived["receipt"]
        if (snapshot_digest(receipt) != metadata["receipt_digest"]
                or receipt["toolchain"]["image_id"] != stored["reservation"]["operator_policy"]["image_id"]):
            raise ValueError("native build original output differs from its registration")
        self.authorization.require_current(access)
        # The bytes remain inside the application boundary; this view exposes
        # no storage address, build log, source text or direct target download.
        return {"project_id": project_id, "invocation_id": invocation_id, "status": stored["status"],
            "call_reserved": True, "outcome_unknown": False,
            "metadata": {key: value for key, value in metadata.items() if key != "artifact_ref"},
            "receipt": receipt, "execution_authorized": False, "historical_not_live": True}
