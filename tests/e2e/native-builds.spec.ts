import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve, join } from 'node:path'
import { analysisAccount, analysisApi, analysisSource, analysisSourcePolicy, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions } from './image-revision-fixtures'
import { installNativeBuildProtocol } from './native-build-fixtures'
import { zhCN } from '../../apps/portal/src/shared/i18n/messages'
import type { FrozenImageSources } from '../../apps/portal/src/domains/system-image/frozenImageSources'

for (const [theme, language] of [['light', 'en'], ['dark', 'zh']] as const) {
  test(`native build explicit confirmation, lost acknowledgement and historical reload (${theme})`, async ({ page, request }) => {
    test.setTimeout(300_000)
    const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
    if (!exweb) writeFileSync(join(source, 'pom.xml'), '<project><modelVersion>4.0.0</modelVersion><groupId>specimen</groupId><artifactId>specimen</artifactId><version>1</version></project>')
    try {
      const v = await captureAnalysis(request, source), [candidate] = await frozenRevisions(request, v.projectId, v.owner.headers)
      const response = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${candidate.image_revision_id}?section=source_members&offset=0&limit=25`, { headers: v.owner.headers })
      expect(response.ok()).toBeTruthy(); const original = await response.json(); expect(original.next_offset).toBeNull()
      const sources: FrozenImageSources = { project_id: v.projectId, image_revision_id: original.revision.image_revision_id, image_artifact_hash: original.revision.artifact_hash,
        manifest_id: original.revision.manifest_id, manifest_hash: original.revision.manifest_hash, source_members: original.items }
      const protocol = await installNativeBuildProtocol(page, sources), label = (key: keyof typeof zhCN) => language === 'zh' ? zhCN[key] : key
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme, language } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', locale) }, { token: v.owner.token, locale: language })
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message))
      const enter = async () => {
        await page.getByRole('button', { name: label('Image revisions'), exact: true }).click()
        const dialog = page.getByRole('dialog', { name: label('Image revisions'), exact: true })
        await dialog.getByRole('combobox', { name: label('Frozen candidate revision'), exact: true }).selectOption(candidate.image_revision_id)
        await dialog.getByRole('button', { name: label('Inspect fixed-source native build'), exact: true }).click()
        return dialog
      }
      await page.goto(`/projects/${v.projectId}/knowledge`)
      expect(protocol.previewReads).toBe(0); expect(protocol.archiveReads).toBe(0); expect(protocol.writes).toHaveLength(0)
      const dialog = await enter(), panel = dialog.getByRole('region', { name: label('Fixed-source native build'), exact: true })
      await expect(panel.getByRole('combobox', { name: label('Frozen code source'), exact: true })).toBeEnabled()
      await expect(panel.getByRole('button', { name: label('Preview exact native build'), exact: true })).toBeDisabled()
      const code = sources.source_members.find((s) => s.source_type === 'code')!
      await panel.getByRole('combobox', { name: label('Frozen code source'), exact: true }).selectOption(code.binding_id)
      const path = panel.getByRole('textbox', { name: label('Target JAR path'), exact: true })
      await path.fill('target/../unsafe.jar'); await expect(panel.getByRole('button', { name: label('Preview exact native build'), exact: true })).toBeDisabled()
      await path.fill('target/specimen.jar'); await panel.getByRole('button', { name: label('Preview exact native build'), exact: true }).click()
      const consent = panel.getByRole('checkbox'), save = panel.getByRole('button', { name: label('Start confirmed native build'), exact: true })
      await expect(save).toBeDisabled(); await consent.check(); await path.fill('target/changed-specimen.jar'); await expect(save).toHaveCount(0)
      await panel.getByRole('button', { name: label('Preview exact native build'), exact: true }).click(); await consent.check()
      protocol.loseCreateAck = true; protocol.denyResolve = true; await save.click()
      await expect(panel.getByRole('alert')).toContainText(label('Native build acknowledgement is unknown. Reload only reads the original command; it never rebuilds or confirms automatically.'))
      expect(protocol.writes).toHaveLength(1); expect(protocol.confirms).toHaveLength(0)
      protocol.denyResolve = false; await panel.getByRole('button', { name: label('Reload original native build'), exact: true }).click()
      const confirm = panel.getByRole('button', { name: label('Confirm original native build'), exact: true })
      await expect(confirm).toBeDisabled(); await expect(consent).toBeDisabled()
      await panel.getByRole('button', { name: label('Verify original build policy again'), exact: true }).click()
      await expect(consent).toBeEnabled(); await expect(consent).not.toBeChecked(); await consent.check()
      protocol.loseConfirmAck = true; await confirm.click()
      await expect(panel.getByTestId('native-build-original-command')).toContainText(label('running'))
      await expect(panel.getByTestId('native-build-original-artifact')).toHaveCount(0)
      expect(protocol.writes).toHaveLength(1); expect(protocol.confirms).toHaveLength(1)
      protocol.complete(); await panel.getByRole('button', { name: label('Reload original native build'), exact: true }).click()
      await expect(panel.getByTestId('native-build-original-artifact')).toBeVisible()
      await expect(panel).toContainText(label('Original build artifact verified; tests have not run'))
      expect(protocol.writes[0].source_revision_id).toBe(code.source_revision_id); expect(protocol.writes[0].artifact_path).toBe('target/changed-specimen.jar')
      await page.reload(); const restoredDialog = await enter(), restored = restoredDialog.getByRole('region', { name: label('Fixed-source native build'), exact: true })
      await expect(restored.getByTestId('native-build-original-artifact')).toBeVisible()
      expect(protocol.writes).toHaveLength(1); expect(protocol.confirms).toHaveLength(1)
      await page.setViewportSize({ width: 390, height: 844 })
      await restored.getByTestId('native-build-original-artifact').scrollIntoViewIfNeeded()
      const body = restoredDialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/native-build-${theme}-mobile.png`) })
      // Administrators retain restricted-source access. Revoke the original
      // actor's administrator role before testing source-reader revocation.
      const steward = await analysisAccount(request)
      expect((await request.put(`${analysisApi}/v1/projects/${v.projectId}/members/${steward.userId}`,
        { headers: v.owner.headers, data: { role: 'project_admin' } })).ok()).toBeTruthy()
      expect((await request.put(`${analysisApi}/v1/projects/${v.projectId}/members/${v.owner.userId}`,
        { headers: steward.headers, data: { role: 'qa_lead' } })).ok()).toBeTruthy()
      await restored.getByRole('button', { name: label('Reload original native build'), exact: true }).click()
      await expect(restored.getByTestId('native-build-original-artifact')).toBeVisible()
      analysisSourcePolicy(v.projectId, [])
      const denied = page.waitForResponse((response) => response.request().method() === 'GET'
        && response.url().includes(`/system-image/revisions/${candidate.image_revision_id}?section=source_members`)
        && response.status() === 403)
      await restored.getByRole('button', { name: label('Reload original native build'), exact: true }).click()
      await denied
      await expect(restoredDialog.getByRole('alert')).toContainText(label('Image revision could not be verified. Previous content is hidden; reload to check access.'))
      await expect(restoredDialog.getByTestId('native-build-original-artifact')).toHaveCount(0)
      expect(protocol.writes).toHaveLength(1); expect(protocol.confirms).toHaveLength(1); expect(errors).toEqual([])
    } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
  })

  test(`native cancellation requires independent consent and recovers its own lost acknowledgements (${theme})`, async ({ page, request }) => {
    test.setTimeout(300_000)
    const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
    if (!exweb) writeFileSync(join(source, 'pom.xml'), '<project><modelVersion>4.0.0</modelVersion><groupId>specimen</groupId><artifactId>specimen</artifactId><version>1</version></project>')
    try {
      const v = await captureAnalysis(request, source), [candidate] = await frozenRevisions(request, v.projectId, v.owner.headers)
      const response = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${candidate.image_revision_id}?section=source_members&offset=0&limit=25`, { headers: v.owner.headers })
      expect(response.ok()).toBeTruthy(); const image = await response.json(); expect(image.next_offset).toBeNull()
      const sources: FrozenImageSources = { project_id: v.projectId, image_revision_id: image.revision.image_revision_id, image_artifact_hash: image.revision.artifact_hash,
        manifest_id: image.revision.manifest_id, manifest_hash: image.revision.manifest_hash, source_members: image.items }
      const protocol = await installNativeBuildProtocol(page, sources), label = (key: keyof typeof zhCN) => language === 'zh' ? zhCN[key] : key
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme, language } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', locale) }, { token: v.owner.token, locale: language })
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message))
      const enter = async () => {
        await page.getByRole('button', { name: label('Image revisions'), exact: true }).click()
        const dialog = page.getByRole('dialog', { name: label('Image revisions'), exact: true })
        await dialog.getByRole('combobox', { name: label('Frozen candidate revision'), exact: true }).selectOption(candidate.image_revision_id)
        await dialog.getByRole('button', { name: label('Inspect fixed-source native build'), exact: true }).click()
        return dialog.getByRole('region', { name: label('Fixed-source native build'), exact: true })
      }
      await page.goto(`/projects/${v.projectId}/knowledge`)
      const panel = await enter(), sourceSelect = panel.getByRole('combobox', { name: label('Frozen code source'), exact: true })
      await expect(sourceSelect).toBeEnabled()
      await sourceSelect.selectOption(sources.source_members.find((s) => s.source_type === 'code')!.binding_id)
      await panel.getByRole('textbox', { name: label('Target JAR path'), exact: true }).fill('target/cancel-specimen.jar')
      await panel.getByRole('button', { name: label('Preview exact native build'), exact: true }).click()
      await panel.getByRole('checkbox').check()
      await panel.getByRole('button', { name: label('Start confirmed native build'), exact: true }).click()
      await expect(panel.getByTestId('native-build-original-command')).toContainText(label('running'))
      const cancellation = panel.getByRole('region', { name: label('Independent native build cancellation'), exact: true })
      const cancel = cancellation.getByRole('button', { name: label('Cancel original native build'), exact: true })
      await expect(cancel).toBeDisabled(); expect(protocol.cancelWrites).toHaveLength(0)
      await cancellation.getByRole('checkbox').check()
      protocol.loseCancelCreateAck = true; protocol.denyCancelResolve = true; await cancel.click()
      await expect(cancellation.getByRole('alert')).toContainText(label('Cancellation acknowledgement is unknown. Reload only reads the original cancellation; it never resends or confirms it automatically.'))
      await expect(cancellation.getByRole('button', { name: label('Prepare another independently confirmed cancellation'), exact: true })).toHaveCount(0)
      expect(protocol.cancelWrites).toHaveLength(1); expect(protocol.cancelConfirms).toHaveLength(0)
      expect(protocol.writes).toHaveLength(1); expect(protocol.confirms).toHaveLength(1)
      protocol.denyCancelResolve = false
      await cancellation.getByRole('button', { name: label('Reload original cancellation'), exact: true }).click()
      const confirm = cancellation.getByRole('button', { name: label('Confirm original cancellation'), exact: true })
      await expect(confirm).toBeDisabled(); await expect(cancellation.getByRole('checkbox')).not.toBeChecked()
      await cancellation.getByRole('checkbox').check(); protocol.loseCancelConfirmAck = true; await confirm.click()
      await expect(cancellation.getByTestId('native-build-cancellation-receipt')).toHaveText(label('Cancellation recorded; resource cleanup remains unverified.'))
      await expect(panel.getByTestId('native-build-original-command')).toContainText(label('cancelled'))
      await expect(panel.getByTestId('native-build-original-artifact')).toHaveCount(0)
      await expect(panel.getByRole('button', { name: label('Prepare another independently confirmed build'), exact: true })).toHaveCount(0)
      expect(protocol.cancelConfirms).toHaveLength(1)
      await page.reload(); const restored = await enter(), control = restored.getByRole('region', { name: label('Independent native build cancellation'), exact: true })
      await expect(control.getByTestId('native-build-cancellation-receipt')).toBeVisible()
      expect(protocol.cancelWrites).toHaveLength(1); expect(protocol.cancelConfirms).toHaveLength(1)
      expect(protocol.writes).toHaveLength(1); expect(protocol.confirms).toHaveLength(1)
      expect(protocol.cancelWrites[0].invocation_id).toBe(await restored.getByTestId('native-build-original-command').locator('code').innerText())
      await page.setViewportSize({ width: 390, height: 844 }); await control.scrollIntoViewIfNeeded()
      const body = page.getByRole('dialog', { name: label('Image revisions'), exact: true }).locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/native-build-cancellation-${theme}-mobile.png`) })
      expect(errors).toEqual([])
    } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
  })

  test(`a verified failed cancellation can only be replaced through a fresh explicit confirmation (${theme})`, async ({ page, request }) => {
    test.setTimeout(300_000)
    const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
    if (!exweb) writeFileSync(join(source, 'pom.xml'), '<project><modelVersion>4.0.0</modelVersion><groupId>specimen</groupId><artifactId>specimen</artifactId><version>1</version></project>')
    try {
      const v = await captureAnalysis(request, source), [candidate] = await frozenRevisions(request, v.projectId, v.owner.headers)
      const response = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${candidate.image_revision_id}?section=source_members&offset=0&limit=25`, { headers: v.owner.headers })
      expect(response.ok()).toBeTruthy(); const image = await response.json(); expect(image.next_offset).toBeNull()
      const sources: FrozenImageSources = { project_id: v.projectId, image_revision_id: image.revision.image_revision_id, image_artifact_hash: image.revision.artifact_hash,
        manifest_id: image.revision.manifest_id, manifest_hash: image.revision.manifest_hash, source_members: image.items }
      const protocol = await installNativeBuildProtocol(page, sources), label = (key: keyof typeof zhCN) => language === 'zh' ? zhCN[key] : key
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme, language } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', locale) }, { token: v.owner.token, locale: language })
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message))
      await page.goto(`/projects/${v.projectId}/knowledge`)
      await page.getByRole('button', { name: label('Image revisions'), exact: true }).click()
      const dialog = page.getByRole('dialog', { name: label('Image revisions'), exact: true })
      await dialog.getByRole('combobox', { name: label('Frozen candidate revision'), exact: true }).selectOption(candidate.image_revision_id)
      await dialog.getByRole('button', { name: label('Inspect fixed-source native build'), exact: true }).click()
      const panel = dialog.getByRole('region', { name: label('Fixed-source native build'), exact: true })
      const sourceSelect = panel.getByRole('combobox', { name: label('Frozen code source'), exact: true })
      await expect(sourceSelect).toBeEnabled(); await sourceSelect.selectOption(sources.source_members.find((s) => s.source_type === 'code')!.binding_id)
      await panel.getByRole('textbox', { name: label('Target JAR path'), exact: true }).fill('target/retry-cancel-specimen.jar')
      await panel.getByRole('button', { name: label('Preview exact native build'), exact: true }).click()
      await panel.getByRole('checkbox').check(); await panel.getByRole('button', { name: label('Start confirmed native build'), exact: true }).click()
      await expect(panel.getByTestId('native-build-original-command')).toContainText(label('running'))
      const target = await panel.getByTestId('native-build-original-command').locator('code').innerText()
      const cancellation = panel.getByRole('region', { name: label('Independent native build cancellation'), exact: true })
      protocol.failCancelConfirm = true; await cancellation.getByRole('checkbox').check()
      await cancellation.getByRole('button', { name: label('Cancel original native build'), exact: true }).click()
      await expect(cancellation.getByTestId('native-build-original-cancellation')).toContainText(label('failed'))
      const failed = await cancellation.getByTestId('native-build-original-cancellation').locator('code').innerText()
      await expect(cancellation.getByRole('checkbox')).toHaveCount(0)
      expect(protocol.cancelWrites).toHaveLength(1); expect(protocol.cancelConfirms).toHaveLength(1)
      await cancellation.getByRole('button', { name: label('Reload original cancellation'), exact: true }).click()
      await expect(cancellation.getByTestId('native-build-original-cancellation')).toContainText(failed)
      expect(protocol.cancelWrites).toHaveLength(1); expect(protocol.cancelConfirms).toHaveLength(1)
      await cancellation.getByRole('button', { name: label('Prepare another independently confirmed cancellation'), exact: true }).click()
      const cancel = cancellation.getByRole('button', { name: label('Cancel original native build'), exact: true })
      await expect(cancel).toBeDisabled(); await expect(cancellation.getByRole('checkbox')).not.toBeChecked()
      expect(protocol.cancelWrites).toHaveLength(1); expect(protocol.cancelConfirms).toHaveLength(1)
      await cancellation.getByRole('checkbox').check(); await cancel.click()
      await expect(cancellation.getByTestId('native-build-cancellation-receipt')).toBeVisible()
      const replacement = await cancellation.getByTestId('native-build-original-cancellation').locator('code').innerText()
      expect(replacement).not.toBe(failed); expect(protocol.cancelConfirms).toEqual([failed, replacement])
      expect(protocol.cancelWrites).toHaveLength(2); expect(protocol.cancelWrites.every((item) => item.invocation_id === target)).toBe(true)
      expect(protocol.writes).toHaveLength(1); expect(protocol.confirms).toHaveLength(1)
      await expect(panel.getByTestId('native-build-original-command')).toContainText(label('cancelled'))
      expect(errors).toEqual([])
    } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
  })
}
