import { expect, test } from '@playwright/test'
import { join, resolve } from 'node:path'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { scopeFixture } from './test-design-scope-fixtures'

for (const theme of ['light', 'dark']) {
  test(`confirmed source invalidation preserves readable context and fails closed (${theme})`, async ({ page, request }) => {
    test.setTimeout(240_000)
    const source = analysisSource(), errors: string[] = []
    const eventStreams: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('request', (value) => {
      if (value.url().includes('/events?access_token=')) eventStreams.push(value.url())
    })
    try {
      const v = await scopeFixture(request, source)
      const root = `${analysisApi}/v1/projects/${v.projectId}/system-image`
      const before = v.context
      const beforeSource = (await v.revisions()).find((item) => item.source_revision_id === v.revision)!
      writeFileSync(join(source, 'AddedController.java'), 'package example; class AddedController { String added() { return "fixture"; } }\n')
      await v.invoke('system_image.sources.ingest')
      const afterSource = (await v.revisions()).find((item) => item.binding_id === beforeSource.binding_id && item.source_revision_id !== v.revision)!
      expect(afterSource).toBeTruthy()
      const selection = { project_id: v.projectId, context_id: v.contextId,
        context_artifact_hash: before.metadata.artifact_hash,
        before_revision_id: beforeSource.source_revision_id, after_revision_id: afterSource.source_revision_id }
      const preview = await v.invoke('query.system_image.context.change_impact', selection)
      expect(preview.result.image_query.invalidation_applied).toBe(false)
      const pending = await v.invoke('system_image.context.invalidate', { ...selection,
        expected_impact_hash: preview.result.image_query.result_hash, invalidation_scope: 'image_current_use',
        reason: 'Explicit browser source-change fixture; not business or execution approval' }, 'waiting_confirmation')
      const contextUrl = `${root}/context-packs/${v.contextId}`
      expect((await (await request.get(contextUrl, { headers: v.owner.headers })).json()).current_use.stale).toBe(false)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
      await page.addInitScript((token) => {
        localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
      }, v.owner.token)
      const inspect = async () => {
        await page.goto(`/projects/${v.projectId}/knowledge`)
        const panel = page.getByRole('region', { name: 'Test-design context packs', exact: true })
        await panel.getByRole('button', { name: 'Inspect published context', exact: true }).click()
        await panel.getByRole('button').filter({ hasText: v.contextId }).click()
        return panel
      }
      let panel = await inspect()
      await expect(panel.getByRole('region', { name: 'Archived context', exact: true })).toContainText(v.contextId)
      await expect(panel.getByTestId('context-invalidation')).toHaveCount(0)
      await expect.poll(() => eventStreams.some((url) => url.includes(`/conversations/${v.conversationId}/events?`))).toBe(true)
      const confirmed = await v.confirm(pending.id)
      const invalidationId = confirmed.result.object_refs[0].split(':')[1]
      const current = await request.get(contextUrl, { headers: v.owner.headers })
      expect(current.ok()).toBeTruthy()
      const archived = await current.json()
      expect(archived.metadata).toEqual(before.metadata)
      expect(archived.context).toEqual(before.context)
      expect(archived.current_use).toEqual({ stale: true, generation_authorized: false,
        reason: 'source_change_invalidated', invalidation_id: invalidationId })
      const receipt = await request.get(`${root}/context-invalidations/${invalidationId}`, { headers: v.owner.headers })
      expect(receipt.ok()).toBeTruthy()
      expect((await receipt.json()).metadata.invalidation_scope).toBe('image_current_use')
      // Real durable SSE must update the already-open pack without navigation,
      // manual refetch or page reload; the archived contents stay readable.
      await expect(panel.getByRole('region', { name: 'Archived context', exact: true })).toContainText(v.contextId)
      await expect(panel).toContainText('Inputs have changed. This historical pack cannot authorize current generation.')
      await expect(panel.getByTestId('context-invalidation')).toContainText(invalidationId)
      await expect(panel.getByRole('list', { name: 'Mandatory context constraints' })).toContainText('Content-Type includes text/event-stream')
      await page.reload()
      panel = page.getByRole('region', { name: 'Test-design context packs', exact: true })
      await panel.getByRole('button', { name: 'Inspect published context', exact: true }).click()
      await panel.getByRole('button').filter({ hasText: v.contextId }).click()
      await expect(panel).toContainText('Inputs have changed. This historical pack cannot authorize current generation.')
      await expect(panel.getByTestId('context-invalidation')).toContainText('Historical contents remain unchanged.')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await panel.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/context-invalidation-${theme}-desktop.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      await panel.getByRole('region', { name: 'Archived context', exact: true }).scrollIntoViewIfNeeded()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
      await page.screenshot({ path: resolve(`output/playwright/context-invalidation-${theme}-mobile.png`) })
      // Only these negative transport fixtures corrupt responses; writes above
      // use the real canonical confirmation and isolated PostgreSQL database.
      for (const guard of ['missing_id', 'bad_id', 'not_stale', 'unrelated_reason']) {
        await page.route(`**/system-image/context-packs/${v.contextId}`, async (route) => {
          const response = await route.fetch(), body = await response.json()
          if (guard === 'missing_id') delete body.current_use.invalidation_id
          if (guard === 'bad_id') body.current_use.invalidation_id = '<img onerror=alert(1)>'
          if (guard === 'not_stale') body.current_use.stale = false
          if (guard === 'unrelated_reason') body.current_use.reason = 'inputs_changed'
          await route.fulfill({ response, json: body })
        })
        await inspect()
        await expect(page.getByRole('alert')).toContainText('Published context could not be verified.')
        await expect(page.getByRole('region', { name: 'Archived context', exact: true })).toHaveCount(0)
        await page.unroute(`**/system-image/context-packs/${v.contextId}`)
      }
      expect(errors).toEqual([])
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}
