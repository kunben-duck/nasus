const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { execFileSync } = require('node:child_process'), { webcrypto } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')
const repo = path.resolve(__dirname, '../..'), root = path.join(repo, 'apps/portal/src')
function load(relative, overrides = {}, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, crypto: webcrypto, TextEncoder, URL, URLSearchParams, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const { verifyRunPlanLocators: verify } = load('domains/quality-loop/runPlanLocatorValidation.ts')
const plain = (v) => JSON.parse(JSON.stringify(v))
function specimen(protocol = 'v1', kind = 'http', condition = false) {
  // Real parser and independent Python matcher; source and business data are protocol specimens.
  return JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json,sys
from apps.api.tests.test_run_plan_locators import plan_fixture,inventory_for,JAVA
from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.app.application.quality_loop.run_plan_locators import RunPlanLocatorApplicationService,RunPlanLocatorQuery
p=plan_fixture(protocol=sys.argv[1],kind=sys.argv[2]); java=JAVA
if sys.argv[3]=='true': java=java.replace('@GetMapping("/explicit-protocol-fixture")','@GetMapping(path="/explicit-protocol-fixture",produces="application/json")')
port,_,_=inventory_for(p,java); report=compile_http_locator_evidence(p,port.inspect(p,require_access=lambda:None))
q=RunPlanLocatorQuery(project_id=p['project_id'],run_plan_id='original-plan',run_plan_artifact_hash='sha256:'+'a'*64)
print(json.dumps(dict(plan=p,receipt=RunPlanLocatorApplicationService._receipt(q,p,report),report=report)))`, protocol, kind, String(condition)], { cwd: repo, encoding: 'utf8' }))
}
function scopedSpecimen(input = {}) {
  return JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json,sys
from apps.api.tests.test_http_locator_uncertainty import scoped_plan,report_for
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.app.application.quality_loop.run_plan_locators import RunPlanLocatorApplicationService,RunPlanLocatorQuery
args=json.loads(sys.argv[1]); legacy=args.pop('legacy',False); p=scoped_plan(args.pop('path','/api/sessions/{{session}}'),args.pop('method','GET'))
report,_,_=report_for(p,**args)
if legacy:
    inventory=report['inventory']; inventory.update(schema='nasus.frozen-http-route-inventory.v1',rule='java.import-resolved-http-locators.v1')
    for source in inventory['sources']:
        for route in source['routes']:
            route['rule']=inventory['rule']; route.pop('unresolved_match_scope',None)
        for file in source['files']:
            file['rules']=[inventory['rule'] if r=='java.import-resolved-http-locators.v2' else r for r in file['rules']]
    inventory['inventory_hash']=acceptance_digest({k:v for k,v in inventory.items() if k!='inventory_hash'})
    report=compile_http_locator_evidence(p,inventory)
q=RunPlanLocatorQuery(project_id=p['project_id'],run_plan_id='original-plan',run_plan_artifact_hash='sha256:'+'a'*64)
print(json.dumps(dict(plan=p,receipt=RunPlanLocatorApplicationService._receipt(q,p,report),report=report)))`, JSON.stringify(input)], { cwd: repo, encoding: 'utf8' }))
}
function saved(v) { return { metadata: { project_id: v.plan.project_id, run_plan_id: 'original-plan', artifact_hash: 'sha256:' + 'a'.repeat(64) }, artifact: { plan: v.plan } } }
function view(v) { return structuredClone({ receipt: v.receipt, report: v.report }) }
async function rehash(v) {
  const { inventory_hash: _i, ...inventory } = v.report.inventory
  v.report.inventory.inventory_hash = v.receipt.inventory_hash = await digest(inventory)
  const { report_hash: _r, ...report } = v.report
  v.report.report_hash = v.receipt.report_hash = await digest(report)
}
for (const protocol of ['v1', 'v2']) test(`Portal validates the complete Python static locator report (${protocol})`, async () => {
  const v = specimen(protocol), original = structuredClone(v), result = view(v)
  assert.equal(await verify(result, saved(v)), result)
  assert.equal(result.report.summary.static_match, result.report.summary.locator_count)
  assert.deepEqual(v, original)
})
test('unresolved request conditions and browser actions are explicit gaps, not matches', async () => {
  for (const [kind, condition, status] of [['http', true, 'unresolved'], ['browser', false, 'unsupported']]) {
    const v = specimen('v1', kind, condition), result = await verify(view(v), saved(v))
    assert.equal(result.report.summary[status], result.report.summary.locator_count)
    assert.equal(result.receipt.runtime_locators_verified, false)
  }
})
const scopedBase = scopedSpecimen({ java: `import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api") class Controller {
  @GetMapping("/sessions/{id}") String session() { return "ok"; }
  @PostMapping(path="/elsewhere",produces="application/json") String conditional() { return "ok"; }
}` })
test('v3 keeps the complete conditional declaration but only disjoint uncertainty is excluded', async () => {
  const v = await verify(view(scopedBase), saved(scopedBase))
  assert.equal(v.report.schema, 'nasus.run-plan-http-locators.v2')
  assert.equal(v.report.summary.static_match, v.report.summary.locator_count)
  assert.equal(v.report.inventory.sources[0].routes.filter((r) => r.status === 'unresolved').length, 1)
  assert.equal(v.receipt.execution_authorized, false)
})
test('a v3 plan can replay its original v1 report without upgrading global uncertainty', async () => {
  const v = scopedSpecimen({ legacy: true, java: `import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api") class Controller {
  @GetMapping("/sessions/{id}") String session() { return "ok"; }
  @PostMapping(path="/elsewhere",produces="application/json") String conditional() { return "ok"; }
}` })
  const result = await verify(view(v), saved(v))
  assert.equal(result.report.policy, 'nasus.http-locator-static-match.v1')
  assert.equal(result.report.summary.unresolved, result.report.summary.locator_count)
  assert.equal(result.report.summary.static_match, 0)
})
for (const [annotation, status] of [
  ['@GetMapping(path="/sessions/{id}",headers="X-Mode=x")', 'unresolved'],
  ['@GetMapping(path="/sessions/fixed",produces="application/json")', 'unresolved'],
  ['@PostMapping(path="/sessions/{id}",headers="X-Mode=x")', 'static_match'],
  ['@RequestMapping(path="/sessions/{id}",produces="application/json")', 'unresolved'],
  ['@GetMapping(path=UNKNOWN,produces="application/json")', 'unresolved'],
  ['@GetMapping(path="/sessions/{id:[0-9]+}",produces="application/json")', 'unresolved'],
  ['@GetMapping("/sessions/fixed")', 'unresolved'],
]) test(`v3 browser independently matches original uncertainty: ${annotation}`, async () => {
  const v = scopedSpecimen({ java: `import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api") class Controller {
  @GetMapping("/sessions/{id}") String session() { return "ok"; }
  ${annotation} String other() { return "ok"; }
}` })
  const result = await verify(view(v), saved(v))
  assert.equal(result.report.summary[status], result.report.summary.locator_count)
})
const scopedCorruptions = {
  'mixed report version': (v) => v.report.schema = 'nasus.run-plan-http-locators.v1',
  'mixed receipt policy': (v) => v.receipt.policy = 'nasus.http-locator-static-match.v1',
  'mixed inventory rule': (v) => v.report.inventory.rule = 'java.import-resolved-http-locators.v1',
  'missing conditional scope': (v, r) => delete r.unresolved_match_scope,
  'empty conditional scope': (v, r) => r.unresolved_match_scope = [],
  'duplicate conditional scope': (v, r) => r.unresolved_match_scope.push(r.unresolved_match_scope[0]),
  'extra scope fields': (v, r) => r.unresolved_match_scope[0].authorization = true,
  'invalid scoped method': (v, r) => r.unresolved_match_scope[0].method = 'get',
  'unbounded scope': (v, r) => r.unresolved_match_scope[0].route_path = '/' + 'x'.repeat(4096),
  'scope controls': (v, r) => r.unresolved_match_scope[0].route_path += '\u0000',
  'scope DEL control': (v, r) => r.unresolved_match_scope[0].route_path += '\u007f',
  'scope not sorted': (v, r) => r.unresolved_match_scope = [{ method: 'POST', route_path: '/b' }, { method: 'POST', route_path: '/a' }],
  'observed scope injection': (v) => v.report.inventory.sources[0].routes.find((r) => r.status === 'observed').unresolved_match_scope = null,
}
for (const [name, mutate] of Object.entries(scopedCorruptions)) test(`rehashed scoped locator corruption is rejected: ${name}`, async () => {
  const v = view(scopedBase), conditional = v.report.inventory.sources[0].routes.find((r) => r.status === 'unresolved')
  mutate(v, conditional); await rehash(v)
  await assert.rejects(verify(v, saved(scopedBase)))
})
test('scope ordering uses Python Unicode code points rather than UTF-16 or locale collation', async () => {
  const v = scopedSpecimen({ java: `import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api") class Controller {
  @GetMapping("/sessions/{id}") String session() { return "ok"; }
  @PostMapping(path={"/z","/a","/\u{10000}","/\ue000"},produces="application/json") String other() { return "ok"; }
}` })
  const result = await verify(view(v), saved(v))
  const scope = result.report.inventory.sources[0].routes.find((r) => r.status === 'unresolved').unresolved_match_scope
  assert.deepEqual(plain(scope.map((s) => s.route_path)), ['/api/a', '/api/z', '/api/\ue000', '/api/\u{10000}'])
})
test('browser protocol fixture executes its original Python template for both inventory versions', async () => {
  const { installLocatorProtocol } = load(path.relative(root, path.join(repo, 'tests/e2e/run-plan-locator-fixtures.ts')), {
    '@playwright/test': { expect: () => { throw new Error('No browser request in this template compile check') } },
    'node:child_process': require('node:child_process'), 'node:path': require('node:path'),
    '../../apps/portal/src/shared/utils/canonicalDigest': { canonicalDigest: digest },
  })
  for (const original of [base, scopedBase]) {
    const routes = [], result = await installLocatorProtocol({ route: async (pattern) => routes.push(pattern) }, saved(original))
    assert.equal(routes.length, 1)
    assert.equal(result.value.report.policy, original === base ? 'nasus.http-locator-static-match.v1' : 'nasus.http-locator-static-match.v2')
    if (original === scopedBase) {
      const conditional = result.value.report.inventory.sources[0].routes.filter((r) => r.status === 'unresolved')
      assert.deepEqual(plain(conditional.map((r) => r.unresolved_match_scope)), [[{ method: 'POST', route_path: '/unrelated-condition' }]])
    }
  }
})
const corruptions = {
  'missing original action': (v) => v.report.locators.pop(),
  'changed action digest': (v) => v.report.locators[0].action_digest = 'sha256:' + 'b'.repeat(64),
  'changed original steps': (v) => v.report.locators[0].source_step_indices = [999],
  'inflated match count': (v) => v.report.summary.static_match++,
  'claimed runtime match': (v) => v.receipt.runtime_locators_verified = true,
  'claimed durable fact': (v) => v.receipt.durable_locator_evidence_verified = true,
  'claimed execution': (v) => v.report.execution_authorized = true,
  'claimed pass count': (v) => v.report.passed_count = 1,
  'foreign plan': (v) => v.receipt.query.run_plan_id = 'foreign',
  'foreign source': (v) => v.report.inventory.sources[0].pin.source_revision_id = 'foreign',
  'missing full source': (v) => v.report.inventory.sources.pop(),
  'foreign image': (v) => v.report.inventory.sources[0].pin.image_revision_id = 'foreign',
  'wrong file hash': (v) => v.report.inventory.sources[0].routes[0].source_file_hash = 'sha256:' + 'b'.repeat(64),
  'bad snippet': (v) => v.report.inventory.sources[0].routes[0].snippet_hash = 'bad',
  'invalid source position': (v) => v.report.inventory.sources[0].routes[0].start_line = true,
  'duplicate files': (v) => v.report.inventory.sources[0].files.push(v.report.inventory.sources[0].files[0]),
  'invented candidate': (v) => v.report.locators[0].candidates[0].relative_path = 'foreign.java',
  'unauthorized extra metadata': (v) => v.report.token = 'private',
}
const base = specimen()
for (const [name, mutate] of Object.entries(corruptions)) test(`rehashed locator corruption is rejected: ${name}`, async () => {
  const value = view(base); mutate(value); await rehash(value)
  await assert.rejects(verify(value, saved(base)))
})
test('locator request is exact, private, GET-only and abortable without a new canonical write', async () => {
  const v = specimen('v2'), calls = []
  const { readRunPlanLocators } = load('domains/quality-loop/runPlanLocatorApi.ts', { '../../shared/api/client': {
    request: async (url, options) => { calls.push({ url, options }); return view(v) },
  } })
  assert.deepEqual(plain(await readRunPlanLocators(saved(v), new AbortController().signal)), view(v))
  assert.equal(calls.length, 1); assert.equal(calls[0].options.cache, 'no-store'); assert.equal(calls[0].options.method, undefined)
  assert.equal(new URL('http://local' + calls[0].url).searchParams.get('run_plan_artifact_hash'), saved(v).metadata.artifact_hash)
  assert.match(calls[0].url, /\/original-plan\/http-locators\?/)
  await assert.rejects(readRunPlanLocators(saved(v), AbortSignal.abort()), { name: 'AbortError' })
  assert.equal(calls.length, 1)
})

function renderPanel(state) {
  const React = require('../../apps/portal/node_modules/react')
  const { renderToStaticMarkup } = require('../../apps/portal/node_modules/react-dom/server')
  const { RunPlanLocatorPanel } = load('routes/project/sections/knowledge/scope/RunPlanLocatorPanel.tsx', {
    react: React, 'react/jsx-runtime': require('../../apps/portal/node_modules/react/jsx-runtime'),
    '../../../../../domains/quality-loop/useRunPlanLocators': { useRunPlanLocators: () => state },
    '../../../../../shared/i18n/I18nProvider': { useI18n: () => ({ t: (key) => key }) },
  })
  return renderToStaticMarkup(React.createElement(RunPlanLocatorPanel, { plan: saved(base), actorId: 'original-reader', onFailure: () => {} }))
}
test('route component is initially folded and does not render private source metadata', () => {
  const html = renderPanel({ open: false, busy: false, failed: false, toggle: () => {}, reload: () => {} })
  assert.match(html, /aria-expanded="false"/)
  assert.doesNotMatch(html, /Controller.java|original-source|run-plan-locators"|<pre/)
})
test('rendering is bounded to twenty rows while keeping the complete verified action denominator', () => {
  const value = view(base), action = value.report.locators[0]
  value.report.locators = Array.from({ length: 43 }, (_, index) => ({ ...action, case_id: `render-specimen-${index}` }))
  value.report.summary.locator_count = 43
  const html = renderPanel({ open: true, busy: false, failed: false, value, toggle: () => {}, reload: () => {} })
  assert.equal((html.match(/<li>/g) ?? []).length, 20)
  assert.match(html, /1-20 \/ 43/); assert.match(html, /Next page/)
  assert.doesNotMatch(html, /<pre/)
  assert.equal(value.report.locators.length, 43)
})
test('pending revalidation and denied reads have no private report in the route view model', () => {
  for (const state of [{ busy: true, failed: false }, { busy: false, failed: true }]) {
    const html = renderPanel({ ...state, open: true, toggle: () => {}, reload: () => {} })
    assert.doesNotMatch(html, /Controller.java|original-source|run-plan-locators"|<pre/)
  }
})
