import { toolIdForAction } from './toolActionMap'
import type { StudioActionCommand, StudioActionContext, StudioActionId } from './types'
import type { Locale } from '../../../shared/i18n/I18nProvider'

export function buildStudioActionCommand(
  actionId: StudioActionId,
  context: StudioActionContext,
  locale: Locale = 'en',
): StudioActionCommand {
  const baseInput = {
    project_id: context.projectId,
    ...(context.input ?? {}),
  }

  if (actionId === 'system-image.build-goal') {
    return {
      kind: 'conversation_message',
      actionId,
      content: locale === 'zh'
        ? '构建当前项目的系统画像。'
        : 'Build the system image for this project.',
    }
  }

  if (actionId === 'quality-loop.continue-goal') {
    return {
      kind: 'conversation_message',
      actionId,
      content: locale === 'zh'
        ? '针对风险最高的未关闭 US，完成范围分析、场景、验证计划、用例、自动化证据、变更文档和发布就绪评估的端到端质量闭环。'
        : 'Complete the end-to-end quality loop for the riskiest open US through scope, scenarios, verification planning, cases, automation evidence, a change document, and release readiness.',
    }
  }

  return {
    kind: 'tool_invocation',
    actionId,
    tool_id: toolIdForAction(actionId),
    input: baseInput,
    initiator_surface: 'ui',
    initiator_actor: 'user',
    target_scope: 'central',
  }
}
