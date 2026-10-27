import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'

for (const [theme, language] of [['light', 'en'], ['dark', 'zh']] as const) {
  test(`unverified source inventory stays blocked with a historical ready decision (${theme})`, async ({ page, request }) => {
    test.setTimeout(120_000)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    const fixedExweb = process.env.EXWEB_FIXTURE_ROOT
    const source = fixedExweb ? resolve(fixedExweb) : analysisSource()
    if (fixedExweb) expect(execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim())
      .toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
    try {
      const v = await captureAnalysis(request, source)
      await v.invoke('system_image.sources.register', { source_specs: [
        { source_type: 'us_doc', source_uri: resolve('tests/fixtures/system-image/exweb-context-requirements.md') },
        { source_type: 'test_asset', source_uri: resolve('tests/fixtures/system-image/exweb-test-cases.csv') },
      ] })
      await v.invoke('system_image.sources.ingest')
      await v.invoke('system_image.context.materialize')
      const projectUrl = `${analysisApi}/v1/projects/${v.projectId}`
      const workspaceResponse = await request.get(projectUrl, { headers: v.owner.headers })
      expect(workspaceResponse.ok()).toBeTruthy()
      const workspace = await workspaceResponse.json()
      expect(workspace.us_items.length).toBeGreaterThan(0)
      const usId = workspace.us_items[0].id
      for (const tool of ['quality.scope.generate', 'quality.scenario.generate', 'quality.plan.generate',
        'quality.case.generate', 'automation.generate', 'quality.change-doc.generate']) {
        await v.invoke(tool, { us_id: usId })
      }
      const draftsResponse = await request.get(projectUrl, { headers: v.owner.headers })
      expect(draftsResponse.ok()).toBeTruthy()
      const drafts = await draftsResponse.json()
      expect(drafts.quality_asset_pack.parts).toHaveLength(6)
      for (const part of drafts.quality_asset_pack.parts) {
        expect(part.status).toBe('ready_for_review')
        expect(part.generation.mode).toBe('fallback') // Explicit protocol fixture, never a live model claim.
      }
      await v.invoke('release.assess', { us_id: usId })
      const assessmentResponse = await request.get(`${projectUrl}/release-readiness`, { headers: v.owner.headers })
      expect(assessmentResponse.ok()).toBeTruthy()
      const assessment = await assessmentResponse.json()
      expect(assessment.evidence_summary.quality_assessment_unknown).toBe(1)
      expect(assessment.score).toBeLessThanOrEqual(59)
      expect(assessment.blocker_items).toContain('System image quality assessment is unknown; retrieval inventory is not release evidence.')
      const image = await (await request.get(`${projectUrl}/system-image`, { headers: v.owner.headers })).json()
      expect(image.quality_profiles.length).toBeGreaterThan(0)
      for (const profile of image.quality_profiles) for (const field of ['risk_score', 'coverage_score', 'release_score', 'automation_feasibility', 'confidence'])
        expect(profile[field]).toBeNull()
      // Persist an old ready decision only as an isolated negative fixture.
      const database = process.env.NASUS_TEST_DATABASE_URL
      if (!database || database !== process.env.NASUS_E2E_DATABASE_URL) throw new Error('Disposable PostgreSQL is required')
      execFileSync(resolve('.venv/bin/python'), ['-c', `
import os, sys
from sqlalchemy.engine import make_url
from apps.api.app.application.quality_loop.quality_models import ReleaseDecision
from apps.api.app.infrastructure.persistence.quality_loop_repository import QualityLoopRepository
url = make_url(os.environ['NASUS_DATABASE_URL'])
assert url.get_backend_name() == 'postgresql' and url.host in {'localhost', '127.0.0.1', '::1'}
assert url.database.startswith('nasus_test_'), 'never seed developer release decisions'
QualityLoopRepository().upsert_release_decision(ReleaseDecision(
    id='historical_' + sys.argv[1], project_id=sys.argv[1], version_id=sys.argv[2], us_id=sys.argv[3],
    status='ready', score=90, rationale='Historical ready conclusion must not replace current evidence',
    evidence_refs=[], created_at='2026-10-01T00:00:00Z'))
`, v.projectId, assessment.version_id, usId], { env: { ...process.env, NASUS_DATABASE_URL: database }, stdio: 'pipe' })
      const settings = await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme, language } })
      expect(settings.ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => {
        localStorage.setItem('nasus_api_token', token)
        localStorage.setItem('nasus.locale', locale)
      }, { token: v.owner.token, locale: language })
      const writes: string[] = []
      page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/v1/tool-invocations')) writes.push(r.url()) })
      await page.goto(`/projects/${v.projectId}`)
      const assets = page.getByTestId('quality-asset-panel')
      await expect(assets.locator('.quality-lane-card.ready_for_review')).toHaveCount(5)
      await expect(assets.locator('.quality-lane-card.approved')).toHaveCount(0)
      await expect(assets.locator('.quality-lane-card.blocked')).toHaveCount(1)
      await expect(assets).toContainText(language === 'zh' ? '待审核' : 'Ready For Review')
      await expect(assets.getByTestId('quality-draft-notice')).toContainText(language === 'zh' ? '尚未经过批准' : 'not approved assets')
      await expect(assets).toContainText(language === 'zh' ? '必需的质量资产尚未经过批准' : 'Required quality assets are not approved')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await assets.getByTestId('quality-draft-notice').scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/quality-draft-notice-${theme}.png`) })
      await page.goto(`/projects/${v.projectId}/release-readiness`)
      const metrics = page.locator('.metric-grid').first()
      const check = async () => {
        await expect(metrics.locator('.metric-card').filter({ hasText: language === 'zh' ? '状态' : 'Status' }).locator('strong'))
          .toHaveText(language === 'zh' ? '已阻塞' : 'blocked')
        await expect(metrics.locator('.metric-card').filter({ hasText: language === 'zh' ? '评分' : 'Score' }).locator('strong'))
          .toHaveText(String(assessment.score))
        await expect(page.locator('.quality-blocker-list')).toContainText(language === 'zh' ? '尚缺少质量评估证据' : 'quality assessment is unknown')
        await expect(page.getByText('Historical ready conclusion must not replace current evidence')).toHaveCount(0)
      }
      await check()
      await page.reload()
      await check()
      await page.setViewportSize({ width: 390, height: 844 })
      await check()
      const assess = page.locator('.quality-panel-header button')
      await expect(assess).toHaveCSS('white-space', 'nowrap')
      const assessSize = await assess.boundingBox()
      expect(assessSize?.width).toBeGreaterThan(70)
      expect(assessSize?.height).toBeLessThan(50)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      expect(writes).toEqual([])
      expect(errors).toEqual([])
      await page.locator('.quality-blocker-list').scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/unknown-quality-release-${theme}-mobile.png`) })
    } finally { if (!fixedExweb) rmSync(source, { recursive: true, force: true }) }
  })
}
