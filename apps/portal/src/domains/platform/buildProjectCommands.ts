import { platformApi } from './api'

export async function createProjectFromBuild(name: string, idempotencyKey: string): Promise<string> {
  const invocation = await platformApi.invokeTool({
    tool_id: 'project.create',
    input: { name },
    idempotency_key: idempotencyKey,
  })
  if (invocation.status !== 'completed') throw new Error(invocation.summary)
  const projectId = invocation.result?.object_refs?.find((ref) => ref.startsWith('project:'))?.slice('project:'.length)
  if (!projectId) throw new Error('Project creation did not return a project.')
  return projectId
}
