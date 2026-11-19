"""Append-only ciphertext credentials and original role-fixture dispatch results."""
from alembic import op
import sqlalchemy as sa


revision = "0132_http_role_private_state"
down_revision = "0131_execution_environment"
branch_labels = None
depends_on = None

TABLES = ("quality_http_role_fixture_results", "quality_http_role_fixture_claims",
          "quality_http_role_credential_envelopes")


def upgrade():
    # This structural check has no decryption key. AES-GCM authentication remains
    # the cipher's responsibility; neither direct SQL nor the adapter may store
    # a plaintext JSON credential in the envelope column.
    op.execute(r"""
        CREATE FUNCTION nasus_http_role_envelope_valid(body bytea) RETURNS boolean AS $$
        DECLARE value jsonb; aad jsonb; scope jsonb; field text; decoded bytea;
                scope_text text; aad_text text; canonical text;
        BEGIN
          IF octet_length(body) NOT BETWEEN 1 AND 32768 THEN RETURN false; END IF;
          value := convert_from(body, 'UTF8')::jsonb;
          IF jsonb_typeof(value) <> 'object' OR NOT value ?& ARRAY['aad', 'nonce', 'ciphertext']
             OR value - ARRAY['aad', 'nonce', 'ciphertext'] <> '{}'::jsonb THEN RETURN false; END IF;
          aad := value->'aad';
          IF jsonb_typeof(aad) <> 'object'
             OR NOT aad ?& ARRAY['schema', 'scope', 'purpose', 'record_id', 'key_id']
             OR aad - ARRAY['schema', 'scope', 'purpose', 'record_id', 'key_id'] <> '{}'::jsonb
             OR jsonb_typeof(aad->'schema') <> 'string' OR jsonb_typeof(aad->'purpose') <> 'string'
             OR aad->>'schema' <> 'nasus.private-http-envelope.v1' OR aad->>'purpose' <> 'credential'
             OR jsonb_typeof(aad->'record_id') <> 'string'
             OR aad->>'record_id' !~ '^role-credential:[0-9a-f]{64}$'
             OR jsonb_typeof(aad->'key_id') <> 'string'
             OR aad->>'key_id' !~ '^[A-Za-z0-9_.:-]{1,128}$' THEN RETURN false; END IF;
          scope := aad->'scope';
          IF jsonb_typeof(scope) <> 'object'
             OR NOT scope ?& ARRAY['project_id', 'version_id', 'batch_id', 'case_id', 'environment_id',
                                  'environment_epoch', 'inventory_hash', 'expires_at']
             OR scope - ARRAY['project_id', 'version_id', 'batch_id', 'case_id', 'environment_id',
                              'environment_epoch', 'inventory_hash', 'expires_at'] <> '{}'::jsonb
             THEN RETURN false; END IF;
          FOREACH field IN ARRAY ARRAY['project_id', 'version_id', 'batch_id', 'case_id', 'environment_id'] LOOP
            IF jsonb_typeof(scope->field) <> 'string'
               OR scope->>field !~ '^[A-Za-z0-9_.:-]{1,128}$' THEN RETURN false; END IF;
          END LOOP;
          IF jsonb_typeof(scope->'environment_epoch') <> 'number'
             OR scope->>'environment_epoch' !~ '^[1-9][0-9]{0,15}$'
             OR (scope->>'environment_epoch')::bigint > 9007199254740991
             OR jsonb_typeof(scope->'inventory_hash') <> 'string'
             OR scope->>'inventory_hash' !~ '^sha256:[0-9a-f]{64}$'
             OR jsonb_typeof(scope->'expires_at') <> 'string'
             OR length(scope->>'expires_at') > 128
             OR scope->>'expires_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
             THEN RETURN false; END IF;
          PERFORM (scope->>'expires_at')::timestamptz;
          FOREACH field IN ARRAY ARRAY['nonce', 'ciphertext'] LOOP
            IF jsonb_typeof(value->field) <> 'string'
               OR value->>field !~ '^[A-Za-z0-9+/]+={0,2}$' THEN RETURN false; END IF;
            decoded := decode(value->>field, 'base64');
            IF replace(encode(decoded, 'base64'), E'\n', '') <> value->>field THEN RETURN false; END IF;
            IF field = 'nonce' AND octet_length(decoded) <> 12 THEN RETURN false; END IF;
            IF field = 'ciphertext' AND octet_length(decoded) NOT BETWEEN 17 AND 16400 THEN RETURN false; END IF;
          END LOOP;
          SELECT '{' || string_agg(to_json(key)::text || ':' || item::text, ',' ORDER BY key COLLATE "C") || '}'
            INTO scope_text FROM jsonb_each(scope) AS entry(key, item);
          SELECT '{' || string_agg(to_json(key)::text || ':' ||
            CASE WHEN key = 'scope' THEN scope_text ELSE item::text END, ',' ORDER BY key COLLATE "C") || '}'
            INTO aad_text FROM jsonb_each(aad) AS entry(key, item);
          SELECT '{' || string_agg(to_json(key)::text || ':' ||
            CASE WHEN key = 'aad' THEN aad_text ELSE item::text END, ',' ORDER BY key COLLATE "C") || '}'
            INTO canonical FROM jsonb_each(value) AS entry(key, item);
          IF convert_from(body, 'UTF8') <> canonical THEN RETURN false; END IF;
          RETURN true;
        EXCEPTION WHEN OTHERS THEN RETURN false;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE STRICT
    """)
    op.create_table("quality_http_role_credential_envelopes",
        sa.Column("storage_key", sa.String(128), primary_key=True),
        sa.Column("envelope", sa.LargeBinary(), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.CheckConstraint("storage_key ~ '^private-http-role-credentials/[0-9a-f]{64}$'", name="ck_role_envelope_key"),
        sa.CheckConstraint("octet_length(envelope) BETWEEN 1 AND 32768", name="ck_role_envelope_bytes"),
        sa.CheckConstraint("nasus_http_role_envelope_valid(envelope)", name="ck_role_envelope_ciphertext"),
        sa.CheckConstraint("content_hash = 'sha256:' || encode(sha256(envelope), 'hex')", name="ck_role_envelope_hash"))
    op.create_table("quality_http_role_fixture_claims",
        sa.Column("project_id", sa.String(128), primary_key=True),
        sa.Column("batch_id", sa.String(128), primary_key=True),
        sa.Column("case_id", sa.String(128), primary_key=True),
        sa.Column("phase", sa.String(16), primary_key=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("claim_hash", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.UniqueConstraint("project_id", "batch_id", "case_id", "phase", "claim_hash", name="uq_role_fixture_claim_hash"),
        sa.CheckConstraint("project_id ~ '^[A-Za-z0-9_.:-]{1,128}$' AND batch_id ~ '^[A-Za-z0-9_.:-]{1,128}$' "
                           "AND case_id ~ '^[A-Za-z0-9_.:-]{1,128}$'", name="ck_role_fixture_claim_identity"),
        sa.CheckConstraint("phase IN ('setup', 'cleanup')", name="ck_role_fixture_claim_phase"),
        sa.CheckConstraint("octet_length(payload) BETWEEN 1 AND 4096", name="ck_role_fixture_claim_bytes"),
        sa.CheckConstraint("claim_hash = 'sha256:' || encode(sha256(payload), 'hex')", name="ck_role_fixture_claim_hash"))
    op.create_table("quality_http_role_fixture_results",
        sa.Column("project_id", sa.String(128), primary_key=True),
        sa.Column("batch_id", sa.String(128), primary_key=True),
        sa.Column("case_id", sa.String(128), primary_key=True),
        sa.Column("phase", sa.String(16), primary_key=True),
        sa.Column("claim_hash", sa.String(71), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.ForeignKeyConstraint(["project_id", "batch_id", "case_id", "phase", "claim_hash"],
            ["quality_http_role_fixture_claims." + name for name in
             ("project_id", "batch_id", "case_id", "phase", "claim_hash")], name="fk_role_fixture_original_claim"),
        sa.CheckConstraint("phase IN ('setup', 'cleanup')", name="ck_role_fixture_result_phase"),
        sa.CheckConstraint("octet_length(payload) BETWEEN 1 AND 16384", name="ck_role_fixture_result_bytes"),
        sa.CheckConstraint("content_hash = 'sha256:' || encode(sha256(payload), 'hex')", name="ck_role_fixture_result_hash"))
    op.execute("""
        CREATE FUNCTION nasus_reject_http_role_private_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'private HTTP role state is immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_http_role_private_mutation()")
        op.execute(f"CREATE TRIGGER retain_{table} BEFORE TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION nasus_reject_http_role_private_mutation()")


def downgrade():
    # Never erase ciphertext or an unknown write to make a downgrade succeed.
    op.execute("LOCK TABLE " + ", ".join(TABLES) + " IN ACCESS EXCLUSIVE MODE")
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("cannot discard retained private HTTP role state")
    for table in TABLES:
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_http_role_private_mutation()")
    op.execute("DROP FUNCTION nasus_http_role_envelope_valid(bytea)")
