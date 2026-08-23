# Nasus Backup And Recovery Runbook

## 1. Scope

This runbook covers the V1 durable facts owned by Nasus:

- PostgreSQL application facts, audit records, SSE outbox, Agent memory,
  LangGraph checkpoints, and the Temporal databases when they are hosted in the
  same Compose PostgreSQL cluster;
- MinIO/S3 raw assets, generated artifacts, screenshots, traces, avatars, and
  execution evidence, including object versions and delete markers.

Source caches, built images, and Portal assets are reproducible and are not part
of the data backup. Secrets are restored from the deployment secret manager,
never from this backup.

## 2. Recovery objectives

| Data class | Production target | V1 portable backup | Required production control |
| --- | --- | --- | --- |
| PostgreSQL control plane | RPO <= 15 minutes | logical snapshot every 6 hours | managed PITR/WAL archive in addition to this script |
| MinIO/S3 evidence | RPO <= 15 minutes | version-aware logical snapshot daily | bucket versioning plus cross-site replication/object lock |
| Whole platform | RTO <= 4 hours | quarterly restore exercise | tested credentials, capacity, DNS and secret recovery |

The repository script is the portable, provider-independent recovery layer. It
does not replace PostgreSQL PITR or S3/MinIO replication. A production release
must configure both the portable snapshot and provider-native continuous data
protection.

## 3. Consistency and security invariants

1. Drain Portal/API writes and stop API, workflow workers, Temporal workers, and
   Runner submissions before a production logical snapshot or restore.
2. Keep PostgreSQL and MinIO available during backup. During restore, only these
   storage services may run.
3. Set `NASUS_BACKUP_QUIESCED=true` for staging/production backup and
   `NASUS_RESTORE_QUIESCED=true` for every restore. These flags are explicit
   operator assertions, not automatic traffic controls.
4. Set a secret `NASUS_BACKUP_MANIFEST_HMAC_KEY` with at least 32 characters.
   Staging and production backups fail closed without it.
5. Store the completed backup directory on encrypted, access-controlled,
   immutable storage. Files are mode `0600`; filesystem permissions are not a
   substitute for encryption and retention policy.
6. Never restore into a running environment. Restore terminates database
   sessions, cleans the backed-up schemas, and replaces every object version in
   the configured bucket.

## 4. Create a backup

For the Compose deployment, load the deployment environment and quiesce writes:

```bash
set -a
source .env
set +a

export NASUS_ENV=production
export NASUS_BACKUP_QUIESCED=true
export NASUS_BACKUP_MANIFEST_HMAC_KEY='<secret-manager-value>'
export NASUS_BACKUP_ROOT=/mnt/encrypted-nasus-backups
npm run backup:data
```

The default database set is `POSTGRES_DB`, `temporal`, and
`temporal_visibility`; missing Temporal databases are skipped, while a missing
application database fails the backup. Override with
`NASUS_BACKUP_POSTGRES_DATABASES=nasus,temporal,temporal_visibility`.

The backup is written into a hidden `.partial` directory first. It becomes a
visible `<timestamp>/` recovery point only after PostgreSQL dumps, every S3
version payload, and the signed integrity manifest validate successfully.

Required artifacts:

```text
<backup-id>/
  backup-manifest.json
  postgres/<database>.dump
  object-storage/object-storage.json
  object-storage/objects/**/*.blob
```

Copy the finalized directory to immutable backup storage. Alert if the command
does not produce a new signed recovery point within the schedule.

## 5. Restore a backup

1. Declare an incident and record the desired recovery point.
2. Stop API, Portal writes, workflow workers, Temporal, and Runner. Keep only
   PostgreSQL and MinIO/S3 reachable.
3. Restore deployment secrets separately. The settings encryption secret must
   be the same value used when encrypted model keys were written.
4. Run the destructive restore with the exact backup ID confirmation:

```bash
set -a
source .env
set +a

export NASUS_ENV=production
export NASUS_BACKUP_MANIFEST_HMAC_KEY='<secret-manager-value>'
export NASUS_RESTORE_CONFIRM='restore:20260808T120000Z'
export NASUS_RESTORE_QUIESCED=true
export NASUS_RESTORE_CLEAR_OBJECT_STORAGE=true
npm run restore:data -- /mnt/encrypted-nasus-backups/20260808T120000Z
```

The restore verifies every file checksum and manifest HMAC before changing
state. It recreates missing databases, restores PostgreSQL with `pg_restore
--clean --exit-on-error`, empties all target bucket versions, replays object
versions oldest-first, replays delete markers, and compares live payload hashes
and version counts with the snapshot. A verified report is written under
`.nasus/restore-reports/`.

## 6. Post-restore validation

Do not reopen traffic until all checks pass:

```bash
docker compose --profile app --profile temporal up -d api-migrate
docker compose --profile app --profile temporal up -d
curl -fsS http://127.0.0.1:8000/readyz
npm run test:smoke
```

Additionally verify:

- Alembic reports the expected head revision;
- `GET /readyz` reports PostgreSQL, object storage, Runner, Temporal workflow,
  and PostgreSQL checkpoints ready;
- a known `conversation -> tool invocation -> domain object -> evidence ->
  approval` chain is queryable;
- a known MinIO evidence reference downloads and its content hash matches;
- a paused AgentGoal can resume or is explicitly terminated through governance;
- encrypted model configuration can be decrypted with the restored secret.

Only then reopen traffic and attach the restore report to the incident record.

## 7. Recovery exercise

Run the isolated, destructive-in-a-temporary-stack exercise on every release and
at least quarterly in the deployed environment:

```bash
npm run verify:backup-restore
```

The exercise seeds multiple object versions and a delete marker, creates a
backup, mutates PostgreSQL and MinIO after the recovery point, restores, and
proves that later facts disappear while the selected recovery point and version
history remain intact. `npm run verify:v1-release` includes this exercise.
