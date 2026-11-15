import { requirementTestDesignSelection, type RequirementReview } from '../../../../domains/quality-loop/requirementReviews'
import { useRequirementTestDesign } from '../../../../domains/quality-loop/useRequirementTestDesign'
import type { ContextRequest } from '../../../../domains/system-image/types/contextPack'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { TestDesignScopePanel } from '../knowledge/scope/TestDesignScopePanel'

export function RequirementTestDesignPanel({ review, actorId }: { review: RequirementReview; actorId: string }) {
  const selection = requirementTestDesignSelection(review)
  if (!selection) return null
  return <TestDesignEntry key={`${actorId}:${selection.iteration!.confirmation_id}`} selection={selection} actorId={actorId} />
}

function TestDesignEntry({ selection, actorId }: { selection: ContextRequest; actorId: string }) {
  const { locale } = useI18n(), zh = locale === 'zh'
  const state = useRequirementTestDesign(selection, actorId)
  const { open, busy, error, selected, failed, preview, history, archive, rows, content } = state
  return <section className="requirement-test-design" data-testid="requirement-test-design">
    <button type="button" className="small-btn" disabled={busy} aria-expanded={open} onClick={state.toggle}>{zh ? '生成用例与执行' : 'Test design and execution'}</button>
    {open && <>
      <p>{zh ? '使用当前迭代已确认的需求和画像。先审核测试范围，再授权模型生成；用例和脚本需独立审核后才能执行。'
        : 'Use the confirmed requirement and iteration image. Review scope before authorizing generation; cases and scripts require independent review before execution.'}</p>
      {(preview.isFetching || history.isFetching || archive.isFetching) && <p role="status">{zh ? '正在核对需求、画像与访问权限…' : 'Verifying requirement, image and access...'}</p>}
      {(preview.isError || history.isError || archive.isError || failed) && <p role="alert">{zh ? '无法核验当前输入，已隐藏受保护内容。请刷新后检查需求批准和画像关联。' : 'Inputs could not be verified. Protected content is hidden; reload and check approvals and image bindings.'}</p>}
      {!preview.isFetching && !preview.isError && preview.data && <>
        <p>{zh ? `固定 ${preview.data.context.required_constraints.length} 条验收条件及业务规则。保存上下文不会调用模型或执行测试。`
          : `${preview.data.context.required_constraints.length} fixed criteria and rules. Saving context does not invoke a model or execute tests.`}</p>
        <button type="button" className="small-btn primary" disabled={busy} onClick={() => void state.compile()}>
          {zh ? '确认输入并准备测试上下文' : 'Confirm inputs and prepare test context'}</button>
      </>}
      {!!rows?.length && <label>{zh ? '已保存的测试上下文' : 'Saved test contexts'}<select value={selected} disabled={busy}
        onChange={(event) => state.choose(event.target.value)}>
        <option value="">{zh ? '选择已保存上下文' : 'Choose saved context'}</option>
        {rows.map((item) => <option key={item.context_id} value={item.context_id}>{item.recorded_at} · {item.mandatory_count}</option>)}
      </select></label>}
      {history.hasNextPage && <button type="button" className="small-btn" disabled={history.isFetching}
        onClick={() => void history.fetchNextPage()}>{zh ? '加载更多' : 'Load more'}</button>}
      {content && <TestDesignScopePanel key={content.metadata.context_id} context={content}
        scope={{ projectId: selection.project_id, sessionId: actorId, onFailure: state.setFailed }} />}
      {error && <p role="alert">{zh ? '无法确认保存结果，请重新读取原请求后再继续。' : 'The save could not be verified. Reload the original request before continuing.'}</p>}
      <button type="button" className="small-btn" disabled={busy} onClick={state.reload}>{zh ? '刷新测试设计状态' : 'Reload test design'}</button>
    </>}
  </section>
}
