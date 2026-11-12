import { BuildComposer } from '../../shared/ui/BuildComposer'
import { BuildConversation } from './components/BuildConversation'
import { BuildAgentFeedback } from './components/BuildAgentFeedback'
import { BuildSidebarToggle } from './components/BuildSidebarToggle'
import type { BuildHeroProps } from './BuildHeroTypes'
import { useI18n } from '../../shared/i18n/I18nProvider'
import { recentUserPrompts } from '../../domains/agent/recentUserPrompts'

export function BuildHero({
  conversation,
  sendPrompt,
  newBuild,
  prompt,
  setPrompt,
  runPrompt,
  stopPrompt,
  loading,
  streaming,
  selectedSkills,
  onToggleSkill,
  onGuessYou,
  feedback,
  sidebarCollapsed,
  toggleSidebar,
}: BuildHeroProps) {
  const { t } = useI18n()
  return (
    <section className={`build-hero${conversation?.messages.length ? ' has-conversation' : ''}`}>
      <BuildSidebarToggle sidebarCollapsed={sidebarCollapsed} toggleSidebar={toggleSidebar} />
      {!conversation?.messages.length ? <div className="hero-title">
        <h1>{t('Build quality projects with Nasus')}</h1>
      </div> : null}
      {conversation?.messages.length ? <button type="button" className="tool-chip" disabled={loading} onClick={newBuild}>
        {t('New build conversation')}
      </button> : null}
      <BuildConversation key={conversation?.id} conversation={conversation} sendPrompt={sendPrompt} busy={loading} />
      <BuildComposer
        key={`composer:${conversation?.id ?? 'pending'}`}
        prompt={prompt}
        promptHistory={recentUserPrompts(conversation?.messages)}
        setPrompt={setPrompt}
        runPrompt={runPrompt}
        stopPrompt={stopPrompt}
        loading={loading}
        streaming={streaming}
        selectedSkills={selectedSkills}
        onToggleSkill={onToggleSkill}
        onGuessYou={onGuessYou}
      />
      <BuildAgentFeedback feedback={feedback} streaming={streaming} />
    </section>
  )
}
