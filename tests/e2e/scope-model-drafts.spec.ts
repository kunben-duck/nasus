// Browser protocol regression only; not retained live-model product acceptance.
import { expect, test } from '@playwright/test'
import { rmSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture, installGenerationProtocol } from './test-design-generation-fixtures'
import type { ScopeDraftSelection, ScopeDraftRequest } from '../../apps/portal/src/domains/quality-loop/scopeDraftApi'

function digest(value: unknown): string {
  const sort = (v: unknown): unknown => Array.isArray(v) ? v.map(sort) : v && typeof v === 'object'
    ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, sort(x)])) : v
  return 'sha256:' + createHash('sha256').update(JSON.stringify(sort(value))).digest('hex')
}
test('scope model request survives a lost acknowledgement and refresh without a new call or restored consent', async ({ page, request }) => {
  test.setTimeout(240_000)
  const source = analysisSource()
  try {
    const v = await generationScopeFixture(request, source)
    await installGenerationProtocol(page, v.scope)
    const hash = 'sha256:' + 'a'.repeat(64), errors: string[] = []
    let writes = 0, confirms = 0
    let original: { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result: null } | undefined
    page.on('pageerror', (e) => errors.push(e.message))
    await page.route(`**/v1/projects/${v.projectId}/quality/scope-drafts/preview`, async (route) => {
      const input = route.request().postDataJSON() as ScopeDraftSelection
      const model = { config_id: input.model_config_id, config_digest: hash, provider: 'openai_compatible', model_name: 'fixture-chat', base_url: 'https://fixture.example/v1' }
      const plan = { source_binding_ids: ['fixture-binding'], source_scope_digest: hash, messages_hash: hash, input_digest: hash,
        model_binding: model, budget: input.budget, timeout_seconds: 120,
        policy: { config_id: model.config_id, provider: model.provider, model_name: model.model_name, base_url: model.base_url,
          currency: 'USD', context_tokens: 32768, max_output_tokens: 8192, input_nanos_per_token: 1, output_nanos_per_token: 2,
          tokenizer_kind: 'tiktoken', tokenizer_id: 'fixture', tokenizer_digest: hash, framing_tokens: 10, policy_id: 'fixture-policy', revision: '1' },
        reservation: { currency: 'USD', call_count: 1, estimated_input_tokens: 4000, reserved_input_tokens_per_call: 32768,
          max_output_tokens_per_call: 1024, reserved_tokens: 33792, reserved_cost_nanos: 34816,
          count_basis: 'local_tokenizer_with_operator_framing', cost_basis: 'operator_rate_ceiling_not_provider_invoice' } }
      const prepared: ScopeDraftRequest = { ...input, input_digest: hash, model_config_digest: hash, plan_digest: digest(plan) }
      await route.fulfill({ json: { request: prepared, plan, provider: model.provider, model_name: model.model_name,
        destination: model.base_url, review_required: true, generation_authorized: false } })
    })
    await page.route(`**/v1/projects/${v.projectId}/quality/scope-drafts?*`, route => route.fulfill({ json: { items: [] } }))
    await page.route('**/v1/tool-invocations', async route => {
      if (route.request().method() !== 'POST' || route.request().postDataJSON()?.tool_id !== 'quality.test_design_scope.draft') return route.fallback()
      const payload = route.request().postDataJSON()
      writes++
      original = { id: 'scope-draft-original', tool_id: payload.tool_id, status: 'waiting_confirmation',
        input_payload: { ...payload.input, idempotency_key: payload.idempotency_key }, result: null }
      await route.abort('failed')
    })
    await page.route('**/v1/tool-invocations/resolve?*', route => route.fulfill({ json: original }))
    await page.route('**/v1/tool-invocations/scope-draft-original', route => route.fulfill({ json: original }))
    await page.route('**/v1/tool-invocations/scope-draft-original/confirm', async route => {
      confirms++; original!.status = 'failed'; original!.input_payload.confirmed_by_user = true
      await route.fulfill({ json: original })
    })
    await page.addInitScript(token => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    const open = async () => {
      await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
      await page.getByRole('button').filter({ hasText: v.contextId }).click()
      await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
    }
    await page.goto(`/projects/${v.projectId}/knowledge`); await open()
    const panel = page.getByRole('region', { name: 'Model scope draft', exact: true })
    await panel.getByRole('combobox', { name: 'Tested chat model', exact: true }).selectOption('ui-tested-model')
    for (const [name, value] of Object.entries({ 'Maximum input tokens': '24576', 'Maximum output tokens': '1024',
      'Total token reservation ceiling': '65536', 'Maximum reserved spend': '1' })) await panel.getByRole('spinbutton', { name, exact: true }).fill(value)
    await panel.getByRole('button', { name: 'Preview scope draft budget', exact: true }).click()
    const generate = panel.getByRole('button', { name: 'Generate scope draft', exact: true })
    const consent = panel.getByRole('checkbox', { name: /^I confirm this exact model destination/ })
    await expect(generate).toBeDisabled(); expect(writes).toBe(0)
    await consent.check(); await generate.click()
    await expect(panel.getByRole('button', { name: 'Verify original scope budget', exact: true })).toBeVisible()
    expect(writes).toBe(1); expect(confirms).toBe(0)
    await page.reload(); await open()
    await panel.getByRole('button', { name: 'Verify original scope budget', exact: true }).click()
    await expect(consent).not.toBeChecked(); await expect(generate).toBeDisabled()
    await expect(panel.getByRole('button', { name: 'Preview scope draft budget', exact: true })).toBeDisabled()
    expect(writes).toBe(1); expect(confirms).toBe(0)
    await consent.check(); await generate.click()
    await expect.poll(() => confirms).toBe(1)
    await panel.getByRole('button', { name: 'Reload model scope history', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Preview scope draft budget', exact: true })).toBeDisabled()
    expect(writes).toBe(1); expect(confirms).toBe(1); expect(errors).toEqual([])
  } finally { rmSync(source, { recursive: true, force: true }) }
})
