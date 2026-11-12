import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { buildSkillCards, type BuildSkillId } from '../../../domains/platform/build-skills'
import { createProjectFromBuild } from '../../../domains/platform/buildProjectCommands'
import { useProjectDirectory } from '../../../domains/platform/useProjectDirectory'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../shared/i18n/messages'
import { BuildSkillStrip } from './BuildSkillStrip'

const destinations: Record<BuildSkillId, string> = {
  git: '?source=code',
  us: '?source=usDoc',
  tests: '?source=testAsset',
  baseline: '?source=all',
  quality: '/versions',
  release: '/release-readiness',
}

export function BuildShortcuts() {
  const [skill, setSkill] = useState<BuildSkillId | null>(null)
  const [creating, setCreating] = useState(false)
  return (
    <>
      <BuildSkillStrip activeSkill={skill} onSelectSkill={(next) => {
        if (!creating) setSkill(skill === next ? null : next)
      }} />
      {skill ? <BuildShortcutPanel key={skill} skill={skill} onBusyChange={setCreating} /> : null}
    </>
  )
}

function BuildShortcutPanel({ skill, onBusyChange }: { skill: BuildSkillId; onBusyChange: (busy: boolean) => void }) {
  const { t, tx } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const directory = useProjectDirectory()
  const [projectId, setProjectId] = useState('')
  const [name, setName] = useState('')
  const attempt = useRef<{ name: string; key: string } | null>(null)
  const busy = useRef(false)
  const destination = destinations[skill]
  const isSourceAction = destination.startsWith('?')
  const title = buildSkillCards.find((card) => card.id === skill)!.title as MessageKey

  function openProject(id: string) {
    navigate(`/projects/${encodeURIComponent(id)}${destination}`)
  }

  const creation = useMutation({
    mutationFn: ({ name, key }: { name: string; key: string }) => createProjectFromBuild(name, key),
    onSuccess: (id) => {
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      void queryClient.invalidateQueries({ queryKey: ['build'] })
      openProject(id)
    },
    onSettled: () => {
      busy.current = false
      onBusyChange(false)
    },
  })

  return (
    <section className="build-shortcut-panel" id="build-shortcut-panel" aria-labelledby="build-shortcut-title">
      <h2 id="build-shortcut-title">{t(title)}</h2>
      <p>{isSourceAction
        ? t('Choose a project to configure its sources. Code is required; requirements and tests are optional.')
        : skill === 'quality'
          ? t('Choose a project, then open a user story in its version workspace.')
          : t('Choose a project to review release evidence and blockers.')}</p>
      {directory.error ? (
        <div role="alert">
          <p>{t('Unable to load projects. Check your connection and try again.')}</p>
          <button className="composer-action-button" type="button" onClick={() => void directory.reload()}>{t('Reload projects')}</button>
        </div>
      ) : directory.loading ? (
        <p role="status">{t('Loading projects...')}</p>
      ) : directory.projects.length ? (
        <form className="build-shortcut-form" onSubmit={(event) => {
          event.preventDefault()
          if (!busy.current && directory.projects.some((project) => project.id === projectId)) openProject(projectId)
        }}>
          <label>
            <span>{t('Project')}</span>
            <select className="source-field-control" value={projectId} disabled={creation.isPending} onChange={(event) => setProjectId(event.target.value)} required>
              <option value="">{t('Choose a project')}</option>
              {directory.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          </label>
          <button className="composer-action-button" type="submit" disabled={!projectId || creation.isPending}>{t('Continue')}</button>
        </form>
      ) : <p role="status">{t('No projects available. Create a project or ask an administrator to add you to one.')}</p>}
      {isSourceAction ? (
        <form className="build-shortcut-form" onSubmit={(event) => {
          event.preventDefault()
          const trimmed = name.trim()
          if (!trimmed || busy.current) return
          if (attempt.current?.name !== trimmed) attempt.current = { name: trimmed, key: crypto.randomUUID() }
          busy.current = true
          onBusyChange(true)
          creation.mutate(attempt.current)
        }}>
          <label>
            <span>{t('New project name')}</span>
            <input className="source-field-control" value={name} onChange={(event) => setName(event.target.value)} disabled={creation.isPending} required />
          </label>
          <button className="composer-action-button build-submit-button" type="submit" disabled={!name.trim() || creation.isPending}>
            {creation.isPending ? t('Creating project...') : t('Create project')}
          </button>
        </form>
      ) : null}
      {creation.error ? <p role="alert" className="source-binding-error">{tx(creation.error.message)}</p> : null}
    </section>
  )
}
