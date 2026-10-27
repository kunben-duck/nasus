import { expect, test } from '@playwright/test'
import { verifyGenerationHistory } from '../../apps/portal/src/domains/quality-loop/testDesignGenerationValidation'
import type { GenerationHistoryPage, GenerationHistoryRequest } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'

const request: GenerationHistoryRequest = { project_id: 'history-protocol-project', scope_revision_id: 'fixed-scope',
  scope_artifact_hash: `sha256:${'a'.repeat(64)}`, after_id: '', limit: 2 }
function fixture(): GenerationHistoryPage {
  return { request: { ...request }, items: ['command-01', 'command-02'].map((id) => ({ invocation_id: id,
    source_invocation_id: id, tool_id: 'quality.test_design.generate', status: 'failed' })), next_after_id: 'command-02',
    has_running: true, generation_authorized: false, execution_authorized: false }
}

test('bounded generation history permits running jobs outside the displayed page, not new authority', () => {
  expect(verifyGenerationHistory(fixture(), request)).toEqual(fixture())
  const empty = { ...fixture(), items: [], next_after_id: null, has_running: false }
  expect(verifyGenerationHistory(empty, request)).toEqual(empty)
  const recovered = fixture()
  recovered.items[1].tool_id = 'quality.test_design.recover'
  recovered.items[1].source_invocation_id = 'command-01'
  expect(verifyGenerationHistory(recovered, request)).toEqual(recovered)
})

test('bounded generation history rejects wrong pins, extra private payloads and cursor or status corruption', () => {
  for (const change of [
    (v: GenerationHistoryPage) => { v.request.scope_artifact_hash = `sha256:${'b'.repeat(64)}` },
    (v: GenerationHistoryPage) => { v.request.project_id = 'another-project' },
    (v: GenerationHistoryPage) => { v.request.after_id = 'unexpected-cursor' },
    (v: GenerationHistoryPage) => { v.next_after_id = 'command-03' },
    (v: GenerationHistoryPage) => { v.items.reverse() },
    (v: GenerationHistoryPage) => { v.items[1].invocation_id = v.items[0].invocation_id },
    (v: GenerationHistoryPage) => { v.items.push({ ...v.items[1], invocation_id: 'command-03', source_invocation_id: 'command-03' }) },
    (v: GenerationHistoryPage) => { v.items[0].status = 'running'; v.has_running = false },
    (v: GenerationHistoryPage) => { v.items[0].source_invocation_id = 'not-its-original-command' },
    (v: GenerationHistoryPage) => { Object.assign(v.items[0], { input_payload: { source_body: 'private' } }) },
    (v: GenerationHistoryPage) => { Object.assign(v, { generation_authorized: true }) },
    (v: GenerationHistoryPage) => { Object.assign(v, { execution_authorized: true }) },
  ]) { const invalid = fixture(); change(invalid); expect(() => verifyGenerationHistory(invalid, request)).toThrow() }
  expect(() => verifyGenerationHistory({ ...fixture(), items: null }, request)).toThrow()
  expect(() => verifyGenerationHistory({ ...fixture(), items: [null] }, request)).toThrow()
  expect(() => verifyGenerationHistory({ ...fixture(), items: [fixture().items[0]], next_after_id: 'command-01' }, request)).toThrow()
})
