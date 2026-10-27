"""Rebuild a leased native projection from immutable source archives."""
from dataclasses import asdict, replace
from pathlib import PurePosixPath
from uuid import uuid4

from ...domain.system_image.code_index_generation import CodeIndexLeaseLost
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_index_generation_ports import CodeIndexGenerationPort
from .code_index_ports import PreparedCodeIndexFactoryPort
from .source_ports import SourceIngestionPort, code_projection_payload


def code_unit_snapshot_hash(units):
    return snapshot_digest(sorted((str(PurePosixPath(unit.relative_path)), unit.content_hash, unit.byte_count) for unit in units))


class CodeIndexGenerationApplicationService:
    def __init__(self, repository: CodeIndexGenerationPort, source_reader: SourceIngestionPort,
                 factory: PreparedCodeIndexFactoryPort):
        self.repository, self.source_reader, self.factory = repository, source_reader, factory

    def open_index(self, source, *, invocation_id, check_current):
        check_current()
        fingerprint = self.factory.projection_fingerprint(check_current=check_current)
        units = self.source_reader.extract_text_units(source)
        check_current()
        pin = self.repository.register(source, invocation_id=invocation_id,
            snapshot_hash=code_unit_snapshot_hash(units), provider_fingerprint=fingerprint)
        return self._open(pin, units, check_current)

    def reopen(self, project_id, generation_id, *, check_current):
        check_current()
        pin = self.repository.get(project_id, generation_id)
        if self.factory.projection_fingerprint(check_current=check_current) != pin.provider_fingerprint:
            raise CodeIndexLeaseLost("code index provider build or policy has changed")
        units = self.source_reader.extract_text_units(self.repository.source(pin))
        check_current()
        return self._open(pin, units, check_current)

    def _open(self, pin, units, check_current):
        if code_unit_snapshot_hash(units) != pin.snapshot_hash:
            raise ValueError("restored code index source is not its pinned snapshot")
        check_current()
        lease = self.repository.claim(pin, owner_id=uuid4().hex)
        try:
            return LeasedCodeIndex(self.repository, lease, self.factory, units, check_current)
        except BaseException:
            self.repository.release(lease, failed=True)
            raise

    def cancel(self, project_id, generation_id, *, check_current):
        check_current()
        pin = self.repository.get(project_id, generation_id)
        self.repository.request_cancel(pin)


class LeasedCodeIndex:
    """Durable generation, ephemeral native session and epoch-scoped cursors."""
    def __init__(self, repository, lease, factory, units, authority):
        self.generation, self.lease = lease.pin, lease
        self._repository, self._authority, self._closed, self._failed = repository, authority, False, False
        self._factory, self._projection_checked = factory, False
        self._session = factory.open_index(units, check_current=self._check,
            namespace="nasus_" + snapshot_digest(asdict(lease.pin))[7:39],
            provider_fingerprint=lease.pin.provider_fingerprint)

    def _check(self):
        if self._closed:
            raise CodeIndexLeaseLost("code index worker session is closed")
        self._authority()
        self._repository.check(self.lease)

    def __enter__(self):
        try:
            self.prepare_index()
            return self
        except BaseException:
            self._failed = True
            self.close()
            raise

    def __exit__(self, exc_type, *_):
        self._failed = self._failed or exc_type is not None
        self.close()

    def prepare_index(self):
        try:
            self._require_provider()
            status = self._session.prepare_index()
            self._require_provider()
            self._repository.record_protocol(self.lease, self._session.protocol_receipt())
            self._repository.mark_prepared(self.lease, state=status.state)
            return status
        except BaseException:
            self._failed = True
            raise

    def _require_provider(self):
        self._check()
        if self._factory.projection_fingerprint(check_current=self._check) != self.generation.provider_fingerprint:
            raise CodeIndexLeaseLost("code index provider build or policy has changed")

    def _read(self, method, *args, **kwargs):
        self._check()
        try:
            verify = not self._projection_checked and method not in {"status", "capabilities", "protocol_receipt"}
            if verify:
                self._require_provider()
            result = getattr(self._session, method)(*args, **kwargs)
            if verify:
                self._require_provider()
                projection = self._session.read_projection()
                self._repository.record_projection(self.lease, projection_hash=snapshot_digest(code_projection_payload(projection)),
                    provider_version=projection.provider_version, entity_count=len(projection.entities),
                    relationship_count=len(projection.relationships))
                self._projection_checked = True
            self._check()
            return result
        except ValueError:
            # A rejected cursor or page bound does not corrupt an otherwise
            # queryable index. Native projection validation can still fail it.
            try:
                self._failed = self._failed or self._session.status().state in {"failed", "cancelled"}
            except BaseException:
                self._failed = True
            raise
        except BaseException:
            self._failed = True
            raise

    def status(self):
        return self._read("status")

    def protocol_receipt(self):
        return self._read("protocol_receipt")

    def capabilities(self):
        return self._read("capabilities")

    def entities(self, *, cursor=None, limit=50):
        return self._read("entities", cursor=cursor, limit=limit)

    def relations(self, *, cursor=None, limit=50):
        return self._read("relations", cursor=cursor, limit=limit)

    def locate(self, candidate_id):
        return self._read("locate", candidate_id)

    def impact(self, candidate_ids, **bounds):
        return self._read("impact", candidate_ids, **bounds)

    def read_projection(self):
        return self._read("read_projection")

    def cancel(self):
        status = self.status()
        self._repository.request_cancel(self.generation)
        return replace(status, state="cancellation_requested")

    def close(self):
        if not self._closed:
            try:
                self._session.close()
            finally:
                self._closed = True
                self._repository.release(self.lease, failed=self._failed)
