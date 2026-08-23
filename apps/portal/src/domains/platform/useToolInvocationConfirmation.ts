import { useMutation } from '@tanstack/react-query'

import { confirmToolInvocation as confirmToolInvocationCommand } from './toolInvocationCommands'

type ToolInvocationConfirmationOptions = {
  onConfirmed?: (invocationId: string) => Promise<void> | void
}

export function useToolInvocationConfirmation({ onConfirmed }: ToolInvocationConfirmationOptions = {}) {
  const mutation = useMutation({
    mutationFn: (invocationId: string) => confirmToolInvocationCommand(invocationId),
    onSuccess: async (_result, invocationId) => {
      await onConfirmed?.(invocationId)
    },
  })

  return {
    confirmToolInvocation: mutation.mutateAsync,
    isConfirmingToolInvocation: mutation.isPending,
  }
}
