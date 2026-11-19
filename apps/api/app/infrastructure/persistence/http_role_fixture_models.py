"""Private v2 state. Import explicitly; PostgreSQL schema is migration-owned."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpRoleCredentialEnvelopeRecord(Base):
    __tablename__ = "quality_http_role_credential_envelopes"
    __table_args__ = (
        CheckConstraint("storage_key ~ '^private-http-role-credentials/[0-9a-f]{64}$'", name="ck_role_envelope_key"),
        CheckConstraint("octet_length(envelope) BETWEEN 1 AND 32768", name="ck_role_envelope_bytes"),
        CheckConstraint("nasus_http_role_envelope_valid(envelope)", name="ck_role_envelope_ciphertext"),
        CheckConstraint("content_hash = 'sha256:' || encode(sha256(envelope), 'hex')", name="ck_role_envelope_hash"),
    )
    storage_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    envelope: Mapped[bytes] = mapped_column(LargeBinary)
    content_hash: Mapped[str] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class HttpRoleFixtureClaimRecord(Base):
    __tablename__ = "quality_http_role_fixture_claims"
    __table_args__ = (
        UniqueConstraint("project_id", "batch_id", "case_id", "phase", "claim_hash", name="uq_role_fixture_claim_hash"),
        CheckConstraint("project_id ~ '^[A-Za-z0-9_.:-]{1,128}$' AND batch_id ~ '^[A-Za-z0-9_.:-]{1,128}$' "
                        "AND case_id ~ '^[A-Za-z0-9_.:-]{1,128}$'", name="ck_role_fixture_claim_identity"),
        CheckConstraint("phase IN ('setup', 'cleanup')", name="ck_role_fixture_claim_phase"),
        CheckConstraint("octet_length(payload) BETWEEN 1 AND 4096", name="ck_role_fixture_claim_bytes"),
        CheckConstraint("claim_hash = 'sha256:' || encode(sha256(payload), 'hex')", name="ck_role_fixture_claim_hash"),
    )
    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    phase: Mapped[str] = mapped_column(String(16), primary_key=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    claim_hash: Mapped[str] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class HttpRoleFixtureResultRecord(Base):
    __tablename__ = "quality_http_role_fixture_results"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "batch_id", "case_id", "phase", "claim_hash"],
            ["quality_http_role_fixture_claims." + name for name in
             ("project_id", "batch_id", "case_id", "phase", "claim_hash")], name="fk_role_fixture_original_claim"),
        CheckConstraint("phase IN ('setup', 'cleanup')", name="ck_role_fixture_result_phase"),
        CheckConstraint("octet_length(payload) BETWEEN 1 AND 16384", name="ck_role_fixture_result_bytes"),
        CheckConstraint("content_hash = 'sha256:' || encode(sha256(payload), 'hex')", name="ck_role_fixture_result_hash"),
    )
    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    phase: Mapped[str] = mapped_column(String(16), primary_key=True)
    claim_hash: Mapped[str] = mapped_column(String(71))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    content_hash: Mapped[str] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
