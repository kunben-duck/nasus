import { expect } from '@playwright/test'
import { execFileSync, spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export async function trackedOrigin() {
  const root = mkdtempSync(join(tmpdir(), 'nasus-tracked-ref-browser-'))
  const repository = join(root, 'repo')
  mkdirSync(repository)
  const env = { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' }
  const git = (...args: string[]) => execFileSync('git', ['-c', 'core.hooksPath=/dev/null',
    '-c', 'commit.gpgsign=false', '-C', repository, ...args], { env, encoding: 'utf8' }).trim()
  const commit = (message: string) => {
    git('add', '.')
    git('-c', 'user.name=Nasus Test', '-c', 'user.email=nasus-test@example.com', 'commit', '-m', message)
    return git('rev-parse', 'HEAD')
  }
  git('init')
  git('branch', '-M', 'main')
  writeFileSync(join(repository, 'checkout.py'), 'def checkout():\n    return "release"\n')
  writeFileSync(join(repository, 'README.md'), '# Controlled branch browser fixture\n')
  const releaseCommit = commit('release fixture')
  git('branch', 'release')
  writeFileSync(join(repository, 'main-only.txt'), 'Not part of the selected release branch.\n')
  const mainCommit = commit('default branch fixture')
  const reservation = createServer()
  await new Promise<void>((resolve, reject) => {
    reservation.once('error', reject)
    reservation.listen(0, '127.0.0.1', resolve)
  })
  const address = reservation.address()
  if (!address || typeof address === 'string') throw new Error('Private Git fixture port unavailable')
  await new Promise<void>((resolve, reject) => reservation.close((error) => error ? reject(error) : resolve()))
  const daemon = spawn('git', ['daemon', '--export-all', '--reuseaddr', '--listen=127.0.0.1',
    `--port=${address.port}`, `--base-path=${root}`, root], { env, stdio: 'ignore' })
  const uri = `git://127.0.0.1:${address.port}/repo`
  const close = async () => {
    if (daemon.exitCode === null && daemon.signalCode === null) {
      const exited = new Promise<void>((resolve) => daemon.once('exit', () => resolve()))
      daemon.kill('SIGTERM')
      await exited
    }
    rmSync(root, { recursive: true, force: true })
  }
  try {
    await expect.poll(() => {
      try { return git('ls-remote', uri, 'refs/heads/release').split(/\s/)[0] } catch { return '' }
    }, { timeout: 10_000 }).toBe(releaseCommit)
  } catch (error) { await close(); throw error }
  return { uri, releaseCommit, mainCommit, close, advanceMain: () => {
    writeFileSync(join(repository, 'checkout.py'), 'def checkout():\n    return "changed"\n')
    return commit('explicit changed-code adoption fixture')
  } }
}
