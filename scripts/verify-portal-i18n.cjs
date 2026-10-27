const fs = require('node:fs')
const path = require('node:path')
const ts = require('../apps/portal/node_modules/typescript')

const portalRoot = path.resolve(__dirname, '../apps/portal/src')
const checkedAttributes = new Set(['alt', 'aria-label', 'placeholder', 'title'])
const checkedProperties = new Set(['copy', 'description', 'emptyText', 'eyebrow', 'heading', 'label', 'placeholder', 'statusText', 'subtitle', 'summary', 'title'])
const allowedVisibleLiterals = new Set([
  'Anthropic',
  'Gemini',
  'Nasus',
  'Nasus Studio',
  'OpenAI',
  '/absolute/path/to/repo or https://git.example/repo.git',
  'agent-first-quality-v1',
  'https://api.example.com/v1',
])

function messageKeys() {
  const file = path.join(portalRoot, 'shared/i18n/messages.ts')
  const source = fs.readFileSync(file, 'utf8')
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const keys = new Set()
  const catalogViolations = []
  function placeholders(value) {
    return [...value.matchAll(/\{(\w+)\}/gu)].map((match) => match[1]).sort().join(',')
  }
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(sourceFile) === 'zhCN') {
      const initializer = ts.isAsExpression(node.initializer) ? node.initializer.expression : node.initializer
      if (!initializer || !ts.isObjectLiteralExpression(initializer)) return
      for (const property of initializer.properties) {
        if (!ts.isPropertyAssignment(property)) continue
        const key = ts.isStringLiteral(property.name)
          ? property.name.text
          : property.name.getText(sourceFile)
        if (keys.has(key)) catalogViolations.push(`Duplicate translation key: ${JSON.stringify(key)}`)
        keys.add(key)
        if (!ts.isStringLiteral(property.initializer)) {
          catalogViolations.push(`Translation must be a string literal: ${JSON.stringify(key)}`)
          continue
        }
        if (placeholders(key) !== placeholders(property.initializer.text)) {
          catalogViolations.push(`Translation placeholders differ: ${JSON.stringify(key)}`)
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  if (catalogViolations.length) {
    console.error('Portal translation catalog validation failed:')
    for (const violation of catalogViolations) console.error(`- ${violation}`)
    process.exit(1)
  }
  return keys
}

const registeredMessages = messageKeys()

function collectFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) return collectFiles(target)
    return target.endsWith('.tsx') ? [target] : []
  })
}

function normalize(value) {
  return value.replace(/\s+/gu, ' ').trim()
}

function containsUserCopy(value) {
  return /[A-Za-z]{3}|[\u3400-\u9fff]/u.test(value)
}

function isAriaHidden(node, sourceFile) {
  let current = node.parent
  while (current) {
    if (ts.isJsxElement(current)) {
      const hidden = current.openingElement.attributes.properties.find((attribute) => (
        ts.isJsxAttribute(attribute) && attribute.name.getText(sourceFile) === 'aria-hidden'
      ))
      if (hidden) return true
    }
    current = current.parent
  }
  return false
}

const violations = []
for (const file of collectFiles(portalRoot)) {
  const source = fs.readFileSync(file, 'utf8')
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

  function report(node, kind, rawValue) {
    const value = normalize(rawValue)
    if (!value || !containsUserCopy(value) || allowedVisibleLiterals.has(value) || isAriaHidden(node, sourceFile)) return
    const location = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
    violations.push(`${path.relative(process.cwd(), file)}:${location.line + 1} ${kind}: ${JSON.stringify(value)}`)
  }

  function visit(node) {
    if (ts.isJsxText(node)) report(node, 'JSX text', node.getText(sourceFile))
    if (
      ts.isJsxAttribute(node)
      && checkedAttributes.has(node.name.getText(sourceFile))
      && node.initializer
      && ts.isStringLiteral(node.initializer)
    ) {
      report(node, node.name.getText(sourceFile), node.initializer.text)
    }
    if (
      ts.isPropertyAssignment(node)
      && checkedProperties.has(node.name.getText(sourceFile).replace(/^['"]|['"]$/gu, ''))
      && (ts.isStringLiteral(node.initializer) || ts.isNoSubstitutionTemplateLiteral(node.initializer))
      && !registeredMessages.has(node.initializer.text)
    ) {
      report(node, `unregistered ${node.name.getText(sourceFile)}`, node.initializer.text)
    }
    ts.forEachChild(node, visit)
  }

  visit(sourceFile)
}

if (violations.length) {
  console.error('Portal internationalization gate failed. Move user-visible copy into shared/i18n/messages.ts:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log('Portal internationalization gate passed: unique keys, matching placeholders and no unregistered visible JSX copy.')
