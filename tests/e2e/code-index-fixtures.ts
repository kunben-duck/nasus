import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'

// Persist a protocol-state fixture, not a claim that a native provider was run.
// Source bytes and public reads/cancellation still use real isolated PG and APIs.
export function registerBrowserIndex(projectId: string, revisionId: string, sdkContract = false) {
  const database = process.env.NASUS_TEST_DATABASE_URL
  if (!database || database !== process.env.NASUS_E2E_DATABASE_URL) throw new Error('Isolated PostgreSQL is required')
  const result = execFileSync(resolve('.venv/bin/python'), ['-c', `
import json, os, sys
from dataclasses import asdict
from uuid import uuid4
from sqlalchemy.engine import make_url
from apps.api.app.application.system_image.code_index_generations import code_unit_snapshot_hash
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.code_provider_protocol import CodeProviderSDKReceipt
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
url = make_url(os.environ['NASUS_DATABASE_URL'])
assert url.get_backend_name() == 'postgresql' and url.host in {'localhost', '127.0.0.1', '::1'}
assert url.database.startswith('nasus_test_'), 'never write browser fixtures to developer data'
project, revision_id, sdk_contract = sys.argv[1:]
with session_scope() as session:
    revision = session.get(SourceRevisionRecord, revision_id)
    assert revision.project_id == project
    binding = session.get(SourceBindingRecord, revision.binding_id)
    source = RawAssetRecord(id=binding.legacy_source_id, project_id=project, source_type='code',
        source_uri=binding.external_identity, content_ref=revision.manifest_ref, content_hash=revision.content_hash,
        ingestion_status='indexed')
    command = 'browser-index-' + uuid4().hex
    session.add(ToolInvocationRecord(id=command, tool_id='system_image.build.structure', status='running',
        summary='Explicit browser protocol-state fixture; native provider not executed', input_payload={'project_id': project}))
units = SourceIngestionService().extract_text_units(source)
repository = CodeIndexGenerationRepository()
pin = repository.register(source, invocation_id=command,
    snapshot_hash=code_unit_snapshot_hash(units),
    provider_fingerprint=snapshot_digest({'fixture': 'browser-protocol-only', 'sdk': sdk_contract}))
if sdk_contract == 'true':
    # Explicit SDK receipt fixture; these digests do not attest native execution.
    lease = repository.claim(pin, owner_id='browser-sdk-fixture')
    receipt = CodeProviderSDKReceipt('codegraph', '@colbymchenry/codegraph', '1.6.2', 'package_public_entry',
        snapshot_digest({'fixture': 'sdk-contract-only'}), snapshot_digest({'fixture': 'sdk-runtime-not-executed'}),
        ('CodeGraph.init', 'setLogger', 'graph.indexAll', 'graph.getStats', 'graph.getFiles', 'graph.getNodesInFile',
         'graph.getOutgoingEdges', 'graph.getIndexState', 'graph.getPendingReferenceCount', 'graph.close'),
        ('sdk_projection_subset_not_complete_native_graph', 'os_sandbox_not_verified'))
    repository.record_protocol(lease, receipt)
    repository.mark_prepared(lease, state='degraded')
    repository.record_projection(lease, projection_hash=snapshot_digest({'fixture': 'empty-browser-projection'}),
        provider_version='1.6.2', entity_count=0, relationship_count=0)
    assert repository.release(lease)
print(json.dumps(asdict(pin)))
`, projectId, revisionId, String(sdkContract)], { env: { ...process.env, NASUS_DATABASE_URL: database }, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  return JSON.parse(result) as { generation_id: string; invocation_id: string; content_hash: string }
}
