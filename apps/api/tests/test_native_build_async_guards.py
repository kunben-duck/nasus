"""Application scheduling specimens, not PG, Temporal or Java build evidence."""
import asyncio
from threading import Event
from types import SimpleNamespace
import time

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope, current_actor
from apps.api.app.application.quality_loop.native_build_inputs import NativeBuildCommand
from apps.api.app.application.quality_loop.native_build_jobs import NativeBuildJobApplicationService
from apps.api.app.application.quality_loop.native_builds import NativeBuildApplicationService
from apps.api.app.domain.quality_loop.native_build import NativeBuildOutput
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_native_build import request_value, protocol_jar


def application_specimen(request, guard, *, replay=False):
    actor = UserProfile(id="guard-actor", name="Guard specimen", email="guard@example.test", role="platform_admin")
    policy = {"image_id": "sha256:" + "a" * 64, "protocol_specimen": True}
    access = SimpleNamespace(actor_id=actor.id, fingerprint=byte_digest(b"scope"), effective_project_role="platform_admin",
        require_binding=lambda _binding: guard("binding"))
    pin = request.source.pin
    command = NativeBuildCommand(project_id=pin.project_id, image_revision_id=pin.image_revision_id,
        image_artifact_hash=pin.image_artifact_hash, binding_id=pin.binding_id,
        source_revision_id=pin.source_revision_id, artifact_path=request.artifact_path,
        request_digest=request.digest, operator_policy_digest=snapshot_digest(policy), source_scope_digest=access.fingerprint)
    calls = []

    def scoped(_project):
        guard("scope")
        return access

    def operator():
        guard("policy")
        return dict(policy)

    def build(original, *, require_work):
        guard("build")
        require_work()
        calls.append("build")
        assert original == request
        artifact = protocol_jar()
        return NativeBuildOutput(original.digest, artifact, b"protocol scheduling specimen",
            {"image_id": policy["image_id"], "maven": "3.9.11", "java": "21", "network": "none",
                "dependency_cache": "operator_read_only", "version_output_hash": byte_digest(b"version")}, {})

    def reserve(_command, _source, _policy, **options):
        guard("reserve")
        options["require_current"]()
        calls.append("reserve")
        return {"build_id": "guard-build"}

    def commit(_command, _saved, receipt, **options):
        guard("commit")
        options["require_current"]()
        assert receipt["request_digest"] == request.digest and receipt["execution_authorized"] is False
        calls.append("commit")
        return {"build_id": "guard-build", "execution_authorized": False}

    def source(**_selection):
        guard("source")
        return request.source

    def inspect(_project, _invocation):
        guard("inspect")
        return {"request": command.model_dump(mode="json"), "result": {} if replay else None, "reservation": None}

    application = NativeBuildApplicationService(SimpleNamespace(read=source),
        SimpleNamespace(scope=scoped, require_current=lambda _scope: guard("authority")),
        SimpleNamespace(policy=operator, build=build), SimpleNamespace(inspect=inspect, reserve=reserve, commit=commit),
        SimpleNamespace(put=lambda *_args: (guard("archive"), {"artifact_ref": "specimen"})[1]))
    if replay:
        application.read = lambda *_args: (guard("read"), {"metadata": {"build_id": "original"}})[1]
    return actor, application, command, calls


@pytest.mark.parametrize("slow_port", ["scope", "policy", "work", "authority", "receipt", "source", "archive"])
def test_blocking_build_guards_do_not_starve_event_loop_and_keep_actor(request_value, monkeypatch, slow_port):
    async def scenario():
        observed, ticks = [], []

        def guard(port):
            assert current_actor().user.id == "guard-actor"
            observed.append(port)
            if port == slow_port:
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("blocking native build port ran on the event loop: " + port)
                time.sleep(0.015)

        actor, application, command, calls = application_specimen(request_value, guard)
        from apps.api.app.application.quality_loop import native_builds
        original_receipt = native_builds.build_receipt

        def receipt(*args):
            guard("receipt")
            return original_receipt(*args)

        monkeypatch.setattr(native_builds, "build_receipt", receipt)
        stop = asyncio.Event()

        async def pulse():
            while not stop.is_set():
                await asyncio.sleep(0.001)
                ticks.append(True)

        with actor_scope(actor):
            pulse_task = asyncio.create_task(pulse())
            try:
                result = await application.execute(command, invocation_id="guard-command", lease="specimen",
                    require_work=lambda: guard("work"))
            finally:
                stop.set()
                await pulse_task
        assert slow_port in observed and len(ticks) >= 2
        assert calls == ["reserve", "build", "commit"] and result["execution_authorized"] is False

    asyncio.run(scenario())


def test_original_result_replay_does_not_block_lease_check_or_rebuild(request_value):
    async def scenario():
        observed = []

        def guard(port):
            assert current_actor().user.id == "guard-actor"
            observed.append(port)
            if port in {"scope", "work", "read"}:
                with pytest.raises(RuntimeError, match="no running event loop"):
                    asyncio.get_running_loop()

        actor, application, command, calls = application_specimen(request_value, guard, replay=True)
        with actor_scope(actor):
            result = await application.execute(command, invocation_id="guard-command", lease="specimen",
                require_work=lambda: guard("work"))
        assert result == {"build_id": "original"} and not calls and "work" in observed

    asyncio.run(scenario())


@pytest.mark.parametrize("control", ["dispatch", "cancel"])
def test_async_job_control_keeps_authority_io_off_loop(request_value, control):
    async def scenario():
        def guard(port):
            if port == "scope":
                with pytest.raises(RuntimeError, match="no running event loop"):
                    asyncio.get_running_loop()

        actor, application, command, _calls = application_specimen(request_value, guard, replay=True)
        delivered = []

        async def deliver(ident):
            delivered.append(ident)

        jobs = NativeBuildJobApplicationService(application,
            SimpleNamespace(require_running=lambda *_args: None, finish=lambda *_args, **_options: "cancelled",
                cancellation_delivered=lambda *_args: None), SimpleNamespace(start=deliver, cancel=deliver))
        with actor_scope(actor):
            if control == "dispatch":
                await jobs.dispatch(command, "guard-command")
            else:
                await jobs.cancel(SimpleNamespace(project_id=command.project_id, invocation_id="guard-command"), control_id="cancel-command")
        assert delivered == ["guard-command"]

    asyncio.run(scenario())


@pytest.mark.parametrize("guard_number", [2, 4])
def test_cancellation_during_slow_guard_never_starts_the_next_side_effect(request_value, guard_number):
    async def scenario():
        entered, released, finished = Event(), Event(), Event()
        checks, observed = [], []

        def guard(port):
            observed.append(port)
            if port == "work":
                checks.append(True)
                if len(checks) == guard_number:
                    entered.set()
                    try:
                        assert released.wait(3)
                    finally:
                        finished.set()

        actor, application, command, calls = application_specimen(request_value, guard)
        with actor_scope(actor):
            task = asyncio.create_task(application.execute(command, invocation_id="guard-command", lease="specimen",
                require_work=lambda: guard("work")))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            finally:
                released.set()
                assert await asyncio.to_thread(finished.wait, 3)
        assert calls == (["reserve"] if guard_number == 2 else ["reserve", "build"])
        assert "archive" not in observed and "commit" not in observed

    asyncio.run(scenario())


@pytest.mark.parametrize("guard_number", [2, 4])
def test_revoked_guard_keeps_original_reservation_without_archiving_or_committing(request_value, guard_number):
    async def scenario():
        checks, observed = [], []

        def guard(port):
            observed.append(port)
            if port == "authority":
                checks.append(True)
                if len(checks) == guard_number:
                    raise PermissionError("explicit authority revoked during native build")

        actor, application, command, calls = application_specimen(request_value, guard)
        with actor_scope(actor):
            with pytest.raises(PermissionError, match="revoked"):
                await application.execute(command, invocation_id="guard-command", lease="specimen",
                    require_work=lambda: guard("work"))
        assert calls == (["reserve"] if guard_number == 2 else ["reserve", "build"])
        assert "archive" not in observed and "commit" not in observed

    asyncio.run(scenario())
